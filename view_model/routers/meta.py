"""⓪ 메타 프로필 API — 표 탐색 범위(카탈로그 992개) 만들기·조회 (로직: services/meta_profile.py)"""
import json

from fastapi import APIRouter, HTTPException, Query

from config import OUT
from schemas import MetaBuildSummary
from services.meta_profile import build_all

router = APIRouter(prefix="/meta", tags=["⓪ meta 메타 프로필"])

_cache = {"mtime": None, "rows": []}


def profiles():
    # meta_profiles.jsonl 을 메모리에 올려 두고, 파일이 바뀌었을 때만 다시 읽음
    p = OUT / "meta_profiles.jsonl"
    if not p.exists():
        raise HTTPException(404, "meta_profiles.jsonl 이 없습니다. POST /meta/profiles/build 를 먼저 실행하세요")
    m = p.stat().st_mtime
    if _cache["mtime"] != m:
        _cache["rows"] = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        _cache["mtime"] = m
    return _cache["rows"]


def brief(p):
    return {"tbl_id": p["tbl_id"], "tbl_nm": p["tbl_nm"], "survey_nm": p["survey_nm"],
            "kinds": [l["kind"] for l in p["levels"]],
            "years": [f"{x['se_raw']} {x['year_from']}~{x['year_to']}" for x in p["periods"]],
            "units": p["units"], "raw_mb": p["raw"]["mb"]}


@router.post("/profiles/build", response_model=MetaBuildSummary, summary="메타 프로필 전체 생성 (약 10초)")
def build():
    """카탈로그(selected == True) 전체의 메타 JSON 을 읽어 `meta_profiles.jsonl` 을 다시 만든다."""
    return build_all()


@router.get("/profiles", summary="메타 프로필 검색 (요약)")
def list_profiles(q: str | None = Query(None, description="표 이름·조사명·항목명에 포함된 단어"),
                  kind: str | None = Query(None, description="이 분류 종류가 있는 표만 (regions, sex, ages, scenario …)"),
                  limit: int = Query(20, ge=1, le=1000)):
    """표 고르기 전에 사람이 범위를 눈으로 확인하는 용도. 점수·판단은 하지 않는다 (판단은 /resolve)."""
    rows = profiles()
    if q:
        rows = [p for p in rows if q in p["tbl_nm"] or q in p["survey_nm"] or any(q in i["name"] for i in p["items"])]
    if kind:
        rows = [p for p in rows if any(l["kind"] == kind for l in p["levels"])]
    return {"total": len(rows), "items": [brief(p) for p in rows[:limit]]}


@router.get("/profiles/{tbl_id}", summary="메타 프로필 1개 (전체)")
def get_profile(tbl_id: str):
    p = next((p for p in profiles() if p["tbl_id"] == tbl_id), None)
    if p is None:
        raise HTTPException(404, f"카탈로그(selected)에 없는 표: {tbl_id}")
    return p
