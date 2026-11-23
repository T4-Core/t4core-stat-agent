"""좌표 → Record 행 resolver (계획 2.2.1, D-22 · D-25 · D-26)

binding 복원 · operands_valid · MT-3a 변형 Record 갱신이 같은 함수를 쓴다.
행을 하나로 특정하지 못하면 판단하지 않고 호출자에게 '모호함' 을 돌려준다.
"""
import re
from dataclasses import dataclass, field
from typing import Any

from eval.generator.checks.normalize import convertible
from eval.generator.trace import table, value_index

PERIOD_COL = "시점"
ITEM_COL = "항목"
REGION_HINTS = ("행정구역", "시도", "시군구", "지역", "읍면동")
MISSING = {None, "", "-", "x", "X", "…", "..."}
UNIT_RE = re.compile(r"\(([^()]{1,8})\)\s*$")
KNOWN_UNITS = {"명", "건", "가구", "개", "호", "%", "%p", "천명", "만명", "천가구", "천호", "원", "천원", "백만원", "십억원",
               "억원", "조원", "세", "년", "㎡", "㎢", "ha", "kg", "톤", "대", "배", "‰", "천명당"}
SAME_UNIT_OPS = {"diff", "combine", "share"}          # calculate.py: _pair(..., same_unit=True) · _combine · _share
SAME_PERIOD_OPS = {"share", "diff", "ratio", "combine"}
DENOMINATOR_OPS = {"share", "ratio"}
BASE_OPS = {"growth_rate", "cagr", "index"}           # 첫 값이 기준값 (0 이면 계산 불가)


def norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s)) if s is not None else ""


def label_eq(want: Any, got: Any) -> bool:
    """서울 ↔ 서울특별시, 출생아수 ↔ 출생아수(명). 짧은 쪽이 2글자 이상이고 긴 쪽의 앞부분이면 같다"""
    a, b = norm(want), norm(got)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and long_.startswith(short)


def item_match(want: Any, got: Any) -> bool:
    a, b = norm(want), norm(got)
    return bool(a) and (a == b or a in b)


def period_eq(want: Any, got: Any) -> bool:
    a, b = norm(want), norm(got)
    return a == b or (a.isdigit() and b.replace(".0", "") == a)


def region_cols(columns: list[str]) -> list[str]:
    return [c for c in columns if any(h in c for h in REGION_HINTS)]


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


@dataclass
class Row:
    record_id: str
    cols: dict[str, Any]
    value: Any
    record: dict = field(repr=False, default_factory=dict)

    def coord(self) -> dict[str, Any]:
        """행의 전체 좌표: period · item · region + 나머지 차원 열 그대로"""
        cols = dict(self.cols)
        out: dict[str, Any] = {}
        if PERIOD_COL in cols:
            out["period"] = str(cols.pop(PERIOD_COL))
        if ITEM_COL in cols:
            out["item"] = cols.pop(ITEM_COL)
        for c in region_cols(list(cols)):
            out.setdefault("region", cols.pop(c))
        out.update(cols)
        return out


def rows_of(rec: dict) -> list[Row]:
    columns, rows = table(rec)
    if not columns:
        return []
    vi = value_index(columns)
    out = []
    for r in rows:
        cols = {c: r[i] for i, c in enumerate(columns) if i != vi and i < len(r)}
        out.append(Row(rec.get("id", ""), cols, r[vi] if vi < len(r) else None, rec))
    return out


def _matches(row: Row, coord: dict[str, Any]) -> bool:
    cols = row.cols
    names = list(cols)
    for k, want in coord.items():
        if want is None:
            continue
        if k == "period":
            if PERIOD_COL not in cols or not period_eq(want, cols[PERIOD_COL]):
                return False
        elif k == "item":
            # 지표 이름이 '항목' 열이 아니라 분류 열(종류별 · 기본항목별)에 있는 View 가 있다 (schemas/chart.py Operand.item 주석)
            if not any(item_match(want, cols[c]) for c in names if c != PERIOD_COL):
                return False
        elif k == "region":
            cand = region_cols(names) or [c for c in names if c not in (PERIOD_COL, ITEM_COL)]
            if not any(label_eq(want, cols[c]) for c in cand):
                return False
        else:
            if k not in cols or norm(cols[k]) != norm(want):
                return False
    return True


def find(records: list[dict], coord: dict[str, Any]) -> list[Row]:
    coord = {k: v for k, v in coord.items() if v is not None}
    return [r for rec in records for r in rows_of(rec) if _matches(r, coord)]


def _total_like(row: Row, coord: dict) -> bool:
    """좌표가 고르지 않은 차원 중 '계 · 전체 · 합계' 값만 남기는 규칙 (지정하지 않은 차원은 합계 행을 뜻한다)"""
    keys = {"period": PERIOD_COL, "item": ITEM_COL}
    used = {keys.get(k, k) for k in coord}
    if "region" in coord:
        used |= set(region_cols(list(row.cols)))
    for c, v in row.cols.items():
        if c in used or c == PERIOD_COL:
            continue
        if norm(v) not in ("계", "전체", "합계", "총계", "소계", "전국"):
            return False
    return True


def find_one(records: list[dict], coord: dict[str, Any]) -> tuple[Row | None, str | None]:
    """정확히 한 행. 여러 행이면 지정하지 않은 차원이 합계(계)인 행으로 좁힌다. 그래도 여럿이면 ambiguous_row"""
    hits = find(records, coord)
    if not hits:
        return None, "missing"
    if coord.get("item") and len(hits) > 1:
        # '출생아수' 가 '모의 연령별 출생아수(명):15-19세' 에도 부분 일치한다 → 앞부분이 같은 항목을 우선
        prefix = [h for h in hits if any(label_eq(coord["item"], v) for c, v in h.cols.items() if c != PERIOD_COL)]
        hits = prefix or hits
    by_record: dict[str, list[Row]] = {}
    for h in hits:
        by_record.setdefault(h.record_id, []).append(h)
    for rid, hs in by_record.items():
        if len(hs) > 1:
            totals = [h for h in hs if _total_like(h, coord)]
            by_record[rid] = totals if len(totals) == 1 else hs
    singles = [hs[0] for hs in by_record.values() if len(hs) == 1]
    if singles:
        return singles[0], None          # ViewSet 안 어느 Record 든 하나로 특정되면 참 (2.2.1)
    return None, "ambiguous_row"


def row_unit(row: Row) -> str | None:
    """항목 이름 끝 괄호의 단위 (항목 열 우선, 없으면 분류 열의 지표 이름) → 없으면 Record 의 단일 단위"""
    vals = ([row.cols[ITEM_COL]] if ITEM_COL in row.cols else []) + [v for c, v in row.cols.items() if c not in (ITEM_COL, PERIOD_COL)]
    for v in vals:
        if v and (m := UNIT_RE.search(str(v))) and m.group(1).strip() in KNOWN_UNITS:
            return m.group(1).strip()
    u = ((row.record.get("metadata") or {}).get("unit") or row.record.get("unit") or "").strip()
    return u if u and len(u.split()) == 1 else None


def row_cycle(row: Row) -> str | None:
    md = row.record.get("metadata") or {}
    return md.get("prd_se") or (row.record.get("source") or {}).get("prd_se") or _cycle_from_id(row.record_id)


def _cycle_from_id(rid: str) -> str | None:
    parts = (rid or "").split("::")
    return parts[2] if len(parts) > 2 and parts[0] == "view" else None


@dataclass
class Pred:
    ok: bool
    reason: str | None = None
    tags: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def operands_valid(records: list[dict], operands: list[dict], denominator: dict | None = None,
                   op: str | None = None, result_unit: str | None = None) -> Pred:
    """계획 2.2.1. 처음 실패한 검사의 사유 코드를 돌려준다"""
    found: list[tuple[str, Row]] = []
    for role, coords in (("operand", operands), ("denominator", [denominator] if denominator else [])):
        for c in coords:
            row, why = find_one(records, c)
            if row is None:
                if why == "ambiguous_row":
                    return Pred(False, "ambiguous_row", ["manual"], {"coord": c})
                return Pred(False, "missing_denominator" if role == "denominator" else "missing_operand", [], {"coord": c})
            found.append((role, row))
    for _, r in found:
        if r.value in MISSING or not is_number(r.value):
            return Pred(False, "missing_value", [], {"coord": r.coord()})
    den = [r for role, r in found if role == "denominator"]
    if op in DENOMINATOR_OPS:
        den = den or [r for _, r in found[1:2]]
    if op in BASE_OPS and found:
        den = [found[0][1]]
    if any(r.value == 0 for r in den):
        return Pred(False, "zero_denominator")
    if op in SAME_PERIOD_OPS and len({norm(r.cols.get(PERIOD_COL)) for _, r in found}) > 1:
        return Pred(False, "period_mismatch")
    cycles = [row_cycle(r) for _, r in found]
    if len({c for c in cycles if c}) > 1 or (any(cycles) and not all(cycles)):
        return Pred(False, "cycle_mismatch", [], {"cycles": cycles})
    if op in SAME_UNIT_OPS:
        units = [row_unit(r) for _, r in found]
        if all(units):
            if len(set(units)) > 1:
                tags = ["convertible_unit"] if all(convertible(units[0], u) or u == units[0] for u in units) else []
                return Pred(False, "unit_mismatch", tags, {"units": units})
        elif any(units):
            return Pred(False, "unit_mismatch", [], {"units": units})
        elif len({norm(r.cols.get(ITEM_COL)) for _, r in found}) > 1:
            return Pred(False, "unit_mismatch", [], {"units": units, "why": "단위를 모르는 다른 항목"})
    if op == "ratio" and result_unit:
        a, b = (row_unit(found[0][1]), row_unit(found[1][1])) if len(found) >= 2 else (None, None)
        got = "배" if a == b else (f"{a}/{b}" if a and b else None)
        if got != result_unit:
            return Pred(False, "unit_mismatch", [], {"expected_result_unit": result_unit, "got": got})
    if op == "share" and den:
        part = [r for role, r in found if role == "operand"]
        if part and not _same_population(part[0], den[0]):
            return Pred(False, "population_mismatch")
    return Pred(True)


def _same_population(a: Row, b: Row) -> bool:
    """비교 차원(지역)을 뺀 나머지 차원이 같은가. 같은 열이 있을 때만 본다"""
    skip = {PERIOD_COL, ITEM_COL} | set(region_cols(list(a.cols))) | set(region_cols(list(b.cols)))
    for c in set(a.cols) & set(b.cols):
        if c in skip:
            continue
        if norm(a.cols[c]) != norm(b.cols[c]):
            return False
    return True


def resolve_input(records: list[dict], inp: dict, select: dict[str, list] | None = None) -> tuple[Row | None, str | None]:
    """CalcInput(record_id + item + key) + 단계의 select → 원본 행. key 는 고정 차원을 생략하므로 select 로 보완한다 (D-25)"""
    rec = next((r for r in records if r.get("id") == inp.get("record_id")), None)
    if rec is None:
        return None, "no_record"
    cand = rows_of(rec)
    key = inp.get("key") or {}
    for col, want in key.items():
        cand = [r for r in cand if col in r.cols and (period_eq(want, r.cols[col]) if col == PERIOD_COL else norm(r.cols[col]) == norm(want))]
    if inp.get("item"):
        dims = lambda r: [v for c, v in r.cols.items() if c != PERIOD_COL]  # noqa: E731
        exact = [r for r in cand if any(norm(v) == norm(inp["item"]) for v in dims(r))]
        cand = exact or [r for r in cand if any(item_match(inp["item"], v) for v in dims(r))]
    # 값으로 먼저 좁힌다: 단계의 select 는 분자 피연산자의 것이라 분모(total) 입력에는 맞지 않을 수 있다
    if inp.get("value") is not None:
        same = [r for r in cand if is_number(r.value) and abs(float(r.value) - float(inp["value"])) < 1e-9]
        if len(same) == 1:
            return same[0], None
        if same:
            cand = same
    for col, vals in (select or {}).items():
        if col in key or col == ITEM_COL and inp.get("item"):
            continue
        vs = {norm(v) for v in (vals if isinstance(vals, list) else [vals])}
        narrowed = [r for r in cand if col in r.cols and norm(r.cols[col]) in vs]
        if narrowed:
            cand = narrowed
    if len(cand) == 1:
        return cand[0], None
    return None, "missing" if not cand else "ambiguous_row"


def select_of(steps: list[dict], step_id: str, record_id: str) -> dict:
    """answer_steps 에서 그 단계 · 그 Record 를 고른 피연산자의 select 합집합"""
    out: dict[str, list] = {}
    for s in steps or []:
        if s.get("step_id") != step_id:
            continue
        for o in s.get("operands") or []:
            if o.get("record_id") == record_id:
                for k, v in (o.get("select") or {}).items():
                    out.setdefault(k, [])
                    out[k] += v if isinstance(v, list) else [v]
    return out
