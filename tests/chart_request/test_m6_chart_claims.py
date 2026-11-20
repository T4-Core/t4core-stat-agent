"""T-12 · T-24: 모듈 6 은 차트 상태를 서술하지 않는다 — 차트 용법 + 생성·표시 서술의 결합만 거절하고, 같은 글자가 든 정상 문장은 통과한다

모듈 6 은 모듈 5 와 병렬이라 답변 시점에는 렌더링 결과를 알 수 없다. 차트 안내는 chart_notice.py 가 최종 상태 기준으로 따로 만든다.
"""
import pytest

from backend.agent.answer_compose.placeholder import chart_claim_problems
from backend.agent.prompts import ANSWER_COMPOSE_SYS


@pytest.mark.parametrize("text", [
    "{a1.r0.key} 인구는 {a1.r0}입니다. 막대로 보여 드립니다.",
    "시도별 인구를 원그래프로 나타냈습니다.",
    "그래프로 표시합니다.",
    "아래 그래프를 참고하세요.",
    "2023년 시도별 인구수에 대한 히스토그램 데이터는 다음과 같습니다: {a1}",
    "지도로 보여 드립니다.",
    "서울의 인구는 {a1}입니다. 꺾은선 그래프를 확인해 주세요.",
    "인구 피라미드 차트로 제공합니다.",
])
def test_chart_claims_are_rejected(text):
    assert chart_claim_problems(text), text


@pytest.mark.parametrize("text", [
    "2023년 운동지도자 수는 {a1}입니다.",                 # 지도자 (T-24)
    "서울의 지도자 수는 {a1}입니다.",
    "막대기 길이는 {a1}입니다.",
    "소방도로 면적은 {a1}입니다.",
    "혼인건수는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} {a1.dir}했습니다.",
    "시도별 인구 분포를 보면 경기도가 가장 많고 {a1.r0.key}가 {a1.r0}입니다.",
    "자세한 값은 아래 표에 있습니다.",                    # 표는 모듈 6 이 직접 만든다
    "도넛 가게 수는 {a1}입니다.",
    "",
])
def test_same_strings_in_normal_sentences_pass(text):
    assert chart_claim_problems(text) == []


def test_placeholders_are_ignored_when_looking_for_chart_words():
    assert chart_claim_problems("{a1.r0.key}의 막대 {a1.r0}") == []


def test_check_includes_chart_claims():
    """check() 가 chart_claim_problems 를 부른다 — 다른 검사를 통과한 답변이라도 차트 서술이 있으면 걸린다"""
    from backend.agent.answer_compose import placeholder
    assert "chart_claim_problems(template)" in open(placeholder.__file__, encoding="utf-8").read()


def test_system_prompt_forbids_chart_statements():
    assert "차트" in ANSWER_COMPOSE_SYS and "언급하지 않는다" in ANSWER_COMPOSE_SYS
