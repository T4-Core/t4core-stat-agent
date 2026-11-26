"""[NEW 11-25] 지표 대응: 질문이 성별을 요청하면 '남자인구수' 를 인구수로 인정한다 (체크리스트 1-2)

15유형 테스트(charts15_try1~3)에서 차트 계획 누락 11건 중 9건이 이것이었다.
'남녀 인구' 를 물었는데 표의 항목이 남자인구수 · 여자인구수라서 "일부를 뜻하는 수식어" 로 보고 보류했다.
질문에 성별이 없으면 지금처럼 막는다 (총인구를 물었는데 남자 인구로 답하지 않는다).
"""
import pytest

from backend.agent.chart_calculate.indicator import correspondence, matches
from backend.agent.chart_calculate.planner import ChartDecision, Decision, _Planner, make_plan
from backend.schemas.chart import ChartRequest
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

COLS = ["시점", "행정구역별", "항목", "값"]
MALE = frozenset({"남자", "남", "남성"})


# ── indicator.matches / correspondence ─────────────────────────────
@pytest.mark.parametrize("item, indicator, modifiers, want", [
    ("남자인구수", "인구수", MALE, True),             # 성별을 물음 → 대응
    ("남자 인구수", "인구수", MALE, True),            # 띄어쓰기
    ("남자인구수(명)", "인구", MALE, True),           # 단위 괄호 · 지표 '인구'
    ("여자인구수", "인구수", MALE, False),            # 다른 성별
    ("남자인구수", "인구수", frozenset(), False),      # 성별을 묻지 않음 → 지금처럼 다른 지표
    ("남자고령인구비율", "고령인구비율", MALE, False),  # 비율 계열은 이름이 같을 때만 (그대로)
    ("인구수", "인구수", MALE, True),                 # 수식어가 없는 항목은 그대로 대응
])
def test_matches_with_requested_sex_modifier(item, indicator, modifiers, want):
    assert matches(item, indicator, modifiers=modifiers) is want


def test_correspondence_passes_modifiers_to_the_name_path_only():
    assert correspondence("남자인구수(명)", "명", ["인구수"], [], (), False, MALE) == "name"
    assert correspondence("남자인구수(명)", "명", ["인구수"], [], (), False) is None


# ── planner._indicator_terms ───────────────────────────────────────
@pytest.mark.parametrize("fixed, wanted, mods", [
    ({"지표": ["인구수"], "성별": ["남자", "여자"]}, ["인구수"], {"남자", "남", "남성", "여자", "여", "여성"}),
    ({"지표": ["남자", "인구"]}, ["인구"], {"남자", "남", "남성"}),               # 지표 칸에 섞인 성별 단어
    ({"지표": ["남자"], "대상": ["인구"]}, ["인구"], {"남자", "남", "남성"}),        # 빼고 비면 대상
    ({"지표": ["남자"]}, [], {"남자", "남", "남성"}),                              # 대상도 없으면 검사하지 않음
    ({"지표": ["인구수"]}, ["인구수"], set()),                                    # 성별 없음 → 그대로
    ({"지표": ["가구수"], "대상": ["가구"]}, ["가구수"], set()),
])
def test_indicator_terms(fixed, wanted, mods):
    got_wanted, got_mods = _Planner._indicator_terms(fixed)
    assert got_wanted == wanted and set(got_mods) == mods


# ── 계획 단계 (make_plan) ──────────────────────────────────────────
SEX_ROWS = [["2024", "전국", "남자인구수", 25498324.0], ["2024", "전국", "여자인구수", 25718897.0]]


def _bundle(filters, subs=None):
    if subs is None:
        return QueryBundle(query_id="q", original="질문", sub_questions=["하위 질문"], sub_filters=[filters])
    return QueryBundle(query_id="q", original="질문", filters=filters, sub_questions=[f"하위 {i}" for i in range(len(subs))],
                       sub_filters=subs)


def _chart_plan(filters, rows=SEX_ROWS, select=None):
    rec = view(rows, COLS, unit="명")
    chart = ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="bar", measure="raw")
    dec = Decision(charts=[ChartDecision(chart_id="c1", record_id=VID, select=select or {"시점": ["2024"]})], answers=[])
    return make_plan([chart], [rec], dec, _bundle(filters))[0]


def test_chart_with_sex_items_is_planned_when_the_question_asks_for_both_sexes():
    cp = _chart_plan({"지표": ["인구수"], "성별": ["남자", "여자"], "시점": [2024]})
    assert cp.plans and not cp.withheld


def test_chart_with_sex_words_in_the_indicator_slot_is_planned():
    cp = _chart_plan({"지표": ["남자", "여자", "인구"], "시점": [2024]})
    assert cp.plans and not cp.withheld


def test_chart_with_sex_items_is_still_withheld_when_the_question_asks_for_the_total():
    cp = _chart_plan({"지표": ["인구수"], "시점": [2024]})
    assert cp.plans == [] and cp.withheld and cp.withheld[0].chart_id == "c1"


def test_answer_for_one_sex_uses_only_that_sex_item():
    """버블 질문처럼 하위 질문마다 성별이 다르면 그 성별의 항목만 인정한다"""
    rec = view(SEX_ROWS, COLS, unit="명")
    subs = [{"지표": ["인구수"], "성별": ["남자"], "시점": [2024]}, {"지표": ["인구수"], "성별": ["여자"], "시점": [2024]}]
    b = _bundle({"지표": ["인구수"], "성별": ["남자", "여자"], "시점": [2024]}, subs)
    good = Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [{"record_id": VID, "item": "남자인구수", "select": {}}]},
        {"sub_question_id": "q-2", "op": "raw", "operands": [{"record_id": VID, "item": "여자인구수", "select": {}}]}]})
    cp, _ = make_plan([], [rec], good, b)
    assert len(cp.answer_steps) == 2 and not cp.withheld
    wrong = Decision.model_validate({"answers": [
        {"sub_question_id": "q-1", "op": "raw", "operands": [{"record_id": VID, "item": "여자인구수", "select": {}}]}]})
    cp, _ = make_plan([], [rec], wrong, b)
    # 남자를 물은 하위 질문에 여자인구수 → 같은 View 의 대응 항목(남자인구수)으로 바꾼다
    assert cp.answer_steps and cp.answer_steps[0].operands[0].item == "남자인구수"
