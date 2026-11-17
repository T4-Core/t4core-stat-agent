"""
③ 답변 · 통합 파이프라인 API

  POST /api/v1/chat           질문 → 분석 → 검색·View → 답변 (중간에 멈추면 status 로 알려 주고, previous 로 이어서)
  POST /api/v1/agent/answer   질문 + Record 목록 → 답변만
"""
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from backend.agent.answer import answer_from_records
from backend.agent.pipeline import run_chat
from backend.api.deps import guard
from backend.schemas.chat import AnswerRequest, AnswerResult, ChatRequest, ChatResponse

TAG = "③ 답변 · 통합 파이프라인"
router = APIRouter(prefix="/api/v1", tags=[TAG])


@router.post("/chat", response_model=ChatResponse, summary="★ 질문 → 분석 → 검색·View → 답변")
def chat(body: ChatRequest):
    """HCX 호출: 재작성 1회 + 임베딩(캐시 없을 때) + 답변 1회.

    - **ok**: `result` 에 답변·차트·출처
    - **needs_clarification**: `analysis.clarifications` 에서 골라 `{previous: 이 응답, selections: {슬롯: [값]}}`
    - **needs_selection** (`auto_select=false`): `views.pending` 에서 골라 `{previous: 이 응답, view_selections: [...]}`
    - **out_of_scope**: 검색하지 않고 안내 답변"""
    with guard("chat: "):
        if body.pipeline and body.pipeline != "default":
            from backend.core import plugins
            if body.pipeline not in plugins.available():
                raise HTTPException(400, f"파이프라인 '{body.pipeline}' 없음. 사용 가능: {list(plugins.available())}")
            out = plugins.get(body.pipeline)(body.question, body.today, body.top_k, body.n_views, max_rows=body.max_rows)
            return JSONResponse(jsonable_encoder(out))
        return run_chat(body.question, body.today, body.top_k, body.n_views, body.max_rows, body.auto_select,
                        body.overrides, body.previous, body.selections, body.view_selections, body.save)


@router.post("/agent/answer", response_model=AnswerResult, summary="질문 + Record 목록 → 답변 (HCX 1회)")
def agent_answer(body: AnswerRequest):
    """`POST /api/v1/rag/views` 응답의 records 를 그대로 붙여 넣는다.
    notes 를 넣으면 조건을 못 맞춘 카드는 근거로 덜 쓰고 insufficient 판단에 반영"""
    with guard("answer: "):
        return answer_from_records(body.question, [r.model_dump() for r in body.records], body.notes, body.titles,
                                   body.max_rows)
