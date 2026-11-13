"""
[NEW] ChartContent 구성 — 계산 결과(Calc)를 Draw 가 그대로 그릴 수 있는 행·축·설정으로 바꾸고 검증한다

  build_chart(plan, records, requirements)
    1. plan.steps 실행 (calculate.run_steps)
    2. 원래 차트로 구성 → 검증 (validate.check_chart)
    3. ② 가 실패하고 fallback_chart 가 있으면 대체 차트로 다시 구성 → 대체 차트의 기본 조건으로 다시 검증
    4. 통과한 것이 있으면 그 ChartContent, 없으면 None. 과정은 ChartValidation 에 남긴다

  행 구조 (명세 5장)
    long    행 하나 = 값 하나.   [분류 열…, 항목, 값]            line bar area stacked_bar combo pie donut …
    joined  행 하나 = 점 하나.   [결합 키…, 지표1, 지표2, …]      scatter bubble dumbbell

  명세에 없어 여기서 정한 것 (TODO: 팀 합의 후 조정)
    - combo 는 long 형식이라 y·y2 가 같은 '값' 열을 가리킨다 → 어느 지표가 어느 축인지 options.series_axis 에 적는다
    - [NEW] line 도 지표 2개의 단위가 다르면 y(왼쪽)·y2(오른쪽) 두 축을 쓴다 (_dual_axis). combo 와 같은 방식으로 적되
      options.marks 가 {"y": "line", "y2": "line"} 이다. 갈래 하나에 항목이 여럿이면 축을 나눌 수 없어 예전처럼 한 축 + 경고
    - 축이 없는 차트(pie, donut, treemap, map, radar)의 표시 설정은 options.display_ref 에 둔다
    - 제목은 규칙으로 만든다 (기간 + 항목 + 주기/기준 + 연산 이름)
    - map 의 color_bins, radar 정규화는 채우지 않는다 (명세 9장 후속)
"""
from dataclasses import dataclass
from typing import Any

from backend.agent.chart_calculate.axis import axis_range, group_sums
from backend.agent.chart_calculate.calculate import TIME_COL, Calc, run_steps
from backend.agent.chart_calculate.display import format_value, strip_unit, unit_of
from backend.agent.chart_calculate.select import ITEM_COL, REGION_HINTS, VALUE_COL  # noqa: F401  (REGION_HINTS: 예전 위치 호환)
from backend.agent.chart_calculate.specs import SPECS, requirements_for
from backend.agent.chart_calculate.validate import check_chart
from backend.schemas.chart import AxisSpec, ChartContent, ChartPlan, ChartValidation, CheckResult, Display, Plan, Step
from backend.schemas.record import Record

SERIES_COL = "구분"            # 범례로 쓸 분류가 둘 이상일 때 합친 열
# [MOVED 11-11] REGION_HINTS → select.py (계산 쪽도 같이 쓴다)
PERIOD_NAME = {"Y": "연도별", "H": "반기별", "Q": "분기별", "M": "월별"}
MEASURE_NAME = {"change": "증감", "growth_rate": "증감률", "cagr": "연평균 증감률", "index": "지수", "share": "비중",
                "diff": "차이", "ratio": "비율", "rank": "순위", "extreme": "최댓값", "aggregate": "합계", "combine": "합산"}
_TIME_X = {"line", "area", "combo"}
_NO_AXIS = {"pie", "donut", "treemap", "map", "radar"}


@dataclass
class _Branch:
    """plan.output 의 갈래 하나 = 차트에 들어갈 계산 결과 하나"""
    role: str | None          # output 이 정한 역할 (y, y2, x, size, start, end). 갈래가 하나면 None
    step: Step
    calc: Calc

    @property
    def label(self) -> str:
        name = strip_unit(self.calc.item) if self.calc.item else VALUE_COL
        return name if self.step.op == "raw" else f"{name} {MEASURE_NAME[self.step.op]}"


def _branches(plan: Plan, calcs: dict[str, Calc]) -> tuple[list[_Branch], list[str]]:
    """→ (갈래 목록, 데이터 오류). 오류가 있으면 검증 ① 실패"""
    if not plan.steps:
        return [], ["계획에 단계가 없음"]
    steps = {s.step_id: s for s in plan.steps}
    wanted = [(o.role, o.step_id) for o in plan.output] if plan.output else [(None, plan.steps[-1].step_id)]
    out, errors = [], []
    for role, sid in wanted:
        if sid not in steps:
            errors.append(f"output 이 없는 단계를 가리킴: {sid}")
            continue
        calc = calcs[sid]
        if all(p.value is None for p in calc.points):      # 결과가 하나도 없음 (points 가 비어도 True)
            errors += calc.notes or [f"{sid}: 계산 결과 없음"]
        out.append(_Branch(role, steps[sid], calc))
    return out, list(dict.fromkeys(errors))


def _scale(unit: str | None) -> str:
    return {"%": "percent", "%p": "percent", "index": "index"}.get(unit, "linear")        # [CHANGED 11-13] %p 추가


def _distinct(cols: list[str], rows: list[list], col: str) -> list:
    i = cols.index(col)
    return list(dict.fromkeys(r[i] for r in rows))


def _varying(cols: list[str], rows: list[list]) -> list[str]:
    return [c for c in cols if c != VALUE_COL and len(_distinct(cols, rows, c)) > 1]


def _is_region(col: str) -> bool:
    return any(h in col for h in REGION_HINTS)


# ── long 형식 ────────────────────────────────────────────────────
def _long(branches: list[_Branch]) -> tuple[list[str], list[list], list[str]]:
    """갈래들을 [분류 열…, 항목, 값] 한 표로 합친다. 값이 None 인 점은 빼고 경고에 남긴다"""
    dims = list(dict.fromkeys(c for b in branches for p in b.calc.points for c in p.key if c != ITEM_COL))
    rows, skipped = [], 0
    for b in branches:
        for p in b.calc.points:
            if p.value is None:
                skipped += 1
                continue
            name = strip_unit(str(p.key[ITEM_COL])) if ITEM_COL in p.key else b.label
            rows.append([p.key.get(c) for c in dims] + [name, p.value])
    return dims + [ITEM_COL, VALUE_COL], rows, ([f"계산할 수 없는 값 {skipped}개 제외"] if skipped else [])


def _merge_series(cols: list[str], rows: list[list], used: list[str]) -> str | None:
    """범례로 쓸 열: used 를 뺀 '값이 달라지는 열'. 둘 이상이면 '구분' 열로 합친다 (cols·rows 를 직접 고침)"""
    rest = [c for c in _varying(cols, rows) if c not in used]
    if len(rest) <= 1:
        return rest[0] if rest else None
    idx = [cols.index(c) for c in rest]
    for r in rows:
        r.insert(len(cols) - 1, " · ".join(str(r[i]) for i in idx))
    cols.insert(len(cols) - 1, SERIES_COL)
    return SERIES_COL


def _assign(chart_type: str, cols: list[str], rows: list[list]) -> dict[str, str]:
    """long 표의 어느 열을 어느 역할에 연결할지. 필수 역할을 못 채우면 그대로 두고 검증이 걸러낸다"""
    var = _varying(cols, rows)
    first = var[0] if var else ITEM_COL
    enc: dict[str, str] = {}
    if chart_type in _TIME_X:
        enc["x"] = TIME_COL if TIME_COL in cols else first
        enc["y"] = VALUE_COL
        enc["series"] = _merge_series(cols, rows, [enc["x"]]) or ITEM_COL
    elif chart_type in ("bar", "stacked_bar"):
        cats = [c for c in var if c != TIME_COL]     # 범주가 있으면 범주를, 없으면 시점을 가로축에
        enc["x"] = cats[0] if cats else (TIME_COL if TIME_COL in cols else ITEM_COL)
        enc["y"] = VALUE_COL
        series = _merge_series(cols, rows, [enc["x"]]) or (ITEM_COL if chart_type == "stacked_bar" else None)
        if series and series != enc["x"]:
            enc["series"] = series
    elif chart_type in ("pie", "donut"):
        enc["label"] = _merge_series(cols, rows, []) or ITEM_COL
        enc["value"] = VALUE_COL
    elif chart_type == "treemap":
        if len(var) >= 2:
            enc["parent"], enc["label"] = var[0], var[1]
        else:
            enc["label"] = first
        enc["value"] = VALUE_COL
    elif chart_type == "radar":
        enc["label"] = ITEM_COL if ITEM_COL in var else first
        if series := _merge_series(cols, rows, [enc["label"]]):
            enc["series"] = series
        enc["value"] = VALUE_COL
    elif chart_type == "map":
        if region := next((c for c in cols if _is_region(c)), None):
            enc["region"] = region
        enc["value"] = VALUE_COL
    elif chart_type == "heatmap":
        order = sorted(var, key=lambda c: c != TIME_COL)     # 시점이 있으면 가로축
        enc.update(zip(("x", "y"), order))
        enc["value"] = VALUE_COL
    elif chart_type == "pyramid":
        two = [c for c in var if len(_distinct(cols, rows, c)) == 2]
        group = "성별" if "성별" in two else (two[0] if two else None)
        y = next((c for c in var if "연령" in c and c != group), None) or next((c for c in var if c != group), None)
        if y:
            enc["y"] = y
        if group:
            enc["group"] = group
        enc["value"] = VALUE_COL
    return enc


def _value_axis(label: str, branch: _Branch, values: list, rule: str | None) -> AxisSpec:
    """숫자 축 하나. rule(specs.axis_rules)이 있으면 min · max 를 계산해 채운다 (axis.axis_range, 원값 기준)
    [CHANGED] 이전: min 만 (zero → 0, include_zero → min(0, 최솟값)), max 는 채우지 않았다"""
    ax = AxisSpec(label=label, type="numeric", scale=_scale(branch.calc.unit), display_ref=branch.step.display_ref)
    if rule:
        ax.min, ax.max = axis_range(values, rule)
    return ax


def _long_axis(chart_type: str, enc: dict, cols: list[str], rows: list[list], branches: list[_Branch],
               dual: dict[str, str] | None = None) -> dict:
    if chart_type in _NO_AXIS:
        return {}
    axis: dict[str, AxisSpec] = {}
    vi, ii = cols.index(VALUE_COL), cols.index(ITEM_COL)
    for role in ("x", "y"):
        if enc.get(role) not in (None, VALUE_COL):
            axis[role] = AxisSpec(label=enc[role], type="time" if enc[role] == TIME_COL else "category")
    rules = SPECS[chart_type].axis_rules             # [CHANGED] 이전: SPECS[chart_type].y_floor 하나 (y 축 min 만)
    values = [r[vi] for r in rows]
    if chart_type == "combo":
        for b in branches:                           # 축마다 단위·표시 설정이 다르다
            if b.role in ("y", "y2"):
                axis[b.role] = _value_axis(b.label, b, [r[vi] for r in rows if r[ii] == b.label], rules.get(b.role))
    elif dual:                                       # [NEW] 이중 축 꺾은선: 단위가 다른 지표를 왼쪽(y)·오른쪽(y2) 축에
        for b in branches:
            axis[dual[b.label]] = _value_axis(b.label, b, [r[vi] for r in rows if r[ii] == b.label],
                                              rules.get(dual[b.label]))
    elif chart_type == "pyramid" and branches:       # [NEW] 값 축은 가로 → axis["x"]. 범주 축(y = 연령)은 위에서 이미 만들었다
        names = _distinct(cols, rows, ITEM_COL)
        axis["x"] = _value_axis(names[0] if len(names) == 1 else VALUE_COL, branches[0], values, rules.get("x"))
    elif enc.get("y") == VALUE_COL and branches:
        names = _distinct(cols, rows, ITEM_COL)
        if chart_type == "stacked_bar" and enc.get("x") in cols:      # 누적 막대의 max 는 같은 x 에서 쌓은 합계의 최댓값
            xi = cols.index(enc["x"])
            values = list(group_sums([r[xi] for r in rows], values).values())
        axis["y"] = _value_axis(names[0] if len(names) == 1 else VALUE_COL, branches[0], values, rules.get("y"))
    return axis


# ── joined 형식 ──────────────────────────────────────────────────
def _joined(chart_type: str, branches: list[_Branch]):
    """→ (columns, rows, encoding, axis, warnings)"""
    roles = [r for r in SPECS[chart_type].required if r != "label"]
    by_role = {b.role: b for b in branches if b.role in roles}
    if chart_type == "dumbbell" and not by_role and len(branches) == 1:
        return _dumbbell_pivot(branches[0])
    used = [by_role[r] for r in roles if r in by_role]
    if not used:
        return [], [], {}, {}, ["output 에 역할이 없어 점을 만들 수 없음"]
    # 결합 키 = 모든 갈래가 공통으로 가진 key 열
    keys = [c for c in used[0].calc.points[0].key if all(p.key.keys() >= {c} for b in used for p in b.calc.points)] \
        if used[0].calc.points else []
    names, warnings = [], []
    for b in used:      # 같은 항목을 두 번 쓰면 열 이름이 겹친다 → 역할을 붙여 구분
        names.append(b.label if b.label not in names else f"{b.label}({b.role})")
    tables = []
    for b in used:
        t: dict[tuple, Any] = {}
        for p in b.calc.points:
            k = tuple(p.key[c] for c in keys)
            if k in t:
                warnings.append(f"{b.label}: 결합 키 중복 {dict(zip(keys, k))}")
            t[k] = p.value
        tables.append(t)
    rows = []
    for k in dict.fromkeys(k for t in tables for k in t):
        vals = [t.get(k) for t in tables]
        if chart_type != "dumbbell" and any(v is None for v in vals):   # 덤벨은 검증(two_points_per_category)이 본다
            warnings.append(f"한쪽 값이 없어 제외: {dict(zip(keys, k))}")
            continue
        rows.append([*k, *vals])
    cols = keys + names
    enc = {b.role: n for b, n in zip(used, names)}
    cats = [c for c in _varying(cols, rows) if c in keys]
    if label := next((c for c in cats if c != TIME_COL), cats[0] if cats else (keys[0] if keys else None)):
        enc["label"] = label
    rules = SPECS[chart_type].axis_rules
    col = {b.role: [r[cols.index(n)] for r in rows] for b, n in zip(used, names)}
    axis = {b.role: _value_axis(n, b, col[b.role], rules.get(b.role))
            for b, n in zip(used, names) if b.role in ("x", "y")}
    if chart_type == "dumbbell":     # [NEW] _dumbbell_pivot 과 출력 모양을 맞춘다: start·end 가 가로 값 축 하나를 나눠 쓴다
        axis["x"] = _value_axis(" · ".join(dict.fromkeys(names)), used[0], [v for b in used for v in col[b.role]],
                                rules.get("x"))
    return cols, rows, enc, axis, warnings


def _dumbbell_pivot(b: _Branch):
    """갈래 하나에 시점이 여럿 → 첫 시점과 마지막 시점을 start·end 로 펼친다"""
    pts = b.calc.points
    times = list(dict.fromkeys(p.key.get(TIME_COL) for p in pts if TIME_COL in p.key))
    cats = list(dict.fromkeys(c for p in pts for c in p.key if c != TIME_COL))
    if len(times) < 2 or not cats:
        return [], [], {}, {}, ["두 시점과 범주가 있어야 덤벨을 만들 수 있음"]
    t0, t1 = str(times[0]), str(times[-1])
    table: dict[tuple, dict] = {}
    for p in pts:
        table.setdefault(tuple(p.key.get(c) for c in cats), {})[str(p.key.get(TIME_COL))] = p.value
    rows = [[*k, v.get(t0), v.get(t1)] for k, v in table.items()]
    axis = {"x": _value_axis(b.label, b, [v for r in rows for v in r[-2:]], SPECS["dumbbell"].axis_rules.get("x"))}
    return cats + [t0, t1], rows, {"label": cats[0], "start": t0, "end": t1}, axis, []


# ── 제목 · options ───────────────────────────────────────────────
def _units(branches: list[_Branch]) -> set:
    """갈래들이 쓰는 단위. 갈래 하나에 항목이 여럿이면(key 에 '항목') 항목 이름마다 단위를 본다"""
    return {unit_of(str(p.key[ITEM_COL])) if ITEM_COL in p.key else b.calc.unit
            for b in branches for p in b.calc.points}


def _dual_axis(branches: list[_Branch]) -> dict[str, str] | None:
    """[NEW] 단위가 다른 갈래 2개 → {지표 이름: 'y'(왼쪽) | 'y2'(오른쪽)}. 그 밖에는 None (한 축)

    역할은 output 이 정한 것(HCX)을 따르되, 없거나 겹치면 순서대로 (첫 갈래 y, 둘째 y2). 단위가 같으면 한 축이 비교에 정직하다.
    갈래 하나에 항목이 여럿이면(key 에 '항목') 축은 갈래 단위라 나눌 수 없다."""
    if len(branches) != 2 or len({b.label for b in branches}) != 2 or len(_units(branches)) < 2 \
            or any(ITEM_COL in p.key for b in branches for p in b.calc.points):
        return None
    roles = [b.role if b.role in ("y", "y2") else None for b in branches]
    if sorted(r or "" for r in roles) != ["y", "y2"]:
        roles = ["y", "y2"]
    return {b.label: r for b, r in zip(branches, roles)}


def _title(plan: Plan, branches: list[_Branch], names: list[str], category: str | None, prd_se: str | None) -> str:
    times = list(dict.fromkeys(str(p.key[TIME_COL]) for b in branches for p in b.calc.points if TIME_COL in p.key))
    step = branches[0].step if branches else None
    if not times and step:        # 두 시점을 하나로 줄인 계산(증감률 등)은 결과에 시점이 없다
        times = [t for t in (step.from_, step.to) if t]
    period = f"{times[0]}~{times[-1]}" if len(times) > 1 else (times[0] if times else "")
    what = MEASURE_NAME.get(plan.measure)
    if category == TIME_COL:
        tail = f"{PERIOD_NAME.get(prd_se, '시점별')} {what or '추이'}"
    elif category and category not in (ITEM_COL, VALUE_COL, SERIES_COL):
        tail = f"{category if category.endswith('별') else category + '별'} {what or '비교'}"
    else:
        tail = what or ""
    return " ".join(x for x in (period, " · ".join(names), tail) if x)


def _options(chart_type: str, plan: Plan, branches: list[_Branch], content_rows, cols, enc, displays, record,
             dual: dict[str, str] | None = None) -> dict:
    opt: dict[str, Any] = {}
    if label := next((b.calc.scope_label for b in branches if b.calc.scope_label), None):
        opt["scope_label"] = label
    ref = branches[0].step.display_ref if branches else None
    if chart_type in _NO_AXIS and ref:
        opt["display_ref"] = ref
    if chart_type == "bar":
        opt["orientation"] = "horizontal" if plan.measure == "rank" else "vertical"
    elif chart_type == "combo":
        opt["marks"] = {"y": "bar", "y2": "line"}
        opt["series_axis"] = {b.label: b.role for b in branches if b.role in ("y", "y2")}
    elif chart_type == "line" and dual:
        opt["marks"] = {"y": "line", "y2": "line"}
        opt["series_axis"] = dual
    elif chart_type == "donut" and plan.measure != "share" and VALUE_COL in cols:
        total = sum(r[cols.index(VALUE_COL)] for r in content_rows)
        shown = format_value(total, displays[ref]) if ref in displays else f"{total:g}"
        opt["center_text"] = f"합계 {shown}"
    elif chart_type == "map":
        opt["geo_level"] = (record.metadata.get("geo_level") if record else None)
        opt["region_key"] = "name"           # View 행에는 지역 이름만 있다 (코드는 Record.source.dims)
        opt["color_bins"] = None             # TODO(명세 9장 후속)
    return opt


# ── 구성 + 검증 ──────────────────────────────────────────────────
def _compose(chart_type: str, plan: Plan, branches: list[_Branch], displays: dict[str, Display],
             record: Record | None) -> ChartContent:
    live = [b for b in branches if b.calc.points]
    warnings = [n for b in live for n in b.calc.notes]
    dual = None                      # 이중 축 꺾은선의 {지표: y|y2}. long 형식의 line 에서만 정해진다
    if SPECS[chart_type].rows == "joined":
        cols, rows, enc, axis, more = _joined(chart_type, live)
    else:
        cols, rows, more = _long(live)
        enc = _assign(chart_type, cols, rows) if rows else {}
        dual = _dual_axis(live) if chart_type == "line" and rows else None
        axis = _long_axis(chart_type, enc, cols, rows, live, dual) if rows else {}
        if chart_type == "combo" and not any(b.role == "y2" for b in live):
            enc.pop("y2", None)
        elif chart_type == "combo":
            enc["y2"] = VALUE_COL
        elif dual:
            enc["y2"] = VALUE_COL
            more.append("단위가 달라 지표별로 왼쪽(y)·오른쪽(y2) 축에 나눠 그림")
        elif len(_units(live)) > 1:
            more.append("단위가 다른 지표를 한 축에 그림")
    category = enc.get("x") or enc.get("label") or enc.get("region")
    # 제목의 항목 이름: 갈래 하나에 항목이 여럿이면 key 의 항목 이름들, 아니면 갈래의 항목
    names = list(dict.fromkeys(
        strip_unit(str(p.key[ITEM_COL])) if ITEM_COL in p.key else strip_unit(b.calc.item or "")
        for b in live for p in b.calc.points))
    return ChartContent(
        chart_id=plan.chart_id, chart_type=chart_type, measure=plan.measure,
        # HCX 가 질문의 말로 쓴 제목이 있으면 그것 (대체 차트·합계로 바뀌어도 질문 기준이라 그대로 맞다), 없으면 규칙 제목
        title=plan.title or _title(plan, live, [n for n in names if n], category,
                                   record.metadata.get("prd_se") if record else None),
        encoding=enc, axis=axis, options=_options(chart_type, plan, live, rows, cols, enc, displays, record, dual),
        columns=cols, rows=rows, record_ids=list(dict.fromkeys(i for b in branches for i in b.calc.record_ids)),
        warnings=list(dict.fromkeys(warnings + more)))


def _totals(plan: Plan, content: ChartContent) -> dict | None:
    """parts_sum_to_total 에서 비교할 총계. 분모가 질문 범위(scope=question)인 구성비는 합이 100% 여야 한다"""
    if not any(s.op == "share" and s.denominator and s.denominator.scope == "question" for s in plan.steps):
        return None
    xs = _distinct(content.columns, content.rows, content.encoding["x"]) if "x" in content.encoding else []
    return {None: 100.0, **{x: 100.0 for x in xs}}


def build_chart(plan: Plan, records: list[Record], requirements: list[str] | None = None,
                displays: dict[str, Display] | None = None,
                attempts: list[tuple[ChartContent, CheckResult]] | None = None,
                calcs: dict[str, Calc] | None = None
                ) -> tuple[ChartContent | None, ChartValidation]:
    """requirements = 모듈 2 가 원래 차트에 대해 넘긴 조건. 대체 차트는 그 차트의 기본 조건으로 검증한다
    attempts = 목록을 넘기면 시도마다 (구성한 내용, 검증 결과)를 순서대로 담는다 (테스트 화면용. 실패한 시도도 담긴다)
    calcs = 딕셔너리를 넘기면 단계마다 계산 결과를 담는다 ('{chart_id}.{step_id}' → Calc. 질문용 계산이 같은 계산을 다시 하지 않게 재사용한다)"""
    done = run_steps(plan.steps, records, default=plan)
    if calcs is not None:
        calcs.update({f"{plan.chart_id}.{sid}": c for sid, c in done.items()})
    branches, errors = _branches(plan, done)
    record = next((r for r in records if r.id == plan.record_id), None)

    def attempt(chart_type: str, reqs: list[str]) -> tuple[ChartContent, CheckResult]:
        content = _compose(chart_type, plan, branches, displays or {}, record)
        result = check_chart(content, reqs, errors, _totals(plan, content))
        if attempts is not None:
            attempts.append((content, result))
        return content, result

    content, original = attempt(plan.chart_type, requirements_for(plan.chart_type, requirements))
    fallback = None
    # ① 실패(데이터 없음)는 차트를 바꿔도 해결되지 않는다 → 대체 차트를 시도하지 않는다 (명세 7장)
    if not original.passed and plan.fallback_chart and "data_present" not in original.failed:
        content, fallback = attempt(plan.fallback_chart, requirements_for(plan.fallback_chart))
    ok = (fallback or original).passed
    return (content if ok else None), ChartValidation(
        original=original, fallback=fallback, final_chart_type=content.chart_type if ok else None, content_built=ok)


def build_charts(chart_plan: ChartPlan, records: list[Record], requirements: dict[str, list[str]] | None = None,
                 displays: dict[str, Display] | None = None) -> tuple[list[ChartContent], dict[str, ChartValidation]]:
    """→ (chart_contents, validation). 대체 차트도 실패한 차트는 chart_contents 에 넣지 않는다"""
    contents, validation = [], {}
    for plan in chart_plan.plans:
        content, validation[plan.chart_id] = build_chart(plan, records, (requirements or {}).get(plan.chart_id), displays)
        if content is not None:
            contents.append(content)
    return contents, validation
