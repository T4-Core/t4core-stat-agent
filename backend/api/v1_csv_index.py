"""
[NEW v4] CSV 값 사전 API — 원본 CSV 의 행·열 값을 스캔한 사전 만들기·조회

  POST /api/v1/csv-index/build              원본 CSV 스캔 (바뀐 표만) → storage/csv_index/
  GET  /api/v1/csv-index/summary            표 수 · 값 수 · 슬롯별 값 수 · 오류
  GET  /api/v1/csv-index/values?slot=지역   슬롯 값 목록 (표 수 순) — 되묻기 후보와 같은 데이터
  GET  /api/v1/csv-index/find?text=…        값 → 그 값이 있는 표 (정확·표기 변형, 없으면 포함 일치)
  GET  /api/v1/csv-index/tables/{tbl_id}    표 하나의 구조 (열 · 분류 값 · 항목·단위 · 기간 · 주석)
"""
from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import guard
from backend.schemas.query_v4 import CsvIndexBuildRequest, CsvRow, CsvValue

router = APIRouter(prefix="/api/v1/csv-index", tags=["⓪ CSV 값 사전 (v4)"])
SCOPE_Q = Query("selected", description="selected = catalog.csv selected 표만 (검색 대상과 같음) / all")


def _idx():
    from backend.rag.csv_index import load_index
    try:
        return load_index()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/build", summary="원본 CSV 스캔 → 값 사전 (바뀐 표만 다시)")
def build(body: CsvIndexBuildRequest):
    from backend.rag.csv_index import build_index
    logs = []
    with guard("CSV 값 사전: "):
        summary = build_index(scope=body.scope, workers=body.workers, force=body.force, limit=body.limit, log=logs.append)
    return {**summary, "log": logs}


@router.get("/summary", summary="값 사전 요약")
def summary():
    return _idx().summary


@router.get("/values", response_model=list[CsvValue], summary="슬롯 값 목록 (표 수 순)")
def values(slot: str = Query("지역", description="지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표"),
           scope: str = SCOPE_Q, limit: int = Query(50, ge=1, le=5000)):
    return _idx().values(slot, scope=scope, limit=limit)


@router.get("/find", response_model=list[CsvRow], summary="값 → 그 값이 있는 표·위치")
def find(text: str = Query(..., examples=["출생아 수"]), slot: str | None = None, scope: str = SCOPE_Q,
         limit: int = Query(50, ge=1, le=1000)):
    idx = _idx()
    slots = [slot] if slot else None
    rows = idx.find(text, slots=slots, scope=scope) or idx.contains(text, slots=slots, scope=scope)
    return rows[:limit]


@router.get("/tables/{tbl_id}", summary="표 하나의 구조 (열·분류 값·항목·단위·기간·주석)")
def table(tbl_id: str, max_values: int = Query(50, ge=1, le=3000, description="분류마다 보여 줄 값 수")):
    t = _idx().table(tbl_id)
    if not t:
        raise HTTPException(404, f"값 사전에 없는 표: {tbl_id}")
    return {**t, "dims": [{**d, "values": d["values"][:max_values]} for d in t["dims"]]}
