"""
[모듈 2·3] 검색 + View 생성 API  (구 view_model/routers/search.py, views.py) + legacy 하이브리드 검색·좌표 조회 [NEW]

  POST /api/v1/rag/retrieve        (구 POST /search)         자연어 → 표 후보 (BM25 → bge-m3 재정렬)
  POST /api/v1/rag/views           (구 POST /views)          QueryBundle → Record 목록      ← 파이프라인 ②
  POST /api/v1/rag/views/detail    (구 POST /views/detail)   QueryBundle → 상세(후보·카드·notes)
  POST /api/v1/rag/pipeline/run    (구 POST /pipeline/run)   질의 묶음 → 카드 목록 파일
  POST /api/v1/rag/hybrid-search   [NEW] records.jsonl 하이브리드 검색 (구 kosis_rag_qa.py search)
  POST /api/v1/data/source         [NEW] Record / source 좌표 → DuckDB 재조회 + 차트 데이터
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Query

from backend.api.deps import guard
from backend.data_engine.chart_generator import chart_from_record
from backend.agent.tools import tool_hybrid_search, tool_record_data
from backend.rag.ingestion.views import N_VIEWS, TOP_K, records_of, run_examples, run_query, save_results
from backend.rag.retrieval.table_search import search
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record
from backend.schemas.search import HybridHit, HybridSearchRequest, SearchRequest, SearchResult
from backend.schemas.view import PipelineRequest, PipelineResult, ViewResult

router = APIRouter(prefix="/api/v1/rag", tags=["② Retrieval 검색·View 생성"])
data = APIRouter(prefix="/api/v1/data", tags=["④ Data 좌표 조회·차트"])

TOPK_Q = Query(TOP_K, ge=1, le=50, description="1단계 BM25 후보 수")
NV_Q = Query(N_VIEWS, ge=0, le=10, description="2단계 bge-m3 재정렬 후 View 를 만들 수 (상위부터)")


@router.post("/retrieve", response_model=SearchResult, summary="자연어 → 메타데이터 상위 top_k (BM25 → bge-m3) — 구 POST /search")
def retrieve(body: SearchRequest):
    """순차 검색: BM25(kiwi)로 989개 중 top_k → 그 안에서만 bge-m3(HCX)로 다시 줄 세움. 표를 하나로 확정하지 않고 순위 그대로 돌려준다."""
    with guard("검색: "):
        return {"query": body.query, "candidates": [{**c, "has_view": False} for c in search(body.query, body.top_k)]}


@router.post("/views", response_model=list[Record], summary="② QueryBundle → View 카드 목록 — 구 POST /views")
def views(body: QueryBundle, top_k: int = TOPK_Q, n_views: int = NV_Q):
    """검색 단위 = 상위 질의 + 서브쿼리 각각. 단위마다 BM25 상위 top_k → bge-m3 재정렬 → 상위 n_views 개 표를 슬롯대로 잘라 카드.
    큰 표가 처음 골리면 정규화에 1분 이상 걸릴 수 있다 (이후 캐시).

    입력은 `POST /api/v1/rag/query-rewrite` 응답의 **view_bundle** 을 그대로 붙여 넣으면 된다.
    응답(Record 목록)은 `POST /api/v1/agent/answer` 의 records 로 그대로 넣는다."""
    with guard("View: "):
        return records_of(run_query(body.model_dump(by_alias=True), top_k, n_views))


@router.post("/views/detail", response_model=ViewResult, summary="질의 하나 → 상세 (검색 후보, 카드, 못 맞춘 조건) — 구 POST /views/detail")
def views_detail(body: QueryBundle, top_k: int = TOPK_Q, n_views: int = NV_Q):
    with guard("View: "):
        return run_query(body.model_dump(by_alias=True), top_k, n_views)


@router.post("/pipeline/run", response_model=PipelineResult, summary="질의 묶음 → 카드 목록 하나 (기본: 예시 12개) — 구 POST /pipeline/run")
def pipeline(body: PipelineRequest):
    """queries 를 비우면 예시 12개 → VIEW_OUT_DIR/view_records.json (카드 목록) + view_results.jsonl (상세).
    queries 를 넣으면 그 질의만 → *_custom_<시각> 파일 (예시 결과를 덮어쓰지 않음)"""
    with guard("pipeline: "):
        if body.queries:
            res = [run_query(q.model_dump(by_alias=True), body.top_k, body.n_views) for q in body.queries]
            tag = f"_custom_{datetime.now():%Y%m%d_%H%M%S}"
        else:
            res = run_examples(body.top_k, body.n_views, progress=lambda m: None)
            tag = ""
    rp, dp = save_results(res, f"view_records{tag}.json", f"view_results{tag}.jsonl")
    recs = records_of(res)
    return {"n_queries": len(res), "n_records": len(recs), "file": str(rp), "detail_file": str(dp), "records": recs}


@router.post("/hybrid-search", response_model=list[HybridHit], summary="(legacy) records.jsonl 하이브리드 검색 BM25+Dense→RRF")
def hybrid_search(body: HybridSearchRequest):
    """구 `python kosis_rag_qa.py search "…"`. 인덱스: RAG_INDEX_DIR/<variant> (python -m backend.agent.light_agent index 로 생성)"""
    with guard("하이브리드 검색: "):
        return tool_hybrid_search(body.query, body.k, body.variant, body.doc_type)


@data.post("/source", summary="Record 또는 source 좌표 → 원본 parquet 재조회 + 차트 데이터")
def data_source(record_or_source: dict[str, Any] = Body(..., examples=[{
        "table_key": "101_DT_1B040A3", "file": "processed/101_DT_1B040A3.parquet", "prd_se": "Y",
        "itm_id": ["T20"], "dims": {"c1": {"codes": ["27"]}}, "period": {"in": ["2025"]}}]),
        limit: int = Query(500, ge=1, le=5000)):
    """View 카드의 `source` (또는 카드 전체)를 넣으면 숫자를 parquet 에서 다시 꺼낸다 — 답변 숫자 검증용"""
    with guard("좌표 조회: "):
        df, sec = tool_record_data(record_or_source, limit)
    keep = [c for c in df.columns if c in ("period_label", "prd_de", "itm_nm", "value", "unit")
            or (c.startswith("c") and (c.endswith("_name") or c.endswith("_label")))]
    out = df[keep].astype(object).where(df[keep].notna(), None)
    res = {"n_rows": len(df), "seconds": sec, "columns": keep, "rows": out.values.tolist()}
    if "table" in record_or_source:
        res["chart"] = chart_from_record(record_or_source)
    return res
