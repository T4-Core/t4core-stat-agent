"""독립 Calculation Tool — LLM Client 없이 동작하는 결정론적 계산기.

구성
  1) Atomic Calculator (Decimal): growth_rate, share_ratio, difference, percentage_point_difference, sum_values,
     mean_values, weighted_mean, agg_metrics, rank_values, top_k_values, convert_unit
  2) SqlSafetyValidator: 읽기 전용 · 등록된 View · 허용 함수만
  3) TableCalculationEngine: DuckDB 인메모리 (작업마다 별도 연결) 에 View 를 view_1.. 로 등록하고
     PlannerAgent 의 구조화된 연산 계획(OperationPlan)을 SQL 로 컴파일 → 실행 → 원본 좌표가 붙은 Intermediate Fact
     와 최종 결과(NumericResult)를 만든다.

LLM 이 만든 임의의 코드·SQL 은 실행하지 않는다 (sql_plan 은 설정에서 허용한 경우에만 검증 후 실행, 정답 산출에는 쓰지 않음).
"""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from synthetic_gold_pipeline.schemas.calculation import (CalcErrorCode, CalculationResult, EvidenceFileRef,
                                                          FinalAnswer, IntermediateFact, JoinDiagnostics,
                                                          NumericResult, RankedEntry, RETRYABLE_CODES,
                                                          SourceCoordinate, StepResult, UnitConversionTrace,
                                                          VectorEntry)
from synthetic_gold_pipeline.schemas.metadata import DimensionType, ValueKind, ViewMetadata
from synthetic_gold_pipeline.schemas.planning import AtomicOp, FilterSpec, Operand, OperationPlan, OperationStep
from synthetic_gold_pipeline.tools.plan_repair import AREA_SPLIT
from synthetic_gold_pipeline.tools.units import (UnitIncompatible, conversion_factor, parse_value, unit_info)
from synthetic_gold_pipeline.utils import atomic_write_text, display_path, period_label, sha256_file

Q18 = Decimal("1e-18")


class CalculationError(Exception):
    def __init__(self, code: CalcErrorCode, message: str, refs: list[str] | None = None):
        super().__init__(f"[{code.value}] {message}")
        self.code, self.message, self.refs = code, message, refs or []


# ═════════════════════════════ 1) 수치 표현 ═════════════════════════════

DEFAULT_ROUNDING = {"COUNT": 0, "AMOUNT": 0, "RATE": 1, "MEAN": 1, "INDEX": 1, "UNKNOWN": 2}


def _q(v: Decimal, digits: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def exact_str(v: Decimal) -> str:
    if v == v.to_integral_value():
        return str(int(v))
    s = format(v.quantize(Q18, rounding=ROUND_HALF_UP), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def result_kind(unit: str) -> ValueKind:
    if unit in ("%", "%p", "‰") or "/" in unit:
        return ValueKind.RATE
    if unit in ("개", "곳"):
        return ValueKind.COUNT
    return unit_info(unit).kind


def fmt_number(v: Decimal, digits: int) -> str:
    q = _q(v, digits)
    s = f"{q:,.{digits}f}" if digits > 0 else f"{int(q):,}"
    return s


def make_numeric(value: Decimal, unit: str, rounding: dict | None = None) -> NumericResult:
    if not value.is_finite():
        raise CalculationError(CalcErrorCode.NON_FINITE, f"결과가 유한하지 않음: {value}")
    rounding = {**DEFAULT_ROUNDING, **(rounding or {})}
    kind = result_kind(unit)
    digits = int(rounding.get(kind.value, 2))
    integral = value == value.to_integral_value()
    if kind in (ValueKind.COUNT, ValueKind.AMOUNT) and not integral:
        digits = max(digits, 1)
    r1, r2 = float(_q(value, 1)), float(_q(value, 2))
    cands: list[str] = []
    if kind in (ValueKind.COUNT, ValueKind.AMOUNT) and integral:
        iv = int(value)
        cands = [f"{iv:,}{unit}", f"{iv}{unit}"]
    else:
        for d in sorted({digits, 1, 2}):
            n = fmt_number(value, d)
            cands += [f"{n}{unit}", f"{n.replace(',', '')}{unit}"]
            if unit == "%p":
                cands.append(f"{n}%포인트")
    cands = list(dict.fromkeys(cands))
    display = f"{fmt_number(value, digits)}{unit}" if not (kind in (ValueKind.COUNT, ValueKind.AMOUNT) and integral) \
        else f"{int(value):,}{unit}"
    return NumericResult(raw=float(value), exact_decimal=exact_str(value),
                         round_0=int(_q(value, 0)), round_1=r1, round_2=r2, unit=unit, display_digits=digits,
                         display=display, formatted_candidates=cands)


# ═════════════════════════════ 2) Atomic Calculator ═════════════════════════════

@dataclass
class CalcOutput:
    value: Decimal
    formula: str
    inputs: dict[str, Any] = field(default_factory=dict)


def _f(v: Decimal) -> str:
    return exact_str(v)


def growth_rate(new: Decimal, old: Decimal) -> CalcOutput:
    if old == 0:
        raise CalculationError(CalcErrorCode.DENOMINATOR_ZERO, "증감률의 기준값(이전 시점)이 0")
    if old < 0:
        raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE, "기준값이 음수인 지표의 증감률은 정의하지 않음")
    v = (new - old) / old * 100
    return CalcOutput(v, f"({_f(new)} − {_f(old)}) / {_f(old)} × 100", {"new": _f(new), "old": _f(old)})


def share_ratio(part: Decimal, whole: Decimal, scale: Decimal = Decimal(100)) -> CalcOutput:
    if whole == 0:
        raise CalculationError(CalcErrorCode.DENOMINATOR_ZERO, "비율의 분모가 0")
    v = part / whole * scale
    return CalcOutput(v, f"{_f(part)} / {_f(whole)} × {_f(scale)}", {"part": _f(part), "whole": _f(whole),
                                                                     "scale": _f(scale)})


def difference(a: Decimal, b: Decimal) -> CalcOutput:
    return CalcOutput(a - b, f"{_f(a)} − {_f(b)}", {"a": _f(a), "b": _f(b)})


def percentage_point_difference(a_pct: Decimal, b_pct: Decimal) -> CalcOutput:
    return CalcOutput(a_pct - b_pct, f"{_f(a_pct)}% − {_f(b_pct)}%", {"a": _f(a_pct), "b": _f(b_pct)})


def sum_values(values: list[Decimal]) -> CalcOutput:
    if not values:
        raise CalculationError(CalcErrorCode.EMPTY_RESULT, "합산할 값이 없음")
    v = sum(values, Decimal(0))
    return CalcOutput(v, " + ".join(_f(x) for x in values), {"n": len(values)})


def mean_values(values: list[Decimal]) -> CalcOutput:
    if not values:
        raise CalculationError(CalcErrorCode.EMPTY_RESULT, "평균낼 값이 없음")
    v = sum(values, Decimal(0)) / Decimal(len(values))
    return CalcOutput(v, f"({' + '.join(_f(x) for x in values)}) / {len(values)}", {"n": len(values)})


def weighted_mean(values: list[Decimal], weights: list[Decimal]) -> CalcOutput:
    if len(values) != len(weights) or not values:
        raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, "값과 가중치 개수가 다름")
    if any(w < 0 for w in weights):
        raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE, "음수 가중치")
    sw = sum(weights, Decimal(0))
    if sw == 0:
        raise CalculationError(CalcErrorCode.DENOMINATOR_ZERO, "가중치 합이 0")
    v = sum((x * w for x, w in zip(values, weights)), Decimal(0)) / sw
    return CalcOutput(v, f"Σ(값×가중치)/Σ가중치 = {_f(sum((x * w for x, w in zip(values, weights)), Decimal(0)))} / {_f(sw)}",
                      {"n": len(values)})


def agg_metrics(values: list[Decimal]) -> dict[str, Decimal | int]:
    if not values:
        raise CalculationError(CalcErrorCode.EMPTY_RESULT, "값이 없음")
    return {"count": len(values), "sum": sum(values, Decimal(0)), "mean": sum(values, Decimal(0)) / len(values),
            "min": min(values), "max": max(values)}


def rank_values(items: list[tuple[str, Decimal]], order: str = "DESC") -> list[tuple[int, str, Decimal]]:
    """경쟁 순위 (1, 2, 2, 4). 같은 값은 같은 순위."""
    rev = order.upper() == "DESC"
    srt = sorted(items, key=lambda kv: (-kv[1] if rev else kv[1], kv[0]))
    out, prev, rank = [], None, 0
    for i, (k, v) in enumerate(srt, 1):
        if v != prev:
            rank, prev = i, v
        out.append((rank, k, v))
    return out


def top_k_values(items: list[tuple[str, Decimal]], k: int, order: str = "DESC") -> tuple[list[tuple[int, str, Decimal]], bool]:
    """(상위 k, 경계 동점 여부). 경계에 동점이 있으면 정답이 하나로 정해지지 않으므로 호출 측에서 폐기."""
    if k <= 0:
        raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, "k 는 1 이상")
    r = rank_values(items, order)
    if k >= len(r):
        raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"k={k} 가 후보 수 {len(r)} 이상 (순위 의미 없음)")
    tie = r[k - 1][2] == r[k][2]
    return r[:k], tie


def convert_unit(value: Decimal, from_unit: str, to_unit: str) -> CalcOutput:
    try:
        f = conversion_factor(from_unit, to_unit)
    except UnitIncompatible as e:
        raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, str(e))
    return CalcOutput(value * f, f"{_f(value)}{from_unit} × {_f(f)} = {_f(value * f)}{to_unit}", {"factor": _f(f)})


SCALE_LABEL = {Decimal(1): "", Decimal(100): "백", Decimal(1000): "천", Decimal(10000): "만", Decimal(100000): "십만"}


# ═════════════════════════════ 3) SQL 안전성 ═════════════════════════════

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|SET|RESET|"
    r"CALL|CHECKPOINT|VACUUM|USE|TRUNCATE|GRANT|REVOKE|SUMMARIZE|DESCRIBE)\b", re.I)
SQL_KEYWORDS = {"select", "from", "where", "and", "or", "not", "in", "exists", "over", "as", "on", "using", "join",
                "filter", "when", "then", "else", "case", "with", "values", "group", "by", "order", "having", "union",
                "all", "distinct", "limit", "is", "null", "between", "like", "partition", "asc", "desc", "inner",
                "left", "right", "outer", "cross", "end"}
ALLOWED_FUNCTIONS = {"sum", "avg", "count", "min", "max", "round", "abs", "coalesce", "nullif", "cast", "try_cast",
                     "row_number", "rank", "dense_rank", "lag", "lead", "greatest", "least", "lower", "upper", "trim",
                     "replace", "length", "substr", "substring", "concat", "first", "last", "any_value", "median",
                     "quantile_cont", "quantile_disc", "stddev_samp", "var_samp", "regexp_replace", "strip_accents"}


class SqlSafetyValidator:
    def __init__(self, allowed_tables: set[str], allowed_columns: set[str]):
        self.tables = {t.lower() for t in allowed_tables}
        self.columns = set(allowed_columns)

    def validate(self, sql: str) -> list[str]:
        errs = []
        s = sql.strip()
        if "--" in s or "/*" in s:
            errs.append("주석 금지")
        body = s[:-1] if s.endswith(";") else s
        if ";" in body:
            errs.append("여러 문장 금지")
        if not re.match(r"^\s*(SELECT|WITH)\b", body, re.I):
            errs.append("SELECT/WITH 로 시작하는 읽기 전용 쿼리만 허용")
        no_str = re.sub(r"'(?:[^']|'')*'", "''", body)
        m = FORBIDDEN_SQL.search(no_str)
        if m:
            errs.append(f"금지 키워드: {m.group(1)}")
        if re.search(r"\b(FROM|JOIN)\s*'", body, re.I):
            errs.append("파일 경로 직접 조회 금지")
        ctes = {c.lower() for c in re.findall(r"(?:WITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", no_str, re.I)}
        for t in re.findall(r"\b(?:FROM|JOIN)\s+(\"?[A-Za-z_][\w]*\"?)", no_str, re.I):
            name = t.strip('"').lower()
            if name not in self.tables and name not in ctes:
                errs.append(f"등록되지 않은 테이블: {name}")
        for fn in re.findall(r"\b([A-Za-z_]\w*)\s*\(", no_str):
            f = fn.lower()
            if f in SQL_KEYWORDS or f in ctes:
                continue
            if f not in ALLOWED_FUNCTIONS:
                errs.append(f"허용되지 않은 함수: {fn}")
        for col in re.findall(r'"([^"]+)"', no_str):
            if col not in self.columns and col.lower() not in self.tables and col.lower() not in ctes:
                errs.append(f"허용되지 않은 컬럼: {col}")
        return list(dict.fromkeys(errs))


def sql_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


# ═════════════════════════════ 4) 엔진 ═════════════════════════════

@dataclass
class Scalar:
    value: Decimal
    unit: str
    fact_ids: list[str]
    label: str = ""


@dataclass
class Vector:
    entries: dict[str, tuple[Decimal, str, list[str]]]    # code → (value, name, fact_ids)
    unit: str
    level: str
    dim_type: str
    source_ref: str
    view_id: str | None = None


@dataclass
class Entity:
    code: str
    name: str
    value: Decimal
    unit: str


@dataclass
class Ranking:
    entries: list[tuple[int, str, str, Decimal]]   # rank, code, name, value
    unit: str


class TableCalculationEngine:
    """작업(샘플)마다 새 DuckDB 인메모리 연결을 만들고 닫는다 — 비동기 작업 간 연결 공유 없음."""

    def __init__(self, index, cfg: dict | None = None, evidence_root: str | Path | None = None):
        cfg = cfg or {}
        self.index = index
        self.timeout_s = float(cfg.get("query_timeout_seconds", 10))
        self.row_limit = int(cfg.get("row_limit", 100_000))
        self.memory_limit = str(cfg.get("memory_limit", "1GB"))
        self.threads = int(cfg.get("threads", 1))
        self.rounding = cfg.get("rounding") or {}
        self.inline_limit = int(cfg.get("inline_vector_fact_limit", 50))
        self.allow_sql_plan = bool(cfg.get("allow_sql_plan", False))
        self.vector_missing_policy = cfg.get("vector_missing_policy", "drop_sample")
        self.evidence_root = Path(evidence_root) if evidence_root else None

    # ── 공개 API ──────────────────────────────────────────────────
    def run(self, plan: OperationPlan, available_view_ids: list[str], write_evidence: bool = True) -> CalculationResult:
        t0 = time.perf_counter()
        res = CalculationResult(plan_id=plan.plan_id, success=False)
        con = None
        try:
            if plan.plan_status.value != "OK":
                raise CalculationError(CalcErrorCode.PLAN_REJECTED, plan.reject_reason or "REJECT_PLAN")
            if plan.operation is None or not plan.operation.steps:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, "operation.steps 가 비어 있음")
            used = list(dict.fromkeys(o.view_id for o in plan.operands))
            unknown = [v for v in used if v not in available_view_ids or v not in self.index.views]
            if unknown:
                raise CalculationError(CalcErrorCode.UNKNOWN_VIEW, f"제공되지 않은 View: {unknown}", unknown)
            con, alias = self._connect(used)
            ctx = _Ctx(self, con, alias, plan, res, write_evidence)
            final = ctx.evaluate()
            res.final = final
            res.success = True
            res.views_used = used
        except CalculationError as e:
            res.error_code, res.error_message, res.retryable = e.code, e.message, e.code in RETRYABLE_CODES
        except duckdb.InterruptException:
            res.error_code, res.error_message = CalcErrorCode.TIMEOUT, f"쿼리 시간 초과 ({self.timeout_s}s)"
        except duckdb.Error as e:
            res.error_code, res.error_message, res.retryable = CalcErrorCode.PLAN_STRUCTURE_ERROR, f"SQL 오류: {e}", True
        finally:
            if con is not None:
                con.close()
            res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return res

    def _connect(self, view_ids: list[str]):
        con = duckdb.connect(":memory:")
        con.execute(f"SET memory_limit='{self.memory_limit}'")
        con.execute(f"SET threads={self.threads}")
        alias = {}
        for i, vid in enumerate(view_ids, 1):
            name = f"view_{i}"
            con.register(name, self.index.load_frame(vid))
            alias[vid] = name
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
        return con, alias

    def execute(self, con, sql: str, params: list[Any]) -> pd.DataFrame:
        timer = threading.Timer(self.timeout_s, con.interrupt)
        timer.start()
        try:
            return con.execute(sql, params).df()
        finally:
            timer.cancel()


class _Ctx:
    def __init__(self, eng: TableCalculationEngine, con, alias: dict[str, str], plan: OperationPlan,
                 res: CalculationResult, write_evidence: bool):
        self.e, self.con, self.alias, self.plan, self.res = eng, con, alias, plan, res
        self.write_evidence = write_evidence
        self.values: dict[str, Any] = {}
        self.op_by_id = {o.operand_id: o for o in plan.operands}
        self.flt_by_id = {f.filter_id: f for f in plan.filters}
        self.step_by_id = {s.step_id: s for s in plan.operation.steps}
        ids = list(self.op_by_id) + list(self.flt_by_id) + list(self.step_by_id)
        if len(ids) != len(set(ids)):
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, "operand/filter/step ID 중복")
        self.fact_seq = 0
        self.declared_conv = {(u.operand_id): u for u in plan.unit_conversion}

    # ── 평가 ──
    def evaluate(self) -> FinalAnswer:
        if self.plan.sql_plan:
            self._run_sql_plan(self.plan.sql_plan)
        out = self.get(self.plan.operation.final_step_id, stack=())
        self.res.executed_formula = "\n".join(f"{s.step_id}: {s.formula}" for s in self.res.step_results)
        if isinstance(out, Scalar):
            return FinalAnswer(kind="SCALAR", value=make_numeric(out.value, out.unit, self.e.rounding), unit=out.unit)
        if isinstance(out, Entity):
            return FinalAnswer(kind="ENTITY", entity=RankedEntry(rank=1, key_code=out.code, key_name=out.name,
                                                                 value=make_numeric(out.value, out.unit, self.e.rounding)),
                               unit=out.unit)
        if isinstance(out, Ranking):
            return FinalAnswer(kind="RANKING", unit=out.unit, ranking=[
                RankedEntry(rank=r, key_code=c, key_name=n, value=make_numeric(v, out.unit, self.e.rounding))
                for r, c, n, v in out.entries])
        raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, "최종 단계 결과가 벡터 (집계 단계가 필요)")

    def get(self, ref: str, stack: tuple):
        if ref in self.values:
            return self.values[ref]
        if ref in stack:
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"순환 참조: {ref}")
        if ref in self.op_by_id:
            v = self.resolve_operand(self.op_by_id[ref])
        elif ref in self.flt_by_id:
            v = self.apply_filter(self.flt_by_id[ref], stack + (ref,))
        elif ref in self.step_by_id:
            v = self.apply_step(self.step_by_id[ref], stack + (ref,))
        else:
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"알 수 없는 참조: {ref}", [ref])
        self.values[ref] = v
        return v

    # ── Operand → SQL ──
    def _where(self, op: Operand, vm: ViewMetadata) -> tuple[list[str], list[Any]]:
        if not vm.item(op.itm_id) and op.itm_id not in vm.source_coordinates.itm_ids:
            raise CalculationError(CalcErrorCode.UNKNOWN_ITEM, f"{op.operand_id}: View 에 없는 항목 {op.itm_id}", [op.operand_id])
        if op.prd_de not in vm.available_periods:
            raise CalculationError(CalcErrorCode.MISSING_PERIOD,
                                   f"{op.operand_id}: View 에 없는 시점 {op.prd_de} (있는 시점 {vm.available_periods[:6]})",
                                   [op.operand_id])
        conds, params = ['"ITM_ID" = ?', '"PRD_DE" = ?'], [op.itm_id, op.prd_de]
        levels = {d.level for d in vm.dimension_definitions}
        for lv, code in op.coordinates.items():
            if lv not in levels:
                raise CalculationError(CalcErrorCode.UNKNOWN_LEVEL, f"{op.operand_id}: 분류 레벨 {lv} 없음 ({sorted(levels)})",
                                       [op.operand_id])
            if code not in vm.code_map(lv):
                raise CalculationError(CalcErrorCode.UNKNOWN_CODE, f"{op.operand_id}: {lv} 에 코드 {code} 없음", [op.operand_id])
            conds.append(f'"{lv}" = ?')
            params.append(code)
        if op.group_by_level:
            if op.group_by_level not in levels:
                raise CalculationError(CalcErrorCode.UNKNOWN_LEVEL, f"{op.operand_id}: group_by_level {op.group_by_level} 없음",
                                       [op.operand_id])
            if op.group_by_level in op.coordinates:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR,
                                       f"{op.operand_id}: group_by_level 을 coordinates 로 고정할 수 없음", [op.operand_id])
        return conds, params

    def resolve_operand(self, op: Operand):
        vm = self.e.index.view(op.view_id)
        conds, params = self._where(op, vm)
        lv_cols = [d.level for d in vm.dimension_definitions]
        cols = ["_src_row", "ORG_ID", "TBL_ID", "PRD_SE", "PRD_DE", "ITM_ID", "ITM_NM", "UNIT_NM", "DT"] + \
               [c for lv in lv_cols for c in (lv, f"{lv}_NM")]
        frame_cols = set(self.e.index.load_frame(op.view_id).columns)
        cols = [c for c in cols if c in frame_cols]
        sql = (f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM {self.alias[op.view_id]} '
               f'WHERE {" AND ".join(conds)} ORDER BY "_src_row" LIMIT {self.e.row_limit + 1}')
        df = self.e.execute(self.con, sql, params)
        self.res.executed_sql.append(self._inline(sql, params))
        self.res.row_counts[op.operand_id] = len(df)
        if len(df) > self.e.row_limit:
            raise CalculationError(CalcErrorCode.ROW_LIMIT_EXCEEDED, f"{op.operand_id}: 행 수 상한 초과")
        if df.empty:
            raise CalculationError(CalcErrorCode.EMPTY_RESULT, f"{op.operand_id}: 조건에 맞는 행 없음", [op.operand_id])
        units = sorted({str(u or "") for u in df["UNIT_NM"]})
        if len(units) != 1:
            raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, f"{op.operand_id}: 단위가 여러 개 {units}")
        unit = units[0]
        if op.group_by_level is None:
            if len(df) > 1:
                free = [lv for lv in lv_cols if lv in df.columns and df[lv].nunique() > 1]
                if not free:
                    raise CalculationError(CalcErrorCode.JOIN_AMPLIFICATION,
                                           f"{op.operand_id}: 같은 원본 좌표의 중복 행 {len(df)}개 (값 증폭 위험)")
                raise CalculationError(CalcErrorCode.CARDINALITY_ERROR,
                                       f"{op.operand_id}: 스칼라인데 {len(df)}행 — 고정되지 않은 분류 {free} 의 코드를 지정하세요",
                                       [op.operand_id])
            row = df.iloc[0]
            fact = self._fact(op, vm, row, kind="SCALAR")
            return Scalar(Decimal(fact.coordinate.normalized_value), unit, [fact.fact_id], op.label)
        # 벡터
        key = op.group_by_level
        if key not in df.columns or key not in lv_cols:
            raise CalculationError(CalcErrorCode.UNKNOWN_LEVEL,
                                   f"{op.operand_id}: group_by_level={key!r} 는 View 에 없는 레벨 — 가능한 레벨 {lv_cols}"
                                   " (스칼라면 null)", [op.operand_id])
        cm = vm.code_map(key)
        region_vec = bool(vm.dim(key) and vm.dim(key).dim_type == DimensionType.REGION)
        dup = df.groupby(key).size()
        dups = dup[dup > 1]
        if len(dups):
            others = [lv for lv in lv_cols if lv != key and lv in df.columns and df[lv].nunique() > 1]
            if others:
                raise CalculationError(CalcErrorCode.CARDINALITY_ERROR,
                                       f"{op.operand_id}: 키 {key} 당 여러 행 — 분류 {others} 를 coordinates 로 고정하세요",
                                       [op.operand_id])
            raise CalculationError(CalcErrorCode.JOIN_AMPLIFICATION,
                                   f"{op.operand_id}: 같은 좌표 중복 행 (키 {list(dups.index)[:5]}) → 다대다 Join 행 증폭")
        dsql = (f'SELECT "{key}", count(*) AS n FROM {self.alias[op.view_id]} WHERE {" AND ".join(conds)} '
                f'GROUP BY "{key}" HAVING count(*) > 1')
        self.res.executed_sql.append(self._inline(dsql, params))
        entries: dict[str, tuple[Decimal, str, list[str]]] = {}
        rows = []
        for _, row in df.iterrows():
            code = str(row[key])
            dc = cm.get(code)
            if dc is None:
                continue
            if op.exclude_totals and (dc.is_total or dc.has_children):
                continue
            if region_vec and AREA_SPLIT.match(dc.name or ""):     # 동부·읍부·면부는 지역 단위가 아님
                continue
            if op.depth is not None and dc.depth != op.depth:
                continue
            if op.include_codes is not None and code not in op.include_codes:
                continue
            rows.append((code, dc, row))
        if op.include_codes:
            missing = [c for c in op.include_codes if c not in {r[0] for r in rows}]
            if missing:
                raise CalculationError(CalcErrorCode.UNKNOWN_CODE, f"{op.operand_id}: include_codes 중 없는 코드 {missing}")
        if len(rows) < 2:
            raise CalculationError(CalcErrorCode.EMPTY_RESULT, f"{op.operand_id}: 벡터 원소가 2개 미만")
        inline = len(rows) <= self.e.inline_limit
        for code, dc, row in rows:
            pv = parse_value(row["DT"])
            if not pv.ok:
                if self.e.vector_missing_policy == "skip_element":
                    continue
                raise CalculationError(CalcErrorCode.MISSING_VALUE,
                                       f"{op.operand_id}: {dc.name}({code}) 값이 결측 '{row['DT']}' ({pv.status})")
            if inline:
                fact = self._fact(op, vm, row, kind="VECTOR_ELEMENT", key=(code, dc.name))
                entries[code] = (Decimal(fact.coordinate.normalized_value), dc.name, [fact.fact_id])
            else:
                entries[code] = (pv.value, dc.name, [])
        if not inline:
            self._evidence_file(op, vm, [r[2] for r in rows], sql, params)
        dim = vm.dim(key)
        return Vector(entries, unit, key, dim.dim_type.value if dim else "OTHER", op.operand_id, op.view_id)

    def _fact(self, op: Operand, vm: ViewMetadata, row, kind: str, key: tuple[str, str] | None = None) -> IntermediateFact:
        pv = parse_value(row["DT"])
        if not pv.ok:
            raise CalculationError(CalcErrorCode.MISSING_VALUE,
                                   f"{op.operand_id}: 필요한 원본 값이 결측 '{row['DT']}' ({pv.status}, 의미: "
                                   f"{vm.symbol_meanings.get(str(row['DT']), '미상')})", [op.operand_id])
        self.fact_seq += 1
        fid = f"F{self.fact_seq}"
        dims, names, labels = {}, {}, {}
        for d in vm.dimension_definitions:
            if d.level in row.index and row[d.level] not in (None, ""):
                dims[d.level] = str(row[d.level])
                names[d.level] = str(row.get(f"{d.level}_NM") or "")
                labels[d.obj_nm] = names[d.level]
        src_row = int(row["_src_row"])
        coord = SourceCoordinate(
            view_id=vm.view_id, parent_table_id=vm.parent_table_id, source_path=vm.source_path,
            source_file_hash=vm.source_file_hash, row_number=src_row, csv_line_number=src_row + 1,
            ORG_ID=str(row["ORG_ID"]), TBL_ID=str(row["TBL_ID"]), PRD_SE=str(row["PRD_SE"] or ""),
            PRD_DE=str(row["PRD_DE"]), ITM_ID=str(row["ITM_ID"]), ITM_NM=str(row.get("ITM_NM") or ""),
            dims=dims, dim_names=names, UNIT_NM=str(row["UNIT_NM"] or ""), raw_value=str(row["DT"]),
            normalized_value=exact_str(pv.value), applied_multiplier="1", normalized_unit=str(row["UNIT_NM"] or ""))
        item = vm.item(op.itm_id)
        fact = IntermediateFact(
            fact_id=fid, operand_id=op.operand_id, view_id=vm.view_id, parent_table_id=vm.parent_table_id, kind=kind,
            key_code=key[0] if key else None, key_name=key[1] if key else None,
            period=period_label(vm.period_frequency, str(row["PRD_DE"])), item_id=op.itm_id,
            item_name=item.itm_nm if item else str(row.get("ITM_NM") or op.itm_id), coordinate_labels=labels,
            unit=str(row["UNIT_NM"] or ""), value=make_numeric(pv.value, str(row["UNIT_NM"] or ""), self.e.rounding),
            coordinate=coord)
        self.res.intermediate_facts.append(fact)
        return fact

    def _evidence_file(self, op, vm, rows, sql, params):
        if not (self.write_evidence and self.e.evidence_root):
            return
        df = pd.DataFrame([r.to_dict() for r in rows])
        p = self.e.evidence_root / (self.plan.plan_id or "plan") / f"{op.operand_id}.csv"
        atomic_write_text(p, df.to_csv(index=False))
        self.res.evidence_files.append(EvidenceFileRef(path=display_path(p), sha256=sha256_file(p), n_rows=len(df),
                                                       query_spec={"view_id": vm.view_id, "sql": self._inline(sql, params),
                                                                   "source_path": vm.source_path}))

    @staticmethod
    def _inline(sql: str, params: list[Any]) -> str:
        parts = sql.split("?")
        out = parts[0]
        for p, rest in zip(params, parts[1:]):
            out += sql_literal(p) + rest
        return out

    # ── 단위 ──
    def _align_units(self, refs: list[str], units: list[str], op: AtomicOp) -> tuple[list[Decimal], str]:
        """같은 계열이면 기본 단위로 맞추는 계수와 공통 단위. 다른 계열이면 오류."""
        if len(set(units)) == 1:
            for r, u in zip(refs, units):
                self._check_declared(r, u, u)
            return [Decimal(1)] * len(units), units[0]
        infos = [unit_info(u) for u in units]
        if not all(i.known for i in infos) or len({i.family for i in infos}) != 1:
            raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, f"{op.value}: 호환되지 않는 단위 {units}")
        base = infos[0].base_unit
        factors = []
        for r, u in zip(refs, units):
            f = conversion_factor(u, base)
            factors.append(f)
            self._check_declared(r, u, base)
            if f != 1:
                self._trace(r, u, base, f, f"{op.value} 피연산자 단위 통일")
        return factors, base

    def _check_declared(self, ref: str, from_u: str, to_u: str):
        d = self.declared_conv.get(ref)
        if d and (unit_info(d.from_unit).canonical != unit_info(from_u).canonical):
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR,
                                   f"unit_conversion[{ref}].from_unit={d.from_unit} 이 실제 단위 {from_u} 와 다름", [ref])
        if d:
            try:
                conversion_factor(d.from_unit, d.to_unit)
            except UnitIncompatible as e:
                raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, f"unit_conversion[{ref}]: {e}")

    def _trace(self, ref: str, from_u: str, to_u: str, f: Decimal, reason: str):
        if any(t.ref == ref and t.from_unit == from_u and t.to_unit == to_u for t in self.res.unit_conversion_trace):
            return
        self.res.unit_conversion_trace.append(UnitConversionTrace(ref=ref, from_unit=from_u, to_unit=to_u, factor=_f(f),
                                                                  reason=reason))
        self._apply_multiplier(ref, f, to_u)

    def _root_operands(self, ref: str, seen: tuple = ()) -> set[str]:
        if ref in self.op_by_id:
            return {ref}
        if ref in seen:
            return set()
        if ref in self.flt_by_id:
            return self._root_operands(self.flt_by_id[ref].target_ref, seen + (ref,))
        if ref in self.step_by_id and self.step_by_id[ref].op in (AtomicOp.LOOKUP,):
            return set().union(*(self._root_operands(r, seen + (ref,)) for r in self.step_by_id[ref].inputs))
        return set()

    def _apply_multiplier(self, ref: str, f: Decimal, base: str):
        """원본 좌표에 적용 배수 기록 (operand · filter · LOOKUP 을 따라 원본 operand 까지)."""
        roots = self._root_operands(ref)
        for fact in self.res.intermediate_facts:
            if fact.operand_id in roots:
                fact.coordinate.applied_multiplier = _f(f)
                fact.coordinate.normalized_unit = base
                fact.coordinate.normalized_value = exact_str(Decimal(parse_value(fact.coordinate.raw_value).value) * f)

    # ── Filter ──
    def apply_filter(self, f: FilterSpec, stack) -> Vector:
        tgt, cond = self.get(f.target_ref, stack), self.get(f.condition_ref, stack)
        if not isinstance(tgt, Vector) or not isinstance(cond, Vector):
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{f.filter_id}: target/condition 은 벡터여야 함")
        self._join_check([f.target_ref, f.condition_ref], tgt, cond)
        if f.threshold_mode == "ABSOLUTE":
            pv = parse_value(f.threshold_value)
            if not pv.ok:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{f.filter_id}: threshold_value 숫자 아님")
            thr = pv.value
        else:
            if f.quantile is None:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{f.filter_id}: quantile 없음")
            vals = sorted(v for v, _, _ in cond.entries.values())
            idx = min(len(vals) - 1, max(0, math.ceil(f.quantile * len(vals)) - 1))
            thr = vals[idx]
            if f.nice_round and thr != 0:
                mag = Decimal(10) ** (abs(thr).adjusted() - 1)
                thr = (thr / mag).quantize(Decimal(1), rounding=ROUND_HALF_UP) * mag
        self.res.resolved_thresholds[f.filter_id] = make_numeric(thr, cond.unit, self.e.rounding)
        ops = {">": lambda a: a > thr, ">=": lambda a: a >= thr, "<": lambda a: a < thr, "<=": lambda a: a <= thr,
               "==": lambda a: a == thr, "!=": lambda a: a != thr}
        keep = {k for k, (v, _, _) in cond.entries.items() if ops[f.comparator](v)}
        common = set(tgt.entries) & set(cond.entries)
        sel = {k: v for k, v in tgt.entries.items() if k in keep and k in common}
        n_common = len(common)
        if not sel:
            raise CalculationError(CalcErrorCode.EMPTY_RESULT, f"{f.filter_id}: 조건을 만족하는 원소 없음")
        if len(sel) == n_common:
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR,
                                   f"{f.filter_id}: 모든 원소가 조건을 만족 → 조건 View 가 결과에 기여하지 않음 (기준값 조정 필요)")
        self.res.step_results.append(StepResult(
            step_id=f.filter_id, op="FILTER", formula=f"{f.condition_ref} {f.comparator} {exact_str(thr)}{cond.unit} → "
                                                       f"{len(sel)}/{n_common}개", input_refs=[f.target_ref, f.condition_ref],
            output_kind="VECTOR", vector=[VectorEntry(key_code=k, key_name=v[1], value=make_numeric(v[0], tgt.unit, self.e.rounding),
                                                      fact_ids=v[2] + cond.entries[k][2]) for k, v in sel.items()]))
        merged = {k: (v[0], v[1], v[2] + cond.entries[k][2]) for k, v in sel.items()}
        return Vector(merged, tgt.unit, tgt.level, tgt.dim_type, f.filter_id, tgt.view_id)

    def _join_check(self, refs: list[str], a: Vector, b: Vector):
        if a.dim_type != b.dim_type:
            raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE, f"{refs}: 키 분류 종류가 다름 {a.dim_type} vs {b.dim_type}")
        ka, kb = set(a.entries), set(b.entries)
        common = ka & kb
        mism = [{"code": k, "name_a": a.entries[k][1], "name_b": b.entries[k][1]} for k in sorted(common)
                if a.entries[k][1].replace(" ", "") != b.entries[k][1].replace(" ", "")]
        diag = JoinDiagnostics(refs=refs, n_left=len(ka), n_right=len(kb), n_joined=len(common), n_left_only=len(ka - kb),
                               n_right_only=len(kb - ka), duplicate_keys_left=0, duplicate_keys_right=0,
                               name_mismatches=mism)
        ops = [self.op_by_id.get(r) for r in refs]
        if all(ops) and ops[0].view_id != ops[1].view_id:
            diag.sql, n_rows, n_keys = self._sql_join_count(ops[0], ops[1], a.level, b.level)
            diag.amplified = n_rows > n_keys
        self.res.join_diagnostics.append(diag)
        if not common:
            raise CalculationError(CalcErrorCode.EMPTY_JOIN, f"{refs}: 공통 키 없음")
        if mism:
            raise CalculationError(CalcErrorCode.JOIN_CODE_SYSTEM_MISMATCH, f"{refs}: 같은 코드의 이름이 다름 {mism[:3]}")
        if diag.amplified:
            raise CalculationError(CalcErrorCode.JOIN_AMPLIFICATION, f"{refs}: Join 행 증폭")

    def _sql_join_count(self, oa: Operand, ob: Operand, la: str, lb: str) -> tuple[str, int, int]:
        """DuckDB 에서 Join 행 수와 고유 키 Join 수를 비교 → 행 증폭(다대다) 여부."""
        va, vb = self.e.index.view(oa.view_id), self.e.index.view(ob.view_id)
        ca, pa = self._where(oa, va)
        cb, pb = self._where(ob, vb)
        base = (f'WITH l AS (SELECT "{la}" AS k FROM {self.alias[oa.view_id]} WHERE {" AND ".join(ca)}), '
                f'r AS (SELECT "{lb}" AS k FROM {self.alias[ob.view_id]} WHERE {" AND ".join(cb)}) ')
        sql = base + ("SELECT (SELECT count(*) FROM l JOIN r ON l.k = r.k) AS n_rows, "
                      "(SELECT count(*) FROM (SELECT DISTINCT k FROM l) dl JOIN (SELECT DISTINCT k FROM r) dr ON dl.k = dr.k) AS n_keys")
        df = self.e.execute(self.con, sql, pa + pb)
        inl = self._inline(sql, pa + pb)
        self.res.executed_sql.append(inl)
        return inl, int(df["n_rows"].iloc[0]), int(df["n_keys"].iloc[0])

    # ── Steps ──
    def apply_step(self, s: OperationStep, stack):
        ins = [self.get(r, stack) for r in s.inputs]
        op = s.op
        if op == AtomicOp.LOOKUP:
            if len(ins) != 1 or not isinstance(ins[0], Scalar):
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: LOOKUP 은 스칼라 1개")
            x = ins[0]
            self._record(s, f"{s.inputs[0]} = {exact_str(x.value)}{x.unit}", scalar=x)
            return x
        if op in (AtomicOp.DIFFERENCE, AtomicOp.GROWTH_RATE, AtomicOp.SHARE_RATIO, AtomicOp.PERCENTAGE_POINT_DIFFERENCE):
            if len(ins) != 2:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: {op.value} 는 입력 2개")
            return self._binary(s, ins[0], ins[1])
        if op in (AtomicOp.SUM, AtomicOp.MEAN, AtomicOp.MIN, AtomicOp.MAX, AtomicOp.TOP_K, AtomicOp.COUNT):
            if len(ins) != 1 or not isinstance(ins[0], Vector):
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: {op.value} 는 벡터 1개")
            return self._aggregate(s, ins[0])
        if op == AtomicOp.WEIGHTED_MEAN:
            if len(ins) != 2 or not all(isinstance(x, Vector) for x in ins):
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: WEIGHTED_MEAN 은 (값 벡터, 가중치 벡터)")
            v, w = ins
            self._join_check(list(s.inputs), v, w)
            keys = sorted(set(v.entries) & set(w.entries))
            if unit_info(w.unit).kind not in (ValueKind.COUNT, ValueKind.AMOUNT):
                raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE, f"{s.step_id}: 가중치는 합산 가능한 수량이어야 함")
            out = weighted_mean([v.entries[k][0] for k in keys], [w.entries[k][0] for k in keys])
            sc = Scalar(out.value, v.unit, [f for k in keys for f in v.entries[k][2] + w.entries[k][2]])
            self._record(s, out.formula, scalar=sc)
            return sc
        raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: 지원하지 않는 연산 {op}")

    def _binary(self, s: OperationStep, a, b):
        if isinstance(a, Vector) or isinstance(b, Vector):
            return self._binary_vector(s, a, b)
        if not (isinstance(a, Scalar) and isinstance(b, Scalar)):
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: 스칼라/벡터 입력이 아님")
        value, unit, formula = self._binary_values(s, a.value, a.unit, b.value, b.unit, s.inputs)
        sc = Scalar(value, unit, a.fact_ids + b.fact_ids)
        self._record(s, formula, scalar=sc)
        return sc

    def _binary_values(self, s, av, au, bv, bu, refs) -> tuple[Decimal, str, str]:
        op = s.op
        if op == AtomicOp.PERCENTAGE_POINT_DIFFERENCE:
            if not (au == "%" and bu == "%"):
                raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, f"{s.step_id}: %p 차이는 두 값이 모두 % 단위여야 함 ({au}, {bu})")
            out = percentage_point_difference(av, bv)
            return out.value, "%p", out.formula
        if op == AtomicOp.SHARE_RATIO:
            scale = Decimal(str(s.params.get("scale", 100)))
            ia, ib = unit_info(au), unit_info(bu)
            if au in ("%", "%p") or bu in ("%", "%p") or not (ia.additive and ib.additive):
                raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE,
                                       f"{s.step_id}: 비율·평균 단위({au}, {bu})로 비율을 만들지 않음")
            if ia.family == ib.family:
                (fa, fb), base = self._align_units(list(refs), [au, bu], op)
                if scale != 100:
                    raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: 같은 단위 계열 비율은 scale=100 (%)")
                out = share_ratio(av * fa, bv * fb, scale)
                return out.value, "%", out.formula + " (%)"
            # 서로 다른 계열: 분모를 기본 단위로 맞춘 뒤 '분자기본/스케일분모기본'
            fa = conversion_factor(au, ia.base_unit) if ia.known else None
            fb = conversion_factor(bu, ib.base_unit) if ib.known else None
            if fa is None or fb is None:
                raise CalculationError(CalcErrorCode.UNIT_INCOMPATIBLE, f"{s.step_id}: 알 수 없는 단위 {au}, {bu}")
            for r, u, f, base in ((refs[0], au, fa, ia.base_unit), (refs[1], bu, fb, ib.base_unit)):
                self._check_declared(r, u, base)
                if f != 1:
                    self._trace(r, u, base, f, "비율 계산 전 기본 단위로")
            if scale not in SCALE_LABEL:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: scale 은 {sorted(SCALE_LABEL)} 중 하나")
            out = share_ratio(av * fa, bv * fb, scale)
            return out.value, f"{ia.base_unit}/{SCALE_LABEL[scale]}{ib.base_unit}", out.formula
        # DIFFERENCE / GROWTH_RATE
        if au == "%" or bu == "%":
            if op == AtomicOp.DIFFERENCE:
                raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR,
                                       f"{s.step_id}: % 값의 차이는 PERCENTAGE_POINT_DIFFERENCE 를 사용")
            if op == AtomicOp.GROWTH_RATE:
                raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE,
                                       f"{s.step_id}: 비율(%)의 증감률 대신 %p 차이를 사용")
        (fa, fb), base = self._align_units(list(refs), [au, bu], op)
        if op == AtomicOp.DIFFERENCE:
            out = difference(av * fa, bv * fb)
            return out.value, base, out.formula
        out = growth_rate(av * fa, bv * fb)
        return out.value, "%", out.formula

    def _binary_vector(self, s, a, b) -> Vector:
        if isinstance(a, Vector) and isinstance(b, Vector):
            self._join_check(list(s.inputs), a, b)
            keys = [k for k in a.entries if k in b.entries]
            get_b = lambda k: b.entries[k]                       # noqa: E731
            unit_b, base = b.unit, a
        elif isinstance(a, Vector) and isinstance(b, Scalar):
            keys = list(a.entries)
            get_b = lambda k: (b.value, "", b.fact_ids)          # noqa: E731
            unit_b, base = b.unit, a
        else:
            raise CalculationError(CalcErrorCode.PLAN_STRUCTURE_ERROR, f"{s.step_id}: (스칼라, 벡터) 순서 미지원")
        entries, unit, formulas = {}, None, []
        for k in keys:
            av, name, fa = base.entries[k]
            bv, _, fb = get_b(k)
            v, u, f = self._binary_values(s, av, a.unit, bv, unit_b, s.inputs)
            entries[k] = (v, name, fa + fb)
            unit = u
            formulas.append(f"{name}: {f}")
        vec = Vector(entries, unit or a.unit, a.level, a.dim_type, s.step_id, a.view_id)
        self._record(s, f"{s.op.value} (원소별) " + "; ".join(formulas[:12]) + (" …" if len(formulas) > 12 else ""), vector=vec)
        return vec

    def _aggregate(self, s: OperationStep, v: Vector):
        op = s.op
        vals = [x[0] for x in v.entries.values()]
        kind = result_kind(v.unit)
        if op in (AtomicOp.SUM, AtomicOp.MEAN) and kind not in (ValueKind.COUNT, ValueKind.AMOUNT):
            raise CalculationError(CalcErrorCode.STATISTICALLY_INCOMPATIBLE,
                                   f"{s.step_id}: {v.unit} 단위(비율·평균·지수)는 단순 {op.value} 하지 않음")
        facts = [f for x in v.entries.values() for f in x[2]]
        if op == AtomicOp.SUM:
            out = sum_values(vals)
            sc = Scalar(out.value, v.unit, facts)
            self._record(s, out.formula, scalar=sc)
            return sc
        if op == AtomicOp.MEAN:
            out = mean_values(vals)
            sc = Scalar(out.value, v.unit, facts)
            self._record(s, out.formula, scalar=sc)
            return sc
        if op == AtomicOp.COUNT:
            sc = Scalar(Decimal(len(vals)), "개", facts)
            self._record(s, f"count({', '.join(x[1] for x in v.entries.values())}) = {len(vals)}", scalar=sc)
            return sc
        items = [(k, x[0]) for k, x in v.entries.items()]
        disp = make_numeric(vals[0], v.unit, self.e.rounding).display_digits if vals else 2

        def shown(x: Decimal) -> Decimal:           # 표시 자릿수에서 같아 보이면 순위가 모호
            return _q(x, disp)
        if op in (AtomicOp.MIN, AtomicOp.MAX):
            r = rank_values(items, "DESC" if op == AtomicOp.MAX else "ASC")
            if len(r) > 1 and shown(r[0][2]) == shown(r[1][2]):
                raise CalculationError(CalcErrorCode.AMBIGUOUS_RESULT, f"{s.step_id}: {op.value} 동점 → 정답이 하나가 아님")
            _, code, val = r[0]
            ent = Entity(code, v.entries[code][1], val, v.unit)
            self._record(s, f"{op.value} = {ent.name} ({exact_str(val)}{v.unit})", entity=ent)
            return ent
        k = int(s.params.get("k", 3))
        order = str(s.params.get("order", "DESC")).upper()
        top, tie = top_k_values(items, k, order)
        ranked = rank_values(items, order)
        shown_tie = any(shown(ranked[i][2]) == shown(ranked[i + 1][2]) for i in range(min(k, len(ranked) - 1)))
        if tie or shown_tie:
            raise CalculationError(CalcErrorCode.AMBIGUOUS_RESULT, f"{s.step_id}: TOP_{k} 경계에 동점 → 정답이 하나가 아님")
        rk = Ranking([(r, c, v.entries[c][1], val) for r, c, val in top], v.unit)
        self._record(s, f"TOP_{k}({order}) = " + ", ".join(f"{r}. {n} {exact_str(val)}{v.unit}" for r, _, n, val in rk.entries),
                     ranking=rk)
        return rk

    def _record(self, s: OperationStep, formula: str, scalar: Scalar | None = None, vector: Vector | None = None,
                entity: Entity | None = None, ranking: Ranking | None = None):
        r = self.e.rounding
        sr = StepResult(step_id=s.step_id, op=s.op.value, formula=formula, input_refs=list(s.inputs),
                        output_kind="SCALAR" if scalar else "VECTOR" if vector else "ENTITY" if entity else "RANKING")
        if scalar:
            sr.scalar = make_numeric(scalar.value, scalar.unit, r)
            sr.formula += f" = {sr.scalar.exact_decimal}{scalar.unit}"
        if vector:
            sr.vector = [VectorEntry(key_code=k, key_name=x[1], value=make_numeric(x[0], vector.unit, r), fact_ids=x[2])
                         for k, x in vector.entries.items()]
        if entity:
            sr.ranking = [RankedEntry(rank=1, key_code=entity.code, key_name=entity.name,
                                      value=make_numeric(entity.value, entity.unit, r))]
        if ranking:
            sr.ranking = [RankedEntry(rank=a, key_code=c, key_name=n, value=make_numeric(v, ranking.unit, r))
                          for a, c, n, v in ranking.entries]
        self.res.step_results.append(sr)

    def _run_sql_plan(self, sql: str):
        if not self.e.allow_sql_plan:
            raise CalculationError(CalcErrorCode.SQL_SAFETY_VIOLATION, "sql_plan 은 설정(allow_sql_plan)에서 허용되지 않음")
        cols = set()
        for vid in self.alias:
            cols |= set(self.e.index.load_frame(vid).columns)
        errs = SqlSafetyValidator(set(self.alias.values()), cols).validate(sql)
        if errs:
            raise CalculationError(CalcErrorCode.SQL_SAFETY_VIOLATION, "; ".join(errs))
        self.e.execute(self.con, sql, [])
        self.res.executed_sql.append(sql)
