"""QualityVerifierAgent — 결정론적 검증을 통과한 레코드만 받아 의미 품질을 검수한다.

- 출력은 QualityReview (Pydantic Structured Output).
- LLM 검수는 결정론적 수치 검증 실패를 무효화하거나 PASS 로 바꿀 수 없다 (호출 측에서 강제).
- 모호성이 있으면 질문 문장만 제한된 횟수 수정하고, 수정본은 같은 결정론적 검사를 다시 통과해야 한다 (Ground Truth 불변).
"""
from __future__ import annotations

import json
import re

from synthetic_gold_pipeline.agents.llm_client import BaseLLMClient, MockLLMClient
from synthetic_gold_pipeline.agents.reverse_qa_agent import region_short
from synthetic_gold_pipeline.schemas.verification import QualityReview

TASK = "quality_verifier"

SYSTEM_PROMPT = """당신은 국가통계 평가셋 검수자입니다. 아래 질문·모범 답변·근거 Fact·연산 계획을 읽고 의미 품질만 판단합니다.
수치는 이미 계산 도구가 검증했으므로 다시 계산하지 않습니다.

판단 항목
- semantic_valid: 질문이 실제 Fact 를 정확하게 요구하는가. facts.question_intent(계산 의미)와 질문이 같은 것을 묻는지 확인
  (예: 의도가 '…보다 많은 지역의 개수' 인데 질문이 '차이' 를 물으면 false)
- question_answer_alignment: 모범 답변이 질문에 직접 답하는가
- ambiguity_detected / missing_conditions: 누락된 조건(시점·지역·모집단·단위·집계 기준) 때문에 다른 정답이 가능한가
- statistical_validity: 잘못된 통계적 비교나 인과관계 해석이 있는가 (있으면 false)
- multi_hop_necessity: 모든 필수 근거 View 가 질문에 의미 있게 기여하는가 (무관한 두 질문을 이어 붙인 형태면 false).
  같은 표의 두 시점 비교·같은 표의 두 분류 비교도 두 View 가 모두 필요하면 true
- paraphrase_equivalence: question_paraphrased 가 question_original 과 같은 의미·조건인가
- natural_question: 통계를 찾는 실제 사용자가 물을 법한 질문인가. 서로 관련 없는 지표를 억지로 나누거나 비교하면
  (예: 혼인 건수 ÷ 외국인 입국자, 비율 ÷ 평균), 조건이 너무 많아 한 번에 읽히지 않으면 false
- rejection_reasons: 문제가 있으면 구체적 이유
- suggested_revision: 모호성만 있을 때, 숫자를 새로 넣지 않고 조건을 보충한 question_original 수정안 (없으면 null)
JSON 하나만 출력합니다."""


class QualityVerifierAgent:
    def __init__(self, llm: BaseLLMClient, cfg: dict | None = None):
        self.llm = llm
        self.cfg = cfg or {}
        if isinstance(llm, MockLLMClient):
            llm.register(TASK, mock_quality_response)

    async def review(self, payload: dict) -> tuple[QualityReview, dict]:
        user = "<record>\n" + json.dumps(payload, ensure_ascii=False) + "\n</record>"
        return await self.llm.generate_structured(TASK, SYSTEM_PROMPT, user, QualityReview, context={"record": payload})


def review_payload(question_original: str, question_paraphrased: str, reference_answer: str, bundle_input: dict,
                   n_views: int, n_tables: int) -> dict:
    return {"question_original": question_original, "question_paraphrased": question_paraphrased,
            "reference_answer": reference_answer, "facts": bundle_input, "n_required_views": n_views,
            "n_required_tables": n_tables}


def mock_quality_response(ctx: dict) -> dict:
    """Demo Mode 규칙 검수 (조건 보존·Multi-View 여부만 확인 — 실제 의미 검수를 대신하지 않음)."""
    r = ctx["record"]
    q1, q2 = r["question_original"], r["question_paraphrased"]
    facts = r["facts"]
    reasons, missing = [], []
    years = {re.sub(r"\D", "", o["period"])[:4] for o in facts["operands"]}
    for y in years:
        if y not in q1:
            missing.append(f"시점 {y}")
        if y not in q2:
            reasons.append(f"paraphrase 에서 시점 {y} 누락")
    regs = {f["region"] for f in facts["scalar_facts"] if f.get("region")}
    for g in regs:
        if g not in q1:
            missing.append(f"지역 {g}")
        if g not in q2 and region_short(g) not in q2:
            reasons.append(f"paraphrase 에서 지역 {g} 누락")
    multi = r["n_required_views"] >= 2
    if not multi:
        reasons.append("필수 View 가 1개 — Multi-View 문제가 아님")
    causal = bool(re.search(r"때문에|원인은|덕분에|영향으로", r["reference_answer"]))
    if causal:
        reasons.append("인과관계 해석 포함")
    return {"semantic_valid": not missing, "question_answer_alignment": True, "ambiguity_detected": bool(missing),
            "missing_conditions": missing, "multi_hop_necessity": multi,
            "paraphrase_equivalence": not any("paraphrase" in x for x in reasons), "statistical_validity": not causal,
            "rejection_reasons": reasons + [f"조건 누락: {m}" for m in missing], "suggested_revision": None}
