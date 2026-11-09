"""[NEW] judge/slots.py 단위 테스트 — 가짜 Record → extract_contents → check_slots (데이터 파일·HCX 없음)

실행  pytest tests/judge -q   (저장소 루트에서)
"""
from backend.rag.judge.extract import extract_contents
from backend.rag.judge.slots import SLOT_ORDER, check_slots
from backend.schemas.judge import JudgeConfig, ReasonCode, SlotStatus
from backend.schemas.query import Filters
from tests.judge._records import make_record

S = SlotStatus


def judge(filters, columns, rows, config=None, **kw):
    """테스트 줄을 짧게: 가짜 Record 를 만들어 바로 슬롯 판정까지"""
    return check_slots(filters, extract_contents(make_record(columns, rows, **kw)), config)


# 자주 쓰는 표: 2023년 대구 남자 연령별 인구 (25~29세 값 없음)
AGE_COLS = ["시점", "행정구역(시도)별", "성별", "연령별", "항목", "값"]
AGE_ROWS = [["2023", "대구광역시", "남자", "계", "인구", 1170000],
            ["2023", "대구광역시", "남자", "20 - 24세", "인구", 61234],
            ["2023", "대구광역시", "남자", "25 - 29세", "인구", 70000]]


# ═════════════ 공통 ═════════════
def test_all_slots_returned_and_not_requested():
    res = judge({"지역": ["대구광역시"]}, AGE_COLS, AGE_ROWS)
    assert list(res) == SLOT_ORDER                          # 항상 8개, 같은 순서
    assert res["지역"].status == S.match
    assert res["시점"].status == S.not_requested            # 묻지 않은 슬롯
    assert res["성별"].status == S.not_requested


def test_pydantic_filters_input():
    f = Filters.model_validate({"연령": {"from": 20, "to": 29}, "성별": ["남자"]})   # 연령은 별칭 'from'
    res = judge(f, AGE_COLS, AGE_ROWS)
    assert res["연령"].status == S.match
    assert res["성별"].status == S.match


# ═════════════ 시점 ═════════════
def test_period_match():
    assert judge({"시점": [2023]}, AGE_COLS, AGE_ROWS)["시점"].status == S.match


def test_period_partial_some_years():
    chk = judge({"시점": [2022, 2023]}, AGE_COLS, AGE_ROWS)["시점"]
    assert chk.status == S.partial and "2022" in chk.evidence


def test_period_substituted():
    chk = judge({"시점": [2024]}, AGE_COLS, AGE_ROWS)["시점"]
    assert chk.status == S.partial                          # 기본 설정: 대체 = partial
    assert chk.reason == ReasonCode.slot_substituted


def test_period_substitution_as_missing_config():
    strict = JudgeConfig(substitution_as=S.missing)
    chk = judge({"시점": [2024]}, AGE_COLS, AGE_ROWS, config=strict)["시점"]
    assert chk.status == S.missing and chk.reason == ReasonCode.slot_substituted


def test_period_row_exists_but_no_values():
    rows = [["2023", "인구", 5], ["2024", "인구", None]]
    chk = judge({"시점": [2024]}, ["시점", "항목", "값"], rows)["시점"]
    assert chk.status == S.partial and "값 없음" in chk.evidence


# ═════════════ 지역 ═════════════
def test_region_alias_normalized():
    assert judge({"지역": ["대구"]}, AGE_COLS, AGE_ROWS)["지역"].status == S.match   # "대구" → "대구광역시"


def test_region_other_region_missing():
    assert judge({"지역": ["부산광역시"]}, AGE_COLS, AGE_ROWS)["지역"].status == S.missing


def test_region_only_national_total():
    rows = [["2023", "전국", "인구", 51000000]]
    chk = judge({"지역": ["대구광역시"]}, ["시점", "행정구역별", "항목", "값"], rows)["지역"]
    assert chk.status == S.missing and "전국" in chk.evidence


def test_region_ambiguous_district():
    rows = [["2023", "부산광역시 중구", "인구", 40000]]
    chk = judge({"지역": ["중구"]}, ["시점", "행정구역별", "항목", "값"], rows)["지역"]
    assert chk.status == S.partial and "모호" in chk.evidence


# ═════════════ 성별 ═════════════
def test_sex_from_item_name():
    rows = [["2023", "기대수명 - 남", 80.6]]
    assert judge({"성별": ["남성"]}, ["시점", "항목", "값"], rows)["성별"].status == S.match   # 남성 → 남자


def test_sex_fake_column_is_missing():
    # '특성별' 은 성별 분류가 아님 → 성별 없음 [CHANGED v4] 이전엔 sex 로 분류돼 근거에 '특성별' 이 나왔음
    rows = [["2023", "1인가구", "가구수", 10], ["2023", "2인가구", "가구수", 20]]
    chk = judge({"성별": ["남자"]}, ["시점", "특성별", "항목", "값"], rows)["성별"]
    assert chk.status == S.missing


# ═════════════ 연령 ═════════════
def test_age_exact_cover():
    chk = judge({"연령": {"from": 20, "to": 29}}, AGE_COLS, AGE_ROWS)["연령"]
    assert chk.status == S.match


def test_age_subrange_without_values():
    rows = AGE_ROWS[:2] + [["2023", "대구광역시", "남자", "25 - 29세", "인구", None]]   # 25~29 값 없음
    chk = judge({"연령": {"from": 20, "to": 29}}, AGE_COLS, rows)["연령"]
    assert chk.status == S.partial and "25 - 29세" in chk.evidence


def test_age_wider_range_only():
    rows = [["2023", "20 - 39세", "인구", 1], ["2023", "40 - 59세", "인구", 2], ["2023", "60세 이상", "인구", 3]]
    chk = judge({"연령": {"from": 20, "to": 29}}, ["시점", "연령별", "항목", "값"], rows)["연령"]
    assert chk.status == S.partial and "넓은" in chk.evidence


def test_age_no_dimension_is_missing_p1():
    # [P1] 연령 분류가 없는 표에서 20대를 요청 → build_view 는 notes 없이 전체 인구를 줬던 사례
    rows = [["2023", "대구광역시", "인구", 2370000]]
    chk = judge({"연령": {"from": 20, "to": 29}}, ["시점", "행정구역별", "항목", "값"], rows)["연령"]
    assert chk.status == S.missing and "연령 분류 없음" in chk.evidence


def test_age_householder_only():
    rows = [["2023", "20 - 24세", "가구수", 1], ["2023", "25 - 29세", "가구수", 2], ["2023", "30 - 34세", "가구수", 3]]
    chk = judge({"연령": {"from": 20, "to": 29}}, ["시점", "가구주의 연령별", "항목", "값"], rows)["연령"]
    assert chk.status == S.partial and "가구주" in chk.evidence


def test_age_open_upper_bound():
    rows = [["2023", "65 - 69세", "인구", 1], ["2023", "70 - 74세", "인구", 2], ["2023", "75세 이상", "인구", 3]]
    chk = judge({"연령": {"from": 65, "to": None}}, ["시점", "연령별", "항목", "값"], rows)["연령"]
    assert chk.status == S.match                            # 65→69, 70→74, 75→∞ 빈틈 없음


# ═════════════ 지표·대상 ═════════════
def test_terms_match_in_items():
    assert judge({"지표": ["인구수"]}, AGE_COLS, AGE_ROWS)["지표"].status == S.match   # 인구수 → 인구


def test_terms_only_in_title():
    rows = [["2023", "계", 250000]]
    chk = judge({"지표": ["출생아수"]}, ["시점", "항목", "값"], rows, title="출생아수 시도별 인구동향조사")["지표"]
    assert chk.status == S.partial


def test_terms_missing():
    chk = judge({"대상": ["사망자"]}, AGE_COLS, AGE_ROWS)["대상"]
    assert chk.status == S.missing


# ═════════════ 의도 ═════════════
def test_intent_trend_needs_two_years():
    chk = judge({"의도": "추이"}, AGE_COLS, AGE_ROWS)["의도"]
    assert chk.status == S.missing and chk.reason == ReasonCode.intent_mismatch


def test_intent_trend_ok():
    rows = [[str(y), "인구", 100] for y in (2021, 2022, 2023)]
    assert judge({"의도": "추이"}, ["시점", "항목", "값"], rows)["의도"].status == S.match
