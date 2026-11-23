"""operands_valid (계획 2.2.1, D-22 · D-26) · 원본 행 복원 (D-25)"""
from eval.generator import resolve as R
from tests.eval_generator._fx import REC_BIRTH, births, record

SEOUL = {"region": "서울", "period": "2024", "item": "출생아수"}
NATION = {"region": "전국", "period": "2024", "item": "출생아수"}


def test_q05_both_rows_answer():
    assert R.operands_valid([births()], [SEOUL], NATION, op="share").ok


def test_q05_national_only_is_missing_operand():
    p = R.operands_valid([births(seoul=False)], [SEOUL], NATION, op="share")
    assert (p.ok, p.reason) == (False, "missing_operand")


def test_missing_denominator():
    p = R.operands_valid([births(national=False)], [SEOUL], NATION, op="share")
    assert p.reason == "missing_denominator"


def test_zero_denominator():
    assert R.operands_valid([births(national_value=0)], [SEOUL], NATION, op="share").reason == "zero_denominator"


def test_missing_value():
    rec = births()
    rec["table"]["rows"][1][3] = "-"
    assert R.operands_valid([rec], [SEOUL], NATION, op="share").reason == "missing_value"


def test_period_mismatch():
    rec = record("r", ["시점", "시군구별", "항목", "값"], [["2024", "서울특별시", "출생아수", 1.0], ["2023", "전국", "출생아수", 2.0]], "명")
    p = R.operands_valid([rec], [SEOUL], {**NATION, "period": "2023"}, op="share")
    assert p.reason == "period_mismatch"


def test_population_mismatch():
    rec = record("r", ["시점", "시군구별", "성별", "항목", "값"],
                 [["2024", "서울특별시", "남자", "출생아수", 1.0], ["2024", "전국", "계", "출생아수", 2.0]], "명")
    p = R.operands_valid([rec], [{**SEOUL, "성별": "남자"}], {**NATION, "성별": "계"}, op="share")
    assert p.reason == "population_mismatch"


def test_ambiguous_row_goes_manual():
    rec = record("r", ["시점", "시군구별", "구분", "항목", "값"],
                 [["2024", "서울특별시", "A", "출생아수", 1.0], ["2024", "서울특별시", "B", "출생아수", 2.0], ["2024", "전국", "계", "출생아수", 9.0]], "명")
    p = R.operands_valid([rec], [SEOUL], NATION, op="share")
    assert (p.reason, "manual" in p.tags) == ("ambiguous_row", True)


# ── 단위 정합은 연산별 (D-26) ──
POP = record("pop", ["시점", "시도별", "항목", "값"], [["2024", "서울특별시", "인구(명)", 100.0]])
AREA = record("area", ["시점", "시도별", "항목", "값"], [["2024", "서울특별시", "면적(㎢)", 2.0]])
POP_C = {"region": "서울", "period": "2024", "item": "인구"}
AREA_C = {"region": "서울", "period": "2024", "item": "면적"}


def test_ratio_allows_different_dimensions():
    p = R.operands_valid([POP, AREA], [POP_C, AREA_C], op="ratio", result_unit="명/㎢")
    assert p.ok                                                       # 100명 ÷ 2㎢ = 50 명/㎢ 는 정상
    assert R.operands_valid([POP, AREA], [POP_C, AREA_C], op="ratio", result_unit="배").reason == "unit_mismatch"


def test_share_requires_same_unit():
    assert R.operands_valid([POP, AREA], [POP_C], AREA_C, op="share").reason == "unit_mismatch"


def test_combine_thousand_and_person_convertible():
    a = record("a", ["시점", "시도별", "항목", "값"], [["2024", "부산광역시", "인구(천명)", 1.0]])
    p = R.operands_valid([a, POP], [{"region": "부산", "period": "2024", "item": "인구"}, POP_C], op="combine")
    assert (p.reason, "convertible_unit" in p.tags) == ("unit_mismatch", True)


def test_cycle_mismatch():
    m = record("m", ["시점", "시도별", "항목", "값"], [["2024", "서울특별시", "인구(명)", 100.0]], prd_se="M")
    p = R.operands_valid([m, AREA], [POP_C, AREA_C], op="ratio")
    assert p.reason == "cycle_mismatch"


# ── 원본 행 복원 ──
def test_resolve_input_restores_fixed_region_by_value():
    """CalcInput.key 는 고정 차원(지역)을 생략한다: {'시점': '2024'} → 값으로 서울 행을 특정 (분모 입력에 분자의 select 를 쓰지 않는다)"""
    recs = [births()]
    part = {"record_id": REC_BIRTH, "item": "출생아수", "key": {"시점": "2024"}, "value": 41605.0}
    total = {"record_id": REC_BIRTH, "item": "출생아수", "key": {"시점": "2024"}, "value": 238317.0}
    sel = {"시군구별": ["서울특별시"], "시점": ["2024"]}
    assert R.resolve_input(recs, part, sel)[0].coord()["region"] == "서울특별시"
    assert R.resolve_input(recs, total, sel)[0].coord()["region"] == "전국"


def test_item_in_classification_column():
    """지표 이름이 '항목' 이 아닌 분류 열(종류별)에 있는 View (Q14 · Q20)"""
    rec = record("r", ["시점", "행정구역별", "종류별", "항목", "값"], [["2025", "전국", "혼인건수(건)", "출생사망혼인이혼", 240326.0]])
    row, why = R.resolve_input([rec], {"record_id": "r", "item": "혼인건수(건)", "key": {"시점": "2025"}, "value": 240326.0})
    assert why is None and R.row_unit(row) == "건"
    assert R.find_one([rec], {"item": "혼인건수", "period": "2025"})[0] is not None
