"""11-23 live 실행(v8_core34)에서 찾은 판정기 결함의 회귀 테스트"""
from eval.generator.checks.m3 import AMBIGUOUS, asked_indicator, find_value
from eval.generator.schema import Question, ValueSpec
from eval.generator.verdict import judge
from tests.eval_generator._fx import record, run

SHARE_ALL_REGIONS = {"step_id": "a1", "op": "share", "unit": "%", "value": [
    {"key": {"시점": "2021", "시군구별": "전국"}, "value": 100.0},
    {"key": {"시점": "2021", "시군구별": "서울특별시"}, "value": 17.474152025237753}]}


def test_partial_key_match_narrowed_by_region():
    """11-23 live 실행 Q28: share 를 전국 포함 모든 지역에 계산 → key {시점} 에 두 점이 맞는다. 기대 지역(서울)으로 좁힌다"""
    vs = ValueSpec(role="FINAL", value=0.17474, unit="ratio", key={"시점": "2021"})
    c, p = find_value([SHARE_ALL_REGIONS], vs, "share", ["서울"])
    assert p["value"] == 17.474152025237753
    c, p = find_value([SHARE_ALL_REGIONS], vs, "share", [])
    assert p is AMBIGUOUS                                           # 지역 정보 없으면 판정하지 않는다


Q32 = Question.model_validate({
    "id": "Q32", "question": "최근 20년 서울, 부산 결혼 건수 비교",
    "sub_questions": [{"key": "cmp", "match": {"item_any": ["혼인건수", "결혼"], "region_any": ["서울", "부산"]}, "m3": {"op": "raw"}}]})


def _q32(item):
    rec = record("r", ["시점", "행정구역별(시도)", "성별", "연령별", "항목", "값"], [["2016", "서울특별시", "계", "합계", item, 440861.0]], "명")
    calc = {"step_id": "a1", "sub_question_id": "q1-1", "op": "raw", "unit": "명", "display_ref": "d1",
            "value": [{"key": {"시점": "2016"}, "value": 440861.0}], "record_ids": ["r"],
            "inputs": [{"role": "value", "record_id": "r", "item": item, "key": {"시점": "2016"}, "value": 440861.0}]}
    return run([rec], [calc], "서울특별시의 최근 20년간 결혼 건수는 2016년 440,861명입니다.", question=Q32.question,
               subs=["2006~2025년 서울특별시 부산광역시 서울", "2006~2025년 서울특별시 부산광역시 부산"])


def test_value_from_unasked_indicator_fails_even_if_unmatched():
    """11-23 live 실행 Q32: 질의 분석이 지역을 지표로 나눠 '항목=서울' 인 다른 표의 값을 '결혼 건수' 로 답함 → 하위 질문 대응과 무관하게 1단계 미달"""
    r = _q32("서울")
    assert [f.ok for f in asked_indicator(Q32, r)] == [False]
    assert judge(Q32, r).verdict == "미달"


def test_value_from_asked_indicator_passes_check():
    assert [f.ok for f in asked_indicator(Q32, _q32("혼인건수(건)"))] == []
