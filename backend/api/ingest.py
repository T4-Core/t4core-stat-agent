"""
⓪ 준비 API — 수집 결과 → 메타 프로필 · 표 색인 · CSV 값 사전 · 정규화

  POST /api/v1/ingest/prepare                 준비 한 번에 (백그라운드): 메타 프로필 → 표 색인 → CSV 값 사전
  GET  /api/v1/ingest/prepare/status          진행 로그
  GET  /api/v1/ingest/meta/profiles           메타 프로필 검색 (요약)
  GET  /api/v1/ingest/meta/profiles/{tbl_id}  메타 프로필 1개
  POST /api/v1/ingest/normalize/{tbl_id}      표 하나 정규화 (검색이 처음 고를 때 자동으로도 됨)
  GET  /api/v1/ingest/normalize/{tbl_id}/profile
  GET  /api/v1/ingest/dict/{name}             표기 통일 사전

KOSIS 수집(collector)은 오래 걸려 CLI 로만 둔다.
"""
import json
import threading
import time
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Query

from backend.core.config import VIEW_OUT_DIR
from backend.data_engine.duckdb_client import connect
from backend.rag.ingestion.normalize import ensure_normalized
from backend.schemas.ingest import NormalizeResult

TAG = "⓪ 준비"
router = APIRouter(prefix="/api/v1/ingest", tags=[TAG])


_prep = {"running": False, "log": [], "started": None, "error": None, "result": None}


def _prep_job(workers, force):
    from backend.rag.ingestion.prepare import prepare
    log = lambda m: _prep["log"].append(f"{datetime.now():%H:%M:%S} {m}")  # noqa: E731
    try:
        _prep["result"] = prepare(log, workers=workers, force=force)
    except Exception as e:  # noqa: BLE001
        _prep["error"] = f"{e.__class__.__name__}: {e}"
    finally:
        _prep["running"] = False


@router.post("/prepare", summary="준비 한 번에: 메타 프로필 → 표 색인 → CSV 값 사전 (백그라운드)")
def prepare(workers: int = Query(4, ge=1, le=16), force: bool = Query(False, description="CSV 값 사전 전체 다시 스캔")):
    """처음 한 번 (또는 catalog/meta/raw 가 바뀌었을 때). 표 정규화(parquet)는 검색에서 고른 표만 그때 한다."""
    if _prep["running"]:
        raise HTTPException(409, "이미 실행 중입니다")
    _prep.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), error=None, result=None)
    threading.Thread(target=_prep_job, args=(workers, force), daemon=True).start()
    return {"started": _prep["started"], "status": "GET /api/v1/ingest/prepare/status"}


@router.get("/prepare/status", summary="준비 진행 상태")
def prepare_status():
    return {k: _prep[k] for k in ("running", "started", "error", "result")} | {"log": _prep["log"][-30:]}


_cache = {"mtime": None, "rows": []}


def profiles():
    # meta_profiles.jsonl 을 메모리에 올려 두고, 파일이 바뀌었을 때만 다시 읽음
    p = VIEW_OUT_DIR / "meta_profiles.jsonl"
    if not p.exists():
        raise HTTPException(404, "meta_profiles.jsonl 이 없습니다. POST /api/v1/ingest/meta/profiles/build 를 먼저 실행하세요")
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


@router.get("/meta/profiles", summary="메타 프로필 검색 (요약)")
def list_profiles(q: str | None = Query(None, description="표 이름·조사명·항목명에 포함된 단어"),
                  kind: str | None = Query(None, description="이 분류 종류가 있는 표만 (regions, sex, ages, scenario …)"),
                  limit: int = Query(20, ge=1, le=1000)):
    """표 고르기 전에 사람이 범위를 눈으로 확인하는 용도. 점수·판단은 하지 않는다."""
    rows = profiles()
    if q:
        rows = [p for p in rows if q in p["tbl_nm"] or q in p["survey_nm"] or any(q in i["name"] for i in p["items"])]
    if kind:
        rows = [p for p in rows if any(l["kind"] == kind for l in p["levels"])]
    return {"total": len(rows), "items": [brief(p) for p in rows[:limit]]}


@router.get("/meta/profiles/{tbl_id}", summary="메타 프로필 1개 (전체)")
def get_meta_profile(tbl_id: str):
    p = next((p for p in profiles() if p["tbl_id"] == tbl_id), None)
    if p is None:
        raise HTTPException(404, f"카탈로그(selected)에 없는 표: {tbl_id}")
    return p


def slim(prof):
    # 코드 목록(지역은 수천 개)을 빼고 구조만 — Swagger 화면에서 읽을 수 있는 크기로
    return {**prof, "levels": [{k: v for k, v in l.items() if k != "codes"} for l in prof["levels"]]}


@router.post("/normalize/{tbl_id}", response_model=NormalizeResult, summary="표 하나 정규화 (캐시 있으면 재사용)")
def normalize(tbl_id: str,
              force: bool = Query(False, description="원본이 그대로여도 다시 정규화"),
              full: bool = Query(False, description="true 면 프로필에 코드 목록까지 포함")):
    """검색이 고른 표를 이 시점에 정규화한다. 큰 표(740MB)는 1분 이상 걸릴 수 있다."""
    con = connect()  # 요청마다 새 연결 (동시 요청 충돌 방지)
    pq = next(iter((VIEW_OUT_DIR / "processed").glob(f"*_{tbl_id}.parquet")), None) if (VIEW_OUT_DIR / "processed").exists() else None
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
    pq = VIEW_OUT_DIR / prof["file"]
    return {"table_key": prof["table_key"], "tbl_nm": prof["tbl_nm"],
            "cached": before is not None and pq.stat().st_mtime == before, "seconds": round(time.time() - t0, 2),
            "row_check": prof["row_check"], "profile": prof if full else slim(prof)}


@router.get("/normalize/{tbl_id}/profile", summary="정규화 프로필 조회 (정규화하지 않음)")
def get_norm_profile(tbl_id: str, full: bool = Query(False, description="true 면 코드 목록까지")):
    p = next(iter((VIEW_OUT_DIR / "profiles").glob(f"*_{tbl_id}.json")), None) if (VIEW_OUT_DIR / "profiles").exists() else None
    if p is None:
        raise HTTPException(404, f"아직 정규화되지 않은 표: {tbl_id} (POST /api/v1/ingest/normalize/{tbl_id})")
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
    p = VIEW_OUT_DIR / "dict" / f"{name.value}.json"
    if not p.exists():
        raise HTTPException(404, "사전이 없습니다. python -m backend.rag.ingestion.normalize --tables <표> 를 한 번 실행하세요")
    return json.loads(p.read_text(encoding="utf-8"))
