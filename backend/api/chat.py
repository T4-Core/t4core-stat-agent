"""
③ 답변 · 통합 파이프라인 API

  POST /api/v1/chat           질문 → 분석 → 검색·View → 답변 (중간에 멈추면 status 로 알려 주고, previous 로 이어서)
  POST /api/v1/agent/answer   질문 + Record 목록 → 답변만
  POST /api/v1/agent/modules  ViewSet → 모듈 2→3→5→6 (차트 계획 → 계산 → 그림 → 답변 문장·근거 표)
"""
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from backend.agent.answer import answer_from_records
from backend.agent.pipeline import run_chat
from backend.api.deps import guard
from backend.schemas.chat import AnswerRequest, AnswerResult, ChatRequest, ChatResponse, ModulesRequest

TAG = "③ 답변 · 통합 파이프라인"
router = APIRouter(prefix="/api/v1", tags=[TAG])


@router.post("/chat", response_model=ChatResponse, summary="★ 질문 → 분석 → 검색·View → 답변")
def chat(body: ChatRequest):
    """HCX 호출: 재작성 1회 + 임베딩(캐시 없을 때) + 답변 1회.

    - **ok**: `result` 에 답변·차트·출처
    - **needs_clarification**: `analysis.clarifications` 에서 골라 `{previous: 이 응답, selections: {슬롯: [값]}}`
    - **needs_selection** (`auto_select=false`): `views.pending` 에서 골라 `{previous: 이 응답, view_selections: [...]}`
    - **out_of_scope**: 검색하지 않고 안내 답변

    `answer_mode=modules` 이면 답변 대신 모듈 2→3→5→6 을 돌린다 (HCX: 모듈 2 0~1회 + 모듈 3 1회 + 모듈 6 1~2회).
    결과 전체는 `modules`, 답변 문장·출처·주의사항은 `result` 에도 같은 모양으로 들어간다."""
    with guard("chat: "):
        if body.pipeline and body.pipeline != "default":
            from backend.core import plugins
            if body.pipeline not in plugins.available():
                raise HTTPException(400, f"파이프라인 '{body.pipeline}' 없음. 사용 가능: {list(plugins.available())}")
            out = plugins.get(body.pipeline)(body.question, body.today, body.top_k, body.n_views, max_rows=body.max_rows)
            return JSONResponse(jsonable_encoder(out))
        return run_chat(body.question, body.today, body.top_k, body.n_views, body.max_rows, body.auto_select,
                        body.overrides, body.previous, body.selections, body.view_selections, body.save,
                        body.answer_mode, body.draw)


@router.post("/agent/answer", response_model=AnswerResult, summary="질문 + Record 목록 → 답변 (HCX 1회)")
def agent_answer(body: AnswerRequest):
    """`POST /api/v1/rag/views` 응답의 records 를 그대로 붙여 넣는다.
    notes 를 넣으면 조건을 못 맞춘 카드는 근거로 덜 쓰고 insufficient 판단에 반영"""
    with guard("answer: "):
        return answer_from_records(body.question, [r.model_dump() for r in body.records], body.notes, body.titles,
                                   body.max_rows)


@router.post("/agent/modules", summary="ViewSet → 모듈 2→3→5→6 (차트 계획 → 계산 → 그림 → 답변 문장·근거 표)")
def agent_modules(body: ModulesRequest):
    """`POST /api/v1/rag/views` 응답을 그대로 `views` 에 넣는다. 단계별로 보려면 /chart/decide → /chart/calc → /answer/compose.

    - 충돌 선택이 끝난 카드(`views.records`)만 쓴다. `status` 가 ok 가 아니면 409
    - 역할 단위(분모·조건)는 따로 답할 질문이 아니라서 모듈 2·3 의 질문에서 빼고, 그 View 를 모든 세트에 붙인다"""
    with guard("modules: "):
        vs = body.views.model_dump(mode="json")
        if vs.get("status") != "ok":
            raise HTTPException(409, f"views.status 가 ok 가 아님 ({vs.get('status')}) — 되묻기·선택을 먼저 끝내야 함")
        from backend.agent.modules import run_modules
        return JSONResponse(jsonable_encoder(run_modules(vs, use_llm_chart=body.use_llm_chart, draw=body.draw,
                                                         max_rows=body.max_rows)))
