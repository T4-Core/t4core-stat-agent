"""
[NEW] Calculate — Step 하나를 실행한다 (연산 11종). 차트용(plans[].steps)과 질문용(answer_steps)이 같이 쓴다

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
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.agent.chart_calculate.display import result_unit, unit_of
from backend.agent.chart_calculate.select import ITEM_COL, VALUE_COL, select_rows
from backend.agent.chart_calculate.validate import TOTAL_LABELS
from backend.schemas.chart import CalcInput, CalcResult, Operand, Plan, Step
from backend.schemas.record import Record

TIME_COL = "시점"
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
    item = operand.item
    if item is None and ITEM_COL in dims and len(found := {r[sel.col(ITEM_COL)] for r in sel.rows}) == 1:
        item = found.pop()
    vi = sel.col(VALUE_COL) if VALUE_COL in sel.columns else None
    fixed = {c: sel.rows[0][sel.col(c)] for c in dims if c not in key_cols} if sel.rows else {}
    return Series(
        role, [rec.id], item, operand.unit or unit_of(item, rec.metadata.get("unit")), rec.metadata.get("prd_se"),
        points=[Point({c: r[sel.col(c)] for c in key_cols}, r[vi]) for r in sel.rows],
        errors=list(sel.errors),
        notes=[f"값이 비어 제외한 행 {len(sel.dropped)}개"] if sel.dropped else [],
        columns=list(sel.columns), fixed=fixed, unit_source=operand.unit_source)


class _Ctx:
    """Step 하나를 실행하는 동안의 문맥: 피연산자를 어디서 가져올지 정한다"""

    def __init__(self, step: Step, records: dict[str, Record], default: Plan | None, done: dict[str, Calc]):
        self.step, self.records, self.default, self.done = step, records, default, done

    def arg(self, name: str, fallback=None):
        """스키마에 아직 없는 연산별 인자 (kind, by, order) — Step 이 extra="allow" 로 보관한다"""
        return (self.step.model_extra or {}).get(name, fallback)

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
            return Series(role, prev.record_ids, item=prev.item, unit=prev.unit, points=[p for p in prev.points if p.value is not None],
                          errors=[] if prev.points else list(prev.notes) or ["앞 단계 결과 없음"], carried=prev.inputs)
        if self.default is not None:
            return load_series(Operand(role=role, record_id=self.default.record_id, select=self.default.select),
                               self.records, role)
        return Series(role, [], errors=[f"피연산자 없음: {role}"])

    def calc(self, *series: Series, unit: str | None = None) -> Calc:
        """빈 결과. 피연산자에 오류가 있으면 points 를 채우지 않고 돌려준다 → 값 None + 사유"""
        ids = list(dict.fromkeys(i for s in series for i in s.record_ids))
        return Calc(self.step.op, unit=unit, item=next((s.item for s in series if s.item), None), record_ids=ids,
                    inputs=[i for s in series for i in s.inputs(with_fixed=len(series) > 1)],
                    notes=[m for s in series for m in s.errors + s.notes])


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
    [단위 미상, 명, 건] 을 함께 계산했다 (GPT 검토). 이제 확인할 수 없으면 계산하지 않는다.
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
    # [CHANGED 11-11] HCX 가 고른 단위는 모르는 단위로 본다: 합계출산율에 '명' 을 붙이면 출생아수(명)와 계산됐다 (GPT 2차 검토)
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
    return (b.value - a.value) / a.value * 100, None


def _cagr(a: Point, b: Point):
    try:
        years = int(str(b.key[TIME_COL])[:4]) - int(str(a.key[TIME_COL])[:4])
    except (KeyError, ValueError):
        return None, "연수를 알 수 없음"
    if years <= 0:
        return None, "연수가 0 이하"
    if a.value <= 0 or b.value < 0:
        return None, "기준값이 0 이하이거나 끝값이 음수"
    return ((b.value / a.value) ** (1 / years) - 1) * 100, None


def _between(fn):
    def run(ctx: _Ctx) -> Calc:
        st, s = ctx.step, ctx.series("value")
        out = ctx.calc(s, unit=result_unit(st.op, s.unit))
        if _failed(s):
            return out
        used: list[Point] = []
        for gk, pts in _groups(s.points, _no_time).items():
            if st.base == "prev":                      # 직전 시점 대비 → 시점마다 값 하나
                pairs = [(a, b, b.key) for a, b in zip(pts, pts[1:])]
                if not pairs:
                    out.notes.append("시점이 하나뿐이라 직전 시점이 없음")
            else:                                      # 두 시점 → 묶음마다 값 하나
                by_t = {str(p.key.get(TIME_COL)): p for p in pts}
                t0 = str(st.from_ or st.base or pts[0].key.get(TIME_COL))
                t1 = str(st.to or pts[-1].key.get(TIME_COL))
                a, b = by_t.get(t0), by_t.get(t1)
                if a is None or b is None:
                    out.points.append(Point(dict(gk), None))
                    out.notes.append(f"시점 {t0 if a is None else t1} 값 없음")
                    continue
                pairs = [(a, b, dict(gk))]
            for a, b, key in pairs:
                v, why = fn(a, b)
                out.points.append(Point(dict(key), v))
                used += [a, b]
                if why:
                    out.notes.append(why)
        out.inputs = s.inputs(list({id(p): p for p in used}.values())) if s.carried is None else s.carried
        return out
    return run


# ── 한 피연산자, 점마다 (raw · index · rank · extreme · aggregate) ─
def _raw(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)
    if not _failed(s):
        out.points = [Point(dict(p.key), p.value) for p in s.points]
    return out


def _index(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=result_unit("index", s.unit))
    if _failed(s):
        return out
    for gk, pts in _groups(s.points, _no_time).items():
        t0 = str(ctx.step.base or ctx.step.from_ or pts[0].key.get(TIME_COL))
        base = next((p for p in pts if str(p.key.get(TIME_COL)) == t0), None)
        if base is None or base.value == 0:
            out.notes.append(f"기준 시점 {t0} 값 없음" if base is None else "기준값 0")
            out.points += [Point(dict(p.key), None) for p in pts]
        else:
            out.points += [Point(dict(p.key), p.value / base.value * 100) for p in pts]
    return out


def _rank(ctx: _Ctx) -> Calc:
    s = ctx.series("value")
    out = ctx.calc(s, unit=s.unit)        # 값은 원래 단위로 두고 순위는 extra["rank"] 에 싣는다
    if _failed(s):
        return out
    desc = ctx.arg("order", "desc") != "asc"
    for pts in _groups(s.points, lambda p: (p.key.get(TIME_COL),)).values():   # 같은 시점 안에서 순위
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
    if not _failed(s):
        pick = min if ctx.arg("kind", "max") == "min" else max
        target = pick(p.value for p in s.points)
        out.points = [Point(dict(p.key), p.value) for p in s.points if p.value == target]   # 동점은 모두
    return out


INDICATOR_HINTS = ("항목", "종류", "지표")   # 분류 열이지만 지표를 담는 이름 (DT_1B8000G '종류별', '기본항목별')


def _mixed_for_sum(points: list[Point], by: list[str]) -> str | None:
    """더하면 안 되는 것이 섞였는가. View 구조: 시점 · KOSIS 분류 열들 · 항목(KOSIS 지표) · 값 (rag/ingestion/build_view.py)

      항목 열(또는 이름이 항목·종류·지표인 분류 열)에 값이 여럿 → 지표가 섞임. 괄호 단위가 모두 같을 때만 허용
      그 밖의 분류 열에 값이 여럿 → 범주 (지역, 혼인상태 …). 더해도 된다. 단 값에 단위가 붙어 서로 다르면 지표로 본다
      범주 값에 총계(계·합계)가 섞이면 두 번 센다 → 보류
    [CHANGED 11-11] 이전: 열 이름(지역·연령·성별)으로만 범주를 알아봐서 '혼인상태별' 15세미만 + 15세이상을 거부했다 (GPT 2차 검토)
    """
    cols = sorted({c for p in points for c in p.key if c != TIME_COL and c not in by})
    for c in cols:
        vals = sorted({str(p.key[c]) for p in points if c in p.key})
        if len(vals) < 2:
            continue
        units = [unit_of(v) for v in vals]
        if c == ITEM_COL or any(h in c for h in INDICATOR_HINTS):
            if None in units or len(set(units)) > 1:
                return f"서로 다른 지표를 합칠 수 없음: { {c: vals} }"
        elif any(units) and (None in units or len(set(units)) > 1):
            return f"서로 다른 지표를 합칠 수 없음: { {c: vals} }"
        elif total := sorted(set(vals) & TOTAL_LABELS):
            return f"총계 행이 섞여 두 번 셈: {c} {total} + 나머지 {[v for v in vals if v not in total]}"
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
    for gk, pts in _groups(s.points, lambda p: tuple(p.key.get(c) for c in by)).items():
        total = sum(p.value for p in pts)
        out.points.append(Point(dict(zip(by, gk)), total / len(pts) if ctx.step.agg == "mean" else total))
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
            unit = result_unit("ratio", None) if a.unit == b.unit else f"{a.unit}/{b.unit}"
        else:
            unit = a.unit
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
        totals = {k: (p.value if p else None) for k, p in _join(total.points, on).items()}
    else:   # 분모 범위가 질문에 없음 → 선택한 항목의 합 (같은 시점끼리)
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
        calc = _OPS[st.op](_Ctx(st, by_id, default, done))
        calc.notes = list(dict.fromkeys(calc.notes))
        done[st.step_id] = calc
    return done


def to_calc_result(step: Step, calc: Calc) -> CalcResult:
    return CalcResult(step_id=step.step_id, op=step.op, value=calc.value, unit=calc.unit, display_ref=step.display_ref,
                      inputs=calc.inputs, record_ids=calc.record_ids, scope_label=calc.scope_label,
                      note="; ".join(calc.notes) or None)


def run_answer_steps(steps: list[Step], records: list[Record]) -> list[CalcResult]:
    """질문용 계산. 차트 검증 결과와 관계없이 실행한다 (명세 7장)"""
    done = run_steps(steps, records)
    return [to_calc_result(st, done[st.step_id]) for st in steps]
