"""
[NEW] 계획 세우기 (규칙 부분) — HCX 의 결정(Decision) + 모듈 2 의 charts[] → ChartPlan + displays

  역할 분담 (명세 4장)
    HCX   Decision 만 정한다: 어느 View 의 어느 행을 쓸지(record_id·select·item), 기간, 분모 범위, 질문용 연산
    규칙  나머지를 채운다: step_id, 갈래 나누기, output, 단위, display_ref, 구성비 분모 기본값

  이 파일은 HCX 를 부르지 않는다. Decision 을 만드는 쪽(HCX 호출·응답 파싱)은 decide.py (6b 단계).

  바로잡기: HCX 응답에서 규칙으로 확실히 고칠 수 있는 실수는 계획을 만들기 전에 고치고 notes 에 남긴다 (_Planner.normalize_*).
    - 피연산자가 아닌 것 (role "join_on", item 이 열 이름) → 버림
    - 피연산자 1개짜리 연산에 같은 항목을 여럿으로 쪼갬 → 조건을 합쳐 하나로
    - 기간 연산(from·to·base)인데 시점 조건에 그 시점이 없음 → 시점 조건에 보탬
    - 갈래가 여럿인 차트(combo …)의 역할이 그 차트에 없음 → 빈 역할에 순서대로
    - QueryBundle 필터의 시점·지역은 고정: 밖의 값을 고르면 고정 값으로 바꾼다 (fix_time, fix_region)
    - 증감·증감률(change·growth_rate)은 View 에 있는 시점마다 직전 시점 대비 (base "prev").
      시점 조건은 고정 시점(없으면 View 의 모든 시점). 시점이 둘이면 결과 하나, 다섯이면 넷
      구성비의 분모(denominator)는 고정하지 않는다 ('전국 대비 서울' 의 전국은 지역 필터 밖이어도 필요하다)
    - 질문에 연령 범위가 있고(미취학아동 = 0~5세) raw 가 나이별 행 여럿을 고르면 → 합계(aggregate sum) 하나로 (질문용·차트 모두)
    - aggregate 는 시점마다 따로 합친다 (by 시점). 여러 해를 한데 더하지 않는다
    - item 에 지표가 아니라 범주 값(0세, 서울특별시, 남자)을 적으면 → 그 열의 조건으로 옮긴다
    - 질문의 연령 범위(0~5세) 안에서 일부 나이만 고르면(['0세']) → View 의 그 범위 나이 전체로 (fix_age)
    - 같은 하위 질문·같은 연산·같은 View·같은 항목의 질문용 계산이 여럿이면 → 하나로 합친다
      (2026-11-11 '최근 2년 미취학아동수': HCX 가 나이마다 raw 를 하나씩 6개 만들어 응답이 출력 한도에서 끊겼다)
    (2026-11-10 테스트 화면 첫 실행에서 나온 실수들. tests/chart_calculate/test_hcx_regression.py)

  검증 방침: HCX 가 없는 열·값을 골라도 계획에서 빼지 않는다. 그대로 실행하면 계산 단계가 None + 사유로 처리하고
            (차트는 validation 의 data_present 실패), 여기서는 같은 사유를 ChartPlan.notes 에 미리 적어 QA 가 보게 한다.
"""
import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.chart_calculate.calculate import SELECTED_LABEL, TIME_COL
from backend.agent.chart_calculate.validate import TOTAL_LABELS
from backend.agent.chart_calculate.display import STANDARD_UNITS, make_display, register, result_unit, unit_of
from backend.agent.chart_calculate.select import AGE_HINTS, CATEGORY_HINTS, ITEM_COL, REGION_HINTS, VALUE_COL, select_rows
from backend.schemas.chart import (ChartPlan, ChartRequest, Denominator, Display, Measure, Operand, Plan, PlanOutput,
                                   Role, Select, Step)
from backend.schemas.query import Filters, QueryBundle
from backend.schemas.record import Record

CHART_ROLES = set(get_args(Role))
TWO_OPERAND = {"diff", "ratio"}        # 피연산자 둘(a, b)을 한 단계에서 쓰는 연산
MULTI_OPERAND = TWO_OPERAND | {"combine"}   # 피연산자 여럿을 한 단계에서 쓰는 연산. 나머지 연산은 피연산자 1개
PERIOD_OPS = {"change", "growth_rate", "cagr", "index"}   # from·to·base 시점이 행에 있어야 하는 연산
# 갈래가 여럿인 차트: 갈래마다 축 역할 하나 (specs.SPECS 의 필수 역할 중 열에 연결되는 것, 순서대로)
MULTI_BRANCH = {"combo": ("y", "y2"), "scatter": ("x", "y"), "bubble": ("x", "y", "size"), "dumbbell": ("start", "end")}
REGION = "지역"                        # 고정 조건의 지역 키 (View 의 지역 열 이름은 표마다 다르다)
GROWTH_OPS = {"change", "growth_rate"}
AGE = "연령"                           # 고정 조건에 함께 싣는 참고 값 (합계 판단용, 고정하지는 않는다)
INTENT = "의도"
# [MOVED 11-11] AGE_HINTS · CATEGORY_HINTS → select.py
PER_CATEGORY_INTENTS = {"비교", "순위"}  # 범주끼리 견주는 질문은 합치지 않는다
_AGE = re.compile(r"(\d+)\s*(?:[-~]\s*(\d+))?\s*세(\s*이상)?")


def age_span(label: str) -> tuple[int, int | None] | None:
    """'0세' → (0, 0), '15~19세' → (15, 19), '65세 이상' → (65, None). 나이가 아니면 None ('계', '합계')"""
    m = _AGE.fullmatch(label.strip())
    if not m:
        return None
    lo = int(m[1])
    return lo, (None if m[3] else int(m[2] or lo))


TITLE_MAX = 40
_NUMBER = re.compile(r"\d[\d,.]*")
_OK_NUMBER = re.compile(r"(19|20)\d{2}|\d{1,3}")     # 연도, 나이·기간 같은 작은 정수만


def clean_title(title: str | None) -> tuple[str | None, str | None]:
    """HCX 제목 검사 → (쓸 제목, 버린 사유). 계산 값(1,551,484 / 24.8)이 제목에 들어가지 않게 숫자를 본다"""
    t = " ".join((title or "").split())
    if not t:
        return None, None
    if len(t) > TITLE_MAX:
        return None, f"제목이 {TITLE_MAX}자를 넘음"
    if bad := [n for n in _NUMBER.findall(t) if not _OK_NUMBER.fullmatch(n)]:
        return None, f"제목에 연도·나이가 아닌 숫자 {bad}"
    return t, None


def sub_question_ids(bundle: QueryBundle) -> list[tuple[str, str]]:
    """[(하위 질문 ID, 문장)]. 하위 질문이 없으면 원 질문 하나

    TODO(임시): 하위 질문 ID 형식은 확정 전이다 (명세 9장 'Record.id 형식'). 지금은 '{query_id}-{순번}'.
    """
    qid = bundle.query_id or "q"
    return [(f"{qid}-{i}", s) for i, s in enumerate(bundle.sub_questions or [bundle.original], 1)]


def _fixed_of(f: Filters | None) -> dict[str, list[str]]:
    """필터에서 코드로 고정할 것: 시점·지역. 대상은 View 의 열 값이 아니라 프롬프트로만 고정한다"""
    out: dict[str, list[str]] = {}
    if f and f.시점:
        out[TIME_COL] = sorted(str(y) for y in f.시점)
    if f and f.지역:     # 지역이 없으면(= 전국 또는 '시도별' 같은 비교) 고정하지 않는다
        out[REGION] = list(f.지역)
    if f and f.연령 and (f.연령.from_ is not None or f.연령.to is not None):
        out[AGE] = [str(f.연령.from_ or 0), "" if f.연령.to is None else str(f.연령.to)]
    if f and f.의도:
        out[INTENT] = [f.의도]
    return out


def fixed_conditions(bundle: QueryBundle | None) -> dict[str, dict[str, list[str]]]:
    """하위 질문 ID → 고정 조건. 하위 질문마다 sub_filters 가 있으면 그것, 없으면 상위 filters"""
    if bundle is None:
        return {}
    main, subs = _fixed_of(bundle.filters), bundle.sub_filters or []
    return {sid: (_fixed_of(subs[i]) if i < len(subs) and subs[i] is not None else main)
            for i, (sid, _) in enumerate(sub_question_ids(bundle))}


# ── HCX 가 정하는 것 ─────────────────────────────────────────────
class Pick(BaseModel):
    """View 에서 값을 가져올 곳 하나"""
    model_config = ConfigDict(coerce_numbers_to_str=True)
    role: str | None = Field(None, description="차트 갈래면 축 역할(y, y2, x, size, start, end), "
                                               "계산 피연산자면 a·b·value·part. 비우면 순서로 정한다")
    record_id: str
    item: str | None = None
    select: Select = Field(default_factory=dict)
    sign: Literal["+", "-"] | None = Field(None, description="combine 전용: + 더하기, - 빼기 (생략하면 +)")
    unit: str | None = Field(None, description="HCX 가 고른 단위. item 괄호 단위가 없을 때만 쓰고, View metadata.unit 안에 있어야 한다")


class _Args(BaseModel):
    """연산 인자 (Step 과 같은 이름). LLM 이 연도를 숫자로 줘도 문자열로 받는다"""
    model_config = ConfigDict(populate_by_name=True, coerce_numbers_to_str=True)
    join_on: list[str] | None = None
    denominator: Denominator | None = None
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    base: str | None = None
    agg: str | None = None
    top_n: int | None = None

    def step_args(self) -> dict:
        return {k: v for k, v in self.model_dump(include=set(_Args.model_fields)).items() if v is not None} \
            | ({"denominator": self.denominator} if self.denominator else {})


class ChartDecision(_Args):
    chart_id: str
    title: str | None = Field(None, description="질문의 말로 쓴 차트 제목 (검사를 통과하면 Plan.title)")
    record_id: str | None = Field(None, description="기본 View. operands 가 있으면 비워도 된다 (첫 피연산자의 View)")
    select: Select = Field(default_factory=dict)
    operands: list[Pick] = Field(default_factory=list, description="갈래가 여럿(combo·scatter·bubble)이거나 "
                                                                   "View 가 여럿(diff·ratio)일 때만 적는다")


class AnswerDecision(_Args):
    sub_question_id: str | None = None
    op: Measure
    operands: list[Pick] = Field(default_factory=list)


class Decision(BaseModel):
    charts: list[ChartDecision] = Field(default_factory=list)
    answers: list[AnswerDecision] = Field(default_factory=list)


# ── 규칙 ─────────────────────────────────────────────────────────
class _Planner:
    def __init__(self, records: list[Record], fixed: dict[str, dict[str, list[str]]] | None = None):
        self.records = {r.id: r for r in records}
        self.fixed = fixed or {}
        self.displays: dict[str, Display] = {}
        self.notes: list[str] = []

    def note(self, tag: str, text: str):
        self.notes.append(f"{tag}: {text}")

    def check(self, tag: str, record_id: str, select: Select, item: str | None):
        """고른 열·값이 View 에 실제로 있는지. 없으면 notes 에만 적는다 (파일 설명의 '검증 방침')"""
        rec = self.records.get(record_id)
        if rec is None:
            self.note(tag, f"View 없음: {record_id}")
            return
        for err in select_rows(rec, select, item).errors:
            self.note(tag, err)

    def unit(self, record_id: str, item: str | None, select: Select) -> str | None:
        rec = self.records.get(record_id)
        if item is None and len(items := select.get(ITEM_COL) or []) == 1:
            item = str(items[0])
        return unit_of(item, rec.metadata.get("unit") if rec else None)

    def ref(self, op: str, units: list[str | None]) -> str:
        """결과 단위로 표시 설정을 등록 → display_ref. 같은 단위의 결과는 같은 키를 쓴다

        TODO(후속): 표시 단위 환산(192,507건 → 19.3만 건)은 아직 누가 정할지 없다. 지금은 원 단위 그대로(unit_scale 1).
        """
        if op == "ratio" and len(units) == 2 and units[0] != units[1]:
            unit = f"{units[0]}/{units[1]}"                 # calculate._pair 와 같은 규칙
        else:
            unit = result_unit(op, units[0] if units else None)
        return register(self.displays, make_display(unit))

    # ── 바로잡기 ─────────────────────────────────────────────────
    def drop_non_operands(self, tag: str, picks: list[Pick]) -> list[Pick]:
        """HCX 가 join_on 같은 연산 인자를 피연산자로 적은 것 (role "join_on", item 이 View 의 열 이름)"""
        keep = []
        for p in picks:
            rec = self.records.get(p.record_id)
            if p.role == "join_on" or (rec is not None and p.item in rec.table.columns):
                self.note(tag, f"피연산자가 아님 → 버림 (role={p.role}, item={p.item})")
            else:
                keep.append(p)
        return keep

    def category_item_to_condition(self, tag: str, picks: list[Pick], quiet: bool = False) -> list[Pick]:
        """item 에 범주 값을 적은 것 → 그 열의 조건으로. item 이 '항목' 열에 있으면 그대로 (진짜 지표)"""
        out, moved = [], {}
        for p in picks:
            rec = self.records.get(p.record_id)
            if rec is None or p.item is None:
                out.append(p)
                continue
            cols, rows = rec.table.columns, rec.table.rows
            in_col = lambda c: c in cols and any(str(r[cols.index(c)]) == p.item for r in rows)  # noqa: E731
            if in_col(ITEM_COL):
                out.append(p)
                continue
            col = next((c for c in cols if any(h in c for h in CATEGORY_HINTS) and in_col(c)), None)
            if col is None:
                out.append(p)
                continue
            have = [str(v) for v in p.select.get(col, [])]
            moved.setdefault(col, []).append(p.item)
            out.append(p.model_copy(update={"item": None, "select": {**p.select, col: list(dict.fromkeys(have + [p.item]))}}))
        if not quiet:
            for col, items in moved.items():
                self.note(tag, f"item {items} 은 지표가 아니라 {col} 값 → 조건으로 옮김")
        return out

    def merge_answers(self, answers: list["AnswerDecision"]) -> list["AnswerDecision"]:
        """같은 하위 질문·연산·View·항목의 질문용 계산(피연산자 1개짜리)을 하나로. 피연산자를 모아 두면 normalize 가 조건을 합친다"""
        out: list[AnswerDecision] = []
        where: dict[tuple, int] = {}
        count: dict[tuple, int] = {}
        for a in answers:
            picks = self.category_item_to_condition("", a.operands, quiet=True)
            if a.op in MULTI_OPERAND or len(picks) != 1:
                out.append(a)
                continue
            key = (a.sub_question_id, a.op, picks[0].record_id, picks[0].item)
            if key in where:
                prev = out[where[key]]
                out[where[key]] = prev.model_copy(update={"operands": prev.operands + a.operands})
                count[key] += 1
            else:
                where[key], count[key] = len(out), 1
                out.append(a)
        for (sid, op, _, _), n in count.items():
            if n > 1:
                self.note(sid or "answers", f"같은 {op} 계산 {n}개를 하나로 합침 (범주마다 따로 적은 것)")
        return out

    def merge_same_item(self, tag: str, op: str, picks: list[Pick], keep_first: bool) -> list[Pick]:
        """피연산자 1개짜리 연산에 같은 View·항목을 여럿으로 쪼갠 것 → 조건을 합쳐 하나로 (예: a=2024, b=2021)

        항목이 다르면 keep_first=True 일 때 첫 번째만 쓴다 (질문용). 차트는 항목이 다르면 갈래로 두므로 그대로 둔다.
        """
        if len(picks) <= 1:
            return picks
        if any((p.record_id, p.item) != (picks[0].record_id, picks[0].item) for p in picks):
            if not keep_first:
                return picks
            self.note(tag, f"{op} 는 피연산자 1개 → 첫 번째만 씀 (버린 항목: {[p.item for p in picks[1:]]})")
            return picks[:1]
        merged: Select = {}
        for p in picks:
            for col, vals in p.select.items():
                have = merged.setdefault(col, [])
                have += [v for v in vals if str(v) not in map(str, have)]
        # 어느 한 피연산자에 없는 열 조건 = 그 피연산자는 그 열을 전부 썼다 → 합친 조건에서도 뺀다
        merged = {c: v for c, v in merged.items() if all(c in p.select for p in picks)}
        self.note(tag, f"{op} 는 피연산자 1개 → 같은 항목의 피연산자를 하나로 합침 ({len(picks)}개, 조건 {merged})")
        return [picks[0].model_copy(update={"select": merged, "role": None})]

    def fill_period(self, tag: str, op: str, select: Select, d: _Args) -> Select:
        """기간 연산인데 시점 조건에 from·to·base 시점이 빠졌으면 보탠다

        시점 조건을 지우지 않는 이유: base="prev" 나 index 처럼 구간 전체가 필요한 연산이 있다.
        """
        if op not in PERIOD_OPS or TIME_COL not in select:
            return select
        have = [str(v) for v in select[TIME_COL]]
        add = [t for t in dict.fromkeys((d.from_, d.to, d.base)) if t and t != "prev" and t not in have]
        if not add:
            return select
        self.note(tag, f"{op} 의 시점 조건에 계산 시점을 보탬 ({have} → {have + add})")
        return {**select, TIME_COL: have + add}

    def fix_branch_roles(self, tag: str, chart_type: str, picks: list[Pick]) -> list[Pick]:
        """갈래가 여럿인 차트에서 그 차트에 없는 역할(예: "combo") → 아직 안 쓴 역할을 순서대로"""
        roles = MULTI_BRANCH.get(chart_type)
        if not roles or len(picks) < 2:
            return picks
        free = [r for r in roles if r not in {p.role for p in picks}]
        out = []
        for p in picks:
            if p.role not in roles and free:
                new = free.pop(0)
                self.note(tag, f"{chart_type} 갈래 역할 {p.role} → {new} ({p.item})")
                p = p.model_copy(update={"role": new})
            out.append(p)
        return out

    def fixed_for(self, sub_ids: list[str | None]) -> dict[str, list[str]]:
        hit = next((self.fixed[s] for s in sub_ids if s in self.fixed), None)
        return hit if hit is not None else next(iter(self.fixed.values()), {})

    def fix_time(self, tag: str, op: str, select: Select, d: _Args, years: list[str] | None) -> tuple[Select, _Args]:
        """고정 시점 적용. 기간 연산은 기간 전체를 쓰고 계산 방식을 정하고, 그 밖의 연산은 고정 시점 밖의 값만 바꾼다"""
        if op in GROWTH_OPS:     # 증감·증감률: 시점마다 직전 시점 대비. HCX 가 두 시점(from·to)만 골랐어도 시점 전체로
            new = {**select, TIME_COL: years} if years else {k: v for k, v in select.items() if k != TIME_COL}
            upd = {"base": "prev", "from_": None, "to": None}
            if new != select or any(getattr(d, k) != v for k, v in upd.items()):
                where = f"고정 시점 {years[0]}~{years[-1]}" if years else "View 의 모든 시점"
                self.note(tag, f"{op}: 시점마다 직전 시점 대비로 계산 ({where})")
            return new, d.model_copy(update=upd)
        if not years:
            return select, d
        have = [str(v) for v in select.get(TIME_COL, [])]
        if op == "cagr" and len(years) >= 2:
            how, upd = f"{years[0]} → {years[-1]}", {"base": None, "from_": years[0], "to": years[-1]}
        elif op == "index" and len(years) >= 2:
            base = d.base if d.base in years else years[0]
            how, upd = f"기준 시점 {base}", {"base": base, "from_": None, "to": None}
        else:
            if have and not set(have) <= set(years):
                self.note(tag, f"시점 {have} 은 고정 시점 {years} 밖 → {years}")
                return {**select, TIME_COL: years}, d
            return select, d
        new = {**select, TIME_COL: years}
        if new != select or any(getattr(d, k) != v for k, v in upd.items()):
            self.note(tag, f"{op}: 고정 시점으로 계산 — {how}")
        return new, d.model_copy(update=upd)

    def fix_region(self, tag: str, select: Select, regions: list[str] | None, record_id: str | None) -> Select:
        """지역 열(열 이름에 행정구역·지역·시도·시군구)의 값이 고정 지역 밖이면 고정 지역으로. 일부만 고른 것은 그대로

        고정 지역 중 그 열에 실제로 있는 값만 쓴다. 하나도 없으면 고정하지 않는다
        (재작성 모듈이 지역 칸에 지역이 아닌 말을 넣는 경우가 있다. 예: 2026-11-11 '지역 혼인건수')
        """
        rec = self.records.get(record_id or "")
        if not regions or rec is None:
            return select
        cols = rec.table.columns
        for col in [c for c in select if c in cols and any(h in c for h in REGION_HINTS)]:
            have = {str(r[cols.index(col)]) for r in rec.table.rows}
            usable = [r for r in regions if r in have]
            vals = [str(v) for v in select[col]]
            if not usable:
                self.note(tag, f"고정 지역 {regions} 이 {col} 에 없음 → 지역은 고정하지 않음")
            elif not set(vals) <= set(usable):
                self.note(tag, f"{col} {vals} 은 고정 지역 {usable} 밖 → {usable}")
                select = {**select, col: usable}
        return select

    def fix_age(self, tag: str, select: Select, age: list[str] | None, record_id: str | None) -> Select:
        """질문 연령 범위 안의 일부 나이만 고른 것 → View 에서 그 범위에 드는 나이 전체 ('미취학아동' 인데 ['0세'] 만)

        View 는 이미 그 범위로 잘려 온다. 범위 밖 나이를 고른 것, 나이로 읽을 수 없는 값('계')은 건드리지 않는다.
        """
        rec = self.records.get(record_id or "")
        if not age or rec is None:
            return select
        lo, hi = int(age[0] or 0), (int(age[1]) if age[1] else None)
        inside = lambda s: s is not None and s[0] >= lo and (hi is None or (s[1] is not None and s[1] <= hi))  # noqa: E731
        cols = rec.table.columns
        for col in [c for c in select if c in cols and any(h in c for h in AGE_HINTS)]:
            have = list(dict.fromkeys(str(r[cols.index(col)]) for r in rec.table.rows))
            in_range = [v for v in have if inside(age_span(v))]
            chosen = [str(v) for v in select[col]]
            if in_range and all(inside(age_span(v)) for v in chosen) and set(chosen) < set(in_range):
                self.note(tag, f"{col} {chosen} → 질문 연령 {lo}~{'' if hi is None else hi}세에 드는 값 전체 {in_range}")
                select = {**select, col: in_range}
        return select

    def fix_select(self, tag: str, op: str, select: Select, d: _Args, fixed: dict,
                   record_id: str | None = None) -> tuple[Select, _Args]:
        select, d = self.fix_time(tag, op, select, d, fixed.get(TIME_COL))
        select = self.fix_region(tag, select, fixed.get(REGION), record_id)
        select = self.fix_age(tag, select, fixed.get(AGE), record_id)
        return self.fill_period(tag, op, select, d), d

    def normalize(self, tag: str, op: str, picks: list[Pick], d: _Args, chart_type: str | None = None,
                  fixed: dict | None = None) -> tuple[list[Pick], _Args]:
        picks = self.category_item_to_condition(tag, self.drop_non_operands(tag, picks))
        if op in TWO_OPERAND:
            if len(picks) > 2:
                self.note(tag, f"{op} 는 피연산자 2개 → 앞의 2개만 씀 (버린 항목: {[p.item for p in picks[2:]]})")
                picks = picks[:2]
        elif op == "combine":                # 더하고 빼는 값들이라 같은 항목이어도 합치지 않는다
            if len(picks) < 2:
                self.note(tag, f"combine 은 피연산자 2개 이상이 필요 (받은 것 {len(picks)}개)")
        elif chart_type is None or chart_type not in MULTI_BRANCH:
            picks = self.merge_same_item(tag, op, picks, keep_first=chart_type is None)
        if chart_type:
            picks = self.fix_branch_roles(tag, chart_type, picks)
        out, d2 = [], d
        for p in picks:
            sel, d2 = self.fix_select(tag, op, p.select, d, fixed or {}, p.record_id)
            out.append(p.model_copy(update={"select": sel}))
        return out, d2

    def operand(self, tag: str, pick: Pick, role: str) -> Operand:
        self.check(tag, pick.record_id, pick.select, pick.item)
        unit, source = self.unit_with_source(pick.record_id, pick.item, pick.select)
        if unit is None and (unit := self.hcx_unit(tag, pick)):
            source = "hcx"
        return Operand(role=role, record_id=pick.record_id, item=pick.item, select=pick.select, unit=unit,
                       unit_source=source)

    def unit_with_source(self, record_id: str, item: str | None, select: Select) -> tuple[str | None, str | None]:
        rec = self.records.get(record_id)
        if item is None and len(items := select.get(ITEM_COL) or []) == 1:
            item = str(items[0])
        if bracket := unit_of(item):
            return bracket, "item"
        if table := unit_of(None, rec.metadata.get("unit") if rec else None):
            return table, "table"
        return None, None

    def hcx_unit(self, tag: str, pick: Pick) -> str | None:
        """항목 이름·metadata.unit 으로 단위를 정하지 못할 때 HCX 가 고른 단위. View 의 단위 목록 안에 있을 때만 믿는다

        KOSIS 가 표 단위로만 단위를 주는 표가 있다 (DT_1B81A23: 모든 행이 '명 가임여자 1명당 명').
        단위 자체에 띄어쓰기가 있어 코드로는 나눌 수 없고, 어느 항목의 단위인지도 데이터에 없다 → HCX 가 고르고 코드는 검사만.
        """
        rec = self.records.get(pick.record_id)
        listed = str(rec.metadata.get("unit") or "") if rec else ""
        if not pick.unit or not listed:
            return None
        # [CHANGED 11-11] 이전: pick.unit in listed (부분 문자열) — '가임여자 1명당 명' 의 '1명당' 도 승인했다 (GPT 검토)
        # 승인: 목록 전체와 같음 (단위가 하나뿐인 표) / 표준 단위이면서 목록 안에 띄어쓰기로 구분된 한 단어로 있음
        unit = pick.unit.strip()
        if unit == listed.strip() or (unit in STANDARD_UNITS and unit in listed.split()):
            return unit
        self.note(tag, f"HCX 단위 '{pick.unit}' 은 View 단위 목록 '{listed}' 의 단위로 확인되지 않음 → 단위 없음")
        return None

    def args(self, tag: str, op: str, d: _Args) -> dict:
        args = d.step_args()
        if op == "share":      # 분모 범위가 질문에 없으면 선택 항목의 합 + "선택 항목 내 비중" 표시 (명세 4장)
            den = args.get("denominator") or Denominator(scope="selected")
            if den.scope == "selected" and not den.label:
                den = den.model_copy(update={"label": SELECTED_LABEL})
            if den.scope == "question" and den.operand:
                self.check(tag, den.operand.record_id, den.operand.select, den.operand.item)
            args["denominator"] = den
        return args

    def columns(self, record_id: str) -> list[str]:
        rec = self.records.get(record_id)
        return list(rec.table.columns) if rec else []

    def range_total(self, tag: str, picks: list[Pick], fixed: dict) -> bool:
        """질문에 연령 범위가 있는데 raw 가 나이별 행 여럿을 골랐는가 (미취학아동수 → 0세·1세 … 5세 나열)"""
        if len(picks) != 1 or AGE not in fixed or set(fixed.get(INTENT, [])) & PER_CATEGORY_INTENTS:
            return False
        rec = self.records.get(picks[0].record_id)
        if rec is None:
            return False
        sel = select_rows(rec, picks[0].select, picks[0].item)
        distinct = {c: {str(r[sel.col(c)]) for r in sel.rows} for c in sel.columns if c != VALUE_COL}
        age_col = next((c for c, v in distinct.items() if any(h in c for h in AGE_HINTS) and len(v) > 1), None)
        if age_col is None:
            return False
        if distinct[age_col] & TOTAL_LABELS:      # '계' 가 섞이면 더할 때 두 번 센다 → 바꾸지 않는다
            self.note(tag, f"{age_col} 에 합계 행이 섞여 있어 합치지 않음 ({sorted(distinct[age_col] & TOTAL_LABELS)})")
            return False
        # 연령·시점 밖의 열이 여러 값이면(총인구와 성비, 서울과 부산) 더하면 서로 다른 것이 섞인다 → 바꾸지 않는다
        mixed = [c for c, v in distinct.items() if c not in (age_col, TIME_COL) and len(v) > 1]
        if mixed:
            self.note(tag, f"{', '.join(mixed)} 에 값이 여럿이라 연령 합계를 내지 않음 ({ {c: sorted(distinct[c]) for c in mixed} })")
            return False
        return True

    def step(self, tag: str, step_id: str, op: str, picks: list[Pick], d: _Args) -> Step:
        """picks 를 피연산자로 쓰는 단계 하나"""
        if op in TWO_OPERAND:
            roles = [p.role if p.role in ("a", "b") else "ab"[i] for i, p in enumerate(picks[:2])]
        elif op == "combine":
            roles = ["term"] * len(picks)
        else:
            roles = ["part" if op == "share" else "value"] * len(picks)
        operands = [self.operand(tag, p, r) for p, r in zip(picks, roles)]
        if op == "combine":
            operands = [o.model_copy(update={"sign": p.sign or "+"}) for o, p in zip(operands, picks)]
            if len({o.unit for o in operands}) > 1:
                self.note(tag, f"combine 피연산자의 단위가 다름: {[o.unit for o in operands]} (계산하지 않음)")
        extra = {}
        if op == "aggregate":            # 시점마다 따로 합친다. HCX 스키마에는 by 가 없어 코드가 정한다
            rec = self.records.get(picks[0].record_id) if picks else None
            if rec is not None and TIME_COL in rec.table.columns:
                extra["by"] = [TIME_COL]
        return Step(step_id=step_id, op=op, operands=operands, display_ref=self.ref(op, [o.unit for o in operands]),
                    **self.args(tag, op, d), **extra)

    # ── 차트용 ───────────────────────────────────────────────────
    def plan(self, chart: ChartRequest, d: ChartDecision) -> Plan | None:
        tag, op = chart.chart_id, chart.measure
        fixed = self.fixed_for(chart.sub_question_ids)
        picks, d2 = self.normalize(tag, op, d.operands, d, chart.chart_type, fixed)
        select, d3 = self.fix_select(tag, op, d.select, d, fixed, d.record_id or (picks[0].record_id if picks else None))
        d = d2 if d.operands else d3
        record_id = d.record_id or (picks[0].record_id if picks else None)
        if record_id is None:
            self.note(tag, "record_id 가 없어 차트 계획을 만들지 않음")
            return None
        output, step_op = None, op
        # 연령 범위의 값 하나를 묻는 질문이면 차트도 나이별이 아니라 합계로 (질문용 계산과 같은 규칙)
        if op == "raw" and self.range_total(tag, picks or [Pick(record_id=record_id, select=select)], fixed):
            self.note(tag, f"차트 raw → aggregate(sum): 연령 {fixed[AGE][0]}~{fixed[AGE][1]}세 범위의 값 하나를 묻는 질문")
            step_op, d = "aggregate", d.model_copy(update={"agg": "sum"})
        if not picks:                                  # 갈래 하나, 상위 record_id·select 를 그대로 쓴다
            self.check(tag, record_id, select, None)
            by = {"by": [TIME_COL]} if step_op == "aggregate" and TIME_COL in self.columns(record_id) else {}
            steps = [Step(step_id="s1", op=step_op, display_ref=self.ref(step_op, [self.unit(record_id, None, select)]),
                          **self.args(tag, step_op, d), **by)]
        elif op in MULTI_OPERAND or len(picks) == 1:   # 단계 하나에 피연산자 여럿 (또는 하나)
            if op in TWO_OPERAND and len(picks) != 2:
                self.note(tag, f"{op} 는 피연산자 2개가 필요 (받은 것 {len(picks)}개)")
            steps = [self.step(tag, "s1", step_op, picks, d)]
        else:                                          # 갈래 여럿 → 갈래마다 단계 하나, output 이 축 역할에 연결
            steps = [self.step(tag, f"s{i}", op, [p], d) for i, p in enumerate(picks, 1)]
            output = [PlanOutput(step_id=s.step_id, role=p.role) for s, p in zip(steps, picks) if p.role in CHART_ROLES]
            if len(output) < len(picks):
                self.note(tag, "축 역할이 없는 갈래가 있음 (차트에 쓰이지 않음)")
            output = output or None
        title, why = clean_title(d.title)
        if why:
            self.note(tag, f"HCX 제목 '{d.title}' 버림 ({why}) → 규칙 제목")
        return Plan(chart_id=chart.chart_id, sub_question_ids=chart.sub_question_ids, record_id=record_id,
                    chart_type=chart.chart_type, fallback_chart=chart.fallback_chart, measure=op, select=select,
                    steps=steps, output=output, title=title)

    # ── 질문용 ───────────────────────────────────────────────────
    def answer(self, n: int, d: AnswerDecision, charts: list[ChartRequest]) -> Step | None:
        tag = d.sub_question_id or f"a{n}"
        picks, d = self.normalize(tag, d.op, d.operands, d, fixed=self.fixed_for([d.sub_question_id]))
        if not picks:                             # answer_steps 는 피연산자를 항상 적는다 (명세 4장)
            self.note(tag, f"질문용 계산 {d.op} 에 피연산자가 없어 건너뜀")
            return None
        # 질문용 연산(HCX)과 모듈 2 의 measure(차트용)를 대조. 다른 것은 오류가 아니다 (차트는 추이, 답은 증감률일 수 있다)
        # → 둘 다 그대로 실행하고, 다르다는 사실만 QA 가 볼 수 있게 남긴다
        for c in charts:
            if c.chart_type and d.sub_question_id in c.sub_question_ids and c.measure != d.op:
                self.note(tag, f"질문용 연산 {d.op} ≠ 모듈 2 measure {c.measure} ({c.chart_id})")
        op = d.op
        if op == "raw" and self.range_total(tag, picks, self.fixed_for([d.sub_question_id])):
            age = self.fixed_for([d.sub_question_id])[AGE]
            self.note(tag, f"raw → aggregate(sum): 연령 {age[0]}~{age[1]}세 범위의 값 하나를 묻는 질문")
            op, d = "aggregate", d.model_copy(update={"agg": "sum"})
        return self.step(tag, f"a{n}", op, picks, d)


def make_plan(charts: list[ChartRequest], records: list[Record], decision: Decision,
              bundle: QueryBundle | None = None) -> tuple[ChartPlan, dict[str, Display]]:
    """→ (ChartPlan, displays). 모듈 2 가 차트 없음(chart_type None)으로 판단한 것은 plans 에 넣지 않는다"""
    p = _Planner(records, fixed_conditions(bundle))
    by_chart = {d.chart_id: d for d in decision.charts}
    plans = []
    for chart in charts:
        if chart.chart_type is None:
            continue
        if chart.chart_id not in by_chart:
            p.note(chart.chart_id, "계획 결정이 없어 차트 계획을 만들지 않음")
            continue
        if plan := p.plan(chart, by_chart[chart.chart_id]):
            plans.append(plan)
    answers = [s for n, d in enumerate(p.merge_answers(decision.answers), 1) if (s := p.answer(n, d, charts))]
    return ChartPlan(plans=plans, answer_steps=answers, notes=list(dict.fromkeys(p.notes))), p.displays
