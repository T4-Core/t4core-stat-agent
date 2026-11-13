"""[NEW] planner.py — HCX 결정(Decision) + 모듈 2 charts[] → ChartPlan · displays (HCX 없이, 결정은 손으로 적는다)"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.content import build_charts
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.schemas.chart import ChartRequest
from tests.chart_calculate._views import VID, view

YEARS = ["2021", "2022", "2023", "2024", "2025"]
NATION = {"행정구역별": ["전국"]}


def chart(chart_id="c1", chart_type="line", measure="raw", subs=("q-1",), fallback="bar", reqs=()):
    return ChartRequest(chart_id=chart_id, sub_question_ids=list(subs), chart_type=chart_type, measure=measure,
                        requirements=list(reqs), fallback_chart=fallback)


def pick(item, role=None, select=None):
    return {"role": role, "record_id": VID, "item": item, "select": NATION if select is None else select}


def plan(charts, decision, records=None):
    return make_plan(charts, records or [view()], Decision.model_validate(decision))


# 명세 4장 "예시: 명세서 시나리오" 의 결정 부분
SCENARIO_CHARTS = [chart("c1", subs=["q-1"]), chart("c2", subs=["q-2"])]
SCENARIO = {
    "charts": [
        {"chart_id": "c1", "record_id": VID, "select": {**NATION, "항목": ["혼인건수(건)"], "시점": YEARS}},
        {"chart_id": "c2", "record_id": VID, "select": {**NATION, "항목": ["출생아수(명)"], "시점": YEARS}}],
    "answers": [
        {"sub_question_id": "q-1", "op": "growth_rate", "from": 2021, "to": 2025, "operands": [pick("혼인건수(건)")]},
        {"sub_question_id": "q-2", "op": "growth_rate", "from": 2021, "to": 2025, "operands": [pick("출생아수(명)")]}],
}


def test_spec_scenario_plan_and_displays():
    cp, displays = plan(SCENARIO_CHARTS, SCENARIO)
    dumped = cp.model_dump(by_alias=True, exclude_none=True)
    assert dumped["plans"][0] == {
        "chart_id": "c1", "sub_question_ids": ["q-1"], "record_id": VID, "chart_type": "line", "fallback_chart": "bar",
        "measure": "raw", "select": {**NATION, "항목": ["혼인건수(건)"], "시점": YEARS},
        "steps": [{"step_id": "s1", "op": "raw", "display_ref": "d1"}]}
    assert dumped["plans"][1]["steps"] == [{"step_id": "s1", "op": "raw", "display_ref": "d2"}]
    # 명세 예시는 증감률을 from·to(2021→2025)로 적었지만, 증감률은 시점마다 직전 대비로 계산한다 (2026-11-11 결정)
    assert dumped["answer_steps"][0] == {
        "step_id": "a1", "op": "growth_rate", "base": "prev", "display_ref": "d3",
        "operands": [{"role": "value", "record_id": VID, "item": "혼인건수(건)", "select": NATION, "unit": "건",
                      "unit_source": "item"}]}
    assert dumped["answer_steps"][1]["display_ref"] == "d3"                # 같은 단위(%) → 같은 표시 설정
    assert {k: (d.source_unit, d.display_unit, d.unit_scale) for k, d in displays.items()} == {
        "d1": ("건", "건", 1), "d2": ("명", "명", 1), "d3": ("%", "%", 1)}


def test_answer_op_differs_from_chart_measure_is_noted_not_blocked():
    cp, _ = plan(SCENARIO_CHARTS, SCENARIO)
    assert [n for n in cp.notes if "≠" in n] == ["q-1: 질문용 연산 growth_rate ≠ 모듈 2 measure raw (c1)",
                                                 "q-2: 질문용 연산 growth_rate ≠ 모듈 2 measure raw (c2)"]
    assert len(cp.plans) == 2 and len(cp.answer_steps) == 2               # 둘 다 실행한다


def test_plan_runs_end_to_end_like_spec():
    """계획 → 차트·계산 결과까지 (명세 5·6장 수치)"""
    cp, displays = plan(SCENARIO_CHARTS, SCENARIO)
    contents, validation = build_charts(cp, [view()], {"c1": ["time_axis_required", "min_points_3"]}, displays)
    assert [(c.chart_id, c.chart_type, len(c.rows)) for c in contents] == [("c1", "line", 5), ("c2", "line", 5)]
    assert contents[0].axis["y"].display_ref == "d1" and validation["c2"].content_built
    a1, a2 = run_answer_steps(cp.answer_steps, [view()])
    assert [v["value"] for v in a1.value] == pytest.approx([-817 / 192507 * 100, 1967 / 191690 * 100,
                                                            28755 / 193657 * 100, 17914 / 222412 * 100])
    assert len(a2.value) == 4 and a2.value[0]["value"] == pytest.approx((249186 - 260562) / 260562 * 100)


def test_no_chart_sub_question_still_gets_answer_step():
    cp, _ = plan([chart("c1", chart_type=None)], {"answers": [SCENARIO["answers"][0]]})
    assert cp.plans == [] and [s.step_id for s in cp.answer_steps] == ["a1"]
    assert cp.notes == ["q-1: growth_rate: 시점마다 직전 시점 대비로 계산 (View 의 모든 시점)"]


def test_combo_branches_get_steps_output_and_own_displays():
    sel = {**NATION, "시점": YEARS}
    cp, displays = plan([chart("c3", "combo", fallback="line")], {"charts": [{
        "chart_id": "c3", "operands": [pick("혼인건수(건)", "y", sel), pick("조혼인율(천명당)", "y2", sel)]}]})
    p = cp.plans[0]
    assert p.record_id == VID and [(s.step_id, s.operands[0].item, s.operands[0].role) for s in p.steps] == [
        ("s1", "혼인건수(건)", "value"), ("s2", "조혼인율(천명당)", "value")]
    assert [(o.step_id, o.role) for o in p.output] == [("s1", "y"), ("s2", "y2")]
    assert [displays[s.display_ref].source_unit for s in p.steps] == ["건", "천명당"]


def test_diff_uses_one_step_with_a_b():
    d = {"chart_id": "c1", "join_on": ["시점"], "operands": [pick("혼인건수(건)"), pick("출생아수(명)")]}
    cp, displays = plan([chart(measure="diff")], {"charts": [d]})
    step = cp.plans[0].steps[0]
    assert [o.role for o in step.operands] == ["a", "b"] and step.join_on == ["시점"] and cp.plans[0].output is None
    ratio, displays = plan([chart(measure="ratio")], {"charts": [d]})
    assert displays[ratio.plans[0].steps[0].display_ref].source_unit == "건/명"
    one, _ = plan([chart(measure="diff")], {"charts": [{**d, "operands": d["operands"][:1]}]})
    assert "c1: diff 는 피연산자 2개가 필요 (받은 것 1개)" in one.notes


def test_share_gets_default_denominator_label():
    cp, displays = plan([chart(chart_type="pie", measure="share")], {"charts": [{
        "chart_id": "c1", "record_id": VID, "select": {"항목": ["혼인건수(건)"], "시점": ["2025"]}}]})
    step = cp.plans[0].steps[0]
    assert (step.denominator.scope, step.denominator.label) == ("selected", "선택 항목 내 비중")
    assert displays[step.display_ref].source_unit == "%"
    den = {"scope": "question", "operand": {"record_id": VID, "item": "혼인건수(건)", "select": {"행정구역별": ["세종"]}}}
    cp, _ = plan([chart(chart_type="pie", measure="share")], {"charts": [{
        "chart_id": "c1", "record_id": VID, "select": {"항목": ["혼인건수(건)"]}, "denominator": den}]})
    assert cp.plans[0].steps[0].denominator.label is None                  # 질문 범위의 문구는 HCX 가 정한다
    assert "c1: 행정구역별에 없는 값: ['세종']" in cp.notes


def test_bad_picks_are_noted_and_fail_later_with_reason():
    """HCX 가 없는 값을 골라도 계획에서 빼지 않는다 → 실행하면 검증이 같은 사유로 걸러낸다"""
    cp, displays = plan([chart()], {"charts": [{
        "chart_id": "c1", "record_id": VID, "select": {**NATION, "항목": ["혼인건수(건)"], "시점": ["2030"]}}]})
    assert "c1: 시점에 없는 값: ['2030']" in cp.notes and len(cp.plans) == 1
    contents, validation = build_charts(cp, [view()], displays=displays)
    assert contents == [] and validation["c1"].original.failed == ["data_present"]
    assert "시점에 없는 값: ['2030']" in validation["c1"].original.reasons


def test_skips_what_cannot_be_planned():
    cp, _ = plan([chart("c1"), chart("c2")], {
        "charts": [{"chart_id": "c1"}], "answers": [{"sub_question_id": "q-1", "op": "rank"}]})
    assert cp.plans == [] and cp.answer_steps == []
    assert cp.notes == ["c1: record_id 가 없어 차트 계획을 만들지 않음", "c2: 계획 결정이 없어 차트 계획을 만들지 않음",
                        "q-1: 질문용 계산 rank 에 피연산자가 없어 건너뜀"]


def test_branch_with_wrong_role_gets_free_role():
    """combo 에 없는 역할('왼쪽') → 비어 있는 y2 에 배정 (2026-11-10 HCX 가 role "combo" 를 준 것과 같은 종류)"""
    sel = {**NATION, "시점": YEARS}
    cp, _ = plan([chart("c3", "combo")], {"charts": [{
        "chart_id": "c3", "operands": [pick("혼인건수(건)", "y", sel), pick("출생아수(명)", "왼쪽", sel)]}]})
    assert [(o.step_id, o.role) for o in cp.plans[0].output] == [("s1", "y"), ("s2", "y2")]
    assert cp.notes == ["c3: combo 갈래 역할 왼쪽 → y2 (출생아수(명))"]


def test_branch_without_free_role_is_noted():
    sel = {**NATION, "시점": YEARS}
    cp, _ = plan([chart("c3", "combo")], {"charts": [{"chart_id": "c3", "operands": [
        pick("혼인건수(건)", "y", sel), pick("출생아수(명)", "y2", sel), pick("조혼인율(천명당)", "왼쪽", sel)]}]})
    assert [(o.step_id, o.role) for o in cp.plans[0].output] == [("s1", "y"), ("s2", "y2")]
    assert cp.notes == ["c3: 축 역할이 없는 갈래가 있음 (차트에 쓰이지 않음)"]


def test_answer_operands_are_normalized():
    """질문용: 피연산자가 아닌 것은 버리고, 같은 항목은 합치고, 증감률은 시점마다 직전 대비로 (회귀 테스트의 단위 버전)"""
    cp, _ = plan([], {"answers": [{"op": "growth_rate", "from": "2021", "to": "2025", "operands": [
        pick("혼인건수(건)", "a", {**NATION, "시점": ["2024"]}), pick("혼인건수(건)", "b", {**NATION, "시점": ["2021"]}),
        pick("시점", "join_on", {})]}]})
    (op,) = cp.answer_steps[0].operands
    assert (op.role, op.item, op.select) == ("value", "혼인건수(건)", NATION)      # 시점 조건 없음 = View 의 모든 시점
    step = cp.answer_steps[0]
    assert (step.base, step.from_, step.to) == ("prev", None, None)
    assert cp.notes == ["a1: 피연산자가 아님 → 버림 (role=join_on, item=시점)",
                        "a1: growth_rate 는 피연산자 1개 → 같은 항목의 피연산자를 하나로 합침 "
                        "(2개, 조건 {'행정구역별': ['전국'], '시점': ['2024', '2021']})",
                        "a1: growth_rate: 시점마다 직전 시점 대비로 계산 (View 의 모든 시점)"]


def test_answer_different_items_are_split_into_steps():
    """[CHANGED] 이전: test_answer_different_items_keep_first — 항목이 다르면 첫 번째만 남기고 나머지는 버렸다.
    그러면 차트에는 두 지표가 있는데 답변(calc_results)에는 한쪽이 없었다 → 항목마다 단계로 쪼갠다 (a1-1, a1-2)"""
    cp, _ = plan([], {"answers": [{"op": "raw", "operands": [pick("혼인건수(건)"), pick("출생아수(명)")]}]})
    assert [(s.step_id, [o.item for o in s.operands]) for s in cp.answer_steps] == [
        ("a1-1", ["혼인건수(건)"]), ("a1-2", ["출생아수(명)"])]
    assert cp.notes == ["a1: raw 는 피연산자 1개 → 항목마다 따로 계산 (['혼인건수(건)', '출생아수(명)'])"]
    assert cp.answer_steps[0].display_ref != cp.answer_steps[1].display_ref        # 단위가 달라 표시 설정도 따로 (건 · 명)


def test_answer_split_steps_all_get_calculated():
    """쪼갠 단계가 모두 실제로 계산되어 calc_results 에 들어간다 (모듈 6 이 두 지표를 다 쓸 수 있다)"""
    sel = {**NATION, "시점": YEARS}
    cp, _ = plan([], {"answers": [{"op": "raw", "operands": [pick("혼인건수(건)", select=sel), pick("출생아수(명)", select=sel)]}]})
    results = run_answer_steps(cp.answer_steps, [view()])
    assert [r.step_id for r in results] == ["a1-1", "a1-2"]
    firsts = [r.value[0]["value"] for r in results]
    assert firsts == [192507.0, 260562.0]                                           # 2021: 혼인건수 · 출생아수


def test_answer_same_item_is_still_merged_while_other_item_is_split():
    """같은 항목은 예전처럼 조건을 합치고(a=2024, b=2021), 다른 항목만 따로 단계가 된다"""
    cp, _ = plan([], {"answers": [{"op": "raw", "operands": [
        pick("혼인건수(건)", select={**NATION, "시점": ["2024"]}), pick("출생아수(명)"),
        pick("혼인건수(건)", select={**NATION, "시점": ["2021"]})]}]})
    first, second = cp.answer_steps
    assert (first.step_id, first.operands[0].item, first.operands[0].select["시점"]) == ("a1-1", "혼인건수(건)", ["2024", "2021"])
    assert (second.step_id, second.operands[0].item) == ("a1-2", "출생아수(명)")


def test_answer_single_step_keeps_plain_id_and_numbering_follows_hcx_answers():
    """쪼개지지 않은 단계는 예전과 같은 a{n}. 번호 n 은 HCX 가 낸 답변 순서라 쪼개도 뒤쪽 ID 가 밀리지 않는다"""
    cp, _ = plan([], {"answers": [
        {"op": "raw", "operands": [pick("혼인건수(건)"), pick("출생아수(명)")]},
        {"op": "raw", "operands": [pick("조혼인율(천명당)")]}]})
    assert [s.step_id for s in cp.answer_steps] == ["a1-1", "a1-2", "a2"]


def test_answer_multi_operand_ops_are_not_split():
    """diff 는 두 항목을 한 단계에서 쓰는 연산이라 쪼개지 않는다"""
    cp, _ = plan([], {"answers": [{"op": "diff", "join_on": ["시점"], "operands": [
        pick("혼인건수(건)", "a", {**NATION, "시점": ["2025"]}), pick("출생아수(명)", "b", {**NATION, "시점": ["2025"]})]}]})
    (step,) = cp.answer_steps
    assert step.step_id == "a1" and [o.item for o in step.operands] == ["혼인건수(건)", "출생아수(명)"]


def test_chart_branches_are_unchanged_by_answer_split():
    """차트 쪽 규칙(항목이 다르면 갈래)은 건드리지 않았다"""
    sel = {**NATION, "시점": YEARS}
    cp, _ = plan([chart()], {"charts": [{"chart_id": "c1", "operands": [pick("혼인건수(건)", select=sel),
                                                                        pick("출생아수(명)", select=sel)]}]})
    assert [s.step_id for s in cp.plans[0].steps] == ["s1", "s2"]


def test_merge_drops_condition_missing_in_one_part():
    """한쪽에 시점 조건이 없으면 그쪽은 전체 시점을 쓴 것 → 합친 조건에서도 시점을 뺀다"""
    cp, _ = plan([], {"answers": [{"op": "raw", "operands": [
        pick("혼인건수(건)", select={**NATION, "시점": ["2024"]}), pick("혼인건수(건)")]}]})
    assert cp.answer_steps[0].operands[0].select == NATION


def test_line_chart_keeps_different_items_as_branches():
    """차트는 항목이 다르면 합치지 않는다 (갈래로 남긴다)"""
    sel = {**NATION, "시점": YEARS}
    cp, _ = plan([chart()], {"charts": [{"chart_id": "c1", "operands": [pick("혼인건수(건)", select=sel),
                                                                        pick("출생아수(명)", select=sel)]}]})
    assert len(cp.plans[0].steps) == 2


def test_chart_period_fill_applies_to_plan_select():
    """차트 계획의 select 에도 같은 규칙: cagr 는 from·to 시점을 보태고, change 는 시점마다 직전 대비"""
    cp, _ = plan([chart(measure="cagr")], {"charts": [{"chart_id": "c1", "record_id": VID, "from": "2021", "to": "2025",
                                                       "select": {**NATION, "항목": ["혼인건수(건)"], "시점": ["2025"]}}]})
    assert cp.plans[0].select["시점"] == ["2025", "2021"]
    cp, _ = plan([chart(measure="change")], {"charts": [{"chart_id": "c1", "record_id": VID, "from": "2021", "to": "2025",
                                                         "select": {**NATION, "항목": ["혼인건수(건)"], "시점": ["2025"]}}]})
    assert "시점" not in cp.plans[0].select and cp.plans[0].steps[0].base == "prev"


# ── 고정 조건 (QueryBundle 필터의 시점·지역) ──────────────────────
from backend.schemas.query import QueryBundle   # noqa: E402

LAST_YEAR = QueryBundle(query_id="q", original="작년 혼인건수는?", rewritten="2025년 전국 혼인건수",
                        filters={"시점": [2025], "대상": ["혼인"], "지표": ["혼인건수"]})


def fixed_plan(charts, decision, bundle=LAST_YEAR):
    return make_plan(charts, [view()], Decision.model_validate(decision), bundle)


def test_last_year_fixed_even_if_hcx_picks_other_year():
    """'작년' → 재작성 2025. HCX 가 스스로 2024 로 해석해도 고정 시점 2025 로 바뀐다 (2026-11-11 사용자 보고)"""
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [
        pick("혼인건수(건)", select={**NATION, "시점": ["2024"]})]}]})
    assert cp.answer_steps[0].operands[0].select == {**NATION, "시점": ["2025"]}
    assert cp.notes == ["q-1: 시점 ['2024'] 은 고정 시점 ['2025'] 밖 → ['2025']"]
    (r,) = run_answer_steps(cp.answer_steps, [view()])
    assert r.value == 240326.0


def test_fixed_years_subset_is_kept_for_non_growth_ops():
    bundle = QueryBundle(query_id="q", original="q", filters={"시점": YEARS})
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [
        pick("혼인건수(건)", select={**NATION, "시점": ["2021", "2025"]})]}]}, bundle)
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2021", "2025"] and cp.notes == []


def test_growth_uses_all_fixed_years():
    """증감률을 2021·2025 두 시점으로 골라도 고정 시점(2021~2025) 전체에서 시점마다 직전 대비"""
    bundle = QueryBundle(query_id="q", original="q", filters={"시점": YEARS})
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "growth_rate", "from": "2021", "to": "2025",
                                         "operands": [pick("혼인건수(건)", select={**NATION, "시점": ["2021", "2025"]})]}]}, bundle)
    step = cp.answer_steps[0]
    assert (step.base, step.from_, step.operands[0].select["시점"]) == ("prev", None, YEARS)
    assert cp.notes == ["q-1: growth_rate: 시점마다 직전 시점 대비로 계산 (고정 시점 2021~2025)"]
    (r,) = run_answer_steps(cp.answer_steps, [view()])
    assert [v["key"]["시점"] for v in r.value] == ["2022", "2023", "2024", "2025"]


def test_two_points_in_view_give_one_growth():
    """View 에 시점이 둘이면 결과도 하나 ('2021년 대비 2025년' 처럼 시점 필터가 둘일 때)"""
    bundle = QueryBundle(query_id="q", original="q", filters={"시점": [2021, 2025]})
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "growth_rate", "operands": [pick("혼인건수(건)")]}]},
                       bundle)
    (r,) = run_answer_steps(cp.answer_steps, [view()])
    assert r.value == pytest.approx(24.84013568337775)    # 결과가 하나면 숫자 하나 (CalcResult.value 규칙)


def test_cagr_uses_first_and_last_fixed_year():
    bundle = QueryBundle(query_id="q", original="q", filters={"시점": YEARS})
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "cagr", "operands": [pick("혼인건수(건)")]}]}, bundle)
    step = cp.answer_steps[0]
    assert (step.from_, step.to, step.base) == ("2021", "2025", None)


REGIONS = QueryBundle(query_id="q", original="서울과 부산 혼인건수 차이", filters={"지역": ["서울특별시", "부산광역시"]})


def regions_view():
    rows = [["2025", r, "혼인건수(건)", v] for r, v in [("서울특별시", 3.0), ("부산광역시", 1.0), ("대구광역시", 0.5)]]
    return view(rows, ["시점", "행정구역별", "항목", "값"])


def test_fixed_region_subset_kept_and_outside_replaced():
    cp, _ = make_plan([], [regions_view()], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "diff", "join_on": ["시점"], "operands": [
            pick("혼인건수(건)", "a", {"행정구역별": ["서울특별시"]}), pick("혼인건수(건)", "b", {"행정구역별": ["부산광역시"]})]},
        {"sub_question_id": "q-1", "op": "raw", "operands": [pick("혼인건수(건)", select={"행정구역별": ["대구광역시"]})]}]}),
        REGIONS)
    a, b = cp.answer_steps[0].operands
    assert (a.select, b.select) == ({"행정구역별": ["서울특별시"]}, {"행정구역별": ["부산광역시"]})   # 일부만 고른 것은 그대로
    assert cp.answer_steps[1].operands[0].select == {"행정구역별": ["서울특별시", "부산광역시"]}
    assert cp.notes == ["q-1: 행정구역별 ['대구광역시'] 은 고정 지역 ['서울특별시', '부산광역시'] 밖 → ['서울특별시', '부산광역시']"]


def test_fixed_region_not_in_view_is_ignored():
    """재작성이 지역 칸에 지역이 아닌 말('혼인건수')을 넣어도 HCX 가 고른 지역을 망치지 않는다 (2026-11-11 실제 사례)"""
    bundle = QueryBundle(query_id="q", original="2021~2025년 혼인건수 증감률", filters={"지역": ["혼인건수"]})
    cp, _ = make_plan([], [regions_view()], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [pick("혼인건수(건)", select={"행정구역별": ["서울특별시"]})]}]}),
        bundle)
    assert cp.answer_steps[0].operands[0].select == {"행정구역별": ["서울특별시"]}
    assert cp.notes == ["q-1: 고정 지역 ['혼인건수'] 이 행정구역별 에 없음 → 지역은 고정하지 않음"]


def test_share_denominator_is_not_fixed():
    """'전국 대비 서울' 의 분모 '전국' 은 지역 필터(서울) 밖이지만 그대로 둔다"""
    bundle = QueryBundle(query_id="q", original="전국 대비 서울 혼인건수 비중", filters={"지역": ["서울특별시"]})
    den = {"scope": "question", "operand": {"record_id": VID, "item": "혼인건수(건)", "select": {"행정구역별": ["전국"]}}}
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "share", "denominator": den, "operands": [
        pick("혼인건수(건)", "part", {"행정구역별": ["서울특별시"]})]}]}, bundle)
    assert cp.answer_steps[0].denominator.operand.select == {"행정구역별": ["전국"]}


def test_no_region_filter_means_not_fixed():
    """지역 필터가 없으면(= 전국 또는 '시도별' 비교) 고정하지 않는다"""
    cp, _ = fixed_plan([], {"answers": [{"sub_question_id": "q-1", "op": "rank", "operands": [
        pick("혼인건수(건)", select={"행정구역별": ["서울특별시", "전국"]})]}]})
    assert cp.answer_steps[0].operands[0].select["행정구역별"] == ["서울특별시", "전국"]


# ── 연령 범위의 값 하나 = 합계 (미취학아동수) ─────────────────────
AGES = ["0세", "1세", "2세", "3세", "4세", "5세"]
PRESCHOOL_2025 = [259973, 241691, 238977, 256417, 270071, 284355]    # 2026-11-11 실제 View (DT_1IN1503, 전국)
AGE_COLS = ["시점", "행정구역별(읍면동)", "연령별", "항목", "값"]
AID = "view::101_DT_1IN1503::Y::q-1::value"


def ages_view(years=("2025",), extra_rows=()):
    rows = [[y, "전국", a, "총인구(명)", float(v + i * 1000)] for i, y in enumerate(years) for a, v in zip(AGES, PRESCHOOL_2025)]
    rows += [[y, "전국", a, "총인구_성비", 105.0] for y in years for a in AGES] + list(extra_rows)
    return view(rows, AGE_COLS, rid=AID)


def preschool(intent="값 조회", years=(2025,)):
    return QueryBundle(query_id="q", original="작년 미취학아동수는?", rewritten="2025년 전국 영유아 인구수",
                       filters={"시점": list(years), "대상": ["인구"], "연령": {"from": 0, "to": 5}, "의도": intent})


def age_pick(ages=AGES):
    return {"record_id": AID, "item": "총인구(명)", "select": {"행정구역별(읍면동)": ["전국"], "연령별": list(ages)}}


def test_preschool_raw_becomes_sum():
    """HCX 가 raw 로 0~5세 나이별 값 6개를 골라도, 연령 범위의 값 하나를 묻는 질문이면 합계 하나"""
    rec = ages_view()
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [age_pick()]}]}), preschool())
    step = cp.answer_steps[0]
    assert (step.op, step.agg, step.model_extra.get("by")) == ("aggregate", "sum", ["시점"])
    assert cp.notes == ["q-1: raw → aggregate(sum): 연령 0~5세 범위의 값 하나를 묻는 질문"]
    (r,) = run_answer_steps(cp.answer_steps, [rec])
    assert (r.value, r.unit) == (sum(PRESCHOOL_2025), "명") and len(r.inputs) == 6
    assert sum(PRESCHOOL_2025) == 1_551_484


def test_comparison_by_age_stays_per_age():
    """'나이별 비교' 처럼 범주끼리 견주는 질문은 합치지 않는다"""
    cp, _ = make_plan([], [ages_view()], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [age_pick()]}]}), preschool("비교"))
    assert cp.answer_steps[0].op == "raw" and cp.notes == []


def test_total_row_mixed_in_is_not_summed():
    """'계' 행이 섞이면 더할 때 두 번 센다 → 바꾸지 않고 사유를 남긴다"""
    rec = ages_view(extra_rows=[["2025", "전국", "계", "총인구(명)", 9.0]])
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [age_pick(AGES + ["계"])]}]}), preschool())
    assert cp.answer_steps[0].op == "raw" and cp.notes == ["q-1: 연령별 에 합계 행이 섞여 있어 합치지 않음 (['계'])"]


def test_sum_is_per_year():
    """여러 해면 해마다 따로 합친다 (최근 2년 미취학아동수 → 2개)"""
    rec = ages_view(("2024", "2025"))
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [age_pick()]}]}), preschool("추이", (2024, 2025)))
    (r,) = run_answer_steps(cp.answer_steps, [rec])
    assert [(v["key"], v["value"]) for v in r.value] == [({"시점": "2024"}, sum(PRESCHOOL_2025)),
                                                         ({"시점": "2025"}, sum(PRESCHOOL_2025) + 6000)]


def test_hcx_aggregate_gets_by_time():
    """HCX 가 처음부터 aggregate 를 골라도 시점마다 합친다 (스키마에 by 가 없어 여러 해를 한데 더하던 문제)"""
    rec = ages_view(("2024", "2025"))
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "aggregate", "agg": "sum", "operands": [age_pick()]}]}), preschool("추이", (2024, 2025)))
    assert cp.answer_steps[0].model_extra.get("by") == ["시점"]
    (r,) = run_answer_steps(cp.answer_steps, [rec])
    assert len(r.value) == 2


def test_chart_of_age_range_is_sum_per_year():
    """'최근 2년 미취학아동수' — 차트도 나이별 6개 선이 아니라 해마다 합계 하나 (2026-11-11 사용자 보고)"""
    rec = ages_view(("2024", "2025"))
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="raw",
                           requirements=["time_axis_required", "min_points_3"], fallback_chart="bar")]
    decision = Decision.model_validate({"charts": [{"chart_id": "c1", "record_id": AID, "select": {
        "행정구역별(읍면동)": ["전국"], "연령별": AGES, "항목": ["총인구(명)"]}}]})
    cp, displays = make_plan(charts, [rec], decision, preschool("추이", (2024, 2025)))
    (step,) = cp.plans[0].steps
    assert (step.op, step.agg, step.model_extra.get("by")) == ("aggregate", "sum", ["시점"])
    assert "c1: 차트 raw → aggregate(sum): 연령 0~5세 범위의 값 하나를 묻는 질문" in cp.notes
    contents, validation = build_charts(cp, [rec], {"c1": charts[0].requirements}, displays)
    (c1,) = contents
    assert [(r[0], r[-1]) for r in c1.rows] == [("2024", sum(PRESCHOOL_2025)), ("2025", sum(PRESCHOOL_2025) + 6000)]
    assert validation["c1"].original.failed == ["min_points_3"] and c1.chart_type == "bar"   # 점 2개 → 막대로 대체


def test_sum_refused_when_other_column_mixes_items():
    """차트가 '항목' 을 안 고르면 총인구와 성비가 섞인다 → 더하지 않고 사유를 남긴다"""
    rec = ages_view(("2024", "2025"))
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="raw")]
    decision = Decision.model_validate({"charts": [{"chart_id": "c1", "record_id": AID, "select": {
        "행정구역별(읍면동)": ["전국"], "연령별": AGES}}]})
    cp, _ = make_plan(charts, [rec], decision, preschool("추이", (2024, 2025)))
    assert cp.plans[0].steps[0].op == "raw"
    assert cp.notes == ["c1: 항목 에 값이 여럿이라 연령 합계를 내지 않음 ({'항목': ['총인구(명)', '총인구_성비']})"]


# ── HCX 가 쓰는 차트 제목 ─────────────────────────────────────────
from backend.agent.chart_calculate.planner import clean_title   # noqa: E402


@pytest.mark.parametrize("title, want", [
    ("2024~2025년 미취학아동(0~5세) 수", "2024~2025년 미취학아동(0~5세) 수"),
    ("  최근 5년  혼인건수 추이 ", "최근 5년 혼인건수 추이"),               # 공백 정리
    ("65세 이상 고령인구비율 순위", "65세 이상 고령인구비율 순위"),
    ("", None), (None, None),
])
def test_clean_title_keeps_question_words(title, want):
    assert clean_title(title) == (want, None)


@pytest.mark.parametrize("title, why", [
    ("미취학아동 1,551,484명", "숫자"),            # 계산 값이 제목에 들어가면 안 된다
    ("혼인건수 24.8% 증가", "숫자"),
    ("가" * 41, "40자"),
])
def test_clean_title_rejects_values_and_long(title, why):
    t, reason = clean_title(title)
    assert t is None and why in reason


def test_hcx_title_used_for_chart_even_after_fallback_and_sum():
    """HCX 제목은 질문 기준이라 꺾은선 → 막대 대체, 나이별 → 합계로 바뀌어도 그대로 쓴다"""
    rec = ages_view(("2024", "2025"))
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="raw",
                           requirements=["time_axis_required", "min_points_3"], fallback_chart="bar")]
    decision = Decision.model_validate({"charts": [{"chart_id": "c1", "title": "최근 2년 미취학아동(0~5세) 수",
                                                    "record_id": AID, "select": {"행정구역별(읍면동)": ["전국"], "연령별": AGES,
                                                                                 "항목": ["총인구(명)"]}}]})
    cp, displays = make_plan(charts, [rec], decision, preschool("추이", (2024, 2025)))
    (c1,), _ = build_charts(cp, [rec], {"c1": charts[0].requirements}, displays)
    assert (c1.chart_type, c1.title) == ("bar", "최근 2년 미취학아동(0~5세) 수")


def test_bad_hcx_title_falls_back_to_rule_title():
    decision = Decision.model_validate({"charts": [{"chart_id": "c1", "title": "혼인건수 240,326건", "record_id": VID,
                                                    "select": {**NATION, "항목": ["혼인건수(건)"], "시점": YEARS}}]})
    cp, displays = make_plan([chart()], [view()], decision)
    assert cp.plans[0].title is None
    assert "c1: HCX 제목 '혼인건수 240,326건' 버림 (제목에 연도·나이가 아닌 숫자 ['240,326']) → 규칙 제목" in cp.notes
    (c1,), _ = build_charts(cp, [view()], displays=displays)
    assert c1.title == "2021~2025 혼인건수 연도별 추이"


from backend.agent.chart_calculate.planner import age_span   # noqa: E402


@pytest.mark.parametrize("label, want", [("0세", (0, 0)), ("15~19세", (15, 19)), ("65-69세", (65, 69)),
                                         ("65세 이상", (65, None)), ("계", None), ("합계", None)])
def test_age_span(label, want):
    assert age_span(label) == want


def test_age_widen_open_range_and_leave_totals():
    """'65세 이상' 범위: 일부만 고르면 범위 전체로. '계' 를 고른 것은 건드리지 않는다"""
    rows = [["2025", "전국", a, "인구수(명)", 1.0] for a in ["계", "60-64세", "65-69세", "70-74세", "75세 이상"]]
    rec = view(rows, ["시점", "행정구역별", "연령별", "항목", "값"], rid="view::t::Y::q-1::value")
    bundle = QueryBundle(query_id="q", original="고령인구", filters={"연령": {"from": 65}})
    pick_ = lambda ages: {"record_id": rec.id, "item": "인구수(명)", "select": {"연령별": ages}}  # noqa: E731
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [pick_(["65-69세"])]},
        {"sub_question_id": "q-1", "op": "extreme", "operands": [pick_(["계"])]}]}), bundle)
    assert cp.answer_steps[0].operands[0].select["연령별"] == ["65-69세", "70-74세", "75세 이상"]
    assert cp.answer_steps[1].operands[0].select["연령별"] == ["계"]


def test_combine_keeps_terms_and_signs():
    """combine 은 같은 항목이어도 합치지 않고, 부호를 피연산자에 싣는다"""
    cp, displays = plan([], {"answers": [{"op": "combine", "operands": [
        {**pick("출생아수(명)"), "sign": "+"}, {**pick("혼인건수(건)"), "sign": "-"}]}]})
    ops = cp.answer_steps[0].operands
    assert [(o.role, o.item, o.sign) for o in ops] == [("term", "출생아수(명)", "+"), ("term", "혼인건수(건)", "-")]
    assert "a1: combine 피연산자의 단위가 다름: ['명', '건'] (계산하지 않음)" in cp.notes
    one, _ = plan([], {"answers": [{"op": "combine", "operands": [pick("출생아수(명)")]}]})
    assert "a1: combine 은 피연산자 2개 이상이 필요 (받은 것 1개)" in one.notes


def test_item_bracket_unit_wins_over_hcx_unit():
    """항목 이름에 괄호 단위가 있으면 HCX 단위보다 그것을 쓴다"""
    cp, _ = plan([], {"answers": [{"op": "raw", "operands": [{**pick("혼인건수(건)"), "unit": "명"}]}]})
    assert cp.answer_steps[0].operands[0].unit == "건"


# ── GPT 검토 (2026-11-11) D. HCX 단위 승인 기준 ──────────────────
@pytest.mark.parametrize("unit, listed, want", [
    ("명", "명 가임여자 1명당 명", "명"),                       # 표준 단위 + 목록 안의 한 단어
    ("1명당", "명 가임여자 1명당 명", None),                    # 부분 문자열 (예전에는 승인)
    ("가임여자", "명 가임여자 1명당 명", None),
    ("가임여자 1명당 명", "명 가임여자 1명당 명", None),        # 목록 전체가 아니고 표준 단위도 아님 → 확인 불가
    ("가임여자 1명당 명", "가임여자 1명당 명", "가임여자 1명당 명"),   # 단위가 하나뿐인 표는 목록 전체와 같으면 승인
    ("건", "명 가임여자 1명당 명", None),                       # 목록에 없음
    ("명", "", None),
])
def test_hcx_unit_acceptance(unit, listed, want):
    rec = view([["2024", "전국", "출생아수", 1.0]], ["시점", "행정구역별", "항목", "값"], rid="view::u", unit=listed)
    cp, _ = make_plan([], [rec], Decision.model_validate({"answers": [
        {"op": "raw", "operands": [{"record_id": "view::u", "item": "출생아수", "select": {}, "unit": unit}]}]}))
    assert cp.answer_steps[0].operands[0].unit == want
    if want is None and listed:
        assert any("확인되지 않음" in n for n in cp.notes)
