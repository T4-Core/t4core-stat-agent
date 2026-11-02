"""① 정규화 API — 고른 표만 지연 정규화, 프로필·공유 사전 조회 (로직: services/normalize.py)"""
import json
import time
from enum import Enum

from fastapi import APIRouter, HTTPException, Query

from config import OUT, connect
from schemas import NormalizeResult
from services.normalize import ensure_normalized

router = APIRouter(tags=["① normalize 정규화"])


def slim(prof):
    # 코드 목록(지역은 수천 개)을 빼고 구조만 — Swagger 화면에서 읽을 수 있는 크기로
    return {**prof, "levels": [{k: v for k, v in l.items() if k != "codes"} for l in prof["levels"]]}


@router.post("/normalize/{tbl_id}", response_model=NormalizeResult, summary="표 하나 정규화 (캐시 있으면 재사용)")
def normalize(tbl_id: str,
              force: bool = Query(False, description="원본이 그대로여도 다시 정규화"),
              full: bool = Query(False, description="true 면 프로필에 코드 목록까지 포함")):
    """resolve 가 고른 표를 이 시점에 정규화한다. 큰 표(740MB)는 1분 이상 걸릴 수 있다."""
    con = connect()   # DuckDB 연결은 요청마다 새로 (동시 요청 충돌 방지)
    pq = next(iter((OUT / "processed").glob(f"*_{tbl_id}.parquet")), None) if (OUT / "processed").exists() else None
    before = pq.stat().st_mtime if pq else None
    t0 = time.time()
    try:
        prof = ensure_normalized(con, tbl_id, force=force)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        con.close()
    if prof is None:
        raise HTTPException(409, f"원본 CSV 가 없어 정규화할 수 없습니다: {tbl_id}")
    pq = OUT / prof["file"]
    return {"table_key": prof["table_key"], "tbl_nm": prof["tbl_nm"],
            "cached": before is not None and pq.stat().st_mtime == before, "seconds": round(time.time() - t0, 2),
            "row_check": prof["row_check"], "profile": prof if full else slim(prof)}


@router.get("/normalize/{tbl_id}/profile", summary="정규화 프로필 조회 (정규화하지 않음)")
def get_profile(tbl_id: str, full: bool = Query(False, description="true 면 코드 목록까지")):
    p = next(iter((OUT / "profiles").glob(f"*_{tbl_id}.json")), None) if (OUT / "profiles").exists() else None
    if p is None:
        raise HTTPException(404, f"아직 정규화되지 않은 표: {tbl_id} (POST /normalize/{tbl_id})")
    prof = json.loads(p.read_text(encoding="utf-8"))
    return prof if full else slim(prof)


class DictName(str, Enum):
    region_dict = "region_dict"
    period_rules = "period_rules"
    symbol_dict = "symbol_dict"
    dim_kinds = "dim_kinds"


@router.get("/dict/{name}", summary="표기 통일 사전 (쿼리·RAG 모듈 공유용)")
def get_dict(name: DictName):
    """region_dict(시도 표준명·별칭), period_rules(시점 코드), symbol_dict(부호 의미), dim_kinds(분류 종류 판정 규칙)"""
    p = OUT / "dict" / f"{name.value}.json"
    if not p.exists():
        raise HTTPException(404, "사전이 없습니다. normalize CLI 를 한 번 실행하세요")
    return json.loads(p.read_text(encoding="utf-8"))
