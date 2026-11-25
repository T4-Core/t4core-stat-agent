"""
[NEW] ChartContent 구성 — 계산 결과(Calc)를 Draw 가 그대로 그릴 수 있는 행·축·설정으로 바꾸고 검증한다

  build_chart(plan, records, requirements)
    1. plan.steps 실행 (calculate.run_steps)
    2. 원래 차트로 구성 → 검증 (validate.check_chart)
    3. ② 가 실패하면 대체 후보(fallback_charts, 없으면 fallback_chart)를 앞에서부터 통과할 때까지 구성 → 그 차트의 기본 조건으로 검증
       [CHANGED 11-24] 이전: 대체 차트 하나만 시도했다. 계산(1)은 다시 하지 않으므로 후보가 늘어도 비용은 구성 · 검사뿐이다
    4. 통과한 것이 있으면 그 ChartContent, 없으면 None. 과정은 ChartValidation 에 남긴다 (fallbacks = 시도한 대체 차트 전부)

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
from backend.agent.chart_calculate.calculate import INDICATOR_HINTS, TIME_COL, Calc, period_index, run_steps
from backend.agent.chart_calculate.display import format_value, strip_unit, unit_of
from backend.core.korean import unit_tail
from backend.agent.chart_calculate.select import ITEM_COL, REGION_HINTS, VALUE_COL  # noqa: F401  (REGION_HINTS: 예전 위치 호환)
from backend.agent.chart_calculate.specs import SPECS, requirements_for
from backend.agent.chart_calculate.validate import check_chart
from backend.core.reasons import humanize
from backend.schemas.chart import AxisSpec, ChartContent, ChartPlan, ChartValidation, CheckResult, Display, Plan, Step
from backend.schemas.record import Record

SERIES_COL = "구분"            # 범례로 쓸 분류가 둘 이상일 때 합친 열
# [MOVED 11-11] REGION_HINTS → select.py (계산 쪽도 같이 쓴다)
PERIOD_NAME = {"Y": "연도별", "H": "반기별", "Q": "분기별", "M": "월별"}
MEASURE_NAME = {"change": "증감", "growth_rate": "증감률", "cagr": "연평균 증감률", "index": "지수", "share": "비중",
                "diff": "차이", "ratio": "비율", "rank": "순위", "extreme": "최댓값", "aggregate": "합계", "combine": "합산"}
_TIME_X = {"line", "area", "combo"}


def measure_name(op: str, agg: str | None = None) -> str | None:
    """연산의 표시 이름. aggregate 는 agg 에 따라 평균 · 합계 (이전에는 평균도 '합계' 로 표시됐다. 검수 7)"""
    return "평균" if op == "aggregate" and agg == "mean" else MEASURE_NAME.get(op)
_NO_AXIS = {"pie", "donut", "treemap", "map", "radar"}


def shown_item(calc: Calc) -> str | None:
    """[NEW 11-25 5단계 5-0] 축 · 범례 · 제목에 쓸 항목 이름 (단위 괄호 포함 원래 값. 쓰는 쪽에서 strip_unit)

    항목 열 값에 단위 괄호가 없고, 지표를 담는 분류 열(이름에 항목 · 종류 · 지표가 든 열. 항목 열 자체는 빼고)의 고정 값 중
    단위 괄호가 있는 것이 정확히 하나면 그 값을 쓴다.
      DT_1B8000G: 항목 '출생사망혼인이혼' · 종류별 '조혼인율(천명당)' → '조혼인율(천명당)' (표시는 '조혼인율')
    이전: 항상 항목 열 값 → '출생사망혼인이혼' 이 막대 · 산점도 · 버블의 축 이름과 범례에 나왔다 (15유형 T1-scatter · T2-bubble).
    단위 괄호가 없는 값('거처종류별: 계')은 지표 이름인지 알 수 없어 쓰지 않는다 (그때는 이전처럼 항목 열 값)"""
    item = calc.item
    if item and unit_tail(item):
        return item
    hits = [str(v) for c, v in calc.fixed.items()
            if c != ITEM_COL and any(h in c for h in INDICATOR_HINTS) and unit_tail(str(v))]
    return hits[0] if len(hits) == 1 else item


@dataclass
class _Branch:
    """plan.output 의 갈래 하나 = 차트에 들어갈 계산 결과 하나"""
    role: str | None          # output 이 정한 역할 (y, y2, x, size, start, end). 갈래가 하나면 None
    step: Step
    calc: Calc
    tag: str = ""             # [NEW 11-16] 이름이 같은 갈래끼리 구분하는 고정 좌표 ('서울특별시'). _branches 가 채운다

    @property
    def base_label(self) -> str:
        item = shown_item(self.calc)              # [CHANGED 11-25 5-0] 이전: self.calc.item (항목 열 값 그대로)
        name = strip_unit(item) if item else VALUE_COL
        return name if self.step.op == "raw" else f"{name} {measure_name(self.step.op, self.step.agg)}"

    @property
    def label(self) -> str:
        return f"{self.base_label} ({self.tag})" if self.tag else self.base_label


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
    _tell_apart(out)
    return out, list(dict.fromkeys(errors))


def _tell_apart(branches: list["_Branch"]) -> None:
    """[NEW 11-16] 이름이 같은 갈래(서울 View 의 인구수 · 부산 View 의 인구수)는 값이 달라지는 고정 좌표를 이름에 붙인다.
    안 붙이면 두 갈래가 같은 범례 · 같은 시점에 값 둘이 되어 선이 섞인다 (검수 M3-08)"""
    groups: dict[str, list[_Branch]] = {}
    for b in branches:
        groups.setdefault(b.base_label, []).append(b)
    for same in groups.values():
        if len(same) < 2:
            continue
        cols = [c for c in dict.fromkeys(c for b in same for c in b.calc.fixed) if c != ITEM_COL
                and len({str(b.calc.fixed.get(c)) for b in same}) > 1]
        for b in same:
            b.tag = " ".join(str(b.calc.fixed[c]) for c in cols if c in b.calc.fixed)


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
def _long(branches: list[_Branch], keep_missing: bool = False) -> tuple[list[str], list[list], list[str]]:
    """갈래들을 [분류 열…, 항목, 값] 한 표로 합친다.

    keep_missing: 시간이 가로축인 차트(꺾은선 · 면적 · 복합)는 계산할 수 없는 점도 값 None 인 행으로 넘겨 선이 그 시점에서 끊기게 한다.
                  행을 빼면 그 시점이 가로축에서 사라져 앞뒤 점이 이어진다 (검수 9). 그 밖의 차트는 점을 뺀다.
    행은 시점 순서로 정렬한다 (시점 라벨을 모두 읽을 수 있을 때. 같은 시점은 갈래 순서 유지). 계열마다 기간이 다르면 가로축이 뒤섞였다.
    """
    dims = list(dict.fromkeys(c for b in branches for p in b.calc.points for c in p.key if c != ITEM_COL))
    rows, skipped = [], 0
    for b in branches:
        for p in b.calc.points:
            if p.value is None:
                skipped += 1
                if not keep_missing:
                    continue
            name = strip_unit(str(p.key[ITEM_COL])) if ITEM_COL in p.key else b.label
            rows.append([p.key.get(c) for c in dims] + [name, p.value])
        if keep_missing:      # [NEW 11-17] 값이 비어 점이 못 된 시점도 값 None 행으로: 그 시점이 가로축에 남고 선이 끊긴다
            have = {tuple(sorted((c, str(v)) for c, v in p.key.items())) for p in b.calc.points}
            for m in b.calc.missing:
                if tuple(sorted((c, str(v)) for c, v in m.items())) in have:
                    continue
                skipped += 1
                name = strip_unit(str(m[ITEM_COL])) if ITEM_COL in m else b.label
                rows.append([m.get(c) for c in dims] + [name, None])
    if TIME_COL in dims:
        ti = dims.index(TIME_COL)
        idx = [period_index(r[ti]) for r in rows]
        if rows and all(idx) and len({k for k, _ in idx}) == 1:
            rows = [r for _, r in sorted(zip((i for _, i in idx), rows), key=lambda t: t[0])]
    more = (f"계산할 수 없는 시점 {skipped}개는 선을 끊어 표시" if keep_missing else f"계산할 수 없는 값 {skipped}개 제외") if skipped else None
    return dims + [ITEM_COL, VALUE_COL], rows, [more] if more else []


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
    # [NEW 11-25] 덤벨: 갈래마다 시점이 하나씩이고 서로 다르면(start 2015 · end 2024) 시점으로 짝짓지 않는다 (체크리스트 1-5).
    #   이전: 시점이 결합 키에 들어가 (2015, 서울) 과 (2024, 서울) 이 다른 행이 됐다 → 범주마다 한쪽 값만 있어
    #   two_points_per_category 에서 떨어지고 막대로 대체됐다 (15유형 테스트 덤벨 질문 3건 모두).
    #   열 이름은 그 갈래의 시점 → _dumbbell_pivot (갈래 1개에 시점 2개) 과 같은 모양 (범례 2015 · 2024)
    time_split = False
    if chart_type == "dumbbell" and TIME_COL in keys:
        times = [{str(p.key.get(TIME_COL)) for p in b.calc.points} for b in used]
        if all(len(t) == 1 for t in times) and len({next(iter(t)) for t in times}) == len(used):
            keys = [c for c in keys if c != TIME_COL]
            names = [next(iter(t)) for t in times]
            time_split = True
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
        # [CHANGED 11-25] 시점으로 나눈 덤벨은 열 이름이 시점이라 축 이름은 지표 이름 (_dumbbell_pivot 과 같음)
        axis_name = used[0].label if time_split else " · ".join(dict.fromkeys(names))
        axis["x"] = _value_axis(axis_name, used[0], [v for b in used for v in col[b.role]], rules.get("x"))
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
    # 제목의 기간은 실제로 표시되는(값이 있는) 점의 시점에서 구한다. 계산을 보류한 점까지 넣으면 그려진 행과 기간이 어긋난다 (검수 7)
    shown = [p for b in branches for p in b.calc.points if TIME_COL in p.key and p.value is not None]
    times = list(dict.fromkeys(str(p.key[TIME_COL]) for p in (shown or [p for b in branches for p in b.calc.points if TIME_COL in p.key])))
    step = branches[0].step if branches else None
    if not times and step:        # 두 시점을 하나로 줄인 계산(증감률 등)은 결과에 시점이 없다
        times = [t for t in (step.from_, step.to) if t]
    # [CHANGED 11-17] 이전: times[0]~times[-1] (처음 나온 시점 ~ 마지막에 나온 시점) — 지역마다 기간이 다르면 2023~2020 처럼 뒤집혔다 (검수 8)
    parsed = [(period_index(t), t) for t in times]
    if len(times) > 1 and all(i for i, _ in parsed) and len({i[0] for i, _ in parsed}) == 1:
        times = [min(parsed, key=lambda x: x[0][1])[1], max(parsed, key=lambda x: x[0][1])[1]]
    period = f"{times[0]}~{times[-1]}" if len(times) > 1 else (times[0] if times else "")
    what = measure_name(plan.measure, step.agg if step else None)
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
        cols, rows, more = _long(live, keep_missing=chart_type in _TIME_X)
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
    names = list(dict.fromkeys(      # [CHANGED 11-25 5-0] 갈래의 항목은 shown_item (축 · 범례와 같은 이름)
        strip_unit(str(p.key[ITEM_COL])) if ITEM_COL in p.key else strip_unit(shown_item(b.calc) or "")
        for b in live for p in b.calc.points))
    return ChartContent(
        chart_id=plan.chart_id, chart_type=chart_type, measure=plan.measure,
        # HCX 가 질문의 말로 쓴 제목이 있으면 그것 (대체 차트·합계로 바뀌어도 질문 기준이라 그대로 맞다), 없으면 규칙 제목
        title=plan.title or _title(plan, live, [n for n in names if n], category,
                                   record.metadata.get("prd_se") if record else None),
        encoding=enc, axis=axis, options=_options(chart_type, plan, live, rows, cols, enc, displays, record, dual),
        columns=cols, rows=rows, record_ids=list(dict.fromkeys(i for b in branches for i in b.calc.record_ids)),
        # [CHANGED 11-17] 이전: 계산 단계의 내부 문구 그대로 ('2023: 직전 시점(2022) 값이 없어 계산하지 않음'). 모듈 5 가 ⚠ 로 사용자에게
        #   보여 주므로 모듈 6 의 답변 · 주의사항과 같은 문장으로 바꾼다 (자체 검토 A-6). 원문은 CalcResult.note · validation 에 남는다
        warnings=list(dict.fromkeys(humanize(w) for w in warnings + more)))


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
    order = [t for t in dict.fromkeys([*([plan.fallback_chart] if plan.fallback_chart else []), *plan.fallback_charts])
             if t != plan.chart_type]
    # [NEW 11-24] 값 1개짜리 차트를 막는 안전망(min_categories_2)은 대체 차트에도 건다. 후보가 여럿이면 1조각 원그래프 같은 차트가 통과할 수 있다
    guard = [r for r in (requirements or []) if r == "min_categories_2"]
    tried: list[CheckResult] = []
    # ① 실패(데이터 없음)는 차트를 바꿔도 해결되지 않는다 → 대체 차트를 시도하지 않는다 (명세 7장)
    if not original.passed and "data_present" not in original.failed:
        for chart_type in order:
            content, check = attempt(chart_type, requirements_for(chart_type, guard))
            tried.append(check)
            if check.passed:
                break
    fallback = tried[-1] if tried else None
    ok = original.passed or bool(fallback and fallback.passed)
    return (content if ok else None), ChartValidation(
        original=original, fallback=fallback, fallbacks=tried, final_chart_type=content.chart_type if ok else None,
        content_built=ok)


def build_charts(chart_plan: ChartPlan, records: list[Record], requirements: dict[str, list[str]] | None = None,
                 displays: dict[str, Display] | None = None) -> tuple[list[ChartContent], dict[str, ChartValidation]]:
    """→ (chart_contents, validation). 대체 차트도 실패한 차트는 chart_contents 에 넣지 않는다"""
    contents, validation = [], {}
    for plan in chart_plan.plans:
        content, validation[plan.chart_id] = build_chart(plan, records, (requirements or {}).get(plan.chart_id), displays)
        if content is not None:
            contents.append(content)
    return contents, validation
