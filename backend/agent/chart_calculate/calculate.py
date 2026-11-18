"""
[NEW] Calculate — Step 하나를 실행한다 (연산 12종). 차트용(plans[].steps)과 질문용(answer_steps)이 같이 쓴다

  Step ─▶ 피연산자마다 select_rows ─▶ Series(점 목록) ─▶ 연산 ─▶ Calc(결과 점 목록)
                                                                  ├▶ to_calc_result()  질문용 → CalcResult
                                                                  └▶ content.py        차트용 → ChartContent.rows

  원칙
    - 계산은 원래 정밀도. 반올림·단위 환산은 하지 않는다 (display.py 가 표시할 때 한 번).
    - 계산할 수 없으면 예외를 던지지 않고 값을 None 으로 두고 사유를 notes 에 남긴다 (명세 4·7장).

  TODO(후속 명세): 연산식·결측 규칙은 팀 합의 전이다. 아래 식은 임시값이고, 바뀌면 이 파일의 _OPS 함수만 고친다.
    change       to − from                         growth_rate  (to − from) ÷ from × 100
    cagr         ((to ÷ from)^(1/연수) − 1) × 100   index        값 ÷ 기준 시점 값 × 100
    share        part ÷ total × 100                diff         a − b          ratio  a ÷ b
    rank         같은 시점 안에서 큰 값부터 (동점은 같은 순위, 다음 순위는 건너뜀: 1, 2, 2, 4)
    extreme      최댓값 (kind="min" 이면 최솟값)    aggregate    agg = sum | mean (by 로 묶을 열 지정)
    combine      Σ (sign × 피연산자)  — 피연산자 2개 이상, join_on(기본 시점)으로 짝짓는다. 단위·수록 주기가 모두 같아야 한다
"""
import copy
import datetime
import json
import logging
import math
import re
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.agent.chart_calculate.display import ratio_unit, result_unit, unit_of
from backend.agent.chart_calculate.select import ITEM_COL, REGION_HINTS, VALUE_COL, age_span, select_rows
from backend.agent.chart_calculate.validate import TOTAL_LABELS, totals_in
from backend.core.korean import strip_unit, unit_tail
from backend.schemas.chart import CalcInput, CalcResult, Operand, Plan, Step
from backend.schemas.record import Record


def _only_unit_added(requested: str, found: str) -> bool:
    """요청한 항목 이름에 View 항목에 없는 단위만 덧붙은 경우 ('인구(1세이상)(명)' ↔ '인구(1세이상)'). 단위가 서로 다르면(명 ↔ 천명) False"""
    return strip_unit(requested) == strip_unit(found) and unit_tail(found) in (None, unit_tail(requested))

log = logging.getLogger(__name__)
INTERNAL_ERROR = "내부 오류로 계산하지 못함"      # 예기치 못한 예외를 사유로 남길 때의 문구 (테스트는 이 문구가 나오면 실패한다. tests/conftest.py)
TIME_COL = "시점"
SINGLE_VALUE = "비교할 값이 하나뿐이라 순위·최댓값·최솟값을 정할 수 없음"
SELECTED_LABEL = "선택 항목 내 비중"
_ALWAYS_LIST = {"rank", "extreme"}   # 값이 하나여도 '어느 것인지'(key)가 답의 일부인 연산


@dataclass
class Point:
    key: dict[str, Any]               # 이 값을 특정하는 열 값 (예: {"시점": "2021"})
    value: int | float | None
    extra: dict[str, Any] = field(default_factory=dict)   # rank 의 순위 등


@dataclass
class Series:
    """피연산자 하나를 행에서 뽑은 것"""
    role: str
    record_ids: list[str]
    item: str | None = None
    unit: str | None = None
    prd_se: str | None = None         # 수록 주기 (집계 기준 비교용)
    points: list[Point] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)       # 있으면 이 피연산자로는 계산하지 않는다
    notes: list[str] = field(default_factory=list)
    carried: list[CalcInput] | None = None                # 앞 단계 결과를 받은 경우: 그 단계의 inputs
    columns: list[str] = field(default_factory=list)      # View 의 열 (결합 열이 실제로 있는지 확인용)
    dropped: list[dict] = field(default_factory=list)     # [NEW 11-16] 값이 비어 제외한 행의 key (직전 시점 대비에서 빠진 시점을 알아보려고)
    missing: list[dict] = field(default_factory=list)     # [NEW 11-17] 같은 행들의 key 열({시점, 지역…}만). 꺾은선이 빈 시점에서 끊기게 차트에 넘긴다
    unit_source: str | None = None                        # hcx = HCX 가 고른 단위 (표시용. 호환 검사에는 쓰지 않는다)
    # 고른 행들에서 값이 하나뿐이라 key 에 넣지 않은 열 (서울, 전국, 항목 하나). 결합 키와 근거 표시에 쓴다
    fixed: dict[str, Any] = field(default_factory=dict)

    def inputs(self, points: list[Point] | None = None, with_fixed: bool = False) -> list[CalcInput]:
        """with_fixed: 피연산자가 여럿인 계산은 고정 좌표(서울·부산)도 key 에 남겨 어느 값인지 QA 가 알 수 있게"""
        if self.carried is not None:
            return self.carried
        fixed = {c: v for c, v in self.fixed.items() if c != ITEM_COL} if with_fixed else {}
        return [CalcInput(role=self.role, record_id=self.record_ids[0], item=self.item, key={**fixed, **p.key},
                          value=p.value, unit=self.unit) for p in (self.points if points is None else points)]


@dataclass
class Calc:
    op: str
    points: list[Point] = field(default_factory=list)
    unit: str | None = None
    item: str | None = None           # 첫 피연산자의 항목 이름 (차트 범례·축 이름용)
    inputs: list[CalcInput] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    scope_label: str | None = None
    notes: list[str] = field(default_factory=list)
    # [NEW 11-16] 첫 피연산자에서 값이 하나로 고정된 열 (서울, 전국 …). 서로 다른 View 의 같은 항목을 갈래로 그릴 때 범례를 구분한다 (검수 M3-08)
    fixed: dict[str, Any] = field(default_factory=dict)
    # [NEW 11-17] 값이 비어 점이 못 된 시점의 key (같은 묶음의 값 있는 시점 사이에 있는 것만). CalcResult 에는 싣지 않고,
    # 시간이 가로축인 차트가 값 None 행으로 써서 그 시점을 가로축에 남기고 선을 끊는다 (시험 화면에서 확인한 빈틈)
    missing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def value(self) -> float | list[dict] | None:
        """CalcResult.value 모양: 결과가 하나면 숫자, 여러 개면 [{"key", "value", …}], 없으면 None"""
        if not self.points:
            return None
        if len(self.points) == 1 and self.op not in _ALWAYS_LIST:
            return self.points[0].value
        return [{"key": p.key, "value": p.value, **p.extra} for p in self.points]


# ── 피연산자 → Series ────────────────────────────────────────────
def load_series(operand: Operand, records: dict[str, Record], role: str) -> Series:
    rec = records.get(operand.record_id)
    if rec is None:
        return Series(role, [operand.record_id], operand.item, operand.unit,
                      errors=[f"View 없음: {operand.record_id}"])
    sel = select_rows(rec, operand.select, operand.item)
    dims = [c for c in sel.columns if c != VALUE_COL]
    # key = 고른 행들 사이에서 값이 달라지는 열 + 시점. 고정된 조건(전국, 항목 하나)은 key 에 넣지 않는다
    key_cols = [c for c in dims if c == TIME_COL or len({r[sel.col(c)] for r in sel.rows}) > 1]
    item, unit, notes = operand.item, operand.unit, ([operand.note] if operand.note else [])
    if item is None and ITEM_COL in dims and len(found := {r[sel.col(ITEM_COL)] for r in sel.rows}) == 1:
        item = found.pop()
    # [CHANGED 11-18] 이전: sel.item != item 만 봤다 → HCX 가 '(명)' 만 덧붙여도 '항목을 바꿔 계산함' 안내가 붙었다 (단위만 다르면 같은 항목)
    if item is not None and sel.item and sel.item != item and not _only_unit_added(item, sel.item):
        # [NEW 11-16] 요청한 항목과 View 의 항목이 괄호 단위만 다르면(인구(명) 와 인구(천명)) View 의 이름과 단위를 쓴다 (검수 M3-12)
        notes.append(f"항목 '{item}' 은 자료의 '{sel.item}' 로 계산함")
        item, unit = sel.item, unit_of(sel.item) or unit
    vi = sel.col(VALUE_COL) if VALUE_COL in sel.columns else None
    fixed = {c: sel.rows[0][sel.col(c)] for c in dims if c not in key_cols} if sel.rows else {}
    if sel.dropped:
        notes.append(f"값이 비어 제외한 행 {len(sel.dropped)}개")
    return Series(
        role, [rec.id], item, unit or unit_of(item, rec.metadata.get("unit")), rec.metadata.get("prd_se"),
        points=[Point({c: r[sel.col(c)] for c in key_cols}, r[vi]) for r in sel.rows],
        errors=list(sel.errors), notes=notes, columns=list(sel.columns), fixed=fixed, unit_source=operand.unit_source,
        # [CHANGED 11-17 외부 피드백] 이전: dropped=list(sel.dropped) — 값이 하나도 없는 다른 지역(부산)의 결측 행까지 간격 판정에 들어가
        #   서울의 정상적인 2년 간격 증감률이 모두 빈 값이 됐다. 차트 빈 점(missing)과 같은 규칙으로 이 계열의 결측 행만 남긴다
        dropped=_own_dropped(sel.dropped, fixed) if sel.rows else [],
        missing=_own_missing(sel.dropped, fixed, key_cols) if sel.rows else [])


def _own_dropped(dropped: list[dict], fixed: dict) -> list[dict]:
    """값이 비어 제외한 행 중 이 계열의 고정 좌표(서울 · 항목 …)와 맞는 것 (원래 열 그대로)"""
    return [d for d in dropped if all(str(d.get(c)) == str(v) for c, v in fixed.items())]


def _own_missing(dropped: list[dict], fixed: dict, key_cols: list[str]) -> list[dict]:
    """값이 비어 제외한 행 중 **이 계열의 것**만, key 열({시점, 지역…})로.
    key_cols 는 값이 있는 행만 보고 정해서, 값이 있는 행이 서울뿐이면 지역 열이 '고정' 으로 빠진다. 그 상태로 결측 행의 지역을 버리면
    부산의 결측 행이 서울 선의 빈 점이 된다. 그래서 버리기 전에 원래 좌표를 고정 좌표(서울, 항목 …)와 대조한다.
    값이 있는 행이 하나도 없으면(고정 좌표를 알 수 없다) 그릴 계열이 없으니 빈 목록 (재검토 11)"""
    if not fixed and not key_cols:
        return []
    return [{c: d.get(c) for c in key_cols} for d in dropped if all(str(d.get(c)) == str(v) for c, v in fixed.items())]


class _Ctx:
    """Step 하나를 실행하는 동안의 문맥: 피연산자를 어디서 가져올지 정한다"""

    def __init__(self, step: Step, records: dict[str, Record], default: Plan | None, done: dict[str, Calc]):
        self.step, self.records, self.default, self.done = step, records, default, done

    def arg(self, name: str, fallback=None):
        """연산별 인자. kind · order 는 Step 의 정식 필드, 스키마에 아직 없는 것(by)은 extra="allow" 로 보관된 값"""
        got = getattr(self.step, name, None)
        return got if got is not None else (self.step.model_extra or {}).get(name, fallback)

    def series(self, role: str, pos: int = 0) -> Series:
        ops = self.step.operands
        if ops:
            # 역할 이름이 맞는 것을 먼저 찾고, 없으면 위치로 받는다 (LLM 이 역할 이름을 다르게 적어도 계산은 되게)
            op = next((o for o in ops if o.role == role), ops[pos] if pos < len(ops) else None)
            if op is None:
                return Series(role, [], errors=[f"피연산자 없음: {role}"])
            return load_series(op, self.records, role)
        if self.step.input:
            prev = self.done.get(self.step.input)
            if prev is None:
                return Series(role, [], errors=[f"앞 단계 없음: {self.step.input}"])
            pts = [p for p in prev.points if p.value is not None]
            # [CHANGED 11-16] 이전: prev.points 가 있기만 하면 오류 없음 — 값이 모두 None 이면 빈 목록으로 extreme 이 예외를 냈다 (검수 M3-09)
            return Series(role, prev.record_ids, item=prev.item, unit=prev.unit, points=pts,
                          errors=[] if pts else list(prev.notes) or ["앞 단계 결과 없음"], carried=prev.inputs)
        if self.default is not None:
            return load_series(Operand(role=role, record_id=self.default.record_id, select=self.default.select),
                               self.records, role)
        return Series(role, [], errors=[f"피연산자 없음: {role}"])

    def calc(self, *series: Series, unit: str | None = None) -> Calc:
        """빈 결과. 피연산자에 오류가 있으면 points 를 채우지 않고 돌려준다 → 값 None + 사유"""
        ids = list(dict.fromkeys(i for s in series for i in s.record_ids))
        return Calc(self.step.op, unit=unit, item=next((s.item for s in series if s.item), None), record_ids=ids,
                    inputs=[i for s in series for i in s.inputs(with_fixed=len(series) > 1)],
                    notes=[m for s in series for m in s.errors + s.notes],
                    fixed=dict(series[0].fixed) if series else {})


def _failed(*series: Series) -> bool:
    return any(s.errors for s in series)


def _groups(points: list[Point], by: Callable[[Point], tuple]) -> dict[tuple, list[Point]]:
    out: dict[tuple, list[Point]] = {}
    for p in points:
        out.setdefault(by(p), []).append(p)
    return out


def _no_time(p: Point) -> tuple:
    return tuple((c, v) for c, v in p.key.items() if c != TIME_COL)


def _incompatible(series: list[Series], same_unit: bool) -> str | None:
    """검증 ③: 단위·집계 기준 호환 (명과 건을 빼지 않는다, 연간과 월간을 섞지 않는다). 모든 피연산자를 함께 본다

    [CHANGED 11-11] 이전: (a, b) 두 개를 비교하고, 한쪽 단위를 모르면 검사를 건너뛰었다 → combine 이 첫 항목만 기준으로
    [단위 미상, 명, 건] 을 함께 계산했다 (검수). 이제 확인할 수 없으면 계산하지 않는다.
      단위를 모두 앎  → 모두 같아야 한다
      모두 모름       → 같은 지표(항목 이름)끼리만 (서울 + 부산 − 대구 출생아수)
      아는 것·모르는 것이 섞임 → 확인할 수 없음
    """
    periods = [s.prd_se for s in series]
    if len({p for p in periods if p}) > 1:
        return f"수록 주기가 다름: {' / '.join(p or '?' for p in periods)}"
    if any(periods) and not all(periods):
        return f"수록 주기를 확인할 수 없음: {' / '.join(p or '?' for p in periods)}"
    if not same_unit:
        return None
    # [CHANGED 11-11] HCX 가 고른 단위는 모르는 단위로 본다: 합계출산율에 '명' 을 붙이면 출생아수(명)와 계산됐다 (2차 검수)
    units = [None if s.unit_source == "hcx" else s.unit for s in series]
    if all(units):
        return None if len(set(units)) == 1 else f"단위가 다름: {' / '.join(units)}"
    if not any(units) and len({s.item for s in series}) == 1 and series[0].item:
        return None
    hcx = " — HCX 가 고른 단위는 확인용으로 쓰지 않음" if any(s.unit_source == "hcx" for s in series) else ""
    return f"단위를 확인할 수 없음: {' / '.join(u or '?' for u in units)} ({' / '.join(str(s.item) for s in series)}){hcx}"


# ── 한 피연산자, 두 시점 사이 (change · growth_rate · cagr) ───────
def _change(a: Point, b: Point):
    return b.value - a.value, None


def _growth_rate(a: Point, b: Point):
    if a.value == 0:
        return None, "기준값 0"
    if a.value < 0:          # [NEW 11-13] -100 → -50 은 50 증가인데 식은 -50% 가 되어 방향이 거꾸로다. 정의되지 않은 값으로 보고 계산하지 않는다
        return None, "기준값이 음수라 증감률을 정할 수 없음"
    return (b.value - a.value) / a.value * 100, None


# [NEW 11-13] 시점 라벨(normalize.PERIOD_LABEL_SQL) → 연 단위 숫자. 월 '2024.01', 분기 '2024 1분기', 반기 '2024 상반기', 일 '2024.01.15', 연 '2024'
_TIME_FORMS: list[tuple[re.Pattern, Callable[[tuple], float]]] = [
    (re.compile(r"^(\d{4})$"), lambda g: int(g[0])),
    (re.compile(r"^(\d{4})\.(\d{2})$"), lambda g: int(g[0]) + (int(g[1]) - 1) / 12),
    (re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$"), lambda g: datetime.date(int(g[0]), int(g[1]), int(g[2])).toordinal() / 365.2425),
    (re.compile(r"^(\d{4}) ?(\d)분기$"), lambda g: int(g[0]) + (int(g[1]) - 1) / 4),
    (re.compile(r"^(\d{4}) ?(상|하)반기$"), lambda g: int(g[0]) + (0 if g[1] == "상" else 0.5)),
]


def time_in_years(label) -> float | None:
    for pattern, to_years in _TIME_FORMS:
        if m := pattern.match(str(label).strip()):
            try:
                return to_years(m.groups())
            except ValueError:
                return None
    return None


# [NEW 11-17] 시점 라벨 → (수록 주기, 그 주기의 칸 번호). 두 시점 사이의 간격을 '몇 칸'으로 센다 (검수 7)
_PERIOD_FORMS: list[tuple[re.Pattern, str, Callable[[tuple], int]]] = [
    (re.compile(r"^(\d{4})$"), "Y", lambda g: int(g[0])),
    (re.compile(r"^(\d{4})\.(\d{2})$"), "M", lambda g: int(g[0]) * 12 + int(g[1]) - 1),
    (re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$"), "D", lambda g: datetime.date(int(g[0]), int(g[1]), int(g[2])).toordinal()),
    (re.compile(r"^(\d{4}) ?(\d)분기$"), "Q", lambda g: int(g[0]) * 4 + int(g[1]) - 1),
    (re.compile(r"^(\d{4}) ?(상|하)반기$"), "H", lambda g: int(g[0]) * 2 + (0 if g[1] == "상" else 1)),
]
_PERIOD_UNIT = {"Y": "년", "M": "개월", "Q": "분기", "H": "반기", "D": "일"}


def period_index(label) -> tuple[str, int] | None:
    for pattern, kind, to_index in _PERIOD_FORMS:
        if m := pattern.match(str(label).strip()):
            try:
                return kind, to_index(m.groups())
            except ValueError:
                return None
    return None


def interval_gaps(labels) -> tuple[str, list[int]] | None:
    """시점들 사이의 간격(수록 주기의 칸 수)의 종류 → (주기, 정렬된 간격 목록). 라벨을 읽을 수 없거나 주기가 섞이면 None"""
    parsed = [period_index(l) for l in labels]
    if not parsed or any(p is None for p in parsed) or len({k for k, _ in parsed}) != 1:
        return None
    idx = sorted({i for _, i in parsed})
    return parsed[0][0], sorted({b - a for a, b in zip(idx, idx[1:])})


def _show(v) -> str:
    """충돌 안내에 쓰는 값. 원래 정밀도를 지킨다 (이전: f'{v:g}' 라서 1000000 과 1000001 이 모두 '1e+06' 으로 보였다. 검수 10)"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if float(v).is_integer():
        return str(int(v))
    return format(Decimal(repr(float(v))), "f")


def _conflicts(pts: list["Point"]) -> dict[str, list]:
    """묶음 안에서 같은 시점 라벨에 **서로 다른** 값이 둘 이상인 시점 → 그 값들. 값이 같은 중복은 충돌이 아니다.
    [NEW 11-17] 이전에는 간격만 중복을 없애고 계산 쌍은 원래 목록을 써서 같은 해의 100 → 125 가 전년 대비 25% 로 나갔다 (검수 9)"""
    seen: dict[str, list] = {}
    for p in pts:
        seen.setdefault(str(p.key.get(TIME_COL)), []).append(p.value)
    return {t: sorted(set(v)) for t, v in seen.items() if len(set(v)) > 1}


def _first_per_time(pts: list["Point"]) -> list["Point"]:
    out, seen = [], set()
    for p in pts:
        t = str(p.key.get(TIME_COL))
        if t not in seen:
            seen.add(t)
            out.append(p)
    return out


def _interior_missing(s: "Series") -> list[dict]:
    """값이 비어 점이 못 된 시점 중, 같은 묶음의 값이 있는 첫 시점과 마지막 시점 **사이**에 있는 것. 앞뒤의 빈 시점은 뺀다"""
    return _interior(s.points, s.missing)


def _interior(points: list["Point"], missing: list[dict]) -> list[dict]:
    spans: dict[tuple, tuple[int, int]] = {}
    for p in points:
        idx = period_index(p.key.get(TIME_COL))
        if idx is None:
            continue
        g = tuple(sorted((c, str(v)) for c, v in p.key.items() if c != TIME_COL))
        lo, hi = spans.get(g, (idx[1], idx[1]))
        spans[g] = (min(lo, idx[1]), max(hi, idx[1]))
    out = []
    for m in missing:
        idx = period_index(m.get(TIME_COL))
        g = tuple(sorted((c, str(v)) for c, v in m.items() if c != TIME_COL))
        if idx and g in spans and spans[g][0] < idx[1] < spans[g][1]:
            out.append(dict(m))
    return out


def _group_dropped(dropped: list[dict], group: tuple) -> list[dict]:
    want = dict(group)
    return [d for d in dropped if all(str(d.get(c)) == str(v) for c, v in want.items())]


def _cagr(a: Point, b: Point):
    ta, tb = time_in_years(a.key.get(TIME_COL)), time_in_years(b.key.get(TIME_COL))
    if ta is None or tb is None:
        return None, "연수를 알 수 없음"
    years = tb - ta                      # 월 · 분기 · 반기는 실제 경과 기간 (2024.01 → 2025.07 = 1.5년)
    if years <= 0:
        return None, "연수가 0 이하"
    if a.value <= 0 or b.value < 0:
        return None, "기준값이 0 이하이거나 끝값이 음수"
    return ((b.value / a.value) ** (1 / years) - 1) * 100, None


def _by_time(points: list[Point]) -> list[Point]:
    """시점 순서로 정렬 (시점 라벨을 모두 읽을 수 있을 때만. 아니면 View 의 순서 그대로). 직전 시점 · 처음 · 끝은 View 의 행 순서가 아니라 시점 순서다 (검수 M3-26)"""
    years = [time_in_years(p.key.get(TIME_COL)) for p in points]
    if not points or any(y is None for y in years):
        return points
    return [p for _, p in sorted(zip(years, points), key=lambda t: t[0])]


def _gap_between(dropped: list[dict], group: tuple, a: Point, b: Point) -> str | None:
    """같은 묶음(group = 시점 뺀 key)에서 a 와 b 사이에 값이 비어 제외된 시점. 없으면 None.
    여럿이면 b 의 **실제 직전 시점**(가장 늦은 것)을 돌려준다.
    [CHANGED 11-17] 이전: 목록에서 처음 나온 결측 — 2021·2022 가 모두 비면 직전 시점을 2021 로 안내했다 (검수 5)"""
    ta, tb = time_in_years(a.key.get(TIME_COL)), time_in_years(b.key.get(TIME_COL))
    if ta is None or tb is None:
        return None
    want = dict(group)
    found = [(t, d.get(TIME_COL)) for d in dropped
             if (t := time_in_years(d.get(TIME_COL))) is not None and ta < t < tb
             and all(str(d.get(c)) == str(v) for c, v in want.items())]
    return str(max(found, key=lambda x: x[0])[1]) if found else None


def _between(fn):
    def run(ctx: _Ctx) -> Calc:
        st, s = ctx.step, ctx.series("value")
        out = ctx.calc(s, unit=result_unit(st.op, s.unit))
        if _failed(s):
            return out
        used: list[Point] = []
        for gk, pts in ((gk, _by_time(pts)) for gk, pts in _groups(s.points, _no_time).items()):
            bad = _conflicts(pts)                      # 같은 시점에 서로 다른 값 → 그 시점에 기대는 비교는 계산하지 않는다
            pts = _first_per_time(pts)
            if st.base == "prev":                      # 직전 시점 대비 → 시점마다 값 하나
                pairs = []
                if len(pts) < 2:
                    out.notes.append("시점이 하나뿐이라 직전 시점이 없음")
                    continue         # [CHANGED 11-17] 이전: 간격 목록이 비어 IndexError 로 요청 전체가 멈췄다 (검수 8)
                dropped = _group_dropped(s.dropped, gk)
                # 직전 시점은 자료의 수록 주기(시점 간격)를 기준으로 한다. 간격은 값이 빈 행까지 센다 (검수 7).
                #   간격이 하나이거나 일정하면 계산하고(1칸이 아니면 간격을 밝힌다).
                #   서로 다르면 수록 주기 1칸 간격인 쌍만 계산하고 나머지는 계산하지 않는다 (검수 8: 정상 전년 대비까지 막지 않는다)
                info = interval_gaps([p.key.get(TIME_COL) for p in pts] + [d.get(TIME_COL) for d in dropped])
                unit = _PERIOD_UNIT[info[0]] if info else ""
                who = f"[{' '.join(str(v) for v in dict(gk).values())}]" if gk else ""      # 묶음 이름(지역 등)을 사유에 남긴다
                irregular = bool(info and len(info[1]) > 1)
                if irregular:
                    out.notes.append(f"시점 간격이 일정하지 않음({', '.join(f'{g}{unit}' for g in info[1])}){who}: "
                                     f"1{unit} 간격이 아닌 시점은 직전 시점 대비를 계산하지 않음")
                elif info and info[1] and info[1] != [1]:
                    out.notes.append(f"시점 {info[1][0]}{unit} 간격{who}: {info[1][0]}{unit} 전 값과 비교함")
                for a, b in zip(pts, pts[1:]):         # 시점 순서대로 한 번에 만든다 (보류한 점을 먼저 넣으면 순서가 어긋난다. 검수 7)
                    ta, tb = str(a.key.get(TIME_COL)), str(b.key.get(TIME_COL))
                    if tb in bad or ta in bad:
                        out.points.append(Point(dict(b.key), None))
                        out.notes.append(f"{tb}: 같은 시점에 값이 둘 이상({', '.join(_show(v) for v in bad[tb])})이라 계산하지 않음" if tb in bad
                                         else f"{tb}: 직전 시점({ta})에 값이 둘 이상이라 계산하지 않음")
                        continue
                    ia, ib = period_index(a.key.get(TIME_COL)), period_index(b.key.get(TIME_COL))
                    if irregular and ia and ib and ib[1] - ia[1] != 1:
                        out.points.append(Point(dict(b.key), None))
                        continue
                    if gap := _gap_between(s.dropped, gk, a, b):     # [M3-13] 두 점 사이에 값이 빈 시점이 있으면 그 둘은 직전 시점이 아니다
                        out.points.append(Point(dict(b.key), None))
                        out.notes.append(f"{b.key.get(TIME_COL)}: 직전 시점({gap}) 값이 없어 계산하지 않음")
                        continue
                    v, why = fn(a, b)
                    out.points.append(Point(dict(b.key), v))
                    used += [a, b]
                    if why:
                        out.notes.append(why)
            else:                                      # 두 시점 → 묶음마다 값 하나
                by_t = {str(p.key.get(TIME_COL)): p for p in pts}
                t0 = str(st.from_ or st.base or pts[0].key.get(TIME_COL))
                t1 = str(st.to or pts[-1].key.get(TIME_COL))
                ya, yb = time_in_years(t0), time_in_years(t1)
                if ya is not None and yb is not None and ya > yb:      # [NEW 11-16] 거꾸로 적은 기간은 바로잡고 남긴다 (검수 M3-19)
                    t0, t1 = t1, t0
                    out.notes.append(f"기간이 거꾸로라 {t0} → {t1} 로 바꿈")
                a, b = by_t.get(t0), by_t.get(t1)
                if a is None or b is None:
                    out.points.append(Point(dict(gk), None))
                    out.notes.append(f"시점 {t0 if a is None else t1} 값 없음")
                    continue
                if clash := [t for t in (t0, t1) if t in bad]:
                    out.points.append(Point(dict(gk), None))
                    out.notes += [f"{t}: 같은 시점에 값이 둘 이상({', '.join(_show(v) for v in bad[t])})이라 계산하지 않음" for t in clash]
                    continue
                pairs = [(a, b, dict(gk))]
            for a, b, key in pairs:
                v, why = fn(a, b)
                out.points.append(Point(dict(key), v))
                used += [a, b]
                if why:
                    out.notes.append(why)
        if st.base == "prev":
            out.missing = _interior_missing(s)       # 전년 대비 차트: 값이 비어 계산 못 한 해 자체도 가로축에 남긴다 (결정)
        out.inputs = s.inputs(list({id(p): p for p in used}.values())) if s.carried is None else s.carried
        return out
    return run


# ── 한 피연산자, 점마다 (raw · index · rank · extreme · aggregate) ─
def _raw(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)
    if _failed(s):
        return out
    # [NEW 11-17] 같은 묶음 · 같은 시점에 서로 다른 값이 둘 이상이면 어느 값인지 알 수 없다 → 빈 값 한 점 + 사유 (검수 10).
    #   값이 같은 중복은 하나로 합친다. 순서는 View 의 순서 그대로. 시점이 없는 자료는 건드리지 않는다
    if not all(TIME_COL in p.key for p in s.points):
        out.points = [Point(dict(p.key), p.value) for p in s.points]
        return out
    clash = {(gk, t): v for gk, pts in _groups(s.points, _no_time).items() for t, v in _conflicts(pts).items()}
    done: set = set()
    for p in s.points:
        k = (tuple(_no_time(p)), str(p.key.get(TIME_COL)))
        if k in done:
            continue
        done.add(k)
        if k in clash:
            out.points.append(Point(dict(p.key), None))
            out.notes.append(f"{k[1]}: 같은 시점에 값이 둘 이상({', '.join(_show(v) for v in clash[k])})이라 계산하지 않음")
        else:
            out.points.append(Point(dict(p.key), p.value))
    out.missing = _interior_missing(s)      # [NEW 11-17] 빈 관측 시점도 차트에 (값 None 행으로)
    return out


def _index(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=result_unit("index", s.unit))
    if _failed(s):
        return out
    for gk, pts in _groups(s.points, _no_time).items():
        t0 = str(ctx.step.base or ctx.step.from_ or pts[0].key.get(TIME_COL))
        clash = _conflicts(pts)
        pts = _first_per_time(pts)                    # 값이 같은 중복은 하나로. 서로 다른 값이 있는 시점은 아래에서 빈 값 한 점으로
        if t0 in clash:          # [NEW 11-17] 기준 시점에 서로 다른 값이 둘이면 지수의 기준을 정할 수 없다
            out.notes.append(f"{t0}: 같은 시점에 값이 둘 이상({', '.join(_show(v) for v in clash[t0])})이라 계산하지 않음")
            out.points += [Point(dict(p.key), None) for p in pts]
            continue
        base = next((p for p in pts if str(p.key.get(TIME_COL)) == t0), None)
        if base is None or base.value <= 0:        # [CHANGED 11-13] 이전: == 0 — 음수 기준은 지수의 방향이 거꾸로 된다
            out.notes.append(f"기준 시점 {t0} 값 없음" if base is None else "기준값 0" if base.value == 0 else "기준값이 음수라 지수를 정할 수 없음")
            out.points += [Point(dict(p.key), None) for p in pts]
        else:
            for p in pts:
                t = str(p.key.get(TIME_COL))
                if t in clash:       # [NEW 11-17] 기준 이후 시점의 충돌도 빈 값으로 (이전: 모두 계산해 표는 둘, 차트는 첫 값만 그렸다. 검수 10)
                    out.points.append(Point(dict(p.key), None))
                    out.notes.append(f"{t}: 같은 시점에 값이 둘 이상({', '.join(_show(v) for v in clash[t])})이라 계산하지 않음")
                else:
                    out.points.append(Point(dict(p.key), p.value / base.value * 100))
    out.missing = _interior_missing(s)      # [NEW 11-17] 원자료가 비어 점이 못 된 시점도 차트에 (값 None 행). 이전: 그 시점이 가로축에서 사라져 앞뒤가 이어졌다 (재검토 11)
    return out


def _single_reason(points: list[Point], ctx: "_Ctx | None" = None) -> str:
    """[NEW 11-17] 비교할 값이 하나뿐인 이유. 남은 점이 시점 하나만 가진 값이면(지역 등은 고정) 해끼리 견주려던 것이다 → 다시 물을 방법을 알린다"""
    # [CHANGED 11-18] 이전: 점이 시점 하나뿐이면 늘 '해끼리 비교' 라고 했다 → 질문이 한 해(2024)만 정해 국적 · 지역끼리 견주는데 자료에 '계' 만 있는 경우
    #   (Q34 국적별 순위)에도 '한 해뿐이라 해끼리 비교하지 못함' 이 나갔다. 조건에 시점을 둘 이상 적었거나 적지 않았을 때만 해 비교로 본다
    asked_years = _explicit_select(ctx).get(TIME_COL, set()) if ctx is not None else set()
    if len(points) == 1 and set(points[0].key) == {TIME_COL} and len(asked_years) != 1:
        return f"자료가 {points[0].key[TIME_COL]} 한 해뿐이라 해끼리 비교하지 못함"
    return SINGLE_VALUE


def _explicit_select(ctx: "_Ctx") -> dict[str, set[str]]:
    """이 단계가 조건(select)에 **이름으로 적은** 값 {열: {값}}. 피연산자가 있으면 첫 피연산자, 없으면 차트 계획의 select"""
    ops = ctx.step.operands
    sel = ops[0].select if ops else (ctx.default.select if ctx.default is not None and not ctx.step.input else {})
    return {c: {str(v) for v in vals} for c, vals in (sel or {}).items()}


def _without_totals(points: list[Point], notes: list[str], explicit: dict[str, set[str]] | None = None) -> list[Point]:
    """[NEW 11-17] 순위 · 극값의 비교 대상에서 총계 행(전국 · 계 · 합계 …)을 뺀다. 전국은 시도의 합이라 늘 1위가 된다 (자체 검토 A-2).
    값이 여럿인 key 열만 본다 (전국 하나를 시점별로 비교하는 극값은 그대로). 총계만 있으면 빼지 않는다.
    [CHANGED 11-17 외부 피드백] explicit: 조건에 총계를 이름으로 적은 열은 건드리지 않는다 ('전국과 서울 중 어디가 많아' 에 서울을 답했다)"""
    for c in dict.fromkeys(c for p in points for c in p.key if c != TIME_COL):
        vals = {str(p.key.get(c)) for p in points if c in p.key}
        if len(vals) < 2 or not (total := totals_in(c, vals)) or not (vals - total):
            continue
        if total & (explicit or {}).get(c, set()):
            continue
        notes.append(f"총계 행 제외: {c} {sorted(total)}")
        points = [p for p in points if str(p.key.get(c)) not in total]
    return points


def _rank(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)        # 값은 원래 단위로 두고 순위는 extra["rank"] 에 싣는다
    if _failed(s):
        return out
    desc = ctx.arg("order", "desc") != "asc"
    pts_all = _without_totals(s.points, out.notes, _explicit_select(ctx))        # [NEW 11-17] 전국 · 계 가 1위가 되지 않게 (자체 검토 A-2)
    # [CHANGED 11-17] 묶음 기준: 시점 말고 달라지는 분류(지역 등)가 있으면 같은 시점 안에서, 시점만 달라지면 해끼리 (보고서 12.3, 결정).
    #   이전: 늘 같은 시점 안에서 → 지역이 하나면 모든 해가 1위였다
    others = any(len({str(p.key.get(c)) for p in pts_all}) > 1 for c in dict.fromkeys(c for p in pts_all for c in p.key) if c != TIME_COL)
    group = (lambda p: (p.key.get(TIME_COL),)) if others else (lambda p: ())
    if all(len(g) < 2 for g in _groups(pts_all, group).values()):
        out.notes.append(_single_reason(pts_all, ctx))        # [NEW 11-17] 값 하나로 순위를 매기면 '1위' 가 사실처럼 나간다 (보고서 11.3 H2)
        return out
    for pts in _groups(pts_all, group).values():
        ordered = sorted(pts, key=lambda p: p.value, reverse=desc)
        rank = 0
        for i, p in enumerate(ordered, 1):
            if i == 1 or p.value != ordered[i - 2].value:
                rank = i
            if ctx.step.top_n and rank > ctx.step.top_n:
                break
            out.points.append(Point(dict(p.key), p.value, {"rank": rank}))
    return out


def _extreme(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)
    if not _failed(s) and not s.points:
        out.notes.append("조건에 맞는 값이 없음")
    elif not _failed(s):
        pick = min if ctx.arg("kind", "max") == "min" else max
        pts = _without_totals(s.points, out.notes, _explicit_select(ctx))        # [NEW 11-17] '가장 많은 곳' 이 전국이 되지 않게 (자체 검토 A-2)
        if len(pts) < 2:
            # [NEW 11-17] View 에 2025년 한 행뿐인데 '가장 적었던 해는 2025년' 이라고 답했다 (보고서 11.3 H2, 실제 HCX)
            out.notes.append(_single_reason(pts, ctx))
            return out
        target = pick(p.value for p in pts)
        out.points = [Point(dict(p.key), p.value) for p in pts if p.value == target]   # 동점은 모두
    return out


INDICATOR_HINTS = ("항목", "종류", "지표")   # 분류 열이지만 지표를 담는 이름 (DT_1B8000G '종류별', '기본항목별')


def _mixed_for_sum(points: list[Point], by: list[str]) -> str | None:
    """더하면 안 되는 것이 섞였는가. View 구조: 시점 · KOSIS 분류 열들 · 항목(KOSIS 지표) · 값 (rag/ingestion/build_view.py)

      항목 열(또는 이름이 항목·종류·지표인 분류 열)에 값이 여럿 → 지표가 섞임. 괄호 단위가 모두 같을 때만 허용
      그 밖의 분류 열에 값이 여럿 → 범주 (지역, 혼인상태 …). 더해도 된다. 단 값에 단위가 붙어 서로 다르면 지표로 본다
      범주 값에 총계(계·합계)가 섞이면 두 번 센다 → 보류
    [CHANGED 11-11] 이전: 열 이름(지역·연령·성별)으로만 범주를 알아봐서 '혼인상태별' 15세미만 + 15세이상을 거부했다 (2차 검수)
    """
    cols = sorted({c for p in points for c in p.key if c != TIME_COL and c not in by})
    for c in cols:
        vals = sorted({str(p.key[c]) for p in points if c in p.key})
        if len(vals) < 2:
            continue
        units = [unit_of(v) for v in vals]
        if c == ITEM_COL and all(age_span(v) for v in vals):
            continue                       # [NEW 11-18] 나이(0세 · 1세 …)가 항목 열 값인 표: 지표가 섞인 것이 아니라 나이 구간이다 (F6)
        if c == ITEM_COL or any(h in c for h in INDICATOR_HINTS):
            if None in units or len(set(units)) > 1:
                return f"서로 다른 지표를 합칠 수 없음: { {c: vals} }"
        elif any(units) and (None in units or len(set(units)) > 1):
            return f"서로 다른 지표를 합칠 수 없음: { {c: vals} }"
        elif total := sorted(totals_in(c, vals)):
            return f"총계 행이 섞여 두 번 셈: {c} {total} + 나머지 {[v for v in vals if v not in total]}"
    return None


def _partial_groups(s: Series, by: list[str]) -> dict[tuple, list[str]]:
    """[NEW 11-17 외부 피드백] 시점별 합계 · 평균에서 다른 시점에는 값이 있는 구성원(지역 등)의 값이 빈 묶음 → {묶음: [빠진 구성원 이름]}.
    구성원 = 점의 key 에서 묶는 열(by)을 뺀 것. 값이 빈 행(dropped)만 본다: 행 자체가 없는 경우(그 해에 없던 지역)는 건드리지 않는다"""
    cols = [c for c in dict.fromkeys(c for p in s.points for c in p.key) if c not in by]
    if not cols:
        return {}
    members = {tuple(str(p.key.get(c)) for c in cols) for p in s.points}
    out: dict[tuple, list[str]] = {}
    for d in s.dropped:
        m = tuple(str(d.get(c)) for c in cols)
        if m in members:
            names = out.setdefault(tuple(d.get(c) for c in by), [])
            if (label := " ".join(m)) not in names:
                names.append(label)
    return out


def _member_cols(s: Series, by: list[str]) -> list[str]:
    return [c for c in dict.fromkeys(c for p in s.points for c in p.key) if c not in by]


def _absent_members(s: Series, by: list[str]) -> dict[tuple, tuple[list[str], int, str]]:
    """[NEW 11-17] 묶음(시점)마다 다른 묶음에는 있는데 **행 자체가 없는** 구성원 → {묶음: ([이름], 남은 구성원 수)}.
    값이 빈 행(dropped)은 _partial_groups 가 맡는다 (그 묶음은 비운다)"""
    cols = _member_cols(s, by)
    if not cols:
        return {}
    key = lambda p: tuple(str(p.key.get(c)) for c in cols)      # noqa: E731
    groups = _groups(s.points, lambda p: tuple(p.key.get(c) for c in by))
    members = list(dict.fromkeys(key(p) for p in s.points))
    empty = {(tuple(d.get(c) for c in by), tuple(str(d.get(c)) for c in cols)) for d in s.dropped}
    out = {}
    for gk, pts in groups.items():
        have = {key(p) for p in pts}
        gone = [m for m in members if m not in have and (gk, m) not in empty]
        if gone:
            out[gk] = ([" ".join(m) for m in gone], len(have), " · ".join(c.removesuffix("별") for c in cols))
    return out


def _empty_members(s: Series, explicit: dict[str, set[str]]) -> list[str]:
    """[NEW 11-17] 조건에 이름을 적었는데 값이 하나도 없는 구성원. 값이 모두 비면 그 열이 고정 좌표가 되어 구성원으로 잡히지 않는다
    (서울만 값이 있으면 '서울 · 부산 합계' 가 서울 값이 됐다)"""
    out = []
    for col, names in explicit.items():
        if col in (TIME_COL, ITEM_COL) or len(names) < 2:
            continue
        seen = {str(p.key[col]) for p in s.points if col in p.key} or ({str(s.fixed[col])} if col in s.fixed else set())
        if seen and (missing := sorted(names - seen)):
            out += missing
    return out


def _double_counted(points: list[Point]) -> str | None:
    """[NEW 11-18] 합치는 값 중 같은 좌표의 행이 둘 이상이거나 나이 구간이 겹치면 합계가 부풀려진다 (F6, 검토 5).
    HCX 가 처음부터 aggregate 를 골라도 planner 의 연령 검사를 거치지 않으므로 계산 단계에서 실제로 고른 행을 본다"""
    seen: dict[tuple, int] = {}
    for p in points:
        k = tuple(sorted((c, str(v)) for c, v in p.key.items()))
        seen[k] = seen.get(k, 0) + 1
    if rep := next((k for k, n in seen.items() if n > 1), None):
        return f"같은 좌표의 행이 둘 이상이라 합계를 낼 수 없음: {dict(rep)}"
    cols = {c for p in points for c in p.key if c != TIME_COL}
    for c in cols:
        groups: dict[tuple, list[tuple[int, int | None]]] = {}
        for p in points:
            span = age_span(str(p.key.get(c))) if c in p.key else None
            if span is None:
                groups = {}
                break
            groups.setdefault(tuple(str(v) for k, v in sorted(p.key.items()) if k != c), []).append(span)
        for spans in groups.values():
            spans.sort(key=lambda s: s[0])
            if any(a[1] is None or b[0] <= a[1] for a, b in zip(spans, spans[1:])):
                return f"합치는 나이 구간이 서로 겹쳐 합계를 낼 수 없음 ({c})"
    return None


def _aggregate(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)
    if _failed(s):
        return out
    # 항목을 여럿 골랐을 때 단위가 다르면 더하지 않는다 ('혼인건수(건)' + '조혼인율(천명당)')
    units = sorted({u for p in s.points for v in p.key.values() if (u := unit_of(str(v)))})
    if len(units) > 1:
        out.notes.append(f"단위가 다른 값을 합칠 수 없음: {', '.join(units)}")
        return out
    by = ctx.arg("by") or []
    if why := _mixed_for_sum(s.points, by):
        out.notes.append(why)
        return out
    if why := _double_counted(s.points):
        out.notes.append(why)
        return out
    partial = _partial_groups(s, by) if TIME_COL in by else {}
    name = "평균" if ctx.step.agg == "mean" else "합계"
    obj = name + ("을" if name == "평균" else "를")
    if empty := _empty_members(s, _explicit_select(ctx)):
        # [NEW 11-17] 조건에 이름을 적은 구성원(부산)의 값이 하나도 없으면, 그 구성원이 빠진 합계를 '합계' 로 내지 않는다 (남은 한계 2)
        out.notes.append(f"{', '.join(empty)} 값이 없어 {obj} 내지 않음")
        return out
    absent = _absent_members(s, by) if TIME_COL in by else {}
    for gk, pts in _groups(s.points, lambda p: tuple(p.key.get(c) for c in by)).items():
        if gk in partial:     # [NEW 11-17 외부 피드백] 일부 입력이 빈 시점의 합계는 다른 시점과 견줄 수 없다 (200 → 100 → 200)
            out.points.append(Point(dict(zip(by, gk)), None))
            out.notes.append(f"{', '.join(str(v) for v in gk)}: {', '.join(partial[gk])} 값이 없어 {obj} 내지 않음")
            continue
        if gk in absent:      # [NEW 11-17] 행 자체가 없는 구성원(출범 전 세종 등): 값은 남기고 몇 개의 합인지 밝힌다 (결정: 부분합 + 명시)
            names, n, what = absent[gk]
            out.notes.append(f"{', '.join(str(v) for v in gk)}: {', '.join(names)} 행이 없어 나머지 {n}개 {what}만 {name}")
        total = sum(p.value for p in pts)
        out.points.append(Point(dict(zip(by, gk)), total / len(pts) if ctx.step.agg == "mean" else total))
    if TIME_COL in by:
        # [NEW 11-17] 그 시점의 입력이 **모두** 비어 합계 점이 안 만들어진 시점은 차트에 빈 점으로 남긴다 (일부만 비었으면 있는 값만 더한 점이 있다. 재검토 11)
        have = {tuple(sorted((c, str(v)) for c, v in p.key.items())) for p in out.points}
        wanted: dict[tuple, dict] = {}       # 여러 입력(서울 · 부산)이 같은 시점을 비웠으면 한 번만
        for m in s.missing:
            k = {c: m.get(c) for c in by}
            wanted.setdefault(tuple(sorted((c, str(v)) for c, v in k.items())), k)
        out.missing = _interior(out.points, [k for t, k in wanted.items() if t not in have])
    return out


# ── 두 피연산자 (diff · ratio) ───────────────────────────────────
def _join(points: list[Point], on: list[str], fixed: dict | None = None) -> dict[tuple, Point | None]:
    """join 키 → 점. 같은 키에 값이 둘 이상이면 None (키 중복)

    fixed: 피연산자 안에서 값이 하나로 고정된 열. join_on 에 그 열이 있으면 고정 값으로 짝짓는다
           (예전: key 에 없는 열은 모두 'None' 이 되어, 서울 값과 부산 값이 같은 지역처럼 짝지어졌다)
    """
    out: dict[tuple, Point | None] = {}
    for p in points:
        k = tuple(str(p.key[c] if c in p.key else (fixed or {}).get(c)) for c in on)
        out[k] = None if k in out else p
    return out


def _missing_join(series: list["Series"], on: list[str]) -> str | None:
    """join_on 의 열이 각 피연산자의 View 에 실제로 있는가. 없으면 모든 점이 'None' 키로 묶여 다른 해·지역이 섞인다"""
    for s in series:
        if s.carried is None and (miss := [c for c in on if c not in s.columns]):
            return f"결합 열이 View 에 없음: {miss} ({s.item or s.record_ids[0]})"
    return None


def _pair(fn, same_unit: bool):
    def run(ctx: _Ctx) -> Calc:
        a, b = ctx.series("a", 0), ctx.series("b", 1)
        if ctx.step.op == "ratio":     # TODO(후속 명세): 단위가 다른 두 지표의 비 — 임시로 'a단위/b단위'
            unit = ratio_unit(a.unit, b.unit)
        else:
            unit = result_unit(ctx.step.op, a.unit)        # [CHANGED 11-13] 이전: a.unit — 비율(%)끼리의 diff 는 %p
        out = ctx.calc(a, b, unit=unit)
        if _failed(a, b):
            return out
        if why := _incompatible([a, b], same_unit):
            out.notes.append(why)
            return out
        on = ctx.step.join_on or []
        if not on and (len(a.points) > 1 or len(b.points) > 1):
            out.notes.append("join_on 필요: 피연산자에 값이 여러 개")
            return out
        if why := _missing_join([a, b], on):
            out.notes.append(why)
            return out
        ja, jb = _join(a.points, on, a.fixed), _join(b.points, on, b.fixed)
        for k in dict.fromkeys([*ja, *jb]):
            pa, pb = ja.get(k), jb.get(k)
            key = dict(zip(on, k))
            if pa is None or pb is None:
                dup = (k in ja and pa is None) or (k in jb and pb is None)
                out.notes.append(f"{key}: " + ("키 중복" if dup else "한쪽 값 없음"))
                out.points.append(Point(key, None))
                continue
            v, why = fn(pa.value, pb.value)
            if why:
                out.notes.append(f"{key}: {why}")
            out.points.append(Point(key, v))
        return out
    return run


def _combine(ctx: _Ctx) -> Calc:
    """여러 값 더하기·빼기. 피연산자마다 sign(+/-). 시점끼리 짝지어 Σ sign × 값

    피연산자 하나는 짝지을 키마다 값이 하나여야 한다 (같은 지표의 여러 범주 합은 aggregate 로 먼저).
    """
    ops = ctx.step.operands or []
    terms = [(o.sign or "+", load_series(o, ctx.records, o.sign or "+")) for o in ops]
    series = [s for _, s in terms]
    out = ctx.calc(*series, unit=series[0].unit if series else None)
    if len(terms) < 2:
        out.notes.append("combine 은 피연산자가 2개 이상 필요")
        return out
    if _failed(*series):
        return out
    if why := _incompatible(series, same_unit=True):
        out.notes.append(why)
        return out
    on = ctx.step.join_on or ([TIME_COL] if all(TIME_COL in p.key for s in series for p in s.points) else [])
    if not on and any(len(s.points) > 1 for s in series):
        out.notes.append("join_on 필요: 피연산자에 값이 여러 개")
        return out
    if why := _missing_join(series, on):
        out.notes.append(why)
        return out
    joins = [_join(s.points, on, s.fixed) for s in series]
    for k in dict.fromkeys(k for j in joins for k in j):
        key, total, why = dict(zip(on, k)), 0, None      # 정수 0 에서 시작: 정수 입력은 정수로 끝까지 (0.0 이면 실수가 된다)
        for (sign, s), j in zip(terms, joins):
            if k not in j:
                why = f"값 없음 ({s.item or '피연산자'})"
                break
            if j[k] is None:
                why = f"키 중복 ({s.item or '피연산자'}: 짝지을 키마다 값이 하나여야 함)"
                break
            total += j[k].value if sign == "+" else -j[k].value
        if why:
            out.notes.append(f"{key}: {why}")
        out.points.append(Point(key, None if why else total))
    return out


def _ratio(a: float, b: float):
    return (None, "분모 0") if b == 0 else (a / b, None)


# ── share ────────────────────────────────────────────────────────
def _same_row_denominator(part: Series, total: Series, den, on: list[str]) -> str | None:
    """[NEW 11-18] 분모로 가져온 행이 부분과 같은 행인가 (F5, Q05·Q28). View 에 전국 행이 없어 분모 조건(시점만)이 서울 행 하나만 골라
    서울 ÷ 서울 = 100.0% 가 됐다. 요청한 분모(basis · label 의 지역)와 실제 분모 행의 지역이 다를 때만 막는다 —
    전국 ÷ 전국 = 100% 처럼 분모가 정말 같은 것인 경우는 그대로 계산한다"""
    # [CHANGED 11-18] 이전: 점 목록 전체가 같을 때만 봤다 → 분모에 다른 연도가 더 있으면 검사를 건너뛰어 100% 가 다시 나왔다 (검토 4).
    #   조인 키(시점)로 맞춘 점마다 분모 값이 부분 값과 같은지 본다
    joined = {tuple(str(p.key.get(c)) for c in on): p for p in total.points}
    if not part.points or any((t := joined.get(tuple(str(p.key.get(c)) for c in on))) is None or t.value != p.value for p in part.points):
        return None
    region_cols = [c for c in part.fixed if any(h in c for h in REGION_HINTS)]
    if not region_cols or any(str(part.fixed[c]) != str(total.fixed.get(c)) for c in region_cols):
        return None
    asked = f"{den.basis or ''} {den.label or ''}"
    actual = [str(part.fixed[c]) for c in region_cols]
    if all(v in asked or v in TOTAL_LABELS and any(t in asked for t in TOTAL_LABELS) for v in actual):
        return None
    return f"분모로 쓴 자료({', '.join(actual)})가 부분과 같은 행이라 비중이 항상 100%가 됨 (질문의 분모 '{asked.strip()}' 자료가 View 에 없음)"


def _share(ctx: _Ctx) -> Calc:
    part, den = ctx.series("part"), ctx.step.denominator
    question = den is not None and den.scope == "question"
    out = ctx.calc(part, unit=result_unit("share", part.unit))
    out.scope_label = (den.label if den else None) or (None if question else SELECTED_LABEL)
    if _failed(part):
        return out
    has_time = all(TIME_COL in p.key for p in part.points)
    on = ctx.step.join_on or ([TIME_COL] if has_time else [])
    if why := _missing_join([part], on):
        out.notes.append(why)
        return out
    if question:
        if den.operand is None:
            out.notes.append("denominator.operand 없음 (scope=question)")
            return out
        total = load_series(den.operand, ctx.records, "total")
        out.inputs += total.inputs()
        out.record_ids = list(dict.fromkeys(out.record_ids + total.record_ids))
        out.notes += total.errors + total.notes
        if _failed(total):
            return out
        if why := _missing_join([total], on):
            out.notes.append(why)
            return out
        if why := _incompatible([part, total], same_unit=True):
            out.notes.append(why)
            return out
        if why := _same_row_denominator(part, total, den, on):
            out.notes.append(why)
            return out
        totals = {k: (p.value if p else None) for k, p in _join(total.points, on).items()}
    else:   # 분모 범위가 질문에 없음 → 선택한 항목의 합 (같은 시점끼리)
        if why := _mixed_for_sum(part.points, on):          # [NEW 11-16] 총계 행(전국·계)이 섞이면 두 번 센다 (검수 M3-06)
            out.notes.append(why)
            return out
        if len({tuple(sorted((c, str(v)) for c, v in p.key.items() if c not in on)) for p in part.points}) < 2:
            out.notes.append("선택한 항목이 하나뿐이라 비중이 항상 100%")      # [NEW 11-16] 검수 M3-17
            return out
        totals = {k: sum(p.value for p in pts)
                  for k, pts in _groups(part.points, lambda p: tuple(str(p.key.get(c)) for c in on)).items()}
    for p in part.points:
        t = totals.get(tuple(str(p.key.get(c)) for c in on))
        if not t:
            out.notes.append(f"{p.key}: " + ("분모 0" if t == 0 else "분모 총계 없음"))
        out.points.append(Point(dict(p.key), p.value / t * 100 if t else None))
    return out


_OPS: dict[str, Callable[[_Ctx], Calc]] = {
    "raw": _raw, "change": _between(_change), "growth_rate": _between(_growth_rate), "cagr": _between(_cagr),
    "index": _index, "share": _share, "diff": _pair(lambda a, b: (a - b, None), same_unit=True),
    "ratio": _pair(_ratio, same_unit=False), "rank": _rank, "extreme": _extreme, "aggregate": _aggregate,
    "combine": _combine,
}


# ── 실행 ─────────────────────────────────────────────────────────
def run_steps(steps: list[Step], records: list[Record], default: Plan | None = None) -> dict[str, Calc]:
    """steps 를 순서대로 실행 → {step_id: Calc}. default = 차트용 단계에서 operands 를 생략했을 때 쓸 계획"""
    by_id = {r.id: r for r in records}
    done: dict[str, Calc] = {}
    for st in steps:
        try:
            calc = _OPS[st.op](_Ctx(st, by_id, default, done))
        except Exception as e:  # noqa: BLE001  [NEW 11-17] 한 단계의 예기치 못한 오류가 같은 요청의 다른 계산까지 멈추지 않게 (검수 8)
            log.exception("%s: %s %s", INTERNAL_ERROR, st.step_id, st.op)
            calc = Calc(st.op, notes=[f"{INTERNAL_ERROR}: {type(e).__name__}"])
        calc.notes = list(dict.fromkeys(calc.notes))
        done[st.step_id] = calc
    return done


def to_calc_result(step: Step, calc: Calc) -> CalcResult:
    return CalcResult(step_id=step.step_id, op=step.op, value=calc.value, unit=calc.unit, display_ref=step.display_ref,
                      inputs=calc.inputs, record_ids=calc.record_ids, scope_label=calc.scope_label,
                      agg=(step.agg or "sum") if step.op == "aggregate" else None,      # [NEW 11-17] 집계 방식 (agg 를 비우면 합계)
                      note="; ".join(calc.notes) or None)


# [NEW] 연산이 실제로 읽는 Step 인자. 여기 없는 인자(raw 의 from·to 등)는 값이 달라도 결과에 영향이 없다 → 같은 계산인지 볼 때 무시한다.
# 연산별 추가 인자(by · order · kind)는 모든 연산에서 비교한다. 새 연산이나 인자를 추가하면 이 표도 고친다
USED_ARGS: dict[str, tuple[str, ...]] = {
    "raw": (), "extreme": ("kind",), "rank": ("top_n", "order"), "aggregate": ("agg",),
    "change": ("from_", "to", "base"), "growth_rate": ("from_", "to", "base"), "cagr": ("from_", "to", "base"),
    "index": ("from_", "base"),
    "diff": ("join_on",), "ratio": ("join_on",), "combine": ("join_on",), "share": ("join_on", "denominator"),
}


def step_key(step: Step, default: Plan | None = None, records: dict[str, Record] | None = None) -> str | None:
    """같은 계산이면 같은 문자열. 앞 단계의 결과를 받는 단계(input)나 피연산자를 알 수 없는 단계는 None (재사용하지 않는다).
    records 를 주면 조건(select) 문구가 아니라 **실제로 고른 행**으로 비교한다
    (View 에 지역이 하나뿐이면 '지역=전국' 조건이 있든 없든 고른 행이 같다)"""
    if step.input:
        return None
    if step.operands:
        ops = list(step.operands)
    elif default is not None:     # 피연산자를 생략하면 계획의 record_id · select 를 쓴다 (_Ctx.series 와 같은 규칙)
        ops = [Operand(role="value", record_id=default.record_id, select=default.select)]
    else:
        return None
    operands = []
    for o in ops:
        d = o.model_dump(mode="json")
        rec = (records or {}).get(o.record_id)
        if rec is not None:
            sel = select_rows(rec, o.select, o.item)
            d["select"] = {"columns": list(sel.columns), "rows": sel.rows, "errors": list(sel.errors)}
        operands.append(d)
    args = {name: getattr(step, name) for name in USED_ARGS.get(step.op, ())}
    args = {k: v.model_dump(mode="json") if hasattr(v, "model_dump") else v for k, v in args.items()}
    return json.dumps({"op": step.op, "operands": operands, "args": args, "extra": step.model_extra or {}},
                      sort_keys=True, ensure_ascii=False, default=str)


def run_answer_steps(steps: list[Step], records: list[Record], reuse: dict[str, Calc] | None = None) -> list[CalcResult]:
    """질문용 계산. 차트 검증 결과와 관계없이 실행한다 (명세 7장).
    reuse = {질문용 step_id: 같은 계산인 차트 단계의 Calc}. 있으면 다시 계산하지 않고 그 결과를 복사해 쓴다"""
    reuse = reuse or {}
    done = run_steps([st for st in steps if st.step_id not in reuse], records)
    done.update({sid: copy.deepcopy(calc) for sid, calc in reuse.items()})
    return [to_calc_result(st, done[st.step_id]) for st in steps]
