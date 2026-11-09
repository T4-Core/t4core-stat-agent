"""[NEW v4] 2-3 선택지 + 선택 토큰 — 서버에 세션을 두지 않는 선택 왕복

  선택지(option) = 값이 같은 표 무리 하나. 표 이름 · 다른 값 미리보기 · 주석(메타 CMMT) · 표 설명 · 산출 기준
  선택 토큰      = (검색 단위, 슬롯, 선택지별 Record id) 를 담은 서명 문자열 (HMAC-SHA256)
                   → POST /api/v1/rag/v4/views/select 에 {selection_token, option_id} 만 보내면 됨
                   → 이전 응답(previous)을 함께 보내면 그 안의 Record 를 그대로, 없으면 좌표로 View 를 다시 만듦
  CLI·노트북: resolve(token, "opt-2") 또는 build_viewset(…, on_ambiguous=콜백)

비밀 키: 환경변수 VIEW_SELECTION_SECRET, 없으면 storage/.view_selection_secret (처음 한 번 만들어 둠)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from backend.core.config import STORAGE_DIR


def _secret():
    s = os.getenv("VIEW_SELECTION_SECRET")
    if s:
        return s.encode()
    p = STORAGE_DIR / ".view_selection_secret"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            p.chmod(0o600)
        except OSError:
            pass
    return p.read_text(encoding="utf-8").strip().encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(unit_id, query_id, filters, options, keep=(), ttl_hours=168):
    """options: [{option_id, record_ids, tbl_ids}] → 토큰"""
    now = int(time.time())
    payload = {"v": 1, "u": unit_id, "q": query_id, "f": filters or {},
               "o": [{"id": o["option_id"], "r": o["record_ids"], "t": o["tbl_ids"]} for o in options],
               "k": list(keep), "iat": now, "exp": now + int(ttl_hours * 3600)}
    body = _b64(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token):
    """토큰 → payload. 서명이 틀리거나 만료면 ValueError"""
    try:
        body, sig = token.rsplit(".", 1)
    except (AttributeError, ValueError):
        raise ValueError("선택 토큰 형식이 아님")
    want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(want, sig):
        raise ValueError("선택 토큰 서명이 맞지 않음 (다른 서버에서 발급했거나 내용이 바뀜)")
    p = json.loads(_unb64(body))
    if p.get("exp") and time.time() > p["exp"]:
        raise ValueError("선택 토큰이 만료됨 — 다시 검색하세요")
    return p


def _num_of(record_id):
    # view::표key::주기::번호::종류 → 번호
    parts = str(record_id).split("::")
    return parts[3] if len(parts) >= 5 else None


def rebuild(record_id, tbl_id, filters, con=None):
    """좌표(표·슬롯·번호)로 View 를 다시 만듦 — 같은 id 가 나와야 함"""
    from backend.rag.ingestion.build_view import build_view
    rec, _ = build_view(tbl_id, filters, _num_of(record_id), con)
    if rec["id"] != record_id:
        raise ValueError(f"다시 만든 View id 가 다름: {rec['id']} ≠ {record_id} (원본 자료가 바뀌었을 수 있음)")
    return rec


def resolve(token, option_id, previous_records=None, con=None):
    """선택 → {unit_id, query_id, option_id, records, kept_ids, dropped_ids, rebuilt}"""
    p = verify(token)
    opt = next((o for o in p["o"] if o["id"] == option_id), None)
    if opt is None:
        raise ValueError(f"선택지 {option_id} 없음. 가능: {[o['id'] for o in p['o']]}")
    have = {r["id"]: r for r in previous_records or []}
    recs, rebuilt = [], []
    for rid, tid in zip(opt["r"], opt["t"]):
        if rid in have:
            recs.append(have[rid])
        else:
            recs.append(rebuild(rid, tid, p["f"], con))
            rebuilt.append(rid)
    dropped = [r for o in p["o"] if o["id"] != option_id for r in o["r"]]
    return {"unit_id": p["u"], "query_id": p["q"], "option_id": option_id, "records": recs,
            "kept_ids": p.get("k") or [], "dropped_ids": dropped, "rebuilt": rebuilt}
