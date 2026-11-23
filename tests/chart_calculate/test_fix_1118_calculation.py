"""[NEW 11-18] F5 · F6 — 계산 회귀 테스트 (계획서 모듈3_모듈6_F1-F16_수정_계획.md 2장)

  F5  비중의 분모가 부분과 같은 행이면 100.0% 가 되던 것: 요청한 분모와 실제 분모가 다를 때만 막는다  (Q05 · Q28)
  F6  나이가 항목 열 값일 때 질문의 연령 범위를 합산하고, 빈틈 · 겹침 · 총계가 있으면 합계라고 답하지 않는다 (Q11)
"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.schemas.chart import Step
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view


# ── F5 ───────────────────────────────────────────────────────────
def share(rec, basis, part_sel):
    st = Step.model_validate({"step_id": "a1", "op": "share", "operands": [
        {"role": "part", "record_id": VID, "item": "출생아수", "select": part_sel}],
        "denominator": {"scope": "question", "basis": basis, "label": f"{basis} 대비",
                        "operand": {"record_id": VID, "item": "출생아수", "select": {"시점": ["2024"]}}}})
    return run_answer_steps([st], [rec])[0]


COLS = ["시점", "시군구별", "항목", "값"]


def test_share_is_withheld_when_the_denominator_row_is_the_same_row_as_the_part():
    rec = view([["2024", "서울특별시", "출생아수", 41605.0]], COLS)         # 전국 행이 View 에 없다
    r = share(rec, "전국", {"시점": ["2024"], "시군구별": ["서울특별시"]})
    assert r.value is None and r.note and "100%" in r.note


def test_share_of_the_national_total_over_itself_is_still_100():
    rec = view([["2024", "전국", "출생아수", 238317.0]], COLS)
    r = share(rec, "전국", {"시점": ["2024"], "시군구별": ["전국"]})
    assert r.value == pytest.approx(100.0) and r.note is None


def test_share_with_a_real_national_denominator_is_computed():
    rec = view([["2024", "전국", "출생아수", 238317.0], ["2024", "서울특별시", "출생아수", 41605.0]], COLS)
    st = Step.model_validate({"step_id": "a1", "op": "share", "operands": [
        {"role": "part", "record_id": VID, "item": "출생아수", "select": {"시점": ["2024"], "시군구별": ["서울특별시"]}}],
        "denominator": {"scope": "question", "basis": "전국", "operand": {
            "record_id": VID, "item": "출생아수", "select": {"시점": ["2024"], "시군구별": ["전국"]}}}})
    assert run_answer_steps([st], [rec])[0].value == pytest.approx(41605 / 238317 * 100)


# ── F6 ───────────────────────────────────────────────────────────
AGE_COLS = ["시점", "행정구역별(시도)", "항목", "값"]
AGES = {"0세": 233617.0, "1세": 231792.0, "2세": 249711.0, "3세": 263446.0, "4세": 277043.0, "5세": 302387.0}


def age_view(ages=None, extra=None):
    rows = [["2024", "전국", k, v] for k, v in (AGES if ages is None else ages).items()] + (extra or [])
    return view(rows, AGE_COLS)


def age_plan(rec, item="0세"):
    b = QueryBundle(query_id="q", original="2024년 미취학아동 수는?", sub_questions=["2024년 미취학아동 수"],
                    sub_filters=[{"시점": [2024], "연령": {"from": 0, "to": 5}, "의도": "값 조회"}])
    dec = {"answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [
        {"record_id": VID, "item": item, "select": {"시점": ["2024"], "행정구역별(시도)": ["전국"]}}]}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    return cp, run_answer_steps(cp.answer_steps, [rec])


def test_age_range_is_summed_when_ages_are_item_values_even_if_hcx_picked_only_age_0():
    cp, res = age_plan(age_view())
    assert cp.answer_steps[0].op == "aggregate" and res[0].value == pytest.approx(1557996.0)


def test_total_row_in_the_item_column_is_not_added():
    cp, res = age_plan(age_view(extra=[["2024", "전국", "계", 9999999.0]]))
    assert res[0].value == pytest.approx(1557996.0)


def test_missing_age_inside_the_range_withholds_the_sum():
    ages = {k: v for k, v in AGES.items() if k != "3세"}
    cp, _ = age_plan(age_view(ages))
    assert cp.answer_steps == [] and cp.warnings and "0~5세" in cp.warnings[0]


def test_overlapping_age_groups_withhold_the_sum():
    cp, _ = age_plan(age_view({"0~5세": 1500000.0, "0~4세": 1200000.0, "5세": 300000.0}), item="0~5세")
    assert cp.answer_steps == [] and cp.warnings


def test_ages_outside_the_asked_range_are_left_alone():
    cp, res = age_plan(age_view({**AGES, "6세": 111.0}), item="6세")      # 6세는 질문의 범위 밖이라 합계로 바꾸지 않는다
    assert cp.answer_steps[0].op == "raw" and res[0].value == 111.0


# ── F9 · F10 ─────────────────────────────────────────────────────
def test_f9_indicator_names_that_contain_an_operation_word_keep_their_title():
    from backend.agent.chart_calculate.planner import clean_title
    assert clean_title("합계출산율 추이", "raw")[0] == "합계출산율 추이"
    assert clean_title("평균연령 변화", "raw")[0] == "평균연령 변화"
    assert clean_title("합계 추이", "raw")[0] is None                     # 진짜 합계 연산 이름은 계속 걸린다


def test_f10_rank_over_categories_in_one_asked_year_does_not_blame_the_years():
    rec = view([["2024", "계", "외국인_계", 371577.0]], ["시점", "국적별", "항목", "값"])
    st = Step.model_validate({"step_id": "a1", "op": "rank", "operands": [
        {"role": "value", "record_id": VID, "item": "외국인_계", "select": {"시점": ["2024"]}}]})
    note = run_answer_steps([st], [rec])[0].note
    assert note and "한 해뿐" not in note


def test_f10_time_comparison_with_one_year_still_says_so():
    rec = view([["2025", "전국", "사망자수(명)", 362968.0]], ["시점", "행정구역별", "항목", "값"])
    st = Step.model_validate({"step_id": "a1", "op": "extreme", "operands": [
        {"role": "value", "record_id": VID, "item": "사망자수(명)", "select": {}}]})
    assert "한 해뿐" in run_answer_steps([st], [rec])[0].note


# ── F11 ──────────────────────────────────────────────────────────
def population_view():
    rows = [["2025", "서울특별시", "인구(천명)", 9340.0], ["2025", "서울특별시", "조출생률(인구천명당)", 3.8],
            ["2025", "서울특별시", "조사망률(인구천명당)", 5.7], ["2025", "서울특별시", "순이동률(인구천명당)", -3.8]]
    return view(rows, ["시점", "행정구역별", "항목", "값"])


def chart_and_answer(rec, chart_item=None):
    from backend.schemas.chart import ChartRequest
    b = QueryBundle(query_id="q", original="2025년 서울 인구는?", sub_questions=["2025년 서울 인구"], sub_filters=[{"시점": [2025]}])
    sel = {"시점": ["2025"], "행정구역별": ["서울특별시"], **({"항목": [chart_item]} if chart_item else {})}
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": sel}],
           "answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [
               {"record_id": VID, "item": "인구(천명)", "select": {"시점": ["2025"], "행정구역별": ["서울특별시"]}}]}]}
    ch = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="bar", measure="raw", view_ids=[VID])]
    cp, _ = make_plan(ch, [rec], Decision.model_validate(dec), b)
    return cp


def test_f11_value_lookup_chart_draws_only_the_item_the_question_asked_for():
    cp = chart_and_answer(population_view())
    assert cp.plans[0].select["항목"] == ["인구(천명)"]


def test_f11_chart_that_already_chose_its_items_is_left_alone():
    cp = chart_and_answer(population_view(), chart_item="조출생률(인구천명당)")
    assert cp.plans[0].select["항목"] == ["조출생률(인구천명당)"]


def test_f11_chart_is_not_narrowed_when_two_sub_questions_use_different_items():
    from backend.schemas.chart import ChartRequest
    rec = population_view()
    b = QueryBundle(query_id="q", original="인구와 출생률", sub_questions=["인구", "출생률"],
                    sub_filters=[{"시점": [2025]}, {"시점": [2025]}])
    ops = lambda it: [{"record_id": VID, "item": it, "select": {"시점": ["2025"], "행정구역별": ["서울특별시"]}}]  # noqa: E731
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"시점": ["2025"], "행정구역별": ["서울특별시"]}}],
           "answers": [{"sub_question_id": "q-1", "op": "raw", "operands": ops("인구(천명)")},
                       {"sub_question_id": "q-2", "op": "raw", "operands": ops("조출생률(인구천명당)")}]}
    ch = [ChartRequest(chart_id="c1", sub_question_ids=["q-1", "q-2"], chart_type="bar", measure="raw", view_ids=[VID])]
    cp, _ = make_plan(ch, [rec], Decision.model_validate(dec), b)
    assert "항목" not in cp.plans[0].select


# ── [검토 4·5] 분모의 여분 연도 · 직접 집계 ────────────────────────
def test_share_with_extra_years_in_the_denominator_is_still_withheld_when_the_row_is_the_part_itself():
    rec = view([["2024", "서울특별시", "출생아수", 41605.0], ["2023", "서울특별시", "출생아수", 40000.0]], COLS)
    r = share(rec, "전국", {"시점": ["2024"], "시군구별": ["서울특별시"]})          # 분모 조건은 시점 없이 전체 연도 → 2024 가 같은 서울 행
    assert r.value is None and r.note and "100%" in r.note


def aggregate(rows, items):
    st = Step.model_validate({"step_id": "a1", "op": "aggregate", "agg": "sum", "by": ["시점"], "operands": [
        {"role": "value", "record_id": VID, "select": {"시점": ["2024"], "항목": items}}]})
    return run_answer_steps([st], [view(rows, AGE_COLS)])[0]


def test_direct_aggregate_rejects_overlapping_age_groups():
    rows = [["2024", "전국", "0~5세", 1500000.0], ["2024", "전국", "0~4세", 1200000.0], ["2024", "전국", "5세", 300000.0]]
    r = aggregate(rows, ["0~5세", "0~4세", "5세"])
    assert r.value is None and "겹" in r.note


def test_direct_aggregate_rejects_duplicate_rows_of_the_same_coordinate():
    rows = [["2024", "전국", "0세", 233617.0], ["2024", "전국", "0세", 233617.0], ["2024", "전국", "1세", 231792.0]]
    r = aggregate(rows, ["0세", "1세"])
    assert r.value is None and "같은 좌표" in r.note


def test_direct_aggregate_of_adjacent_age_groups_is_still_computed():
    rows = [["2024", "전국", "0~4세", 1200000.0], ["2024", "전국", "5~9세", 1300000.0]]
    assert aggregate(rows, ["0~4세", "5~9세"]).value == 2500000.0


# ── [검토 6·9] F11 표시 설정 재확정 · F3 명시 자릿수 ──────────────────
def test_f11_display_of_the_narrowed_chart_is_the_same_as_the_answers():
    from backend.agent.chart_calculate.display import format_value
    from backend.schemas.chart import ChartRequest
    rec = population_view()
    b = QueryBundle(query_id="q", original="2025년 서울 인구는?", sub_questions=["2025년 서울 인구"], sub_filters=[{"시점": [2025]}])
    sel = {"시점": ["2025"], "행정구역별": ["서울특별시"]}
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": sel}],
           "answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [{"record_id": VID, "item": "인구(천명)", "select": sel}]}]}
    ch = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="bar", measure="raw", view_ids=[VID])]
    cp, displays = make_plan(ch, [rec], Decision.model_validate(dec), b)
    chart_ref, answer_ref = cp.plans[0].steps[0].display_ref, cp.answer_steps[0].display_ref
    assert format_value(9340.0, displays[chart_ref]) == format_value(9340.0, displays[answer_ref]) == "934만 명"


def test_f3_explicit_digits_or_units_keep_the_source_unit_and_only_unset_cheon_myeong_is_converted():
    from backend.agent.chart_calculate.display import format_value, make_display
    assert format_value(9340.0, make_display("천명", digits=2)) == "9,340.00천명"          # 명시 자릿수는 보존
    assert format_value(9340.0, make_display("천명", "천명", 1, 0)) == "9,340천명"
    assert format_value(9340.0, make_display("천명")) == "934만 명"
    assert format_value(9340.0, make_display("천명", auto_digits=0)) == "934만 명"          # 코드가 구한 자동 자릿수는 환산에 맞지 않아 쓰지 않는다
