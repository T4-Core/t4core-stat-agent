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


def _previous_from_session(body: ChatRequest):
    """이어가기(selections · view_selections)인데 previous 가 없으면 세션(Redis)의 직전 응답"""
    if body.previous is not None or not (body.selections or body.view_selections) or not body.session_id:
        return body.previous
    from backend.db import sessions
    st = sessions.store()
    if st is None:
        raise HTTPException(400, "previous 가 필요합니다 (서버에 세션 저장(REDIS_URL)이 꺼져 있음)")
    try:
        prev = st.previous(body.session_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"세션 저장소(Redis)에 연결하지 못했습니다: {e.__class__.__name__}")
    if not prev:
        raise HTTPException(409, "세션이 만료되었거나 없습니다. 질문을 처음부터 다시 보내 주세요.")
    return prev


@router.post("/chat", response_model=ChatResponse, summary="★ 질문 → 분석 → 검색·View → 답변")
def chat(body: ChatRequest):
    """HCX 호출: 재작성 1회 + 임베딩(캐시 없을 때) + 답변 1회.

    - **ok**: `result` 에 답변·차트·출처
    - **needs_clarification**: `analysis.clarifications` 에서 골라 `{previous: 이 응답, selections: {슬롯: [값]}}`
    - **needs_selection** (`auto_select=false`): `views.pending` 에서 골라 `{previous: 이 응답, view_selections: [...]}`
    - **out_of_scope**: 검색하지 않고 안내 답변

    `answer_mode=modules` 이면 답변 대신 모듈 2→3→5→6 을 돌린다 (HCX: 모듈 2 0~1회 + 모듈 3 1회 + 모듈 6 1~2회).
    결과 전체는 `modules`, 답변 문장·출처·주의사항은 `result` 에도 같은 모양으로 들어간다.

    `session_id` 를 주면 진행 상태와 응답을 Redis 에 둔다 (GET /api/v1/sessions/{id}, 이어갈 때 previous 생략 가능).
    CHAT_HISTORY=on 이면 PostgreSQL(app.chat_turn)에 이력을 남긴다."""
    import time
    from backend.db import history, sessions
    previous = _previous_from_session(body)
    st = sessions.store() if body.session_id else None
    if st is not None:
        sessions.safe(st.start, body.session_id, body.question)
    t0 = time.time()
    try:
        out = _chat(body, previous)
    except Exception as e:
        detail = e.detail if isinstance(e, HTTPException) else f"{e.__class__.__name__}: {str(e)[:300]}"
        if st is not None:
            sessions.safe(st.fail, body.session_id, detail)
        history.record(body.session_id, body.model_dump(mode="json"), None, str(detail),
                       int((time.time() - t0) * 1000))
        raise
    data = jsonable_encoder(out)
    if body.session_id:
        data["session_id"] = body.session_id
        if st is not None:
            sessions.safe(st.finish, body.session_id, data)
    history.record(body.session_id, body.model_dump(mode="json"), data, None, int((time.time() - t0) * 1000))
    return JSONResponse(data)


def _chat(body: ChatRequest, previous):
    """파이프라인 실행 (세션·이력 처리는 chat() 에서)"""
    with guard("chat: "):
        if body.pipeline and body.pipeline != "default":
            from backend.core import plugins
            if body.pipeline not in plugins.available():
                raise HTTPException(400, f"파이프라인 '{body.pipeline}' 없음. 사용 가능: {list(plugins.available())}")
            return plugins.get(body.pipeline)(body.question, body.today, body.top_k, body.n_views, max_rows=body.max_rows)
        out = run_chat(body.question, body.today, body.top_k, body.n_views, body.max_rows, body.auto_select,
                       body.overrides, previous, body.selections, body.view_selections, body.save,
                       body.answer_mode, body.draw)
        return ChatResponse.model_validate(out).model_dump(mode="json")


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
        from backend.agent.qa import run_modules_with_qa      # QA: 모듈 사이마다 형식 검사·대응 (backend/agent/qa)
        return JSONResponse(jsonable_encoder(run_modules_with_qa(vs, use_llm_chart=body.use_llm_chart, draw=body.draw,
                                                                 max_rows=body.max_rows)))
