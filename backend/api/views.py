"""
② 검색·View API

  POST /api/v1/rag/search          자연어 (+ 슬롯) → 표 후보
  POST /api/v1/rag/views           질문 | analysis | view_bundle → 단위별 View + Point 충돌 판정 + records / pending
  POST /api/v1/rag/views/select    선택 토큰 + option_id → 고른 View 반영 (서버 세션 없음)
  POST /api/v1/rag/views/points    Record 목록 + 슬롯 → Point 펼치기 + 충돌 판정만 (검색 없음)
  POST /api/v1/data/source         Record / source 좌표 → parquet 재조회 + 차트 데이터
"""
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from backend.api.deps import guard
from backend.schemas.view import (
    PointsRequest,
    PointsResponse,
    SearchRequest,
    SearchResult,
    SelectRequest,
    SelectResponse,
    ViewSet,
    ViewsRequest,
)

TAG = "② 검색·View"
DATA_TAG = "④ 좌표 재조회"
router = APIRouter(prefix="/api/v1/rag", tags=[TAG])
data = APIRouter(prefix="/api/v1/data", tags=[DATA_TAG])


def _first(conf):
    return conf["options"][0]["option_id"] if conf.get("options") else None


@router.post("/search", response_model=SearchResult, summary="자연어 (+ 슬롯) → 표 후보 (View 는 만들지 않음)")
def search(body: SearchRequest):
    from backend.rag.search import search_fn
    from backend.rag.search.resolve import search_query
    f = body.filters.model_dump(by_alias=True, exclude_none=True) if body.filters else {}
    with guard("검색: "):
        cands = search_fn()(search_query(body.query, f), body.top_k, filters=f, question=body.query)
    return {"query": body.query, "candidates": cands}


@router.post("/views", response_model=ViewSet, summary="단위별 View 묶음 + Point 충돌 판정")
def views(body: ViewsRequest):
    """- 입력: `question` · `analysis` · `view_bundle` 중 하나
    - **ok**: `records` → `POST /api/v1/agent/answer`
    - **needs_selection**: 같은 교차점(시점·지역·성별·연령·지표·단위) 값이 표마다 다름 → `pending[].options` 에서 하나를 골라
      `POST /api/v1/rag/views/select` 에 `{selection_token, option_id}` (+ 이 응답을 `previous` 로)
    - **needs_clarification / out_of_scope**: 질의 분석 단계 결과 (검색 안 함)"""
    from backend.rag.view.viewset import build_viewset
    src = body.view_bundle.model_dump(by_alias=True) if body.view_bundle else (body.analysis or body.question)
    if not src:
        raise HTTPException(422, "question · analysis · view_bundle 중 하나가 필요합니다")
    with guard("View: "):
        return build_viewset(src, today=body.today, top_k=body.top_k, n_views=body.n_views,
                             overrides=body.overrides or None, on_ambiguous=_first if body.auto_select == "first" else None)


@router.post("/views/select", response_model=SelectResponse, summary="선택 반영 (토큰 + option_id)")
def select(body: SelectRequest):
    """`previous` 를 주면 그 응답의 Record 를 그대로 쓰고 전체 `records` 를 다시 묶어 `viewset` 으로 돌려줌.
    없으면 토큰 안의 좌표(표·슬롯)로 View 를 다시 만들어 고른 Record 만 돌려줌"""
    from backend.rag.view.selection import resolve
    from backend.rag.view.viewset import apply_selections
    sels = [s.model_dump() for s in body.selections]
    with guard("선택: "):
        if body.previous:
            vs, applied = apply_selections(body.previous, sels)
            return {"viewset": vs, "records": vs["records"], "applied": _slim(applied)}
        applied = [resolve(s["selection_token"], s["option_id"]) for s in sels]
        return {"viewset": None, "records": [r for a in applied for r in a["records"]], "applied": _slim(applied)}


def _slim(applied):
    return [{k: v for k, v in a.items() if k != "records"} | {"record_ids": [r["id"] for r in a["records"]]}
            for a in applied]


@router.post("/views/points", response_model=PointsResponse, summary="Record → Point + 충돌 판정 (검색 없음)")
def points(body: PointsRequest):
    """이미 가진 View 카드끼리 비교만 해 볼 때. 순서 = 우선순위 (선택지 순서)"""
    from backend.core.settings import with_overrides
    from backend.rag.view.conflict import detect
    from backend.rag.view.points import record_points
    from backend.rag.view.viewset import build_options
    s = with_overrides(body.overrides or None)
    recs = [r.model_dump(mode="json") for r in body.records]
    with guard("Point 비교: "):
        pts, pn = {}, {}
        for r in recs:
            ps, notes = record_points(r, body.filters)
            pts[r["id"]], pn[r["id"]] = [p.as_dict() for p in ps], notes
        views = [{"record": r, "rank": i, "tbl_id": (r.get("source") or {}).get("tbl_id", "")} for i, r in enumerate(recs, 1)]
        conf = detect(views, body.filters or {}, s, "points")
        if conf["status"] == "ambiguous":
            conf["options"] = build_options(conf, {v["record"]["id"]: v for v in views}, s)
        return {"points": pts, "point_notes": pn, "conflict": conf}


@data.post("/source", summary="Record 또는 source 좌표 → 원본 parquet 재조회 + 차트 데이터")
def data_source(record_or_source: dict[str, Any] = Body(..., examples=[{
        "table_key": "101_DT_1B040A3", "file": "processed/101_DT_1B040A3.parquet", "prd_se": "Y",
        "itm_id": ["T20"], "dims": {"c1": {"codes": ["27"]}}, "period": {"in": ["2025"]}}]),
        limit: int = Query(500, ge=1, le=5000)):
    """View 카드의 `source` (또는 카드 전체)를 넣으면 숫자를 parquet 에서 다시 꺼낸다 — 답변 숫자 검증용"""
    from backend.data_engine.chart_generator import chart_from_record
    from backend.data_engine.duckdb_client import load_record_data
    t0 = time.time()
    with guard("좌표 조회: "):
        df = load_record_data(record_or_source, limit=limit)
    keep = [c for c in df.columns if c in ("period_label", "prd_de", "itm_nm", "value", "unit")
            or (c.startswith("c") and (c.endswith("_name") or c.endswith("_label")))]
    out = df[keep].astype(object).where(df[keep].notna(), None)
    res = {"n_rows": len(df), "seconds": round(time.time() - t0, 3), "columns": keep, "rows": out.values.tolist()}
    if "table" in record_or_source:
        res["chart"] = chart_from_record(record_or_source)
    return res
