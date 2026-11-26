"""
세션 · 대화 이력 API

  GET    /api/v1/sessions/{id}      진행 중·끝난 /chat 응답 (Redis, 새로고침 뒤 복구용)
  DELETE /api/v1/sessions/{id}
  GET    /api/v1/history            최근 대화 이력 (PostgreSQL app.chat_turn, CHAT_HISTORY=on)
  GET    /api/v1/history/{turn_id}  이력 하나 (응답 전체 포함)

이력 조회는 ADMIN_TOKEN 이 설정되어 있으면 X-Admin-Token 헤더가 같아야 한다 (팀 내부 시연용 최소 보호).
"""
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder

TAG = "세션 · 대화 이력"
router = APIRouter(prefix="/api/v1", tags=[TAG])


def _store():
    from backend.db import sessions
    st = sessions.store()
    if st is None:
        raise HTTPException(404, "세션 저장(REDIS_URL)이 꺼져 있습니다")
    return st


@router.get("/sessions/{session_id}", summary="세션의 마지막 응답 (진행 중이면 status=running)")
def get_session(session_id: str):
    from backend.db import sessions
    if not sessions.valid_id(session_id):
        raise HTTPException(400, "session_id 형식이 아닙니다")
    try:
        s = _store().get(session_id)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"세션 저장소(Redis) 오류: {e.__class__.__name__}")
    if s is None:
        raise HTTPException(404, "세션이 없거나 만료되었습니다")
    return s


@router.delete("/sessions/{session_id}", summary="세션 지우기")
def delete_session(session_id: str):
    return {"deleted": _store().delete(session_id)}


def _admin(token):
    from backend.db import conn, history
    need = conn.env("ADMIN_TOKEN")
    if need and token != need:
        raise HTTPException(401, "X-Admin-Token 이 필요합니다")
    if not history.enabled():
        raise HTTPException(404, "대화 이력(CHAT_HISTORY=on, DATABASE_URL)이 꺼져 있습니다")


@router.get("/history", summary="최근 대화 이력")
def list_history(session_id: str | None = None, limit: int = Query(50, ge=1, le=500),
                 x_admin_token: str | None = Header(None)):
    from backend.db import history
    _admin(x_admin_token)
    return jsonable_encoder(history.turns(session_id, limit))


@router.get("/history/{turn_id}", summary="대화 이력 하나 (응답 전체)")
def get_history(turn_id: int, x_admin_token: str | None = Header(None)):
    from backend.db import history
    _admin(x_admin_token)
    t = history.turn(turn_id)
    if t is None:
        raise HTTPException(404, "없는 이력")
    return jsonable_encoder(t)
