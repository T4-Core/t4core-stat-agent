"""백엔드 호출 (FastAPI · backend/main.py). 주소는 환경변수 STAT_AGENT_API (기본 http://localhost:8000)

  chat(question, …)                   POST /api/v1/chat  — 분석 → 검색·View → 답변 (answer_mode default | modules)
  chat(…, previous=r, view_selections=[{selection_token, option_id}])   통계표 선택 반영
  chat(…, previous=r, selections={슬롯: [값]})                         되묻기 응답 반영
  search(query, top_k)                POST /api/v1/rag/search — 조건으로 볼 수 있는 통계표 후보
  health()                            GET /health
"""
from __future__ import annotations

import os

import requests

BASE = os.getenv("STAT_AGENT_API", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("STAT_AGENT_TIMEOUT", "180"))


class ApiError(RuntimeError):
    pass


def _post(path, body, base=None, timeout=None):
    url = f"{(base or BASE).rstrip('/')}{path}"
    try:
        r = requests.post(url, json=body, timeout=timeout or TIMEOUT)
    except requests.RequestException as e:
        raise ApiError(f"백엔드에 연결하지 못함 ({url}): {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise ApiError(f"{path} → HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def chat(question, *, today=None, answer_mode="modules", auto_select=False, draw=True, previous=None,
         view_selections=None, selections=None, overrides=None, base=None):
    body = {"question": question, "answer_mode": answer_mode, "auto_select": auto_select, "draw": draw}
    if today:
        body["today"] = today
    if previous is not None:
        body["previous"] = previous
    if view_selections:
        body["view_selections"] = view_selections
    if selections:
        body["selections"] = selections
    if overrides:
        body["overrides"] = overrides
    return _post("/api/v1/chat", body, base)


def search(query, top_k=3, base=None):
    return _post("/api/v1/rag/search", {"query": query, "top_k": top_k}, base, timeout=60).get("candidates") or []


def health(base=None):
    try:
        r = requests.get(f"{(base or BASE).rstrip('/')}/health", timeout=5)
        return r.json() if r.status_code == 200 else None
    except requests.RequestException:
        return None
