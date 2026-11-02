"""③ 검색 API — 자연어로 메타데이터(표 설명문) 검색, 표 색인 만들기 (로직: services/search.py, services/table_text.py)"""
import json
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from schemas import SearchResult
from services.search import search
from services.table_text import INDEX, build_index

router = APIRouter(prefix="/search", tags=["③ search 자연어 검색"])

_build = {"running": False, "log": [], "started": None, "error": None}


class SearchRequest(BaseModel):
    query: str = Field(..., examples=["최근 5년간 대전의 인구 변화 추이"])
    top_k: int = Field(10, ge=1, le=100)


@router.post("", response_model=SearchResult, summary="자연어 → 메타데이터 상위 top_k (bge-m3 + BM25, RRF)")
def run(body: SearchRequest):
    """순차 검색: BM25(kiwi)로 989개 중 top_k → 그 안에서만 bge-m3(HCX)로 다시 줄 세움. 표를 하나로 확정하지 않고 순위 그대로 돌려준다."""
    try:
        return {"query": body.query, "candidates": [{**c, "has_view": False} for c in search(body.query, body.top_k)]}
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))


def _job():
    try:
        build_index(progress=lambda m: _build["log"].append(f"{datetime.now():%H:%M:%S} {m}"))
    except Exception as e:  # noqa: BLE001
        _build["error"] = f"{e.__class__.__name__}: {e}"
    finally:
        _build["running"] = False


@router.post("/index/build", summary="표 색인 만들기 (설명문 + BM25 토큰, 몇 초)")
def build():
    """메타 프로필로 표 설명문과 BM25 토큰을 만든다 (임베딩은 검색 때 뽑힌 10개만). 진행은 GET /search/index/status"""
    if _build["running"]:
        raise HTTPException(409, "이미 만드는 중입니다")
    _build.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), error=None)
    threading.Thread(target=_job, daemon=True).start()
    return {"started": _build["started"]}


@router.get("/index/status", summary="표 색인 상태·진행 로그")
def status():
    meta = INDEX / "meta.json"
    return {"running": _build["running"], "error": _build["error"], "log": _build["log"][-20:],
            "index": json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None}
