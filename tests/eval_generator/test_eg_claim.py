"""claim 추출 · claim 기반 binding · 근거 가시성 · 인과 단정 규칙의 단위 테스트와 과거 실행 오탐 회귀"""
from decimal import Decimal

import pytest

from eval.generator import binding
from eval.generator.checks import m6
from eval.generator.claim import numeric_claims
from eval.generator.schema import Question
from tests.eval_generator._fx import record, run


@pytest.mark.parametrize("text,value,unit", [
    ("23만 8,317명", 238317, "명"), ("934만 명", 9340000, "명"), ("1억 2천만 원", 120000000, "원"),
    ("−120,252명", -120252, "명"), ("2.5%p", Decimal("2.5"), "%p"), ("17.5%", Decimal("17.5"), "%")])
def test_korean_quantity_merge(text, value, unit):
    c, = numeric_claims(text)
    assert (c.value, c.unit) == (value, unit)


def test_period_rank_and_per_capita_are_not_claims():
    assert [c.text for c in numeric_claims("2024년 3월 1위, 여성 1명당 0.748명")] == ["0.748명"]


def test_denominator_region_is_skipped():
    c, = numeric_claims("2024년 서울의 출생아 비중은 전국 대비 17.5%입니다.")
    assert c.region == "서울"


def test_no_binding_expectation_is_na_not_pass():
    """binding 기대가 없으면 semantic_ok=None (검증하지 않은 값을 100% 로 세지 않는다)"""
    b = binding.check("2024년 서울 100명입니다.", 100, "명", None)
    assert b.numeric_match and b.semantic_ok is None


def test_level_values_in_decreasing_trend_keep_positive_sign():
    """과거 실행 run5 Q17: '640,089명 … 238,317명으로 감소' 의 양수 수준값은 부호 위반이 아니다"""
    b = binding.check("2000년의 출생아수는 640,089명였고, 2024년의 출생아수는 238,317명으로 감소했습니다.", 640089, "명", None)
    assert b.sign_ok is True


def test_negative_value_needs_sign_or_direction():
    assert binding.check("순이동 20명 순유출입니다.", -20, "명", None).sign_ok is True
    assert binding.check("순이동 20명 순유입입니다.", -20, "명", None).sign_ok is False
    assert binding.check("순이동 20명입니다.", -20, "명", None).sign_ok is None


LIST = {"step_id": "a1", "sub_question_id": "q1-1", "op": "raw", "unit": "명", "display_ref": "d1", "record_ids": ["r"],
        "value": [{"key": {"시점": str(y)}, "value": float(1000 + y)} for y in range(1981, 2000)],
        "inputs": []}
REC = record("r", ["시점", "항목", "값"], [[str(y), "출생아수", float(1000 + y)] for y in range(1981, 2000)], "명")
Q = Question.model_validate({"id": "Q31", "question": "80~90년대 대구 출생아수는?"})


def _shown(r, toks):
    r["m6_shown_tokens"] = toks
    return r


def test_count_phrases_are_not_citations():
    """과거 실행 run12 Q31: '외 14개' · '19개 중' 은 목록 개수 표현이다"""
    r = _shown(run([REC], [LIST], "1981년 2,981명, 1982년 2,982명 외 17개입니다. 19개 중 일부입니다.", question=Q.question),
               ["a1.r0", "a1.r1"])
    rows = [f for f in m6.visibility_checks(Q, r) if f.code == "invisible_citation"]
    assert [f.ok for f in rows] == [True]


def test_value_outside_prompt_preview_is_invisible_for_llm_answer():
    r = _shown(run([REC], [LIST], "1995년 2,995명입니다.", question=Q.question), ["a1.r0", "a1.r1"])
    assert [f.ok for f in m6.visibility_checks(Q, r) if f.code == "invisible_citation"] == [False]


def test_template_answer_is_not_checked_for_visibility():
    """과거 실행 v8 Q31: 템플릿 답변은 코드가 결과 전체에서 쓴다 → 가시 문맥 제약 대상이 아니다"""
    r = _shown(run([REC], [LIST], "가장 큰 값은 1995년 2,995명입니다.", question=Q.question, method="template"), ["a1.r0"])
    assert not [f for f in m6.visibility_checks(Q, r) if f.code == "invisible_citation"]


def test_arithmetic_restatement_is_not_causal_claim():
    """과거 실행 run3 Q12: 계산 입력값을 다시 말하는 '~이기 때문입니다' 는 산술 설명이다"""
    calcs = [{"step_id": "a1", "op": "raw", "value": 238317.0, "inputs": []},
             {"step_id": "a2", "op": "raw", "value": 358569.0, "inputs": []},
             {"step_id": "a3", "op": "diff", "value": -120252.0, "inputs": []}]
    text = "뺀 값은 -120,252명입니다. 이는 출생아수가 238,317명이고, 사망자수가 358,569명이기 때문입니다."
    assert not m6.causal_checks(Q, run([], calcs, text))
    assert [f.ok for f in m6.causal_checks(Q, run([], calcs, text + " 출산율 하락은 정책 때문입니다."))] == [False]


@pytest.mark.parametrize("q,n", [("소수 셋째 자리까지 알려줘", 3), ("소수점 둘째 자리", 2), ("소수 1자리", 1), ("비중은?", None)])
def test_asked_digits(q, n):
    assert m6.asked_digits(q) == n


# ── isolated 시범 실행(R06 · S12 · C06)에서 찾은 채점기 결함 회귀 ──
def test_month_period_binding():
    """S12: '2024-12 120건' 의 기간은 2024-12 다 (연도 2024 와 비교해 불일치로 판정했다)"""
    text = "가장 큰 값은 2024-12 120건, 가장 작은 값은 2024-01 10건입니다."
    assert binding.check(text, 120, "건", {"period": ["2024-12"]}).semantic_ok is True
    assert binding.check(text, 120, "건", {"period": ["2024-11"]}).semantic_ok is False
    assert [c.text for c in numeric_claims(text)] == ["120건", "10건"]      # '-12' · '-01' 은 월이지 숫자 claim 이 아니다


def test_number_with_comma_after_year_dash():
    """isolated 전체 실행: '2024-1,234' 처럼 연도-뒤 숫자에 콤마가 있으면 월 판정에서 예외가 났다"""
    assert [c.value for c in numeric_claims("2023-2024 1,234명, 2024-1,234명")] == [1234, 1234]


def test_scalar_result_has_no_key():
    """R06: share 단일 값 결과(key 없음)를 기대 key {시점: 2024} 때문에 실패로 판정했다"""
    from eval.generator.checks.m3 import find_value
    from eval.generator.schema import ValueSpec
    c = {"step_id": "a1", "op": "share", "unit": "%", "value": 17.4578}
    assert find_value([c], ValueSpec(value=0.174578, unit="ratio", key={"시점": "2024"}), "share")[1]["value"] == 17.4578


def test_multi_op_subquestion_matches_by_unit():
    """C06: 연산이 raw + share 인 하위 질문에서 원값 claim(20명)을 구성비 결과와 비교했다"""
    from eval.generator.checks.m3 import find_value
    from eval.generator.schema import ValueSpec
    share = {"step_id": "a1", "op": "share", "unit": "%", "value": [{"key": {"시점": "2024", "지역": "서울특별시"}, "value": 16.67}]}
    assert find_value([share], ValueSpec(value=20, unit="명", key={"시점": "2024"}), None) == (None, None)
    assert find_value([share], ValueSpec(value=0.1667, unit="ratio", key={"시점": "2024"}), None)[1]["value"] == 16.67


# ── isolated 전체 실행(C04 · S06 · S04)에서 찾은 채점기 오탐 회귀 ──
AGE = {"step_id": "a1", "sub_question_id": "q1-1", "op": "raw", "unit": "명", "record_ids": ["r"], "inputs": [],
       "value": [{"key": {"시점": "2024", "연령": "0~4세"}, "value": 10.0}, {"key": {"시점": "2024", "연령": "5~9세"}, "value": 11.0}]}


def test_age_band_label_is_not_citation():
    """C04: '0~4세 남자: 10명' 의 '4세' 는 프롬프트에 실린 key 레이블이다"""
    r = _shown(run([REC], [AGE], "0~4세: 10명, 5~9세: 11명", question="합성 인구 피라미드"),
               ["a1.r0", "a1.r0.key", "a1.r1", "a1.r1.key"])
    assert [f.ok for f in m6.visibility_checks(Q, r) if f.code == "invisible_citation"] == [True]
    r["m6_shown_tokens"] = ["a1.r0", "a1.r1"]                          # key 가 프롬프트에 없으면 여전히 근거 없음
    assert [f.ok for f in m6.visibility_checks(Q, r) if f.code == "invisible_citation"] == [False]


def test_bracket_label_copied_from_question_is_not_citation():
    """S06: 질문의 '[합성 자료 검증]' 을 답변이 되풀이한 것은 근거 라벨 인용이 아니다"""
    q = Question.model_validate({"id": "S06", "question": "[합성 자료 검증] 가상 인구는?", "citation_labels": ["E1"]})
    r = run([REC], [LIST], "[합성 자료 검증] 가상 인구는 934만 명입니다 [E2].", question=q.question, method="template")
    f, = [f for f in m6.visibility_checks(q, r) if f.code == "invisible_citation"]
    assert f.detail["labels"] == ["E2", "합성 자료 검증"] and "E2" in f.message and "합성" not in f.message


def test_ratio_claim_is_not_matched_to_pp_without_display():
    """S04: 표시 정보가 없을 때 기본 허용오차 0.5 로 20.0%(0.2) 를 pp 기대값 0.025 와 일치로 판정했다"""
    from eval.generator.schema import SubQuestion
    from eval.generator.subq import OutSub, SubResult
    spec = SubQuestion.model_validate({"key": "pp", "m3": {"op": "diff"}, "values": [{"value": 0.025, "unit": "pp"}]})
    growth = {"step_id": "a2", "op": "growth_rate", "unit": "%", "value": 20.0, "inputs": []}
    rr = run([], [growth], "상대 증감률은 20.0%입니다.")
    fs = m6.value_checks(spec, SubResult(spec.key, "q1-1", "matched", "value", False, [], OutSub("q1-1", "", calcs=[growth])), rr)
    assert [(f.code, f.ok) for f in fs] == [("final_in_answer", False)]


def test_missing_region_point_is_omission_not_ambiguous():
    """v2 slots C15: M3 가 '나시' 를 빼고 계산했는데, 좁히기 전 후보로 되돌아가 모호(수동) → 통과로 판정했다"""
    from eval.generator.checks.m3 import MISSING, find_value
    from eval.generator.schema import ValueSpec
    calc = {"step_id": "a1", "op": "raw", "unit": "명", "value": [
        {"key": {"시점": "2023", "지역": "가시"}, "value": 20}, {"key": {"시점": "2023", "지역": "다시"}, "value": 40}]}
    vs = ValueSpec.model_validate({"value": 30, "unit": "명", "key": {"시점": "2023"}, "binding": {"region": ["나시"]}})
    assert find_value([calc], vs, "raw") == (None, MISSING)
    ok = ValueSpec.model_validate({"value": 40, "unit": "명", "key": {"시점": "2023"}, "binding": {"region": ["다시"]}})
    assert find_value([calc], ok, "raw")[1]["value"] == 40
    other = {"step_id": "a1", "op": "raw", "unit": "명", "value": [
        {"key": {"시점": "2022", "성별": "남자"}, "value": 10}, {"key": {"시점": "2022", "성별": "여자"}, "value": 20}]}
    g = ValueSpec.model_validate({"value": 10, "unit": "명", "key": {"시점": "2022"}, "binding": {"region": ["가상시"]}})
    assert find_value([other], g, "raw")[1] is not MISSING          # 지역 차원이 없는 결과 점은 누락 판정 대상이 아니다
