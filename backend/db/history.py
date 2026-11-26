"""
대화 이력 — backend-server PostgreSQL 의 app 스키마 (CHAT_HISTORY=on, DATABASE_URL)

  record(session_id, request, response, error, elapsed_ms)   /chat 한 번 = app.chat_turn 한 행
  turns(session_id=None, limit=50)                            최근 기록 (응답 본문 없이)
  turn(turn_id)                                               기록 하나 (응답 포함)

CHAT_HISTORY_RESPONSE=summary 면 응답 전체(response)는 저장하지 않는다 (답변 문장·표 목록·상태만).
저장 실패는 로그만 남기고 답변은 그대로 돌려준다.
"""
from __future__ import annotations

import json
import logging
import uuid

from backend.db import conn

log = logging.getLogger("t4core.history")


def enabled():
    return conn.chat_history_on() and bool(conn.database_url())


def _kind(req):
    if req.get("view_selections"):
        return "select"
    if req.get("selections"):
        return "clarify"
    return "ask"


def _tables(resp):
    out = []
    for r in (resp or {}).get("records") or []:
        t = ((r or {}).get("source") or {}).get("tbl_id")
        if t and t not in out:
            out.append(t)
    return out


def record(session_id, request, response=None, error=None, elapsed_ms=None):
    if not enabled():
        return None
    sid = session_id or f"anon-{uuid.uuid4().hex}"
    req = {k: v for k, v in (request or {}).items() if k != "previous"}
    req["has_previous"] = bool((request or {}).get("previous"))
    resp = response or {}
    full = conn.env("CHAT_HISTORY_RESPONSE", "full").lower() != "summary"
    try:
        with conn.main_pool().connection() as c:
            with c.transaction():
                n = c.execute("""
                    INSERT INTO app.chat_session (session_id, first_question, n_turns, last_status)
                    VALUES (%s, %s, 1, %s)
                    ON CONFLICT (session_id) DO UPDATE SET n_turns = app.chat_session.n_turns + 1,
                        updated_at = now(), last_status = EXCLUDED.last_status
                    RETURNING n_turns""", (sid, req.get("question"), resp.get("status") or "error")).fetchone()[0]
                tid = c.execute("""
                    INSERT INTO app.chat_turn (session_id, turn_no, kind, question, status, answer, tables, request,
                                               response, timings, error, elapsed_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s) RETURNING turn_id""",
                                (sid, n, _kind(req), req.get("question") or "", resp.get("status") or "error",
                                 ((resp.get("result") or {}).get("answer")), _tables(resp),
                                 json.dumps(req, ensure_ascii=False, default=str),
                                 json.dumps(resp, ensure_ascii=False, default=str) if (full and response) else None,
                                 json.dumps(resp.get("timings") or {}, default=str), error, elapsed_ms)).fetchone()[0]
        return tid
    except Exception as e:  # noqa: BLE001
        log.warning("대화 이력 저장 실패 (계속): %s: %s", e.__class__.__name__, e)
        return None


def turns(session_id=None, limit=50):
    q = ("SELECT turn_id, session_id, turn_no, kind, question, status, answer, tables, elapsed_ms, error, created_at "
         "FROM app.chat_turn")
    args = []
    if session_id:
        q += " WHERE session_id = %s"
        args.append(session_id)
    q += " ORDER BY turn_id DESC LIMIT %s"
    args.append(int(limit))
    with conn.main_pool().connection() as c:
        cur = c.execute(q, args)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def turn(turn_id):
    with conn.main_pool().connection() as c:
        cur = c.execute("SELECT * FROM app.chat_turn WHERE turn_id = %s", (int(turn_id),))
        row = cur.fetchone()
        return dict(zip([d.name for d in cur.description], row)) if row else None
