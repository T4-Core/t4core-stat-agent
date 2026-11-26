"""
멀티턴 세션 — Redis (REDIS_URL)

POST /api/v1/chat 은 되묻기(needs_clarification)·표 선택(needs_selection)에서 멈추면 다음 요청에 직전 응답 전체를
previous 로 다시 받는다. session_id 를 함께 보내면 그 직전 응답을 서버(Redis)에 두므로

  - 브라우저가 새로고침돼도 GET /api/v1/sessions/{id} 로 진행 중·끝난 응답을 다시 받을 수 있고
  - 이어서 할 때 previous 없이 session_id + selections(또는 view_selections) 만 보내도 된다.

키 하나 = 세션 하나 (hash)   t4:session:<id>
  status      running | ok | needs_clarification | needs_selection | out_of_scope | error
  question    마지막 질문
  response    마지막 응답 JSON (previous 로 쓰는 것)
  started_at · updated_at (epoch 초) · error · turns (이 세션의 /chat 호출 수)

만료: SESSION_TTL_SECONDS (기본 86400 = 24시간). 쓸 때마다 다시 늘어난다.
Redis 는 AOF(appendonly)로 디스크에 남겨 컨테이너 재시작·재배포 뒤에도 남는다 (deploy/backend/compose.yml).
세션이 없을 때: previous 를 함께 보냈으면 그것으로 계속, 아니면 409 '세션 만료 — 질문을 다시 보내 주세요'.
"""
from __future__ import annotations

import json
import logging
import re
import time

from backend.db import conn

log = logging.getLogger("t4core.sessions")
PREFIX = "t4:session:"
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")


def ttl():
    return int(conn.env("SESSION_TTL_SECONDS", "86400"))


def valid_id(sid):
    return bool(sid) and bool(ID_RE.match(str(sid)))


class SessionStore:
    def __init__(self, client):
        self.r = client

    def _key(self, sid):
        return PREFIX + str(sid)

    def _write(self, sid, fields):
        k = self._key(sid)
        p = self.r.pipeline()
        p.hset(k, mapping={a: ("" if b is None else b) for a, b in fields.items()})
        p.expire(k, ttl())
        p.execute()

    def start(self, sid, question):
        k = self._key(sid)
        p = self.r.pipeline()
        p.hset(k, mapping={"status": "running", "question": question or "", "started_at": int(time.time()),
                           "updated_at": int(time.time()), "error": ""})
        p.hincrby(k, "turns", 1)
        p.expire(k, ttl())
        p.execute()

    def finish(self, sid, response):
        self._write(sid, {"status": str(response.get("status") or "ok"), "updated_at": int(time.time()),
                          "response": json.dumps(response, ensure_ascii=False, default=str), "error": ""})

    def fail(self, sid, error):
        self._write(sid, {"status": "error", "updated_at": int(time.time()), "error": str(error)[:500]})

    def get(self, sid):
        raw = self.r.hgetall(self._key(sid))
        if not raw:
            return None
        d = {(a.decode() if isinstance(a, bytes) else a): (b.decode() if isinstance(b, bytes) else b)
             for a, b in raw.items()}
        resp = d.pop("response", "") or ""
        out = {"session_id": sid, "status": d.get("status"), "question": d.get("question"),
               "turns": int(d.get("turns") or 0), "started_at": int(d.get("started_at") or 0),
               "updated_at": int(d.get("updated_at") or 0), "error": d.get("error") or None,
               "ttl_seconds": self.r.ttl(self._key(sid))}
        out["response"] = json.loads(resp) if resp else None
        return out

    def previous(self, sid):
        s = self.get(sid)
        return (s or {}).get("response")

    def delete(self, sid):
        return bool(self.r.delete(self._key(sid)))


def store():
    """REDIS_URL 이 없으면 None (세션 저장 안 함)"""
    c = conn.redis_client()
    return SessionStore(c) if c is not None else None


def safe(fn, *a):
    """세션 저장 실패가 답변을 막지 않게 (Redis 가 잠깐 끊겨도 /chat 은 계속)"""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        log.warning("세션 저장 실패 (계속): %s: %s", e.__class__.__name__, e)
        return None
