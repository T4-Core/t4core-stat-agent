"""[NEW 11-20] KOS-26 — Linear 버그 리포트 수정 (docs/plans/2026-11-19-linear-버그리포트-수정.md) 모듈 3 회귀 테스트 (HCX 없음)

  A-1  지표 대응: 별칭(원문표현 · 조건 값)은 후보일 뿐 — 측정 대상 · 원 단위가 맞을 때만 승인
  A-2  조건식: 분류 축을 식별해 선택을 맞추고, 못 찾거나 비교 연산이면 계산하지 않는다
  A-3  차트 경로: 상위 select 가 고르는 행의 항목 전체를 검사한다
  A-4  같은 View 의 전체 행을 분모로 (나머지 좌표가 모두 같을 때만)
  A-5  계산 단계의 소속 하위 질문 (Step · CalcResult.sub_question_id)
"""
from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.indicator import correspondence, is_count_indicator, measure_compatible
from backend.agent.chart_calculate.planner import ChartDecision, Decision, fixed_conditions, make_plan
from backend.schemas.chart import ChartRequest, Denominator, Operand
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

COLS = ["시점", "행정구역별", "항목", "값"]


def cond(field, value, op="=", text=None, unit=None):
    return {"field": field, "op": op, "value": value, "unit": unit, "text": text or f"{field}{op}{value}", "source": "slot"}


def bundle(filters, sub_questions=("하위 질문",)):
    return QueryBundle(query_id="q", original="질문", sub_questions=list(sub_questions), sub_filters=[filters] * len(sub_questions))


def answer(rec, op, operand, b, **extra):
    dec = {"answers": [{"sub_question_id": "q-1", "op": op, "operands": [operand], **extra}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    return cp


def hv(rows, columns=COLS, unit="가구", **kw):
    return view(rows, columns, unit=unit, **kw)


# ── A-1 ──────────────────────────────────────────────────────────
def test_alias_is_approved_only_when_measure_and_unit_match():
    rows = [["1990", "화성군", "보증부월세(가구)", 1404.0], ["1990", "화성군", "계(가구)", 43799.0]]
    f = {"지표": ["가구수"], "시점": [1990], "조건식": [cond("점유형태", "보증부월세")]}
    cp = answer(hv(rows), "raw", {"record_id": VID, "item": "보증부월세(가구)", "select": {"시점": ["1990"]}}, bundle(f))
    assert cp.warnings == [] and cp.answer_steps and cp.answer_steps[0].sub_question_id == "q-1"


def test_original_expression_alias_for_an_indicator_in_a_different_name():
    rows = [["2015", "부산진구", "국제결혼이주자(명)", 651.0], ["2018", "부산진구", "국제결혼이주자(명)", 666.0]]
    f = {"지표": ["인구수"], "시점": [2015, 2018], "원문표현": ["국제결혼이주자"]}
    cp = answer(hv(rows, unit="명"), "change", {"record_id": VID, "item": "국제결혼이주자(명)", "select": {}}, bundle(f),
                **{"from": "2015", "to": "2018"})
    assert cp.warnings == [] and cp.answer_steps


def test_alias_with_a_household_item_measured_in_persons_is_refused():
    """지표 가구수 · 항목 보증부월세 인데 원 단위가 '명' 이면 가구 수가 아니다"""
    rows = [["1990", "화성군", "보증부월세(명)", 4000.0]]
    f = {"지표": ["가구수"], "시점": [1990], "조건식": [cond("점유형태", "보증부월세")]}
    cp = answer(hv(rows, unit="명"), "raw", {"record_id": VID, "item": "보증부월세(명)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and cp.warnings


def test_average_household_size_is_not_a_count_indicator_so_an_alias_cannot_stand_in():
    assert not is_count_indicator("평균가구원수") and is_count_indicator("가구원수")
    rows = [["1990", "화성군", "보증부월세(가구)", 1404.0]]
    f = {"지표": ["평균가구원수"], "시점": [1990], "조건식": [cond("점유형태", "보증부월세")]}
    cp = answer(hv(rows), "raw", {"record_id": VID, "item": "보증부월세(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and cp.warnings


def test_target_name_does_not_approve_a_household_item_for_a_person_indicator():
    """지표 가구원수 · 대상 가구 · 항목 가구수(가구) — 가구원 수와 가구 수는 다른 측정값"""
    assert measure_compatible("가구원수", "가구") is False and measure_compatible("가구수", "가구") is True
    assert correspondence("가구수(가구)", "가구", ["가구원수"], ["가구"]) is None
    rows = [["1990", "화성군", "가구수(가구)", 43799.0]]
    f = {"지표": ["가구원수"], "대상": ["가구"], "시점": [1990]}
    cp = answer(hv(rows), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and cp.warnings


def test_target_name_is_still_approved_when_the_unit_is_unknown_or_compatible():
    assert correspondence("1인가구", None, ["가구수"], ["1인가구"]) == "target"
    assert correspondence("1인가구", "가구", ["가구수"], ["1인가구"]) == "target"


def test_alias_is_not_used_when_the_view_has_the_indicator_item_itself():
    rows = [["1990", "화성군", "보증부월세(가구)", 1404.0], ["1990", "화성군", "가구수(가구)", 43799.0]]
    f = {"지표": ["가구수"], "시점": [1990], "원문표현": ["보증부월세"]}
    assert correspondence("보증부월세(가구)", "가구", ["가구수"], [], ["보증부월세"]) == "alias"
    cp = answer(hv(rows), "raw", {"record_id": VID, "item": "보증부월세(가구)", "select": {}}, bundle(f))
    op = cp.answer_steps[0].operands[0]
    assert op.item == "가구수(가구)" and op.note        # 별칭 항목은 분류 값이라 지표 항목으로 바꾼다


# ── A-2 ──────────────────────────────────────────────────────────
MARRIAGE = ["시점", "혼인상태", "항목", "값"]


def test_condition_narrows_a_wider_selection_to_the_condition_value():
    rows = [["2044", "미혼", "가구수(가구)", 100.0], ["2044", "기혼", "가구수(가구)", 300.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond("혼인상태", "미혼")]}
    cp = answer(hv(rows, MARRIAGE), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {"혼인상태": ["미혼", "기혼"]}}, bundle(f))
    assert cp.warnings == [] and cp.answer_steps[0].operands[0].select["혼인상태"] == ["미혼"]
    assert run_answer_steps(cp.answer_steps, [hv(rows, MARRIAGE)])[0].value == 100.0


def test_condition_is_added_when_the_hcx_selection_does_not_mention_the_column():
    rows = [["2044", "미혼", "가구수(가구)", 100.0], ["2044", "기혼", "가구수(가구)", 300.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond("혼인상태", "미혼")]}
    cp = answer(hv(rows, MARRIAGE), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps[0].operands[0].select["혼인상태"] == ["미혼"]


def test_condition_is_not_moved_to_another_axis_that_merely_has_the_same_value():
    """가구주연령=30~39세 인데 View 에는 배우자연령 열만 있고 거기 '30~39세' 가 있다 → 적용한 것이 아니다"""
    rows = [["2044", "30~39세", "가구수(가구)", 100.0], ["2044", "40~49세", "가구수(가구)", 300.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond("가구주연령", "30~39세")]}
    cp = answer(hv(rows, ["시점", "배우자연령", "항목", "값"]), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and any("30~39세" in w and "적용할 자료가 없어" in w for w in cp.warnings)
    assert [w.text for w in cp.withheld] == cp.warnings and cp.withheld[0].sub_question_id == "q-1"


def test_known_axis_synonym_is_accepted():
    rows = [["2020", "아파트", "가구수(가구)", 7.0], ["2020", "단독주택", "가구수(가구)", 3.0]]
    f = {"지표": ["가구수"], "시점": [2020], "조건식": [cond("거처의 종류", "아파트")]}
    cp = answer(hv(rows, ["시점", "거처종류", "항목", "값"]), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.warnings == [] and cp.answer_steps[0].operands[0].select["거처종류"] == ["아파트"]


def test_value_without_a_field_is_ambiguous_when_two_columns_have_it():
    rows = [["2044", "미혼", "미혼", "가구수(가구)", 1.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond(None, "미혼")]}
    cp = answer(hv(rows, ["시점", "혼인상태", "배우자혼인상태", "항목", "값"]), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and cp.warnings


def test_comparison_condition_is_withheld_as_unsupported():
    rows = [["2044", "미혼", "가구수(가구)", 100.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond("가구원수", "5", ">=", "가구원수 5명 이상", "명")]}
    cp = answer(hv(rows, MARRIAGE), "raw", {"record_id": VID, "item": "가구수(가구)", "select": {}}, bundle(f))
    assert cp.answer_steps == [] and cp.warnings == ["'가구원수 5명 이상' 같은 조건부 집계는 아직 지원하지 않아 계산하지 못했습니다."]


def test_threshold_in_the_parent_filter_still_reaches_a_sub_question_that_has_its_own_filters():
    """하위 필터가 우선이라 상위에만 있던 숫자 기준이 본 질문에서 사라지던 문제 — 조건식 만 합집합"""
    thr = cond("가구원수", "99000", ">=", "가구원수 99,000명 이상", "명")
    b = QueryBundle(query_id="q", original="질문", sub_questions=["본 질문"], filters={"조건식": [thr]},
                    sub_filters=[{"지표": ["가구수"], "조건식": [cond("혼인상태", "미혼")]}])
    fixed = fixed_conditions(b)["q-1"]
    assert [c["field"] for c in fixed["조건식"]] == ["혼인상태", "가구원수"]


def test_threshold_does_not_reach_a_role_unit():
    thr = cond("가구원수", "99000", ">=", "가구원수 99,000명 이상", "명")
    b = QueryBundle(query_id="q", original="질문", sub_questions=["본 질문", "가구원수"], filters={"조건식": [thr]},
                    sub_filters=[{"지표": ["가구수"]}, {"지표": ["가구원수"], "역할": "조건"}])
    fixed = fixed_conditions(b)
    assert fixed["q-1"]["조건식"] == [thr] and "조건식" not in fixed["q-2"]


def test_condition_is_rechecked_after_merging_and_a_widened_selection_is_withheld():
    """같은 View · 항목의 피연산자를 하나로 합치면 조건 값이 여럿으로 넓어진다 — 최종 선택이 조건을 어기면 보류"""
    rows = [["2044", "미혼", "가구수(가구)", 100.0], ["2044", "기혼", "가구수(가구)", 300.0]]
    f = {"지표": ["가구수"], "시점": [2044], "조건식": [cond("혼인상태", "미혼")]}
    rec = hv(rows, MARRIAGE)
    dec = {"answers": [{"sub_question_id": "q-1", "op": "aggregate", "agg": "sum", "operands": [
        {"record_id": VID, "item": "가구수(가구)", "select": {"혼인상태": ["미혼"]}},
        {"record_id": VID, "item": "가구수(가구)", "select": {"혼인상태": ["기혼"]}}]}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), bundle(f))
    for st in cp.answer_steps:           # 어떤 경로로든 최종 단계는 미혼만 읽는다
        assert all(o.select.get("혼인상태") == ["미혼"] for o in st.operands)


# ── A-3 ──────────────────────────────────────────────────────────
CHART = ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="bar", measure="raw")


def chart_plan(rec, f, select=None):
    dec = Decision(charts=[ChartDecision(chart_id="c1", record_id=VID, select=select or {"시점": ["2023"]})], answers=[])
    return make_plan([CHART], [rec], dec, bundle(f))[0]


def test_chart_with_only_a_time_select_is_checked_against_every_selected_item():
    rec = view([["2023", "서울특별시", "총출생성비", 105.0], ["2023", "부산광역시", "총출생성비", 104.0]], ["시점", "시도별", "항목", "값"])
    cp = chart_plan(rec, {"지표": ["인구수"], "시점": [2023]})
    assert cp.plans == [] and cp.withheld and cp.withheld[0].chart_id == "c1"


def test_chart_select_is_narrowed_to_the_one_item_that_matches_the_indicator():
    rec = view([["2023", "서울특별시", "인구(명)", 9.0], ["2023", "서울특별시", "조출생률(천명당)", 5.0]], ["시점", "시도별", "항목", "값"])
    cp = chart_plan(rec, {"지표": ["인구수"], "시점": [2023]})
    assert cp.plans and cp.plans[0].select["항목"] == ["인구(명)"]


def test_chart_with_matching_items_is_untouched():
    rec = view([["2023", "서울특별시", "인구(명)", 9.0]], ["시점", "시도별", "항목", "값"])
    cp = chart_plan(rec, {"지표": ["인구수"], "시점": [2023]})
    assert cp.plans and "항목" not in cp.plans[0].select


# ── A-4 ──────────────────────────────────────────────────────────
OTHER = "view::other::Y::q-2-1::breakdown"


SHARE_FILTERS = {"지표": ["가구수"], "시점": [1990], "조건식": [cond("점유형태", "보증부월세")]}


def share(rec, select=None, f=None):
    den = Denominator(scope="question", operand=Operand(record_id=OTHER, item="계", select={}))
    dec = {"answers": [{"sub_question_id": "q-1", "op": "share", "denominator": den.model_dump(),
                        "operands": [{"record_id": VID, "item": "보증부월세", "select": select or {"시점": ["1990"]}}]}]}
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type=None, view_ids=[VID])]
    cp, _ = make_plan(charts, [rec], Decision.model_validate(dec), bundle(f or SHARE_FILTERS))
    return cp


def test_share_uses_the_whole_row_of_the_same_view_when_the_denominator_is_outside_the_set():
    rec = hv([["1990", "화성군", "보증부월세", 1404.0], ["1990", "화성군", "계", 43799.0]])
    cp = share(rec)
    assert cp.warnings == [] and cp.answer_steps
    den = cp.answer_steps[0].denominator.operand
    assert (den.record_id, den.item, den.select["시점"]) == (VID, "계", ["1990"]) and den.note
    res = run_answer_steps(cp.answer_steps, [rec])[0]
    assert round(res.value, 4) == round(1404 / 43799 * 100, 4)


def test_share_denominator_must_match_every_other_coordinate():
    rec = hv([["1990", "화성군", "남자", "보증부월세", 1404.0], ["1990", "화성군", "여자", "계", 43799.0]],
             ["시점", "행정구역별", "성별", "항목", "값"])
    cp = share(rec)
    assert cp.answer_steps == [] and cp.warnings          # 남자 부분 ÷ 여자 계 는 만들지 않는다


def test_share_does_not_treat_a_subtotal_as_the_whole():
    rec = hv([["1990", "화성군", "보증부월세", 1404.0], ["1990", "화성군", "소계", 20000.0]])
    cp = share(rec)
    assert cp.answer_steps == [] and cp.warnings


def test_share_is_withheld_when_the_total_row_is_missing_for_the_period_or_duplicated():
    missing = hv([["1990", "화성군", "보증부월세", 1404.0], ["1995", "화성군", "계", 43799.0]])
    dup = hv([["1990", "화성군", "보증부월세", 1404.0], ["1990", "화성군", "계", 43799.0], ["1990", "화성군", "합계", 43799.0]])
    assert share(missing).answer_steps == [] and share(missing).warnings
    assert share(dup).answer_steps == [] and share(dup).warnings


def test_share_with_a_different_unit_total_is_withheld():
    rec = hv([["1990", "화성군", "보증부월세(가구)", 1404.0], ["1990", "화성군", "계(명)", 43799.0]])
    cp = share(rec)
    assert cp.answer_steps == [] and cp.warnings


# ── A-5 ──────────────────────────────────────────────────────────
def test_answer_steps_and_results_carry_their_sub_question_id():
    rec = hv([["2024", "전국", "가구수(가구)", 10.0]])
    f = {"지표": ["가구수"], "시점": [2024]}
    cp = answer(rec, "raw", {"record_id": VID, "item": "가구수(가구)", "select": {"시점": ["2024"]}}, bundle(f))
    (res,) = run_answer_steps(cp.answer_steps, [rec])
    assert cp.answer_steps[0].sub_question_id == "q-1" and res.sub_question_id == "q-1"


# ── 재검토 11-20: 다른 열 좁히기 · 분모 축 제한 ──────────────────────
def test_chart_select_is_narrowed_in_the_classification_column_that_holds_the_indicator_names():
    """지표 이름이 항목 열이 아니라 종류별 열에 있는 표 — 출생아수만 물었는데 사망자수 행까지 통과하던 문제"""
    rec = view([["2023", "전국", "출생아수(명)", "출생사망", 100.0], ["2023", "전국", "사망자수(명)", "출생사망", 999.0]],
               ["시점", "행정구역별", "종류별", "항목", "값"])
    cp = chart_plan(rec, {"지표": ["출생아수"], "시점": [2023]})
    assert cp.plans and cp.plans[0].select["종류별"] == ["출생아수(명)"]


def test_chart_select_in_the_classification_column_is_untouched_when_every_value_matches():
    rec = view([["2023", "전국", "출생아수(명)", "출생사망", 100.0]], ["시점", "행정구역별", "종류별", "항목", "값"])
    cp = chart_plan(rec, {"지표": ["출생아수"], "시점": [2023]})
    assert cp.plans and "종류별" not in cp.plans[0].select


def test_share_denominator_is_not_taken_from_another_axis_total():
    """남자 가구주 중 보증부월세 비율 — 성별 '계' 의 보증부월세 값을 분모로 잡으면 모집단 조건이 바뀐다 (전체 일반가구 분모가 없으면 보류)"""
    rec = hv([["1990", "화성군", "남자", "보증부월세", 1404.0], ["1990", "화성군", "계", "보증부월세", 43799.0]],
             ["시점", "행정구역별", "성별", "항목", "값"])
    cp = share(rec, select={"시점": ["1990"], "성별": ["남자"]})
    assert cp.answer_steps == [] and cp.warnings
