"""[NEW 11-16] 검수 보고서(모듈3_모듈6_검수_보고서.md) 모듈 3 항목의 회귀 테스트. 항목 번호는 보고서의 M3-NN"""
import pytest

from backend.agent.chart_calculate.axis import axis_range
from backend.agent.chart_calculate.calculate import run_answer_steps, run_steps
from backend.agent.chart_calculate.content import build_charts
from backend.agent.chart_calculate.display import format_value, make_display
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.schemas.chart import ChartRequest, Step
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

COLS = ["시점", "행정구역별", "항목", "값"]
NAT = {"행정구역별": ["전국"]}


def regions(rid, rows):
    return view([[t, r, "인구수(명)", float(v)] for t, r, v in rows], COLS, rid=rid)


def step(**d):
    return Step.model_validate({"step_id": "a1", **d})


def operand(item="인구수(명)", rid=VID, select=None, role="value", **kw):
    return {"role": role, "record_id": rid, "item": item, "select": NAT if select is None else select, **kw}


def run(d, records):
    return run_answer_steps([step(**d)], records)[0]


def chart(cid="c1", ctype="line", measure="raw", subs=("q-1",), fallback="bar", view_ids=()):
    return ChartRequest(chart_id=cid, sub_question_ids=list(subs), chart_type=ctype, measure=measure,
                        fallback_chart=fallback, view_ids=list(view_ids))


def bundle(subs, filters):
    return QueryBundle(query_id="q", original="질문", sub_questions=list(subs), sub_filters=list(filters))


# ── M3-08 서로 다른 View 의 같은 항목을 갈래로 ───────────────────
def test_m3_08_same_item_from_two_views_gets_distinct_series():
    seoul = regions("view::S", [(y, "서울특별시", n) for y, n in (("2021", 950), ("2022", 940), ("2023", 930))])
    busan = regions("view::B", [(y, "부산광역시", n) for y, n in (("2021", 340), ("2022", 335), ("2023", 330))])
    decision = {"charts": [{"chart_id": "c1", "operands": [
        {"role": "y", "record_id": "view::S", "item": "인구수(명)", "select": {}},
        {"role": "y", "record_id": "view::B", "item": "인구수(명)", "select": {}}]}]}
    plan, displays = make_plan([chart()], [seoul, busan], Decision.model_validate(decision))
    contents, validation = build_charts(plan, [seoul, busan], displays=displays)
    assert validation["c1"].original.passed
    rows = contents[0].rows
    names = {r[contents[0].columns.index("항목")] for r in rows}
    assert names == {"인구수 (서울특별시)", "인구수 (부산광역시)"}
    # 같은 시점에 같은 이름의 값이 둘인 상태가 아니다
    keys = [(r[0], r[contents[0].columns.index("항목")]) for r in rows]
    assert len(keys) == len(set(keys))


# ── M3-02 질문용 증감률은 두 시점 (결정 D-1) ─────────────────────
def test_m3_02_answer_growth_is_one_value_between_two_points_but_chart_stays_yearly():
    b = bundle(["2021~2025년 전국 혼인건수"], [{"시점": [2021, 2022, 2023, 2024, 2025]}])
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {**NAT, "항목": ["혼인건수(건)"]}}],
           "answers": [{"sub_question_id": "q-1", "op": "growth_rate", "from": "2021", "to": "2025", "operands": [operand("혼인건수(건)")]}]}
    cp, _ = make_plan([chart(measure="growth_rate")], [view()], Decision.model_validate(dec), b)
    assert (cp.answer_steps[0].from_, cp.answer_steps[0].to, cp.answer_steps[0].base) == ("2021", "2025", None)
    assert cp.plans[0].steps[0].base == "prev"                      # 차트용은 연도별 전년 대비
    assert run_answer_steps(cp.answer_steps, [view()])[0].value == pytest.approx(24.84013568337775)


def _answer(**kw):
    return {"answers": [{"sub_question_id": "q-1", "op": "growth_rate", "operands": [operand("혼인건수(건)")], **kw}]}


def test_m3_02_without_from_to_uses_first_and_last_fixed_year_and_prev_is_respected():
    b = bundle(["2021~2025년 전국 혼인건수"], [{"시점": [2021, 2022, 2023, 2024, 2025]}])
    cp, _ = make_plan([], [view()], Decision.model_validate(_answer()), b)
    assert (cp.answer_steps[0].from_, cp.answer_steps[0].to) == ("2021", "2025")
    cp, _ = make_plan([], [view()], Decision.model_validate(_answer(base="prev")), b)
    assert cp.answer_steps[0].base == "prev"
    assert len(run_answer_steps(cp.answer_steps, [view()])[0].value) == 4


def test_m3_02_period_outside_fixed_years_is_pulled_in():
    b = bundle(["2021~2025년 전국 혼인건수"], [{"시점": [2021, 2022, 2023, 2024, 2025]}])
    cp, _ = make_plan([], [view()], Decision.model_validate(_answer(**{"from": "2015", "to": "2025"})), b)
    assert (cp.answer_steps[0].from_, cp.answer_steps[0].to) == ("2021", "2025")
    assert any("고정 시점" in n for n in cp.notes)


# ── M3-03 소수 값 지표의 자릿수 (결정 D-2) ───────────────────────
def test_m3_03_fractional_values_keep_their_decimals_up_to_three():
    v = view([["2023", "전국", "합계출산율(명)", 0.721], ["2024", "전국", "합계출산율(명)", 0.748]])
    dec = {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [operand("합계출산율(명)")]},
                       {"sub_question_id": "q-1", "op": "change", "operands": [operand("합계출산율(명)")]}]}
    cp, displays = make_plan([], [v], Decision.model_validate(dec))
    res = run_answer_steps(cp.answer_steps, [v])
    shown = [format_value(res[0].value[0]["value"], displays[cp.answer_steps[0].display_ref]),
             format_value(res[1].value, displays[cp.answer_steps[1].display_ref])]
    assert shown == ["0.721명", "0.027명"]


def test_m3_03_integer_data_and_computed_ratios_keep_default_digits():
    dec = {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [operand("혼인건수(건)")]},
                       {"sub_question_id": "q-1", "op": "growth_rate", "from": "2021", "to": "2025", "operands": [operand("혼인건수(건)")]}]}
    cp, displays = make_plan([], [view()], Decision.model_validate(dec))
    assert [displays[s.display_ref].digits for s in cp.answer_steps] == [None, None]


def test_m3_16_tiny_negative_is_not_shown_as_minus_zero():
    assert format_value(-0.04, make_display("%")) == "0.0%" and format_value(-0.4, make_display("건")) == "0건"
    assert format_value(-0.06, make_display("%")) == "-0.1%"


# ── M3-04 보류는 계산 하나만 ─────────────────────────────────────
def test_m3_04_withholding_one_answer_keeps_the_other_answers_of_the_same_question():
    other = view(rid="view::OTHER")
    den = {"scope": "question", "operand": {"record_id": "view::OTHER", "item": "혼인건수(건)", "select": NAT}}
    dec = {"answers": [
        {"sub_question_id": "q-1", "op": "share", "operands": [operand("혼인건수(건)")], "denominator": den},
        {"sub_question_id": "q-1", "op": "raw", "operands": [operand("혼인건수(건)", select={**NAT, "시점": ["2025"]})]}]}
    cp, _ = make_plan([chart(ctype=None, view_ids=[VID])], [view(), other], Decision.model_validate(dec))
    assert [s.op for s in cp.answer_steps] == ["raw"]            # 비중만 보류, 조회는 남는다
    assert len(cp.warnings) == 1


# ── M3-05 하위 질문 ID 를 못 찾을 때 ─────────────────────────────
def test_m3_05_unknown_sub_question_id_does_not_borrow_the_first_filter():
    b = bundle(["2021년 혼인건수", "2025년 출생아수"], [{"시점": [2021]}, {"시점": [2025]}])
    dec = {"answers": [{"sub_question_id": "q-9", "op": "raw", "operands": [operand("출생아수(명)", select={**NAT, "시점": ["2025"]})]}]}
    cp, _ = make_plan([], [view()], Decision.model_validate(dec), b)
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2025"]          # 2021 로 바뀌지 않는다
    assert any("고정 조건을 적용하지 않음" in n for n in cp.notes)


def test_m3_05_single_sub_question_still_falls_back_to_it():
    b = bundle(["2021년 혼인건수"], [{"시점": [2021]}])
    dec = {"answers": [{"sub_question_id": "", "op": "raw", "operands": [operand("혼인건수(건)", select={**NAT, "시점": ["2025"]})]}]}
    cp, _ = make_plan([], [view()], Decision.model_validate(dec), b)
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2021"]


# ── M3-06 '전국' 은 지역 총계 ────────────────────────────────────
NATION_MIX = [("2025", "전국", 5000), ("2025", "서울특별시", 900), ("2025", "부산광역시", 300)]


def test_m3_06_aggregate_refuses_to_add_nation_with_its_parts():
    r = run({"op": "aggregate", "agg": "sum", "by": ["시점"], "operands": [operand(select={})]}, [regions(VID, NATION_MIX)])
    assert r.value is None and "총계 행이 섞여 두 번 셈" in r.note


def test_m3_06_selected_share_refuses_nation_mixed_with_regions_and_single_item():
    rec = regions(VID, NATION_MIX)
    r = run({"op": "share", "operands": [operand(select={}, role="part")]}, [rec])
    assert r.value is None and "총계 행이 섞여" in r.note
    only = run({"op": "share", "operands": [operand(select={"행정구역별": ["서울특별시"]}, role="part")]}, [rec])
    assert only.value is None and "하나뿐" in only.note                          # M3-17


def test_m3_06_pie_check_rejects_nation_among_parts():
    from backend.agent.chart_calculate.validate import check_chart
    from backend.schemas.chart import ChartContent
    c = ChartContent(chart_id="c1", chart_type="pie", measure="raw", title="t", encoding={"label": "행정구역별", "value": "값"},
                     columns=["행정구역별", "값"], rows=[["전국", 5000], ["서울특별시", 900], ["부산광역시", 300]])
    got = check_chart(c, ["parts_sum_to_total"])
    assert "parts_sum_to_total" in got.failed and "전국" in got.reasons[0]


# ── M3-07 diff 의 역할 ───────────────────────────────────────────
@pytest.mark.parametrize("roles,expected", [(["a", "b"], 600.0), (["b", None], -600.0), ([None, "a"], -600.0), (["b", "a"], -600.0),
                                            (["b", "b"], 600.0)])
def test_m3_07_diff_roles_never_collapse_to_the_same_operand(roles, expected):
    rec = regions("view::R", [("2025", "서울특별시", 900), ("2025", "부산광역시", 300)])
    dec = {"answers": [{"sub_question_id": "q-1", "op": "diff", "operands": [
        {**operand(rid="view::R", select={"행정구역별": ["서울특별시"]}), "role": roles[0]},
        {**operand(rid="view::R", select={"행정구역별": ["부산광역시"]}), "role": roles[1]}]}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec))
    assert sorted(o.role for o in cp.answer_steps[0].operands) == ["a", "b"]
    assert run_answer_steps(cp.answer_steps, [rec])[0].value == expected


# ── M3-09 앞 단계 결과가 전부 null ───────────────────────────────
def test_m3_09_extreme_over_an_all_null_previous_step_does_not_raise():
    rec = regions("view::R", [("2021", "서울특별시", 0), ("2022", "서울특별시", 0)])
    steps = [Step(step_id="s1", op="index", operands=[operand(rid="view::R", select={})]),
             Step.model_validate({"step_id": "s2", "op": "extreme", "input": "s1"})]
    done = run_steps(steps, [rec])
    assert done["s2"].points == [] and done["s2"].notes                                  # 예외 없이 사유


def test_m3_15_treemap_same_child_name_under_different_parents_is_not_a_duplicate():
    from backend.agent.chart_calculate.validate import check_chart
    from backend.schemas.chart import ChartContent
    c = ChartContent(chart_id="c1", chart_type="treemap", measure="raw", title="t",
                     encoding={"parent": "지역", "label": "성별", "value": "값"}, columns=["지역", "성별", "값"],
                     rows=[["서울", "남자", 10], ["서울", "여자", 12], ["부산", "남자", 5], ["부산", "여자", 6]])
    assert check_chart(c, ["non_negative", "parts_sum_to_total"]).passed


# ── M3-10 고정 시점이 있는데 HCX 가 시점 조건을 빼면 ───────────────
def test_m3_10_missing_time_condition_is_filled_from_the_fixed_year():
    b = bundle(["2025년 전국 혼인건수"], [{"시점": [2025]}])
    dec = {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [operand("혼인건수(건)")]}]}
    cp, _ = make_plan([], [view()], Decision.model_validate(dec), b)
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2025"]
    assert run_answer_steps(cp.answer_steps, [view()])[0].value == [{"key": {"시점": "2025"}, "value": 240326.0}] or \
        run_answer_steps(cp.answer_steps, [view()])[0].value == 240326.0


# ── M3-11 지역 이름 판별 ─────────────────────────────────────────
@pytest.mark.parametrize("name,real", [("서울특별시", True), ("경기도", True), ("세종특별자치시", True), ("시도", False), ("수도", False),
                                       ("연도", False), ("서울", False), ("수원시", False)])
def test_m3_11_only_sido_names_count_as_regions(name, real):
    from backend.agent.chart_calculate.planner import _REAL_REGION
    assert bool(_REAL_REGION.search(name)) is real


def test_m3_11_a_non_region_word_in_the_region_slot_does_not_withhold_the_calculation():
    rec = regions(VID, [("2025", "부산광역시", 100)])
    b = bundle(["x"], [{"지역": ["시도"]}])
    dec = {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [operand(select={"행정구역별": ["부산광역시"]})]}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    assert len(cp.answer_steps) == 1 and cp.warnings == []


# ── M3-12 항목 이름의 괄호 단위가 View 와 다를 때 ─────────────────
def test_m3_12_unit_comes_from_the_view_item_not_from_the_requested_one():
    rec = view([["2025", "전국", "인구(천명)", 51000.0]])
    r = run({"op": "raw", "operands": [operand("인구(명)", rid=VID, unit="명")]}, [rec])
    assert r.unit == "천명" and r.inputs[0].item == "인구(천명)"
    assert r.note and "인구(천명)" in r.note


# ── M3-13 직전 시점이 비어 있을 때 ───────────────────────────────
def test_m3_13_previous_period_with_empty_value_is_not_skipped_over():
    rec = view([["2021", "전국", "혼인건수(건)", 100.0], ["2022", "전국", "혼인건수(건)", None], ["2023", "전국", "혼인건수(건)", 121.0]])
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}, [rec])
    assert r.value is None                                                                  # 2023 은 2021 대비가 아니다 (계산한 값이 없다)
    assert "직전 시점(2022)" in r.note


# ── M3-14 ratio 단위 ─────────────────────────────────────────────
def test_m3_14_ratio_unit_never_contains_the_word_none():
    rec = view([["2025", "전국", "혼인건수(건)", 10.0], ["2025", "전국", "합계출산율", 0.72]])
    r = run({"op": "ratio", "operands": [operand("혼인건수(건)", role="a"), operand("합계출산율", role="b")]}, [rec])
    assert r.unit is None or "None" not in r.unit


def test_m3_14_ratio_unit_rules():
    from backend.agent.chart_calculate.display import ratio_unit
    assert (ratio_unit("명", "명"), ratio_unit("건", "명"), ratio_unit("건", None), ratio_unit(None, None)) == ("배", "건/명", None, "배")


# ── M3-18 · M3-19 ────────────────────────────────────────────────
def test_m3_18_nan_and_inf_are_not_numbers():
    from backend.agent.chart_calculate.select import to_number
    assert [to_number(x) for x in ("nan", "inf", "-inf", float("nan"), float("inf"))] == [None] * 5
    assert to_number(" 1,234 ") == 1234.0 and to_number("1e3") == 1000.0


def test_m3_19_reversed_period_is_put_in_order_and_noted():
    r = run({"op": "growth_rate", "from": "2025", "to": "2021", "operands": [operand("혼인건수(건)")]}, [view()])
    assert r.value == pytest.approx(24.84013568337775) and "기간이 거꾸로" in r.note


# ── M3-21 · M3-22 축 범위 ────────────────────────────────────────
def test_m3_21_bar_axis_with_only_negative_values_ends_at_zero():
    lo, hi = axis_range([-10, -6, -2], "include_zero")
    assert hi == 0.0 and lo <= -10


def test_m3_22_single_fractional_value_gets_a_proportional_range():
    lo, hi = axis_range([0.72], "free")
    assert 0.6 < lo < 0.72 < hi < 0.9
    assert axis_range([5], "free") == (4.0, 6.0)                 # 정수 한 점은 그대로


# ── M3-26 시점 순서 ──────────────────────────────────────────────
def test_m3_26_previous_period_follows_time_order_even_if_view_rows_are_shuffled():
    rec = view([["2023", "전국", "혼인건수(건)", 121.0], ["2021", "전국", "혼인건수(건)", 100.0], ["2022", "전국", "혼인건수(건)", 110.0]])
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}, [rec])
    assert [(p["key"]["시점"], round(p["value"], 1)) for p in r.value] == [("2022", 10.0), ("2023", 10.0)]


# ── 검수 5: 연속 결측이면 실제 직전 시점을 안내한다 ─────────────
def _gap_rows(years_values):
    return [[y, "전국", "혼인건수(건)", v] for y, v in years_values]


@pytest.mark.parametrize("order", ["asc", "shuffled"])
def test_recheck5_consecutive_missing_periods_name_the_actual_previous_period(order):
    data = [("2020", 100.0), ("2021", None), ("2022", None), ("2023", 121.0)]
    if order == "shuffled":
        data = [data[0], data[2], data[1], data[3]]          # 결측 행이 2022, 2021 순으로 들어와도 같다
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}, [view(_gap_rows(data))])
    assert r.value is None and "직전 시점(2022)" in r.note and "직전 시점(2021)" not in r.note


def test_recheck5_single_gap_and_monthly_labels():
    one = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]},
              [view(_gap_rows([("2020", 100.0), ("2021", None), ("2022", 110.0)]))])
    assert "직전 시점(2021)" in one.note
    monthly = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]},
                  [view(_gap_rows([("2024.01", 100.0), ("2024.02", None), ("2024.03", None), ("2024.04", 110.0)]))])
    assert "직전 시점(2024.03)" in monthly.note


# ══ 검수 7 (2026-11-17): 시점 간격 · 평균 이름 · 순서와 제목 ═════════
def _prev(rows):
    return run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}, [view(_gap_rows(rows))])


def test_recheck7_single_interval_is_computed_and_stated():
    r = _prev([("2020", 100.0), ("2023", 130.0)])
    assert r.value == pytest.approx(30.0) and r.note == "시점 3년 간격: 3년 전 값과 비교함"


def test_recheck7_regular_interval_is_computed_and_stated_but_one_step_needs_no_note():
    five = _prev([("2010", 100.0), ("2015", 110.0), ("2020", 121.0)])
    assert [round(p["value"], 1) for p in five.value] == [10.0, 10.0] and "5년 간격" in five.note
    assert _prev([("2020", 100.0), ("2021", 110.0), ("2022", 121.0)]).note is None
    quarterly = _prev([("2024 1분기", 100.0), ("2024 3분기", 110.0), ("2025 1분기", 121.0)])
    assert "2분기 간격" in quarterly.note and len(quarterly.value) == 2


def test_recheck7_irregular_intervals_block_only_the_pairs_that_are_not_one_step_apart():
    """[CHANGED 11-17] 이전: 간격이 섞이면 묶음 전체를 막았다. 결정(검수 8): 수록 주기 1칸 간격인 쌍은 계산한다"""
    r = _prev([("2020", 100.0), ("2021", None), ("2023", 130.0)])        # 값이 빈 행도 시점으로 센다 → 1년, 2년
    assert r.value is None and "시점 간격이 일정하지 않음(1년, 2년)" in r.note
    r = _prev([("2020", 100.0), ("2021", 110.0), ("2024", 130.0)])
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [("2021", pytest.approx(10.0)), ("2024", None)] and "(1년, 3년)" in r.note
    r = _prev([("2024.01", 100.0), ("2024.02", 110.0), ("2024.05", 130.0)])
    assert [p["value"] is None for p in r.value] == [False, True] and "(1개월, 3개월)" in r.note


def test_recheck7_intervals_are_judged_per_group():
    cols = ["시점", "행정구역별", "항목", "값"]
    rows = [[y, "서울특별시", "인구수(명)", v] for y, v in (("2020", 100.0), ("2021", 110.0), ("2022", 121.0))] + \
           [[y, "부산광역시", "인구수(명)", v] for y, v in (("2020", 100.0), ("2021", 110.0), ("2023", 130.0))]
    rec = view(rows, cols)
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("인구수(명)", select={})]}, [rec])
    by = {(p["key"]["행정구역별"], p["key"]["시점"]): p["value"] for p in r.value}
    assert by[("서울특별시", "2021")] == pytest.approx(10.0) and by[("서울특별시", "2022")] == pytest.approx(10.0)
    assert by[("부산광역시", "2021")] == pytest.approx(10.0) and by[("부산광역시", "2023")] is None      # 부산은 1년 간격 쌍만 계산


def test_recheck7_points_stay_in_time_order_when_a_value_is_missing_and_title_follows_shown_rows():
    from backend.agent.chart_calculate.content import build_charts
    rows = _gap_rows([("2020", 100.0), ("2021", 110.0), ("2022", None), ("2023", 130.0), ("2024", 140.0)])
    v = view(rows)
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}, [v])
    assert [(p["key"]["시점"], p["value"] is None) for p in r.value] == [("2021", False), ("2023", True), ("2024", False)]
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {**NAT, "항목": ["혼인건수(건)"]}}]}
    plan, displays = make_plan([chart(measure="growth_rate")], [v], Decision.model_validate(dec))
    contents, _ = build_charts(plan, [v], displays=displays)
    assert [row[0] for row in contents[0].rows] == ["2021", "2024"] and contents[0].title.startswith("2021~2024 ")


def test_recheck7_average_chart_is_titled_and_labelled_as_average_while_sum_stays_sum():
    from backend.agent.chart_calculate.content import build_charts, measure_name
    v = view([["2025", "서울", "인구(천명)", 50.0], ["2025", "부산", "인구(천명)", 51.0]], COLS)
    sel = {"행정구역별": ["서울", "부산"], "항목": ["인구(천명)"]}
    for agg, word in (("mean", "평균"), ("sum", "합계")):
        dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": sel, "agg": agg}]}
        plan, displays = make_plan([chart(ctype="bar", measure="aggregate", fallback="line")], [v], Decision.model_validate(dec))
        contents, _ = build_charts(plan, [v], displays=displays)
        assert contents[0].title.endswith(f"연도별 {word}") and contents[0].axis["y"].label == f"인구 {word}"
    assert measure_name("aggregate", "mean") == "평균" and measure_name("aggregate", None) == "합계"


# ══ 검수 8 (2026-11-17): 한 시점 · 정상 간격 쌍 · 제목 범위 · 지역별 사유 ═════
def test_recheck8_single_period_ends_only_that_calculation_and_the_other_steps_still_run():
    rec = view(_gap_rows([("2025", 100.0)]))
    steps = [Step.model_validate({"step_id": "a1", "op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}),
             Step.model_validate({"step_id": "a2", "op": "raw", "operands": [operand("혼인건수(건)")]})]
    first, second = run_answer_steps(steps, [rec])
    assert first.value is None and first.note == "시점이 하나뿐이라 직전 시점이 없음" and second.value == 100.0


@pytest.mark.internal_error_ok
def test_recheck8_unexpected_error_in_one_step_does_not_stop_the_rest(monkeypatch):
    from backend.agent.chart_calculate import calculate

    def boom(ctx):
        raise IndexError("boom")
    monkeypatch.setitem(calculate._OPS, "growth_rate", boom)
    steps = [Step.model_validate({"step_id": "a1", "op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)")]}),
             Step.model_validate({"step_id": "a2", "op": "raw", "operands": [operand("혼인건수(건)")]})]
    first, second = run_answer_steps(steps, [view()])
    assert first.value is None and first.note == "내부 오류로 계산하지 못함: IndexError" and second.value is not None


@pytest.mark.parametrize("rows,expected", [
    ([("2020", 100.0), ("2021", 110.0), ("2024", 130.0)], [("2021", False), ("2024", True)]),         # 정상 전년 대비는 남긴다
    ([("2020", 100.0), ("2023", 130.0)], [("2023", False)]),                                         # 간격이 하나 → 계산 (3년 표기)
    ([("2010", 100.0), ("2015", 110.0), ("2020", 121.0)], [("2015", False), ("2020", False)]),       # 일정한 5년 간격
    ([("2020", 100.0), ("2021", 110.0), ("2022", 121.0), ("2025", 130.0)], [("2021", False), ("2022", False), ("2025", True)])])
def test_recheck8_only_pairs_one_step_apart_survive_mixed_intervals(rows, expected):
    r = _prev(rows)
    got = r.value if isinstance(r.value, list) else [{"key": {"시점": rows[-1][0]}, "value": r.value}]
    assert [(p["key"]["시점"], p["value"] is None) for p in got] == expected


def test_recheck8_title_year_range_uses_earliest_and_latest_shown_period_across_groups():
    from backend.agent.chart_calculate.content import build_charts
    rows = [[y, "서울", "혼인건수(건)", v] for y, v in (("2022", 100.0), ("2023", 110.0), ("2024", 121.0))] + \
           [[y, "부산", "혼인건수(건)", v] for y, v in (("2018", 100.0), ("2019", 110.0), ("2020", 121.0))]
    v = view(rows, COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"행정구역별": ["서울", "부산"], "항목": ["혼인건수(건)"]}}]}
    plan, displays = make_plan([chart(measure="growth_rate")], [v], Decision.model_validate(dec))
    contents, _ = build_charts(plan, [v], displays=displays)
    assert contents[0].title.startswith("2019~2024 ")          # 2023~2020 처럼 뒤집히지 않는다


def test_recheck8_interval_reason_names_the_group_it_belongs_to():
    rows = [[y, "서울", "혼인건수(건)", v] for y, v in (("2020", 100.0), ("2021", 110.0), ("2022", 121.0))] + \
           [[y, "부산", "혼인건수(건)", v] for y, v in (("2010", 100.0), ("2015", 110.0), ("2020", 121.0))]
    r = run({"op": "growth_rate", "base": "prev", "operands": [operand("혼인건수(건)", select={"행정구역별": ["서울", "부산"]})]},
            [view(rows, COLS)])
    assert r.note == "시점 5년 간격[부산]: 5년 전 값과 비교함"          # 서울은 1칸 간격이라 표기가 없다


# ══ 검수 9 (2026-11-17): 같은 시점 값 충돌 · 가로축 시간순 · 계산 불가 시점의 선 끊기 ═══
def test_recheck9_two_different_values_in_the_same_period_are_not_compared_as_a_year_over_year_change():
    r = _prev([("2024", 100.0), ("2024", 125.0), ("2025", 150.0)])
    assert r.value is None and r.note == "2025: 직전 시점(2024)에 값이 둘 이상이라 계산하지 않음"      # 25% 도 20% 도 나가지 않는다
    r = _prev([("2020", 90.0), ("2024", 100.0), ("2024", 125.0), ("2025", 150.0)])
    assert [p["value"] for p in r.value] == [None, None]
    assert "2024: 같은 시점에 값이 둘 이상(100, 125)이라 계산하지 않음" in r.note and "2025: 직전 시점(2024)에 값이 둘 이상" in r.note


def test_recheck9_identical_duplicates_are_not_a_conflict_and_other_periods_are_unaffected():
    r = _prev([("2022", 100.0), ("2023", 110.0), ("2023", 110.0), ("2024", 121.0)])
    assert [round(p["value"], 1) for p in r.value] == [10.0, 10.0] and r.note is None
    r = _prev([("2021", 100.0), ("2022", 110.0), ("2023", 120.0), ("2023", 125.0), ("2024", 130.0)])
    assert [(p["key"]["시점"], p["value"] is None) for p in r.value] == [("2022", False), ("2023", True), ("2024", True)]


def test_recheck9_conflicting_values_block_two_point_growth_and_index_base():
    r = run({"op": "growth_rate", "from": "2024", "to": "2025", "operands": [operand("혼인건수(건)")]},
            [view(_gap_rows([("2024", 100.0), ("2024", 125.0), ("2025", 150.0)]))])
    assert r.value is None and "2024: 같은 시점에 값이 둘 이상(100, 125)" in r.note and r.inputs == []
    r = run({"op": "index", "base": "2024", "operands": [operand("혼인건수(건)")]},
            [view(_gap_rows([("2024", 100.0), ("2024", 125.0), ("2025", 150.0)]))])
    assert all(p["value"] is None for p in r.value) and "같은 시점에 값이 둘 이상" in r.note


def _draw(content, displays):
    from backend.agent.draw_chart import run_module5
    out = run_module5(chart_plan={"query_id": "q", "charts": [{"chart_id": content.chart_id, "chart_type": content.chart_type, "measure": content.measure}]},
                      chart_contents=[content.model_dump()], calc_results=[], displays={k: d.model_dump() for k, d in displays.items()}, save=False)
    return out["results"][0]


def test_recheck9_rows_and_the_plotly_x_axis_follow_time_even_when_groups_cover_different_years():
    from backend.agent.chart_calculate.content import build_charts
    rows = [[y, "서울", "혼인건수(건)", v] for y, v in (("2022", 100.0), ("2023", 110.0), ("2024", 121.0))] + \
           [[y, "부산", "혼인건수(건)", v] for y, v in (("2018", 100.0), ("2019", 110.0), ("2020", 121.0))]
    v = view(rows, COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"행정구역별": ["서울", "부산"], "항목": ["혼인건수(건)"]}}]}
    plan, displays = make_plan([chart(measure="growth_rate")], [v], Decision.model_validate(dec))
    contents, _ = build_charts(plan, [v], displays=displays)
    times = [r[0] for r in contents[0].rows]
    assert times == sorted(times) and contents[0].title.startswith("2019~2024 ")
    res = _draw(contents[0], displays)
    assert res.status == "drawn" and all(list(t.x) == ["2019", "2020", "2023", "2024"] for t in res.figure.data)      # 2023 → 2024 → 2019 → 2020 이던 것


def _line(values, ctype="line", fallback="bar"):
    from backend.agent.chart_calculate.content import build_charts
    v = view([[y, "서울", "혼인건수(건)", x] for y, x in values], COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"행정구역별": ["서울"], "항목": ["혼인건수(건)"]}}]}
    plan, displays = make_plan([chart(ctype=ctype, measure="growth_rate", fallback=fallback)], [v], Decision.model_validate(dec))
    contents, validation = build_charts(plan, [v], displays=displays)
    return contents, validation, displays


_YEARS = [("2018", 100.0), ("2019", 104.0), ("2020", 108.0), ("2021", 112.0), ("2022", None), ("2023", 130.0), ("2024", 140.0), ("2025", 150.0)]


def test_recheck9_line_keeps_the_period_it_could_not_calculate_as_an_empty_value_so_the_line_breaks():
    contents, validation, displays = _line(_YEARS)
    c = contents[0]
    # [CHANGED 11-17] 이전: 2023 만 빈 값 행. 결정: 값이 빈 해(2022) 자체도 가로축에 남긴다 (2022 와 2023 둘 다 계산 못 함)
    assert c.chart_type == "line" and [(r[0], r[-1] is None) for r in c.rows] == [
        ("2019", False), ("2020", False), ("2021", False), ("2022", True), ("2023", True), ("2024", False), ("2025", False)]
    assert "계산할 수 없는 시점 2개는 선을 끊어 표시" in c.warnings
    res = _draw(c, displays)
    trace = res.figure.data[0]
    assert list(trace.x) == ["2019", "2020", "2021", "2022", "2023", "2024", "2025"] and trace.y[3] is None and trace.y[4] is None \
        and not trace.connectgaps


def test_recheck9_missing_points_do_not_count_as_points_and_other_chart_types_still_drop_them():
    contents, validation, _ = _line([("2018", 100.0), ("2019", 104.0), ("2020", 108.0), ("2021", None), ("2022", 120.0)])
    assert "min_points_3" in validation["c1"].original.failed          # 행은 3개(2019·2020·2022)지만 값이 있는 점은 2개
    bar, _, _ = _line(_YEARS, ctype="bar", fallback="line")
    assert bar[0].chart_type == "bar" and all(r[-1] is not None for r in bar[0].rows)


# ══ 검수 10 (2026-11-17): 지수·raw 의 충돌, 충돌 값의 정밀도 ═══════════════
def _index(rows, base="2023"):
    return run({"op": "index", "base": base, "operands": [operand("혼인건수(건)")]}, [view(_gap_rows(rows))])


def test_recheck10_index_conflict_after_the_base_period_becomes_one_empty_point():
    r = _index([("2023", 100.0), ("2024", 110.0), ("2024", 120.0), ("2025", 130.0)])
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [("2023", 100.0), ("2024", None), ("2025", 130.0)]
    assert "2024: 같은 시점에 값이 둘 이상(110, 120)이라 계산하지 않음" in r.note


def test_recheck10_index_identical_duplicates_collapse_and_chart_gets_an_empty_point_not_the_first_value():
    from backend.agent.chart_calculate.content import build_charts
    r = _index([("2023", 100.0), ("2024", 110.0), ("2024", 110.0), ("2025", 130.0)])
    assert [p["value"] for p in r.value] == pytest.approx([100.0, 110.0, 130.0]) and r.note is None
    v = view(_gap_rows([("2022", 90.0), ("2023", 100.0), ("2024", 110.0), ("2024", 120.0), ("2025", 130.0)]))
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {**NAT, "항목": ["혼인건수(건)"]}, "base": "2023"}]}
    plan, displays = make_plan([chart(measure="index")], [v], Decision.model_validate(dec))
    contents, _ = build_charts(plan, [v], displays=displays)
    assert [(r[0], r[-1] is None) for r in contents[0].rows] == [("2022", False), ("2023", False), ("2024", True), ("2025", False)]
    trace = _draw(contents[0], displays).figure.data[0]
    assert list(trace.x) == ["2022", "2023", "2024", "2025"] and trace.y[2] is None          # 110 이 그려지지 않는다


def test_recheck10_raw_conflict_is_one_empty_point_and_identical_duplicates_collapse_in_view_order():
    r = run({"op": "raw", "operands": [operand("혼인건수(건)")]}, [view(_gap_rows([("2023", 100.0), ("2024", 110.0), ("2024", 120.0)]))])
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [("2023", 100.0), ("2024", None)]
    assert r.note == "2024: 같은 시점에 값이 둘 이상(110, 120)이라 계산하지 않음"
    r = run({"op": "raw", "operands": [operand("혼인건수(건)")]}, [view(_gap_rows([("2023", 100.0), ("2024", 110.0), ("2024", 110.0)]))])
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [("2023", 100.0), ("2024", 110.0)] and r.note is None


def test_recheck10_raw_conflict_is_judged_per_group_and_keeps_the_view_order():
    rows = [["2024", "서울", "인구수(명)", 5.0], ["2024", "부산", "인구수(명)", 3.0], ["2024", "서울", "인구수(명)", 6.0], ["2025", "부산", "인구수(명)", 4.0]]
    r = run({"op": "raw", "operands": [operand("인구수(명)", select={})]}, [view(rows, COLS)])
    got = [(p["key"]["행정구역별"], p["key"]["시점"], p["value"]) for p in r.value]
    assert got == [("서울", "2024", None), ("부산", "2024", 3.0), ("부산", "2025", 4.0)]


def test_recheck10_conflicting_values_keep_their_original_precision_in_the_reason():
    from backend.agent.chart_calculate.calculate import _show
    assert (_show(1000000.0), _show(1000001), _show(0.721), _show(2.5), _show(100.0)) == ("1000000", "1000001", "0.721", "2.5", "100")
    r = _prev([("2023", 900000.0), ("2024", 1000000.0), ("2024", 1000001.0)])
    assert "(1000000, 1000001)" in r.note and "e+" not in r.note


def _raw_line(values, ctype="line", fallback="bar", measure="raw", group="서울"):
    from backend.agent.chart_calculate.content import build_charts
    v = view([[y, group, "혼인건수(건)", x] for y, x in values], COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"행정구역별": [group], "항목": ["혼인건수(건)"]}}]}
    plan, displays = make_plan([chart(ctype=ctype, measure=measure, fallback=fallback)], [v], Decision.model_validate(dec))
    contents, validation = build_charts(plan, [v], displays=displays)
    return contents, validation, displays


def test_recheck9_raw_line_keeps_the_period_whose_observed_value_is_empty_so_the_line_breaks():
    """시험 화면에서 확인한 빈틈: 값이 비어 있는 관측 시점(raw)도 가로축에 남기고 선을 끊는다"""
    contents, validation, displays = _raw_line([("2019", 100.0), ("2020", 104.0), ("2021", 108.0), ("2022", None), ("2023", 130.0), ("2024", 140.0)])
    c = contents[0]
    assert c.chart_type == "line" and [(r[0], r[-1] is None) for r in c.rows] == [
        ("2019", False), ("2020", False), ("2021", False), ("2022", True), ("2023", False), ("2024", False)]
    assert "계산할 수 없는 시점 1개는 선을 끊어 표시" in c.warnings
    res = _draw(c, displays)
    trace = res.figure.data[0]
    assert list(trace.x) == ["2019", "2020", "2021", "2022", "2023", "2024"] and trace.y[3] is None and not trace.connectgaps
    bar, _, _ = _raw_line([("2019", 100.0), ("2020", 104.0), ("2021", 108.0), ("2022", None), ("2023", 130.0)], ctype="bar", fallback="line")
    assert bar[0].chart_type == "bar" and "2022" not in [r[0] for r in bar[0].rows]       # 막대는 빈 시점을 그리지 않는다
    # 빈 시점은 CalcResult(답변용 수치)에 점으로 들어가지 않는다 — 모듈 6 의 표·문장은 지금까지와 같다
    r = run({"op": "raw", "operands": [operand("혼인건수(건)")]}, [view(_gap_rows([("2021", 1.0), ("2022", None), ("2023", 3.0)]))])
    assert [p["key"]["시점"] for p in r.value] == ["2021", "2023"]


def test_recheck9_leading_and_trailing_empty_periods_are_not_added_to_the_axis():
    contents, _, _ = _raw_line([("2018", None), ("2019", None), ("2020", 100.0), ("2021", 104.0), ("2022", 108.0), ("2023", None)])
    assert [r[0] for r in contents[0].rows] == ["2020", "2021", "2022"]        # 값이 있는 첫 시점 앞과 마지막 시점 뒤는 뺀다


def test_recheck9_growth_line_shows_both_the_period_it_cannot_calculate_and_the_empty_year_itself():
    """결정: 2022 값이 비면 증감률 2022(본인 값 없음)와 2023(직전 2022 없음)을 모두 가로축에 표시"""
    contents, _, displays = _raw_line(_YEARS, measure="growth_rate")
    c = contents[0]
    assert [(r[0], r[-1] is None) for r in c.rows] == [("2019", False), ("2020", False), ("2021", False), ("2022", True),
                                                       ("2023", True), ("2024", False), ("2025", False)]
    trace = _draw(c, displays).figure.data[0]
    assert list(trace.x)[3:5] == ["2022", "2023"] and trace.y[3] is None and trace.y[4] is None and not trace.connectgaps


# ══ 재검토 11 (2026-11-17): 다른 계열의 결측 행 · 지수와 합계의 빈 관측 시점 ═════════
def _chart_and_figure(rows, regions, measure, ctype="line", **extra):
    from backend.agent.chart_calculate.content import build_charts
    v = view(rows, COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"행정구역별": regions, "항목": ["혼인건수(건)"]}, **extra}]}
    plan, displays = make_plan([chart(ctype=ctype, measure=measure)], [v], Decision.model_validate(dec))
    contents, validation = build_charts(plan, [v], displays=displays)
    assert contents, validation["c1"].original.reasons
    return contents[0], _draw(contents[0], displays).figure.data


def _r(y, g, v):
    return [y, g, "혼인건수(건)", v]


def test_recheck11_a_missing_row_of_another_region_does_not_break_the_line_of_this_region():
    rows = [_r("2020", "서울", 100.0), _r("2021", "부산", None), _r("2022", "서울", 110.0), _r("2023", "서울", 120.0)]
    c, data = _chart_and_figure(rows, ["서울", "부산"], "raw")
    assert [(r[0], r[-1]) for r in c.rows] == [("2020", 100.0), ("2022", 110.0), ("2023", 120.0)]      # 부산 2021 이 서울 선의 빈 점이 되지 않는다
    assert list(data[0].x) == ["2020", "2022", "2023"] and None not in list(data[0].y)
    r = run({"op": "raw", "operands": [operand("혼인건수(건)", select={"행정구역별": ["서울", "부산"]})]}, [view(rows, COLS)])
    assert [p["key"]["시점"] for p in r.value] == ["2020", "2022", "2023"]                              # 답변과 같다


def test_recheck11_own_missing_row_still_breaks_only_its_own_region_line():
    rows = [_r(y, "서울", v) for y, v in (("2020", 100.0), ("2021", 101.0), ("2022", 102.0))] + \
           [_r("2020", "부산", 50.0), _r("2021", "부산", None), _r("2022", "부산", 52.0)]
    c, data = _chart_and_figure(rows, ["서울", "부산"], "raw")
    by = {t.name: list(t.y) for t in data}
    assert None not in by["서울"] and by["부산"] == [50.0, None, 52.0]


def test_recheck11_region_with_only_missing_rows_is_not_drawn_and_leading_trailing_gaps_are_dropped():
    rows = [_r("2018", "서울", None), _r("2019", "서울", 100.0), _r("2020", "서울", 105.0), _r("2021", "서울", None), _r("2022", "서울", 110.0),
            _r("2023", "서울", None), _r("2019", "부산", None), _r("2020", "부산", None), _r("2021", "부산", None)]
    c, data = _chart_and_figure(rows, ["서울", "부산"], "raw")
    assert [(r[0], r[-1] is None) for r in c.rows] == [("2019", False), ("2020", False), ("2021", True), ("2022", False)]
    assert len(data) == 1                                      # 값이 하나도 없는 부산은 계열이 없다


def test_recheck11_index_chart_keeps_the_year_whose_source_value_is_empty():
    rows = [_r(y, "서울", v) for y, v in (("2019", 90.0), ("2020", 100.0), ("2021", 110.0), ("2022", None), ("2023", 130.0), ("2024", 140.0))]
    c, data = _chart_and_figure(rows, ["서울"], "index", base="2020")
    assert [(r[0], r[-1] is None) for r in c.rows] == [("2019", False), ("2020", False), ("2021", False), ("2022", True), ("2023", False), ("2024", False)]
    assert list(data[0].x) == ["2019", "2020", "2021", "2022", "2023", "2024"] and data[0].y[3] is None


def test_recheck11_per_period_sum_chart_keeps_a_period_when_every_input_is_empty_but_not_when_some_are():
    rows = [_r(y, g, v) for y, g, v in (("2019", "서울", 90.0), ("2019", "부산", 40.0), ("2020", "서울", 100.0), ("2020", "부산", 50.0),
                                         ("2021", "서울", None), ("2021", "부산", None), ("2022", "서울", 130.0), ("2022", "부산", None),
                                         ("2023", "서울", 140.0), ("2023", "부산", 70.0))]
    c, data = _chart_and_figure(rows, ["서울", "부산"], "aggregate", agg="sum")
    got = {r[0]: r[-1] for r in c.rows}
    # [CHANGED 11-17 외부 피드백] 이전: 2022 는 있는 값만 더해 130 — 다른 해의 서울+부산 합계와 견줄 수 없는 부분합이었다. 이제 빈 점
    assert got == {"2019": 130.0, "2020": 150.0, "2021": None, "2022": None, "2023": 210.0} and len(c.rows) == 5      # 2021 · 2022 한 번씩
    assert data[0].y[2] is None
