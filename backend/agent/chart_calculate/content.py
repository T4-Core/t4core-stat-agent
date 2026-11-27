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
from backend.agent.chart_calculate.calculate import TIME_COL, Calc, period_index, run_steps
from backend.agent.chart_calculate.display import format_value, indicator_name, strip_unit, unit_of
from backend.agent.chart_calculate.select import INDICATOR_HINTS, ITEM_COL, REGION_HINTS, VALUE_COL  # noqa: F401  (REGION_HINTS: 예전 위치 호환)
from backend.agent.chart_calculate.specs import SPECS, requirements_for
from backend.agent.chart_calculate.validate import PARTS_TOLERANCE, check_chart, totals_in
from backend.agent.period_cycle import CYCLE_COLS, YEAR_COL, cycle_info, cycle_of
from backend.core.korean import unit_tail
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
    규칙은 display.indicator_name — 갈래의 고정 좌표(calc.fixed)에서 지표형 분류 열의 값을 본다.
      DT_1B8000G: 항목 '출생사망혼인이혼' · 종류별 '조혼인율(천명당)' → '조혼인율(천명당)' (표시는 '조혼인율')
    이전: 항상 항목 열 값 → '출생사망혼인이혼' 이 막대 · 산점도 · 버블의 축 이름과 범례에 나왔다 (15유형 T1-scatter · T2-bubble).
    [CHANGED 11-25 6-5] 규칙을 display.indicator_name 으로 옮겼다 (모듈 6 의 계산 이름도 같이 쓴다)"""
    return indicator_name(calc.item, calc.fixed)


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
    # [CHANGED 11-27] 해끼리 매긴 순위(시점만 달라짐)는 순위 순서 그대로 둔다. '최근 10년 혼인건수가 많은 해 순서대로' 의
    #   순위 막대가 연도 순서(2016 → 2025)로 다시 정렬됐다. 같은 해 안에서 지역끼리 매긴 순위는 이전처럼 시점별로 묶는다
    by_year_rank = any(b.step.op == "rank" for b in branches) and not any(
        len({str(r[i]) for r in rows}) > 1 for i, c in enumerate(dims) if c != TIME_COL)
    if TIME_COL in dims and not by_year_rank:
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


RADAR_SPOKES = (3, 8)       # 레이더 축으로 고르는 범주 수 (지표 · 지역 …)
CYCLE_SPOKES_MAX = 12       # [NEW 11-27] 주기 칸(월)은 12개까지. specs 의 radar 조건은 min_categories_3 · max_categories_12


def _cycle_split(cols: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    """[NEW 11-27] 레이더: 시점이 월 · 분기 · 반기면 시점 열을 [주기 칸('3월' · '1분기'), 연도] 두 열로 나눈다 (period_cycle.py).
    축 = 주기 칸, 다각형 = 연도(여럿일 때) · 지역 · 지표. '전국 월별 출생아수의 2015·2020·2025년' → 1월~12월 축에 해마다 다각형.
    이전: 시점 36개가 한 열이라 축 개수(최대 8)를 넘거나 2015.01 · 2020.01 이 서로 다른 축이 됐다. 주기가 아니면 그대로"""
    if TIME_COL not in cols:
        return cols, rows
    ti = cols.index(TIME_COL)
    info = cycle_info(r[ti] for r in rows)
    if info is None:
        return cols, rows
    split = [cycle_of(r[ti]) for r in rows]
    return (cols[:ti] + [info["col"], YEAR_COL] + cols[ti + 1:],
            [r[:ti] + [c[3], c[0]] + r[ti + 1:] for r, c in zip(rows, split)])


def _radar_spokes(cols: list[str], rows: list[list], var: list[str]) -> str:
    """[NEW 11-25 6-2] 레이더의 축(label)으로 쓸 열. 주기 칸 → 지표(항목) → 시점이 아닌 범주 → 시점 순서로, 값이 3~8개(주기 칸은 12개)인 첫 열.
    나머지 열은 계열(다각형)이 된다. 맞는 열이 없으면 이전과 같다 (항목이 달라지면 항목, 아니면 첫 열 — 검증이 걸러낸다)
    이전: 항목이 아니면 항상 첫 열 → '2020년과 2024년 서울·부산·대구·인천·광주' 는 시점 2개가 축이 되어 레이더가 실패하고 막대로 대체됐다.
    지금: 지역 5곳이 축, 2020 · 2024 가 다각형 (15유형 T2-radar). 시점 5개 · 지역 3곳이면 지역 3곳이 축이 된다
    [CHANGED 11-27] 주기 칸(월 · 분기 · 반기, _cycle_split)을 먼저 본다: 같은 주기끼리 견주는 질문은 1월~12월이 축이다"""
    lo, hi = RADAR_SPOKES
    order = [c for c in var if c in CYCLE_COLS] + ([ITEM_COL] if ITEM_COL in var else []) \
        + [c for c in var if c not in (ITEM_COL, TIME_COL) and c not in CYCLE_COLS] + ([TIME_COL] if TIME_COL in var else [])
    fit = next((c for c in order if lo <= len(_distinct(cols, rows, c)) <= (CYCLE_SPOKES_MAX if c in CYCLE_COLS else hi)), None)
    return fit or (ITEM_COL if ITEM_COL in var else (var[0] if var else ITEM_COL))


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
        enc["label"] = _radar_spokes(cols, rows, var)
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


REMAINDER_LABEL = "그 외"          # [NEW 11-27] 전체 대비 부분 비중의 나머지 조각 (지역 열이면 '그 외 지역')


def _question_share(plan: Plan) -> bool:
    """분모가 질문에 정해진 비중(전국 대비 · 전체 대비)인가 — 조각의 합이 100% 여야 한다 (_totals 와 같은 조건)"""
    return any(s.op == "share" and s.denominator and s.denominator.scope == "question" for s in plan.steps)


def _whole_remainder(plan: Plan, cols: list[str], rows: list[list], fixed: dict | None = None
                     ) -> tuple[list[str], list[list], dict | None, list[str]]:
    """[NEW 11-27] 원 · 도넛의 전체 대비 부분 비중 → (열, 행, 나머지 조각 정보 | None, 안내).
    '2024년 전국 대비 서울 출생아 비중' 은 조각이 총계(전국 100%)와 부분(서울 17.5%)뿐이라 원을 채울 수 없어 막대로 대체됐다
    (전국 100 옆에 서울 17.5). 총계 행을 빼고 '그 외' 조각 = 100% − 부분 합 을 더한다 → 서울 17.5% · 그 외 지역 82.5%.
    - 분모가 질문 범위인 비중 · 시점 하나 · 조각 열 하나 · 값이 모두 있고 음수 없음 일 때만
    - 부분 합이 100% 면 총계 행만 뺀다 (계 · 남자 · 여자). 100% 를 넘으면(겹치는 부분) 그대로 둔다 — 검증이 걸러낸다
    fixed: 갈래의 고정 좌표 (calc.fixed). 부분을 하나만 골랐으면 조각 열(시군구별 = 서울특별시)이 행이 아니라 여기에 있다 → 열로 꺼낸다"""
    if not rows or plan.measure != "share" or not _question_share(plan):
        return cols, rows, None, []
    vi = cols.index(VALUE_COL)
    if any(r[vi] is None or r[vi] < 0 for r in rows):
        return cols, rows, None, []
    if TIME_COL in cols and len(_distinct(cols, rows, TIME_COL)) > 1:
        return cols, rows, None, []
    rows, cols0 = [list(r) for r in rows], cols
    tol = 100 * PARTS_TOLERANCE
    total_col = total_name = None
    totals: list[list] = []
    for c in (c for c in cols if c != VALUE_COL):
        ci = cols.index(c)
        names = totals_in(c, _distinct(cols, rows, c))
        hit = [r for r in rows if str(r[ci]) in names and abs(r[vi] - 100) <= tol]       # 분모 자신 (전국 ÷ 전국 = 100%)
        if hit and len(hit) < len(rows):
            total_col, total_name, totals = c, str(hit[0][ci]), hit
            break
    parts = [r for r in rows if not any(r is t for t in totals)]
    var = _varying(cols, parts)
    if len(var) > 1 or (total_col and var and var != [total_col]):
        return cols, rows, None, []
    den = next(s.denominator for s in plan.steps if s.op == "share" and s.denominator)
    label_col = var[0] if var else total_col
    if label_col is None and den.operand and len(parts) == 1:     # 부분 하나 · 총계 행 없음: 분모와 값이 다른 열이 조각 열
        for c, vals in den.operand.select.items():
            want = {str(v) for v in vals}
            if c in cols and str(parts[0][cols.index(c)]) not in want:
                label_col = c
            elif c not in cols and c in (fixed or {}) and str(fixed[c]) not in want:
                at = cols.index(ITEM_COL) if ITEM_COL in cols else vi          # 고정 좌표 → 열 (항목 앞)
                cols = cols[:at] + [c] + cols[at:]
                parts = [r[:at] + [fixed[c]] + r[at:] for r in parts]
                vi, label_col = cols.index(VALUE_COL), c
            if label_col:
                total_name = next(iter(vals), None)
                break
    if label_col is None:
        return cols0, rows, None, []
    li = cols.index(label_col)
    total_name = str(total_name or den.basis or "전체")
    s = sum(r[vi] for r in parts)
    if s > 100 + tol:
        return cols0, rows, None, []                 # 고정 좌표를 꺼낸 열이 아니라 원래 열 · 행 그대로
    if s >= 100 - tol:
        return cols, parts, None, ([f"총계 '{total_name}' 는 조각이 아니라서 뺌"] if totals else [])
    label = f"{REMAINDER_LABEL} 지역" if _is_region(label_col) else REMAINDER_LABEL
    rest = list(parts[0])
    rest[li], rest[vi] = label, 100 - s
    names = [str(r[li]) for r in parts]
    note = f"'{label}' = {total_name} − {' − '.join(names)} (나머지 {100 - s:.1f}%)"
    return cols, parts + [rest], {"label": label, "col": label_col, "parts": names, "total": total_name}, [note]


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
    if chart_type in PIVOT_MEASURES and not by_role and len(branches) == 1:     # [NEW 11-25 6-3]
        if (pivot := _measure_pivot(chart_type, branches[0])) is not None:
            return pivot
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


PIVOT_MEASURES = {"scatter": 2, "bubble": 3}       # 갈래 하나를 지표 열로 펼칠 때 필요한 값 수 (x · y / x · y · size)
_SEX_COL = "성별"


def _pivot_rank(col: str) -> int:
    """펼칠 열을 고르는 순서: 항목 → 지표형 분류 열(종류별 · 기본항목별 …) → 성별 → 그 밖의 열"""
    if col == ITEM_COL:
        return 0
    if any(h in col for h in INDICATOR_HINTS):
        return 1
    return 2 if col == _SEX_COL else 3


def _measure_pivot(chart_type: str, b: _Branch):
    """[NEW 11-25 6-3] 산점도 · 버블인데 역할(x · y · size)이 나뉜 갈래가 없고, 갈래 하나에 지표가 2 · 3개 섞여 있으면
    그 열의 값을 지표 열로 펼친다 → (columns, rows, encoding, axis, warnings).
    펼칠 수 없으면 None → 이전과 같다 ('output 에 역할이 없어 점을 만들 수 없음' → 행 없음 → data_present 실패라 대체 차트도 시도하지 않음)
      예: '2024년 시도별 남자 인구수와 여자 인구수의 관계를 산점도로' — 항목 = 남자인구수 · 여자인구수, 시도 18곳
          → [시점, 시도, 남자인구수, 여자인구수] 18행, x = 남자인구수 · y = 여자인구수 · 점 이름 = 시도 (15유형 T3-scatter)
      이전: '역할이 없어 점을 만들 수 없음' → 막대로 대체 (모듈 2 도 산점도를 고르지 않았다 — chart_type_frames 의 6-3)
    펼칠 열: 값이 정확히 2 · 3개인 열 (_pivot_rank 순서). 나머지 열 중 값이 달라지는 열(점 이름)이 정확히 하나일 때만 —
    둘 이상이면(시도 × 연도) 같은 점 이름이 여러 번 나와 어느 점인지 알 수 없다.
    역할 순서 = 그 열에서 값이 처음 나온 순서 (HCX 가 고른 순서 = 보통 질문에 나온 순서)"""
    k = PIVOT_MEASURES[chart_type]
    pts = b.calc.points
    keys = list(dict.fromkeys(c for p in pts for c in p.key))
    distinct = {c: list(dict.fromkeys(str(p.key.get(c)) for p in pts if c in p.key)) for c in keys}
    for col in sorted((c for c in keys if len(distinct[c]) == k), key=_pivot_rank):
        rest = [c for c in keys if c != col]
        varying = [c for c in rest if len(distinct[c]) > 1]
        if len(varying) != 1:
            continue
        values = distinct[col]
        item = shown_item(b.calc)
        if col == ITEM_COL or any(h in col for h in INDICATOR_HINTS) or not item:
            names = [strip_unit(v) for v in values]
        else:                                                      # 성별 열 → '남자 인구수' · '여자 인구수'
            names = [f"{v} {strip_unit(item)}" for v in values]
        if len(set(names)) < k:
            continue
        table: dict[tuple, dict] = {}
        warnings: list[str] = []
        for p in pts:
            key = tuple(p.key.get(c) for c in rest)
            cell = table.setdefault(key, {})
            if str(p.key.get(col)) in cell:
                warnings.append(f"{b.label}: 결합 키 중복 {dict(zip(rest, key))}")
            cell[str(p.key.get(col))] = p.value
        rows = []
        for key, cell in table.items():
            vals = [cell.get(v) for v in values]
            if any(v is None for v in vals):
                warnings.append(f"한쪽 값이 없어 제외: {dict(zip(rest, key))}")
                continue
            rows.append([*key, *vals])
        cols = rest + names
        roles = [r for r in SPECS[chart_type].required if r != "label"]
        enc = {**dict(zip(roles, names)), "label": varying[0]}
        rules = SPECS[chart_type].axis_rules
        units = {unit_tail(v) for v in values} - {None}
        axis = {}
        for r, n in zip(roles, names):
            if r in ("x", "y"):
                axis[r] = _value_axis(n, b, [row[cols.index(n)] for row in rows], rules.get(r))
                if len(units) > 1:          # 지표마다 단위가 다르면 갈래의 표시 설정(단위 하나)을 축에 붙이지 않는다
                    axis[r].display_ref = None
        return cols, rows, enc, axis, warnings
    return None


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
             dual: dict[str, str] | None = None, rest: dict | None = None) -> dict:
    opt: dict[str, Any] = {}
    if label := next((b.calc.scope_label for b in branches if b.calc.scope_label), None):
        opt["scope_label"] = label
    # [NEW 11-27] 환산 지수(minmax · mean). 모듈 5 가 반지름 · 값 축을 0~100 으로 잡거나 100 기준선을 그린다 (합친 레이더도 물려받는다)
    if scale := next((sc for b in branches if b.step and (sc := (b.step.model_extra or {}).get("scale"))), None):
        opt["index_scale"] = scale
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
    elif chart_type == "donut" and rest and len(rest["parts"]) == 1:
        # [NEW 11-27] 전체 대비 부분 하나 → 가운데에 그 부분의 비중 ('서울특별시 17.5%')
        v = next(r[cols.index(VALUE_COL)] for r in content_rows if str(r[cols.index(rest["col"])]) == rest["parts"][0])
        shown = format_value(v, displays[ref]) if ref in displays else f"{v:.1f}%"
        opt["center_text"] = f"{rest['parts'][0]}<br>{shown}"
    elif chart_type == "map":
        opt["geo_level"] = (record.metadata.get("geo_level") if record else None)
        opt["region_key"] = "name"           # View 행에는 지역 이름만 있다 (코드는 Record.source.dims)
        opt["color_bins"] = None             # TODO(명세 9장 후속)
    if rest:
        opt["remainder_label"] = rest["label"]      # [NEW 11-27] 모듈 5 가 이 조각을 회색으로 칠한다
    return opt


# ── 구성 + 검증 ──────────────────────────────────────────────────
def _compose(chart_type: str, plan: Plan, branches: list[_Branch], displays: dict[str, Display],
             record: Record | None) -> ChartContent:
    live = [b for b in branches if b.calc.points]
    warnings = [n for b in live for n in b.calc.notes]
    dual = None                      # 이중 축 꺾은선의 {지표: y|y2}. long 형식의 line 에서만 정해진다
    rest = None                      # [NEW 11-27] 원 · 도넛의 '그 외' 조각 (_whole_remainder)
    if SPECS[chart_type].rows == "joined":
        cols, rows, enc, axis, more = _joined(chart_type, live)
    else:
        cols, rows, more = _long(live, keep_missing=chart_type in _TIME_X)
        if chart_type == "radar":                    # [NEW 11-27] 월 · 분기 · 반기 시점 → [주기 칸, 연도] (같은 주기끼리 견준다)
            cols, rows = _cycle_split(cols, rows)
        elif chart_type in ("pie", "donut"):         # [NEW 11-27] 전국 대비 서울 비중 → 서울 · 그 외 지역 두 조각
            cols, rows, rest, notes = _whole_remainder(plan, cols, rows, live[0].calc.fixed if len(live) == 1 else None)
            more += notes
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
        encoding=enc, axis=axis, options=_options(chart_type, plan, live, rows, cols, enc, displays, record, dual, rest),
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
