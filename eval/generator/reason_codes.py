"""보류 사유 문장 → 평가기 사유 코드 (계획 2.4.3, D-15)

모듈 3 에 사유 코드 필드가 없어 Withheld.text · CalcResult.note · chart_plan.warnings 의 문장에서 도출한다.
원문 note 패턴은 core/reasons.py 의 _RULES, 사용자 문장은 그 변환 결과에 대응한다. 모르는 문구는 unclassified (수동 판정).
operands_valid(resolve.py)의 사유 코드와 같은 집합을 쓴다.
"""
import re

CODES = ("no_data", "missing_operand", "missing_denominator", "missing_value", "zero_denominator", "period_mismatch",
         "cycle_mismatch", "unit_mismatch", "population_mismatch", "missing_period", "single_period", "item_mismatch",
         "duplicate_key", "truncated", "internal_error", "unclassified")

# (정규식, 코드). 위에서부터 처음 맞는 것. 구체적인 사유를 먼저 둔다
_RULES: list[tuple[re.Pattern, str]] = [(re.compile(p), c) for p, c in [
    (r"내부 오류|오류가 발생", "internal_error"),
    (r"분모 ?0|분모가 0|기준값 ?0|기준 ?값이 0|0이라 나눌", "zero_denominator"),
    (r"수록 주기", "cycle_mismatch"),
    (r"단위가 (다름|달라|다른)|단위.*(맞지 않|다릅)|단위를 확인할 수 없", "unit_mismatch"),
    (r"키 중복|같은 조건의 값이 여러 개", "duplicate_key"),
    (r"truncated|행이 잘려", "truncated"),
    (r"선택한 항목이 하나뿐이라 비중", "missing_denominator"),
    (r"분모.*(없|찾지|세트 밖|정하지)|전국.*(없어|없습니다).*(비중|비율)|(비중|비율).*전국.*없", "missing_denominator"),
    (r"모집단|대상이 (다름|달라)", "population_mismatch"),
    (r"항목 없음|항목이 자료에 없|지표.*(없어|없습니다|찾지 못해)|표에 없어|맞는 항목 없음|맞는 코드 없음", "item_mismatch"),
    (r"View 없음|자료를 찾지 못|지표를 찾지 못했습니다|records 가 비어", "no_data"),
    (r"한 해뿐|하나뿐", "single_period"),
    (r"한쪽 값 없음|값이 비어|값이 없어|결측|^값 없음 \(", "missing_value"),
    (r"피연산자 없음|값을 정하지 못|지역.*(없어|없습니다)|자료에 없는 지역|조건에 맞는 값이 없|열 없음|열이 없습니다"
     r"|^(?!시점)\S+에 없는 값|^\S+에 \S+이\(가\) 없습니다", "missing_operand"),
    (r"수록 시점|시점 .* 값 없음|기준 시점 .* 값 없음|\d{4}(년)?.*(자료|값)(가|이)? ?없|시점에 없는 값|값이 없습니다|자료가 없습니다$",
     "missing_period"),
]]

# QA A0 중단 종류 → 사유 코드 (qa_nodes.check_input)
A0_KIND = {"no_data": "no_data", "indicator_not_found": "item_mismatch", "enum": "no_data"}


def classify(text: str | None) -> str:
    t = (text or "").strip()
    if not t:
        return "unclassified"
    for pat, code in _RULES:
        if pat.search(t):
            return code
    return "unclassified"


def codes_of(texts: list[str | None]) -> list[str]:
    return list(dict.fromkeys(classify(t) for t in texts if t))
