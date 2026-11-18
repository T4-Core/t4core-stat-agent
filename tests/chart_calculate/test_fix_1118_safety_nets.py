"""[NEW 11-18] F12 · F13 · F7 · F16 — 입력 안전망 회귀 테스트 (계획서 모듈3_모듈6_F1-F16_수정_계획.md 2장)

  F12  시점 열은 프롬프트에서 자르지 않고, 코드가 극값 · 순위의 시점 선택 범위를 검증한다  (Q33)
  F13  표에 없는 열 조건: 이미 반영된 것이 확인될 때만 버리고, 아니면 계산하지 않는다      (Q02)
  F7·F16  계산에 쓴 항목이 질문의 지표와 대응하지 않으면 바로잡거나 계산하지 않는다       (Q08)
"""
from backend.agent.chart_calculate.decide import _values, _year_runs
from backend.agent.chart_calculate.indicator import matches
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

TS_COLS = ["시점", "기본항목별", "항목", "값"]


def bundle(indicator=None, years=None, region=None, intent=None):
    f = {k: v for k, v in {"지표": indicator, "시점": years, "지역": region, "의도": intent}.items() if v}
    return QueryBundle(query_id="q", original="질문", sub_questions=["하위 질문"], sub_filters=[f])


def plan(rec, op, operand, bundle_):
    dec = {"answers": [{"sub_question_id": "q-1", "op": op, "operands": [operand]}]}
    cp, _ = make_plan([], [rec], Decision.model_validate(dec), bundle_)
    return cp


# ── F12 ──────────────────────────────────────────────────────────
def test_year_runs_does_not_hide_a_gap():
    got = _year_runs([str(y) for y in [*range(1970, 2000), *range(2001, 2026)]])
    assert got == "1970~1999, 2001~2025 (모두 55개)"
    assert _year_runs(["2020", "2022", "2023"]) == "2020, 2022~2023 (모두 3개)"


def test_time_column_is_never_cut_in_the_prompt():
    rows = [[str(y), "사망자수(명)", "인구동태", float(y)] for y in range(1970, 2026)]
    text = _values(view(rows, TS_COLS), "시점", "")
    assert "2025" in text and "외 " not in text and "1970~2025" in text and "56개" in text


def test_extreme_over_time_is_widened_to_every_available_year_even_if_hcx_picked_the_first_forty():
    from backend.agent.chart_calculate.calculate import run_answer_steps
    rows = [[str(y), "사망자수(명)", "인구동태", float(1000 + y) if y != 2022 else 999999.0] for y in range(1970, 2026)]
    rec = view(rows, TS_COLS)
    first40 = [str(y) for y in range(1970, 2010)]
    cp = plan(rec, "extreme", {"record_id": VID, "item": "사망자수(명)", "select": {"시점": first40}}, bundle(["사망자수"], intent="순위"))
    res = run_answer_steps(cp.answer_steps, [rec])[0]
    assert res.value[0]["key"]["시점"] == "2022" and res.value[0]["value"] == 999999.0


def test_extreme_keeps_a_deliberately_single_year_selection():
    rows = [[str(y), "사망자수(명)", "인구동태", float(y)] for y in range(1970, 2026)]
    cp = plan(view(rows, TS_COLS), "extreme", {"record_id": VID, "item": "사망자수(명)", "select": {"시점": ["2024"]}}, bundle(["사망자수"]))
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2024"]


# ── F13 ──────────────────────────────────────────────────────────
def marriage_view():
    return view([["2021", "혼인건수(건)", "인구동태건수 및 동태율 추이", 192507.0], ["2025", "혼인건수(건)", "인구동태건수 및 동태율 추이", 240326.0]], TS_COLS)


def test_condition_on_a_missing_column_is_dropped_when_the_item_already_carries_it():
    cp = plan(marriage_view(), "change", {"record_id": VID, "item": "혼인건수(건)", "select": {"시점": ["2021", "2025"], "대상": ["혼인"]}},
              bundle(["혼인건수"]))
    assert cp.warnings == [] and "대상" not in cp.answer_steps[0].operands[0].select


def test_condition_on_a_missing_column_that_changes_the_meaning_is_withheld_not_dropped():
    rec = view([["2024", "계", "인구(명)", 100.0], ["2024", "남자", "인구(명)", 60.0], ["2024", "여자", "인구(명)", 40.0]], ["시점", "성별", "항목", "값"])
    cp = plan(rec, "raw", {"record_id": VID, "item": "인구(명)", "select": {"시점": ["2024"], "남녀구분": ["여자"]}}, bundle(["인구"]))
    assert cp.answer_steps == [] and cp.warnings and "남녀구분" in cp.warnings[0]


# ── F7 · F16 ─────────────────────────────────────────────────────
def test_indicator_matching():
    assert matches("총출생성비", "인구수") is False
    assert matches("인구성장률", "인구수") is False            # 이름이 겹쳐도 비율 · 증가 계열은 다른 지표
    assert matches("인구(천명)", "인구수") and matches("출생아수(명)", "출생아") and matches("혼인건수(건)", "혼인건수")
    assert matches("고령인구 구성비(%)", "고령인구비율")         # 구성비 = 비율
    assert matches("추계인구", "인구수") and not matches("추계인구", "인구수", strict=True)
    assert not matches("남자인구", "인구수") and not matches("1인가구", "가구수")          # 일부(남자 · 1인)는 전체 지표가 아니다
    assert not matches("총전입", "인구수")


def sex_ratio_view(extra=None, notes=None):
    rows = [["2023", "서울특별시", "총출생성비", 105.5], ["2023", "부산광역시", "총출생성비", 106.0]] + (extra or [])
    return view(rows, ["시점", "시도별", "항목", "값"], notes=notes)


def test_item_that_is_not_the_requested_indicator_is_withheld():
    cp = plan(sex_ratio_view(), "rank", {"record_id": VID, "item": "총출생성비", "select": {}}, bundle(["인구수"], years=[2023]))
    assert cp.answer_steps == [] and cp.warnings and "인구수" in cp.warnings[0]


def test_wrong_item_is_replaced_by_the_matching_one_in_the_same_view():
    extra = [["2023", "서울특별시", "인구(명)", 9.0e6], ["2023", "부산광역시", "인구(명)", 3.3e6]]
    cp = plan(sex_ratio_view(extra), "rank", {"record_id": VID, "item": "총출생성비", "select": {}}, bundle(["인구수"], years=[2023]))
    op = cp.answer_steps[0].operands[0]
    assert op.item == "인구(명)" and op.note and "인구수" in op.note


def test_growth_rate_item_is_not_accepted_for_a_count_indicator():
    rec = view([["2023", "서울특별시", "인구성장률(%)", 0.2], ["2023", "부산광역시", "인구성장률(%)", -0.4]], ["시점", "시도별", "항목", "값"])
    cp = plan(rec, "rank", {"record_id": VID, "item": "인구성장률(%)", "select": {}}, bundle(["인구수"], years=[2023]))
    assert cp.answer_steps == [] and cp.warnings


def test_matching_item_passes_untouched():
    rec = view([["2023", "서울특별시", "인구(천명)", 9400.0], ["2023", "부산광역시", "인구(천명)", 3300.0]], ["시점", "시도별", "항목", "값"])
    cp = plan(rec, "rank", {"record_id": VID, "item": "인구(천명)", "select": {}}, bundle(["인구수"], years=[2023]))
    assert cp.warnings == [] and cp.answer_steps and cp.answer_steps[0].operands[0].note is None


def test_item_may_match_the_target_instead_of_the_indicator_and_category_items_are_not_checked():
    # Q25 '1인가구 수' — 지표 가구수 · 대상 1인가구: 항목 '1인가구' 는 대상에 대응하므로 통과
    rec = view([["2024", "전국", "1인가구", 8044948.0]], ["시점", "행정구역별(시군구)", "항목", "값"])
    b = QueryBundle(query_id="q", original="질문", sub_questions=["q"], sub_filters=[{"지표": ["가구수"], "대상": ["1인가구"], "시점": [2024]}])
    cp = plan(rec, "raw", {"record_id": VID, "item": "1인가구", "select": {"시점": ["2024"]}}, b)
    assert cp.warnings == [] and cp.answer_steps
    # 항목 열에 나이가 든 표(Q11)는 항목으로 지표를 알 수 없어 검사하지 않는다
    age = view([["2024", "전국", "0세", 1.0], ["2024", "전국", "1세", 1.0]], ["시점", "행정구역별", "항목", "값"])
    b2 = QueryBundle(query_id="q", original="질문", sub_questions=["q"], sub_filters=[{"지표": ["인구수"], "시점": [2024]}])
    cp2 = plan(age, "raw", {"record_id": VID, "item": "0세", "select": {"시점": ["2024"]}}, b2)
    assert cp2.warnings == []


def test_item_of_a_movers_table_is_not_accepted_for_a_population_question():
    rec = view([["2024", "수원시", "총전입", 151826.0], ["2024", "용인시", "총전입", 144893.0]], ["시점", "행정구역(시군구)별", "항목", "값"])
    cp = plan(rec, "rank", {"record_id": VID, "item": "총전입", "select": {}}, bundle(["인구수"], years=[2024]))
    assert cp.answer_steps == [] and cp.warnings


def test_description_suffix_of_a_scenario_value_is_resolved_but_region_prefixes_are_not():
    from backend.agent.chart_calculate.select import select_rows
    long = "중위 추계(기본 추계: 출산율-중위 / 기대수명-중위)"
    rec = view([["2025", long, "서울특별시", "인구(천명)", 9340.0], ["2025", "고위 추계(높은 출산율)", "서울특별시", "인구(천명)", 9500.0]],
               ["시점", "시나리오별", "시도별", "항목", "값"])
    assert select_rows(rec, {"시나리오별": ["중위 추계"]}).rows[0][-1] == 9340.0
    seoul = view([["2025", "서울특별시", "인구(천명)", 9340.0]], ["시점", "시도별", "항목", "값"])
    assert select_rows(seoul, {"시도별": ["서울"]}).errors            # 이름 앞부분만 맞는다고 같은 지역으로 보지 않는다


# ── [검토 10] 질문이 해끼리 견주는데 HCX 가 한 해만 고른 경우 ───────────────
def time_axis_bundle():
    return QueryBundle(query_id="q", original="가장 사망자수가 많은 해는?", sub_questions=["q"],
                       sub_filters=[{"지표": ["사망자수"], "비교축": "연도", "의도": "순위"}])


def test_review10_single_year_picked_by_hcx_is_widened_when_the_question_compares_years():
    from backend.agent.chart_calculate.calculate import run_answer_steps
    rows = [[str(y), "사망자수(명)", "인구동태", float(y) if y != 2022 else 999999.0] for y in range(1970, 2026)]
    rec = view(rows, TS_COLS)
    cp = plan(rec, "extreme", {"record_id": VID, "item": "사망자수(명)", "select": {"시점": ["1980"]}}, time_axis_bundle())
    assert run_answer_steps(cp.answer_steps, [rec])[0].value[0]["key"]["시점"] == "2022"


def test_review10_year_asked_by_the_user_is_kept_and_region_rank_is_not_widened():
    rows = [[str(y), "서울특별시", "인구(명)", float(y)] for y in (2022, 2023)] + [[str(y), "부산광역시", "인구(명)", float(y) - 1] for y in (2022, 2023)]
    rec = view(rows, ["시점", "시도별", "항목", "값"])
    asked = QueryBundle(query_id="q", original="q", sub_questions=["q"], sub_filters=[{"지표": ["인구수"], "시점": [2023], "비교축": "연도"}])
    cp = plan(rec, "rank", {"record_id": VID, "item": "인구(명)", "select": {"시점": ["2023"]}}, asked)
    assert cp.answer_steps[0].operands[0].select["시점"] == ["2023"]          # 사용자가 정한 한 해
    by_region = QueryBundle(query_id="q", original="q", sub_questions=["q"], sub_filters=[{"지표": ["인구수"], "비교축": "시도", "의도": "순위"}])
    cp2 = plan(rec, "rank", {"record_id": VID, "item": "인구(명)", "select": {"시점": ["2023"]}}, by_region)
    assert cp2.answer_steps[0].operands[0].select["시점"] == ["2023"]         # 비교축이 시점이 아니다


# ── [검토 1~3] 지표 정규화 · 설명문 단어로 조건을 버리지 않기 ────────────────
def test_review3_derived_item_names_and_population_qualifiers_are_not_normalised_away():
    assert matches("인구증가율(%)", "인구수") is False
    assert matches("인구(내국인)", "인구(외국인)") is False
    assert matches("인구(1세이상)", "인구수") and matches("인구증가율(%)", "인구 증가율")


def test_review2_a_word_in_the_view_description_is_not_proof_that_a_condition_was_applied():
    from backend.schemas.record import Record
    rec = Record.model_validate({"id": VID, "lexical_text": "성별 인구 남자 여자", "parent_id": "table::x", "metadata": {},
                                 "table": {"columns": ["시점", "성별", "항목", "값"],
                                           "rows": [["2024", "계", "인구(명)", 100.0], ["2024", "남자", "인구(명)", 60.0], ["2024", "여자", "인구(명)", 40.0]]}})
    cp = plan(rec, "raw", {"record_id": VID, "item": "인구(명)", "select": {"시점": ["2024"], "남녀구분": ["여자"]}}, bundle(["인구"], years=[2024]))
    assert cp.answer_steps == [] and cp.warnings and "남녀구분" in cp.warnings[0]


# ── [검토 11·12] 대상 이름만 맞는 항목 · 설명 보정의 범위 ────────────────────
def test_review11_item_matching_only_the_target_is_rejected_when_the_indicator_is_a_rate():
    # 대상=인구, 지표=인구성장률: 인구수(5천만 명)는 대상에는 맞아도 요청한 지표(성장률)가 아니다
    rec = view([["2024", "전국", "인구(명)", 51000000.0], ["2024", "전국", "인구성장률(%)", 0.2]], ["시점", "행정구역별", "항목", "값"])
    b = QueryBundle(query_id="q", original="q", sub_questions=["q"], sub_filters=[{"대상": ["인구"], "지표": ["인구성장률"], "시점": [2024]}])
    cp = plan(rec, "raw", {"record_id": VID, "item": "인구(명)", "select": {"시점": ["2024"]}}, b)
    op = cp.answer_steps[0].operands[0] if cp.answer_steps else None
    assert op is None or op.item == "인구성장률(%)"                      # 바로잡거나 계산하지 않는다 (인구수를 그대로 쓰지 않는다)
    assert op is not None or cp.warnings


def test_review11_item_matching_the_target_is_still_accepted_for_a_count_indicator():
    rec = view([["2024", "전국", "1인가구", 8044948.0]], ["시점", "행정구역별", "항목", "값"])
    b = QueryBundle(query_id="q", original="q", sub_questions=["q"], sub_filters=[{"대상": ["1인가구"], "지표": ["가구수"], "시점": [2024]}])
    assert plan(rec, "raw", {"record_id": VID, "item": "1인가구", "select": {"시점": ["2024"]}}, b).warnings == []


def test_review12_age_condition_is_not_widened_to_a_longer_label():
    from backend.agent.chart_calculate.select import select_rows
    rec = view([["2024", "전국", "65세", 600000.0], ["2024", "전국", "65세 이상", 9000000.0]], ["시점", "행정구역별", "연령별", "값"])
    got = select_rows(rec, {"연령별": ["65세"]})
    assert [r[-1] for r in got.rows] == [600000.0]                       # 65세 이상(900만)으로 바뀌면 안 된다
    only_long = view([["2024", "전국", "65세 이상", 9000000.0]], ["시점", "행정구역별", "연령별", "값"])
    assert select_rows(only_long, {"연령별": ["65세"]}).errors            # 65세 행이 없으면 없는 값으로 남는다
