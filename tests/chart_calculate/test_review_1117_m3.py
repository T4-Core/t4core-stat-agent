"""[NEW 11-17] 자체 검토 보고서(모듈3_모듈6_수정_자체검토_보고서.md) 모듈 3 항목의 회귀 테스트. 항목 번호는 보고서의 A-N"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.display import format_value, make_display
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.schemas.chart import Step
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

COLS = ["시점", "행정구역별", "항목", "값"]
NAT = {"행정구역별": ["전국"]}
# View 모듈(build_view.match_period)이 시점을 명시한 요청에 남기는 메모. latest_shift 는 시점을 묻지 않은 최신값 조회에서만 생긴다
DEFAULT = {"slot": "시점", "type": "default", "requested": [2026], "applied": [2025], "text": "요청 시점이 모두 없어 최신 2025 사용"}
MISSING = {"slot": "시점", "type": "missing", "requested": [2026], "text": "시점 [2026] 은 이 표에 없음 (수록 2021~2025)"}

def bundle(years):
    return QueryBundle(query_id="q", original="질문", sub_questions=["하위 질문"], sub_filters=[{"시점": years}])


def answer(op, select, **kw):
    return {"answers": [{"sub_question_id": "q-1", "op": op, **kw,
                         "operands": [{"record_id": VID, "item": "혼인건수(건)", "select": select}]}]}


def solve(decision, records, b):
    cp, _ = make_plan([], records, Decision.model_validate(decision), b)
    return cp, run_answer_steps(cp.answer_steps, records)


# ── A-1 고정 시점이 View 에 없으면: View 가 대체를 기록한 경우에만 ─────────────
# [CHANGED 11-17 외부 피드백] 이전 테스트는 '2026 요청 + latest_shift' 라는 실제로 나오지 않는 조합이었고, 메모가 없어도 시점을 뺐다
def test_a1_view_default_note_lets_the_answer_use_the_substituted_year():
    rec = view([["2025", "전국", "혼인건수(건)", 240326.0]], notes=[DEFAULT])
    for select in (NAT, {**NAT, "시점": ["2025"]}):               # HCX 가 시점을 빼거나 대체 연도를 고른 경우
        cp, res = solve(answer("raw", select), [rec], bundle([2026]))
        assert res[0].value == 240326.0 and res[0].note is None
    assert any("고정 시점 ['2026'] 이 자료에 없음" in n for n in cp.notes)


def test_a1_without_a_view_note_the_fixed_year_is_kept_and_the_calculation_says_why():
    rec = view([["2025", "전국", "혼인건수(건)", 240326.0]])
    _, res = solve(answer("raw", NAT), [rec], bundle([2026]))
    assert res[0].value is None and "2026" in res[0].note


def test_a1_shortened_period_is_told_to_the_user():
    cp, res = solve(answer("growth_rate", NAT), [view(notes=[MISSING])], bundle([2021, 2022, 2023, 2024, 2025, 2026]))
    st = cp.answer_steps[0]
    assert (st.from_, st.to) == ("2021", "2025") and res[0].value == pytest.approx(24.84013568337775, rel=1e-12)
    assert "2026" not in st.operands[0].select["시점"]
    assert cp.warnings == ["2026년 자료가 없어 2021~2025년 자료로 계산했습니다."]


def test_a1_shortened_period_without_a_note_is_not_shortened():
    _, res = solve(answer("growth_rate", NAT), [view()], bundle([2021, 2022, 2023, 2024, 2025, 2026]))
    assert res[0].value is None and "2026" in res[0].note


def test_a1_fixed_year_present_in_the_view_is_still_enforced():
    _, res = solve(answer("raw", {**NAT, "시점": ["2021"]}), [view()], bundle([2025]))
    assert res[0].value == 240326.0                     # 고정 시점 밖의 2021 → 2025 (이전 동작 유지)


# ── A-2 순위 · 극값에서 지역 총계 ────────────────────────────────
NATION_MIX = [["2025", "전국", "인구수(명)", 5000.0], ["2025", "서울특별시", "인구수(명)", 900.0],
              ["2025", "부산광역시", "인구수(명)", 300.0]]


def run(d, rows=NATION_MIX):
    st = Step.model_validate({"step_id": "a1", **d, "operands": [{"role": "value", "record_id": VID, "item": "인구수(명)", "select": {}}]})
    return run_answer_steps([st], [view(rows, COLS)])[0]


def test_a2_rank_leaves_out_the_nation_total():
    r = run({"op": "rank"})
    assert [(p["key"]["행정구역별"], p["rank"]) for p in r.value] == [("서울특별시", 1), ("부산광역시", 2)]
    assert "총계 행 제외: 행정구역별 ['전국']" in r.note


def test_a2_extreme_leaves_out_the_nation_total_both_ways():
    assert run({"op": "extreme"}).value == [{"key": {"시점": "2025", "행정구역별": "서울특별시"}, "value": 900.0}]
    assert run({"op": "extreme", "kind": "min"}).value[0]["key"]["행정구역별"] == "부산광역시"


def test_a2_age_total_is_left_out_of_rank_too():
    cols = ["시점", "연령별", "항목", "값"]
    rows = [["2025", "계", "인구수(명)", 100.0], ["2025", "0세", "인구수(명)", 30.0], ["2025", "1세", "인구수(명)", 70.0]]
    st = Step.model_validate({"step_id": "a1", "op": "rank",
                              "operands": [{"role": "value", "record_id": VID, "item": "인구수(명)", "select": {}}]})
    r = run_answer_steps([st], [view(rows, cols)])[0]
    assert [p["key"]["연령별"] for p in r.value] == ["1세", "0세"]


def test_a2_nation_alone_or_over_time_is_untouched():
    only = run({"op": "extreme"}, [["2024", "전국", "인구수(명)", 10.0], ["2025", "전국", "인구수(명)", 12.0]])
    assert only.value == [{"key": {"시점": "2025"}, "value": 12.0}] and only.note is None


# [NEW 11-17 외부 피드백] 조건에 총계를 이름으로 적은 비교(전국 vs 서울)는 전국을 남긴다
def run_with(d, select, rows):
    st = Step.model_validate({"step_id": "a1", **d, "operands": [{"role": "value", "record_id": VID, "item": "인구수(명)", "select": select}]})
    return run_answer_steps([st], [view(rows, COLS)])[0]


def test_a2_total_named_in_the_condition_stays_in_the_comparison():
    rows = [["2025", "전국", "인구수(명)", 6000.0], ["2025", "서울특별시", "인구수(명)", 999.0]]
    r = run_with({"op": "extreme"}, {"행정구역별": ["전국", "서울특별시"]}, rows)
    assert r.value == [{"key": {"시점": "2025", "행정구역별": "전국"}, "value": 6000.0}] and r.note is None
    # 조건 없음 → 뺀다 (전국을 빼면 서울 하나뿐이라 [CHANGED 11-17 H2] 이제 비교하지 않는다)
    assert run_with({"op": "extreme"}, {}, rows).value is None
    assert run_with({"op": "extreme"}, {}, NATION_MIX).value[0]["key"]["행정구역별"] == "서울특별시"
    assert run_with({"op": "extreme"}, {"행정구역별": ["서울특별시", "부산광역시"]},
                    NATION_MIX).value[0]["key"]["행정구역별"] == "서울특별시"


def test_a2_known_limit_listing_every_region_including_nation_keeps_the_nation():
    """HCX 가 시도별 순위에 전국까지 나열하면 직접 고른 것으로 본다 (프롬프트로 막는다. 실제 HCX 확인 대상)"""
    r = run_with({"op": "rank"}, {"행정구역별": ["전국", "서울특별시", "부산광역시"]}, NATION_MIX)
    assert r.value[0]["key"]["행정구역별"] == "전국"


# ── 외부 피드백 결측 1: 다른 계열의 결측 행이 이 계열의 간격 판정에 끼어들지 않는다 ──────
def test_missing_row_of_a_region_with_no_values_does_not_wipe_another_regions_growth():
    rows = [[y, "서울특별시", "인구수(명)", 100.0 + int(y) - 2017] for y in ("2017", "2019", "2021", "2023")]
    rows.append(["2020", "부산광역시", "인구수(명)", None])         # 부산은 값 없는 행 하나뿐 → 지역 열이 고정 좌표(서울)가 된다
    r = run_with({"op": "growth_rate", "base": "prev"}, {}, rows)
    assert [round(p["value"], 2) for p in r.value] == [2.0, 1.96, 1.92]
    assert "일정하지 않음" not in (r.note or "")


# ── 외부 피드백 결측 2: 한 지역 값이 빈 시점의 합계 ─────────────────────
def _sum_rows():
    rows = [[y, reg, "인구수(명)", 100.0] for y in ("2022", "2023", "2024", "2025") for reg in ("서울특별시", "부산광역시")]
    rows[5][3] = None                                        # 2024 부산 (꺾은선은 값 있는 점이 3개 이상이어야 해서 4년)
    return rows


def test_per_period_sum_with_one_region_empty_is_left_empty_with_the_reason():
    r = run_with({"op": "aggregate", "agg": "sum", "by": ["시점"]}, {}, _sum_rows())
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [("2022", 200.0), ("2023", 200.0), ("2024", None), ("2025", 200.0)]
    assert "2024: 부산광역시 값이 없어 합계를 내지 않음" in r.note


def test_per_period_mean_follows_the_same_rule_and_complete_periods_are_unaffected():
    r = run_with({"op": "aggregate", "agg": "mean", "by": ["시점"]}, {}, _sum_rows())
    assert [p["value"] for p in r.value] == [100.0, 100.0, None, 100.0] and "평균을 내지 않음" in r.note


def test_sum_chart_breaks_the_line_at_the_incomplete_period():
    from backend.agent.chart_calculate.content import build_charts
    from backend.schemas.chart import ChartRequest
    v = view(_sum_rows(), COLS)
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {"항목": ["인구수(명)"]}}]}
    cp, displays = make_plan([ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="aggregate",
                                           fallback_chart="bar")], [v], Decision.model_validate(dec))
    st = cp.plans[0].steps[0]
    assert st.op == "aggregate"
    contents, _ = build_charts(cp, [v], displays=displays)
    rows = contents[0].rows
    assert contents[0].chart_type == "line"
    assert [(r[0], r[-1]) for r in rows] == [("2022", 200.0), ("2023", 200.0), ("2024", None), ("2025", 200.0)]
    assert "2024년은 부산광역시 값이 없어 합계를 내지 못했습니다" in contents[0].warnings


# ── 남은 한계 1 (A-2): 범주 비교 질문(비교축 · 순위 의도)이면 HCX 가 전국을 적어도 뺀다 ─────────
def rank_plan(op, filters, select):
    b = QueryBundle(query_id="q", original="질문", sub_questions=["하위 질문"], sub_filters=[filters])
    dec = {"answers": [{"sub_question_id": "q-1", "op": op,
                        "operands": [{"record_id": VID, "item": "인구수(명)", "select": select}]}]}
    rec = view(NATION_MIX, COLS)
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    return cp, run_answer_steps(cp.answer_steps, [rec])[0]


ALL = {"행정구역별": ["전국", "서울특별시", "부산광역시"]}


@pytest.mark.parametrize("filters", [{"비교축": "시도"}, {"의도": "순위"}])
def test_limit1_category_question_drops_the_nation_even_if_hcx_lists_it(filters):
    cp, r = rank_plan("rank", filters, ALL)
    assert [p["key"]["행정구역별"] for p in r.value] == ["서울특별시", "부산광역시"]
    assert "전국" not in cp.answer_steps[0].operands[0].select["행정구역별"]
    assert any("총계" in n and "전국" in n for n in cp.notes)


def test_limit1_direct_comparison_without_category_axis_keeps_the_nation():
    _, r = rank_plan("extreme", {"의도": "비교"}, {"행정구역별": ["전국", "서울특별시"]})
    assert r.value[0]["key"]["행정구역별"] == "전국"


def test_limit1_nation_alone_is_never_dropped():
    cp, _ = rank_plan("extreme", {"비교축": "시도"}, {"행정구역별": ["전국"]})
    assert cp.answer_steps[0].operands[0].select["행정구역별"] == ["전국"]       # 조건은 그대로 (값 하나라 비교는 H2 가 막는다)


# ── 남은 한계 2 (결측 2): 행이 없는 해는 부분합 + 명시, 값이 모두 빈 구성원은 합계를 내지 않는다 ─────
def test_limit2_year_without_a_row_keeps_the_partial_sum_and_says_so():
    from backend.core.reasons import humanize
    rows = [["2010", "서울특별시", "인구수(명)", 100.0], ["2011", "서울특별시", "인구수(명)", 100.0], ["2011", "세종특별자치시", "인구수(명)", 10.0],
            ["2012", "서울특별시", "인구수(명)", 100.0], ["2012", "세종특별자치시", "인구수(명)", 12.0]]
    r = run_with({"op": "aggregate", "agg": "sum", "by": ["시점"]}, {}, rows)
    assert [p["value"] for p in r.value] == [100.0, 110.0, 112.0]
    assert "2010: 세종특별자치시 행이 없어 나머지 1개 행정구역만 합계" in r.note
    assert humanize(r.note) == "2010년은 세종특별자치시 자료가 없어 1개 행정구역의 합계입니다"


def test_limit2_member_named_in_the_condition_with_no_values_at_all_blocks_the_sum():
    rows = [[y, reg, "인구수(명)", 100.0 if reg == "서울특별시" else None]
            for y in ("2023", "2024", "2025") for reg in ("서울특별시", "부산광역시")]
    r = run_with({"op": "aggregate", "agg": "sum", "by": ["시점"]}, {"행정구역별": ["서울특별시", "부산광역시"]}, rows)
    assert r.value is None or all(p["value"] is None for p in r.value)
    assert "부산광역시 값이 없어 합계를 내지 않음" in r.note
    from backend.core.reasons import humanize
    assert "부산광역시 값이 없어 합계를 내지 못했습니다" in humanize(r.note)


def test_limit2_complete_years_get_no_warning():
    rows = [[y, reg, "인구수(명)", 100.0] for y in ("2023", "2024") for reg in ("서울특별시", "부산광역시")]
    r = run_with({"op": "aggregate", "agg": "sum", "by": ["시점"]}, {}, rows)
    assert [p["value"] for p in r.value] == [200.0, 200.0] and r.note is None


# ── 실제 HCX 확인 (보고서 11.3) ─────────────────────────────────────
YEARLY_ROWS = [[y, "전국", "인구수(명)", n] for y, n in (("2021", 300.0), ("2022", 100.0), ("2023", 200.0))]


def plan_one(op, filters=None, select=None, rows=None, sub="하위 질문", original="질문", **kw):
    b = QueryBundle(query_id="q", original=original, sub_questions=[sub], sub_filters=[filters or {}])
    dec = {"answers": [{"sub_question_id": "q-1", "op": op, **kw,
                        "operands": [{"record_id": VID, "item": "인구수(명)", "select": {} if select is None else select}]}]}
    rec = view(rows or YEARLY_ROWS, COLS)
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    return cp, run_answer_steps(cp.answer_steps, [rec])[0]


def test_h1_rank_with_kind_and_no_top_n_is_a_superlative():
    """'가장 적은 해' 에 HCX 가 rank + kind=min + order=desc 를 냈다 (2026-11-17 실제 HCX).
    rank 는 같은 시점 안에서 순위를 매겨 해끼리는 견주지 못한다 → 최솟값(extreme)으로"""
    cp, r = plan_one("rank", kind="min", order="desc")
    st = cp.answer_steps[0]
    assert (st.op, st.kind) == ("extreme", "min") and r.value == [{"key": {"시점": "2022"}, "value": 100.0}]
    assert any("extreme" in n for n in cp.notes)
    cp, r = plan_one("rank", kind="max", top_n=1)
    assert (cp.answer_steps[0].op, cp.answer_steps[0].kind) == ("extreme", "max") and r.value[0]["key"]["시점"] == "2021"


def test_h1_rank_with_kind_and_top_n_keeps_rank_with_the_matching_order():
    rows = [["2025", reg, "인구수(명)", n] for reg, n in (("서울특별시", 9.0), ("부산광역시", 3.0), ("대구광역시", 2.0))]
    cp, r = plan_one("rank", rows=rows, kind="min", top_n=2)
    st = cp.answer_steps[0]
    assert (st.op, st.order, st.kind) == ("rank", "asc", None)
    assert [p["key"]["행정구역별"] for p in r.value] == ["대구광역시", "부산광역시"]


@pytest.mark.parametrize("op", ["rank", "extreme"])
def test_h2_single_compared_value_is_not_ranked(op):
    """View 에 2025년 한 행뿐인데 '가장 적었던 해는 2025년' 이라고 답했다 (2026-11-17 실제 HCX)"""
    _, r = plan_one(op, rows=[["2025", "전국", "인구수(명)", 240326.0]])
    assert r.value is None and "한 해뿐" in r.note          # [CHANGED 11-17] 해끼리 비교라 다시 물을 방법을 알리는 문구 (보고서 13장)


def test_h2_two_values_are_still_compared():
    _, r = plan_one("extreme", kind="min", rows=YEARLY_ROWS[:2])
    assert r.value == [{"key": {"시점": "2022"}, "value": 100.0}]


@pytest.mark.parametrize("sub,original", [("2021~2023년 전국 인구수 연도별 증감률 추이", "인구 매년 증감률은?"),
                                          ("인구수 증감률", "인구의 전년 대비 증감률"), ("인구수 증감률", "해마다 얼마나 변했어")])
def test_h3_yearly_words_make_the_answer_year_over_year(sub, original):
    cp, r = plan_one("growth_rate", {"시점": [2021, 2022, 2023]}, sub=sub, original=original, **{"from": "2021", "to": "2023"})
    assert cp.answer_steps[0].base == "prev" and [p["key"]["시점"] for p in r.value] == ["2022", "2023"]


def test_h3_whole_period_question_stays_two_points():
    cp, r = plan_one("growth_rate", {"시점": [2021, 2022, 2023]}, sub="2021~2023년 전국 인구수 연도별 추이", original="최근 3년 얼마나 변했어?")
    assert cp.answer_steps[0].base is None and isinstance(r.value, float)


@pytest.mark.parametrize("title,measure,kept", [("최근 5년 혼인건수 매년 증감률 추이", "raw", False),
                                                ("최근 5년 혼인건수 추이", "raw", True),
                                                ("최근 5년 혼인건수 증감률 추이", "growth_rate", True),
                                                ("시도별 인구 비중", "raw", False)])
def test_h4_title_naming_another_measure_is_replaced(title, measure, kept):
    from backend.schemas.chart import ChartRequest
    dec = {"charts": [{"chart_id": "c1", "title": title, "record_id": VID, "select": {"항목": ["인구수(명)"]}}]}
    cp, _ = make_plan([ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure=measure, fallback_chart="bar")],
                      [view(YEARLY_ROWS, COLS)], Decision.model_validate(dec))
    assert (cp.plans[0].title == title) is kept


# ── 남은 한계 (보고서 12.3) ───────────────────────────────────────
def test_r1_rank_over_years_when_only_the_time_varies():
    _, r = plan_one("rank")
    assert [(p["key"]["시점"], p["rank"]) for p in r.value] == [("2021", 1), ("2023", 2), ("2022", 3)]


def test_r1_rank_stays_per_period_when_regions_vary_too():
    rows = [[y, reg, "인구수(명)", n] for y, reg, n in (("2022", "서울특별시", 9.0), ("2022", "부산광역시", 3.0),
                                                         ("2023", "서울특별시", 8.0), ("2023", "부산광역시", 4.0))]
    _, r = plan_one("rank", rows=rows)
    assert [(p["key"]["시점"], p["key"]["행정구역별"], p["rank"]) for p in r.value] == [
        ("2022", "서울특별시", 1), ("2022", "부산광역시", 2), ("2023", "서울특별시", 1), ("2023", "부산광역시", 2)]


@pytest.mark.parametrize("op", ["rank", "extreme"])
def test_r2_single_year_says_what_to_ask_instead(op):
    from backend.core.reasons import humanize
    _, r = plan_one(op, rows=[["2025", "전국", "인구수(명)", 240326.0]])
    assert r.value is None and "2025" in r.note
    assert humanize(r.note) == "자료가 2025년 한 해뿐이라 해끼리 비교하지 못했습니다. 기간(예: 최근 10년)을 넣어 다시 물어봐 주세요"


def test_r2_single_region_keeps_the_generic_reason():
    rows = [["2025", "전국", "인구수(명)", 5000.0], ["2025", "서울특별시", "인구수(명)", 900.0]]
    _, r = plan_one("extreme", rows=rows)
    assert r.value is None and "비교할 값이 하나뿐" in r.note


@pytest.mark.parametrize("title,kept", [("2023년 인구가 가장 많은 시도는?", False), ("혼인건수가 얼마나 변했는지", False),
                                        ("최근 5년 혼인건수 알려줘", False), ("2021~2025년 혼인건수 추이", True)])
def test_r3_question_shaped_title_is_replaced(title, kept):
    from backend.agent.chart_calculate.planner import clean_title
    assert (clean_title(title, "raw")[0] == title) is kept

