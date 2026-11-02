"""
[통합] Agent API  [NEW]

  POST /api/v1/chat           질문 하나 → ① 재작성 → ② 검색·View → ③ 답변  (전체 파이프라인 한 번에)
  POST /api/v1/agent/answer   ③ 만: 질문 + Record 목록 → 답변              (Swagger 에서 ①②③ 을 이어 붙여 테스트)
  POST /api/v1/chat/legacy    구 kosis_rag_qa.py ask (records.jsonl 하이브리드 인덱스) — 비교용
"""
from fastapi import APIRouter

from backend.agent.light_agent import answer, answer_from_records, run_chat
from backend.api.deps import guard
from backend.schemas.chat import AnswerRequest, AnswerResult, ChatRequest, ChatResponse, LegacyChatRequest

router = APIRouter(prefix="/api/v1", tags=["③ Agent 통합 (전체 파이프라인)"])


@router.post("/chat", response_model=ChatResponse, summary="★ 전체 파이프라인: 질문 → 재작성 → 검색·View → 답변")
def chat(body: ChatRequest):
    """HCX 호출: 재작성 1회 + 임베딩(캐시 없을 때) + 답변 1회. 각 단계 결과를 모두 돌려준다
    (rewrite → view_bundle → views/records → result, timings)."""
    with guard("chat: "):
        return run_chat(body.question, body.today, body.top_k, body.n_views, body.search_with, body.use_rewrite,
                        body.max_rows, body.save)


@router.post("/agent/answer", response_model=AnswerResult, summary="③ 질문 + Record 목록 → 답변 (HCX 1회)")
def agent_answer(body: AnswerRequest):
    """`POST /api/v1/rag/views` 응답을 records 에 그대로 붙여 넣는다.
    notes 를 넣으면(views/detail 의 views[].notes) 조건을 못 맞춘 카드는 근거로 덜 쓰고 insufficient 판단에 반영."""
    with guard("answer: "):
        return answer_from_records(body.question, [r.model_dump() for r in body.records], body.notes, body.titles,
                                   body.max_rows)


@router.post("/chat/legacy", summary="(legacy) 구 kosis_rag_qa.py ask — records.jsonl 하이브리드 인덱스 기반")
def chat_legacy(body: LegacyChatRequest):
    with guard("legacy: "):
        return answer(body.question, body.variant, k=body.k, use_rewrite=body.use_rewrite, max_rows=body.max_rows,
                      save=body.save)
