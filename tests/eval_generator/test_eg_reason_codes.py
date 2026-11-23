"""보류 사유 문장 → 평가기 사유 코드 (계획 2.4.3, D-15)"""
import re

import pytest

from backend.core import reasons
from eval.generator.reason_codes import CODES, classify

CASES = [
    ("분모로 쓸 총계 값이 없습니다", "missing_denominator"),
    ("분모가 0이라 계산할 수 없습니다", "zero_denominator"),
    ("단위가 달라 비교할 수 없습니다: 명 / 건", "unit_mismatch"),
    ("수록 주기가 달라 비교할 수 없습니다: Y / M", "cycle_mismatch"),
    ("'가구수' 항목이 자료에 없습니다", "item_mismatch"),
    ("요청한 지표(인구수, 인구)가 이 표에 없어 계산하지 못했습니다", "item_mismatch"),
    ("자료가 2025년 한 해뿐이라 해끼리 비교하지 못했습니다", "single_period"),
    ("한쪽 값이 없어 계산하지 못했습니다", "missing_value"),
    ("2008 값이 없습니다", "missing_period"),
    ("계산 중 오류가 발생해 계산하지 못했습니다", "internal_error"),
    ("계산에 쓸 자료를 찾지 못했습니다", "no_data"),
    ("같은 조건의 값이 여러 개라 계산하지 못했습니다", "duplicate_key"),
    ("전혀 새로운 문구", "unclassified"),
]


@pytest.mark.parametrize("text,code", CASES)
def test_classify(text, code):
    assert classify(text) == code


def _example(pattern: str) -> str:
    """core/reasons.py _RULES 의 원문 패턴에서 예시 문자열을 만든다 (그룹은 'X' 로)"""
    s = pattern.strip("^$").replace(".*", "").replace("(.+)", "X").replace("(.+?)", "X").replace("(\\S+)", "X")
    s = s.replace("(\\d+)", "3").replace("(?:없음|결과 없음)", "없음").replace("\\.", ".").replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\(\?:[^)]*\)", "", s)


def test_every_core_reason_rule_maps_to_one_code():
    """원문 note 패턴과 그 사용자 문장이 모두 하나의 코드로 정해진다. 미분류가 생기면 reason_codes.py 를 보강한다"""
    unmapped = []
    for pat, sentence in reasons._RULES:
        for text in (_example(pat.pattern), sentence.replace("{1}", "X").replace("{2}", "Y")):
            code = classify(text)
            assert code in CODES
            if code == "unclassified":
                unmapped.append(text)
    # 계산 방식 안내(기간 앞뒤 바꿈 · 항목 대체)는 보류 사유가 아니라 미분류가 정상이다
    allowed = ("기간의 앞뒤", "항목 대신", "기간이 거꾸로", "로 계산함", "로 바꿈", "부호", "음수", "합산할 값", "combine",
               "짝지을", "결합 열", "join_on", "비교할 시점", "기간이 0년", "연수가", "시점 표기", "연수를", "기준 값이 0 이하",
               "기준값이 0 이하", "정할 수 없", "두 번", "총계 행", "서로 다른 지표", "denominator", "비교할 값이 하나뿐",
               "앞 단계", "앞 계산")
    left = [t for t in unmapped if not any(a in t for a in allowed)]
    assert not left, left
