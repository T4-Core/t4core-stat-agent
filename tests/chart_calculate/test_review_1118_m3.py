"""[NEW 11-18] 전체 파이프라인 테스트(질문 34개, 실제 HCX)에서 나온 모듈 3 항목의 회귀 테스트
  - 항목 이름 끝의 괄호가 단위가 아닌데 단위로 읽힘: 인구(1세이상) → '1세이상', 인구(내국인) → '내국인'  (Q06·Q13·Q21·Q22·Q26)
  - HCX 가 항목 이름 뒤에 단위를 덧붙이면(인구(1세이상)(명)) 항목을 못 찾음                          (Q13 2회차)
  - 단위가 천명이면 '9,340천명' 이 아니라 '934만 명'                                                  (Q01)
"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.display import format_value, make_display, strip_unit, unit_of
from backend.agent.chart_calculate.select import find_item_column, select_rows
from backend.schemas.chart import Step
from tests.chart_calculate._views import VID, view

COLS = ["시점", "행정구역별(읍면동)", "성별", "항목", "값"]


# ── 항목 이름 끝의 괄호가 단위인가 ──────────────────────────────────
@pytest.mark.parametrize("item,fallback,expected", [
    ("인구(1세이상)", "명", "명"),            # 괄호는 대상 설명 → 표의 단위(명)
    ("인구(내국인)", "명", "명"),
    ("인구(1세이상)", None, None),            # 단위를 알 수 없음 (괄호를 단위로 지어내지 않는다)
    ("인구(1세이상)(명)", "명", "명"),        # 마지막 괄호가 단위
    ("인구(1세이상)(명)", None, "명"),
    ("혼인건수(건)", None, "건"),
    ("인구(천명)", None, "천명"),
    ("인구(천 명)", None, "천명"),            # 띄어쓰기
    ("인구밀도(명/㎢)", None, "명/㎢"),
    ("고령인구비율(%)", None, "%"),
    ("조출생률(인구천명당)", None, "인구천명당"),
    ("합계출산율", "명", "명"),
    ("인구(남/여)", "명", "명"),              # [11-18 검토] '/' 가 있어도 양쪽이 단위가 아니면 설명 괄호
    ("인구(1인당)", None, None),              # '당' 으로 끝나도 정해진 비율 단위가 아니면 설명
    ("인구(만65세이상/전체)", None, None),
    ("인구밀도(건/천명)", None, "건/천명"),
])
def test_unit_of_reads_only_unit_like_parentheses(item, fallback, expected):
    assert unit_of(item, fallback) == expected


@pytest.mark.parametrize("item,expected", [
    ("인구(1세이상)", "인구(1세이상)"), ("인구(1세이상)(명)", "인구(1세이상)"), ("혼인건수(건)", "혼인건수"),
    ("인구(천명)", "인구"), ("인구(내국인)", "인구(내국인)"), ("인구밀도(명/㎢)", "인구밀도")])
def test_strip_unit_keeps_descriptive_parentheses(item, expected):
    assert strip_unit(item) == expected


# ── Q13 2회차: HCX 가 단위를 덧붙인 항목 이름 ─────────────────────────
def seoul():
    return view([["2025", "서울특별시", "계", "인구(1세이상)", 8896466.0]], COLS, unit="명")


def run(item, **kw):
    st = Step.model_validate({"step_id": "a1", "op": "raw", "operands": [
        {"role": "value", "record_id": VID, "item": item, "select": {"행정구역별(읍면동)": ["서울특별시"], "시점": ["2025"]}}], **kw})
    return run_answer_steps([st], [seoul()])[0]


@pytest.mark.parametrize("item", ["인구(1세이상)", "인구(1세이상)(명)"])
def test_item_with_or_without_the_unit_suffix_finds_the_same_row(item):
    r = run(item)
    assert r.value == 8896466.0 and r.note is None
    assert r.unit == "명"                                           # 이전: '1세이상'
    assert format_value(r.value, make_display(r.unit)) == "8,896,466명"


def test_find_item_column_strips_only_a_unit_like_suffix():
    cols, rows = ["시점", "항목", "값"], [["2025", "인구(1세이상)", 1.0], ["2025", "인구(내국인)", 2.0]]
    assert find_item_column(cols, rows, "인구(내국인)(명)") == ("항목", "인구(내국인)")
    assert find_item_column(cols, rows, "인구(1세이상)(명)") == ("항목", "인구(1세이상)")
    assert find_item_column(cols, rows, "인구") is None                     # 설명 괄호를 떼고 '인구' 로 맞추지 않는다 (둘 중 어느 것인지 모른다)


def test_select_rows_does_not_pick_a_different_item_that_only_shares_the_stem():
    got = select_rows(seoul(), {}, "인구(내국인)(명)")
    assert got.errors and "항목 없음" in got.errors[0]


# ── Q01: 천명 → 만 명 (결정: 천명 단위만) ──────────────────────────────
@pytest.mark.parametrize("value,expected", [
    (9340.0, "934만 명"), (1200.0, "120만 명"), (378.793, "37.9만 명"), (99.5, "10.0만 명"), (-378.0, "-37.8만 명"), (0.0, "0만 명")])
# [11-18 검토 4] 99.5천명 = 9.95만 명. 표시는 사사오입(ROUND_HALF_UP)이라 10.0만 명이다 (이전 기대값 9.9 는 은행가 반올림 기준이라 틀렸다)
def test_cheon_myeong_is_shown_in_man_myeong(value, expected):
    assert format_value(value, make_display("천명")) == expected


def test_other_units_are_not_rescaled():
    assert format_value(8896466.0, make_display("명")) == "8,896,466명"
    assert format_value(240326.0, make_display("건")) == "240,326건"
    assert format_value(-120252.0, make_display("명")) == "-120,252명"
    assert format_value(4.7, make_display("천명당")) == "4.7"


def test_explicit_display_settings_win_over_the_default_scale():
    from backend.schemas.chart import Display
    assert format_value(9340.0, Display(source_unit="천명", display_unit="천명", unit_scale=1, digits=0)) == "9,340천명"


# ── Q19: '경기도 시군구별 순위' 인데 시군구 표에는 '경기도' 행이 없어 계산을 보류함 ──────────────
# [11-18 검토 1] 시군구 수준이라는 사실이 아니라 View 가 고른 지역 코드가 요청한 시도 아래인지 프로필 계층으로 확인한다
PROFILE = {"levels": [{"level": 1, "kind": "regions", "codes": [
    {"code": "00", "name": "전국", "std": "전국", "parent": None, "is_total": True},
    {"code": "11", "name": "서울특별시", "std": "서울특별시", "parent": None, "is_total": False},
    {"code": "11110", "name": "종로구", "std": "종로구", "parent": "11", "is_total": False},
    {"code": "11140", "name": "중구", "std": "중구", "parent": "11", "is_total": False},
    {"code": "11680", "name": "강남구", "std": "강남구", "parent": "11", "is_total": False},
    {"code": "41", "name": "경기도", "std": "경기도", "parent": None, "is_total": False},
    {"code": "41110", "name": "수원시", "std": "수원시", "parent": "41", "is_total": False},
    {"code": "41280", "name": "고양시", "std": "고양시", "parent": "41", "is_total": False},
    {"code": "41820", "name": "가평군", "std": "가평군", "parent": "41", "is_total": False},
    {"code": "41135", "name": "성남시", "std": "성남시", "parent": "41", "is_total": False}]}]}
CODE = {"수원시": "41110", "고양시": "41280", "가평군": "41820", "성남시": "41135", "종로구": "11110", "중구": "11140", "강남구": "11680",
        "서울특별시": "11", "경기도": "41", "부산광역시": "26"}


def region_plan(region, regions, cols=("시점", "행정구역(시군구)별", "항목", "값"), notes=None, codes=True):
    from unittest.mock import patch

    from backend.agent.chart_calculate.planner import Decision, make_plan
    from backend.schemas.query import QueryBundle
    from backend.schemas.record import Record
    b = QueryBundle(query_id="q", original="질문", sub_questions=["하위 질문"], sub_filters=[{"지역": [region], "시점": [2024]}])
    source = {"table_key": "t", "dims": {"c1": {"codes": [CODE.get(r, "99") for r in regions]}}} if codes else {}
    rec = Record.model_validate({
        "id": VID, "lexical_text": "표", "parent_id": "table::t", "source": source, "notes": notes or [],
        "table": {"columns": list(cols), "rows": [["2024", r, "인구수(명)", float(100 - i)] for i, r in enumerate(regions)]},
        "metadata": {"prd_se": "Y", "view_type": "breakdown", "geo_level": "시군구"}})
    dec = {"answers": [{"sub_question_id": "q-1", "op": "rank", "operands": [{"record_id": VID, "item": "인구수(명)", "select": {}}]}]}
    with patch("backend.agent.chart_calculate.region_scope.load_profile", return_value=PROFILE):
        cp, _ = make_plan([], [rec], Decision.model_validate(dec), b)
    return cp, run_answer_steps(cp.answer_steps, [rec])


def test_sigungu_table_scoped_by_the_view_is_not_withheld_for_its_sido_question():
    cp, res = region_plan("경기도", ["수원시", "고양시", "가평군", "성남시"])
    assert cp.warnings == [] and len(cp.answer_steps) == 1
    assert [p["key"]["행정구역(시군구)별"] for p in res[0].value][:2] == ["수원시", "고양시"]


def test_sido_values_without_the_asked_sido_are_still_withheld():
    cp, _ = region_plan("서울특별시", ["부산광역시", "대구광역시", "경기도"])         # 서울 질문에 다른 시도 값만 (M3-11 의 원래 사례)
    assert cp.answer_steps == [] and cp.warnings and "서울특별시" in cp.warnings[0]


def test_sido_table_that_contains_the_asked_sido_is_not_withheld():
    cp, _ = region_plan("경기도", ["서울특별시", "경기도", "부산광역시"], ("시점", "행정구역별", "항목", "값"))
    assert cp.warnings == [] and len(cp.answer_steps) == 1


# [11-18 검토 1] 지역 수준 · 메모 부재는 증거가 아니다: 다른 시도의 시군구는 경고 없이 통과하면 안 된다
def test_sigungu_rows_of_another_sido_are_withheld_even_when_the_view_reports_no_region_problem():
    cp, _ = region_plan("경기도", ["종로구", "중구", "강남구"])
    assert cp.answer_steps == [] and cp.warnings and "경기도" in cp.warnings[0]


def test_sigungu_table_without_region_codes_or_profile_is_withheld():
    cp, _ = region_plan("경기도", ["수원시", "고양시"], codes=False)
    assert cp.answer_steps == [] and cp.warnings


def test_mixed_sigungu_of_two_sidos_is_withheld():
    cp, _ = region_plan("경기도", ["수원시", "종로구"])
    assert cp.answer_steps == [] and cp.warnings
