"""④⑤ View API — 질의(자연어 + 슬롯) → View 카드 목록 (로직: services/views.py, services/build_view.py)"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from schemas import PipelineRequest, PipelineResult, QueryBundle, Record, ViewResult
from services.views import N_VIEWS, TOP_K, records_of, run_examples, run_query, save_results

router = APIRouter(tags=["④ views View 생성"])

TOPK_Q = Query(TOP_K, ge=1, le=50, description="1단계 BM25 후보 수")
NV_Q = Query(N_VIEWS, ge=0, le=10, description="2단계 bge-m3 재정렬 후 View 를 만들 수 (상위부터)")


@router.post("/views", response_model=list[Record], summary="질의 하나 → View 카드 목록 (판단·RAG 모듈로 넘기는 모양)")
def views(body: QueryBundle, top_k: int = TOPK_Q, n_views: int = NV_Q):
    """검색 단위 = 상위 질의 + 서브쿼리 각각. 단위마다 BM25 상위 top_k → bge-m3 재정렬 → 상위 n_views 개 표를 슬롯대로 잘라 카드.
    큰 표가 처음 골리면 정규화에 1분 이상 걸릴 수 있다 (이후 캐시)."""
    try:
        return records_of(run_query(body.model_dump(by_alias=True), top_k, n_views))
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))


@router.post("/views/detail", response_model=ViewResult, summary="질의 하나 → 상세 (검색 후보 10개, 카드, 못 맞춘 조건 메모)")
def views_detail(body: QueryBundle, top_k: int = TOPK_Q, n_views: int = NV_Q):
    try:
        return run_query(body.model_dump(by_alias=True), top_k, n_views)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))


@router.post("/pipeline/run", response_model=PipelineResult, tags=["pipeline 일괄 실행"],
             summary="질의 묶음 → 카드 목록 하나 (기본: 쿼리 모듈 예시 12개)")
def pipeline(body: PipelineRequest):
    """queries 를 비우면 예시 12개 → output/view_records.json (카드 목록) + view_results.jsonl (상세).
    queries 를 넣으면 그 질의만 → *_custom_<시각> 파일 (예시 결과를 덮어쓰지 않음)"""
    try:
        if body.queries:
            res = [run_query(q.model_dump(by_alias=True), body.top_k, body.n_views) for q in body.queries]
            tag = f"_custom_{datetime.now():%Y%m%d_%H%M%S}"
        else:
            res = run_examples(body.top_k, body.n_views, progress=lambda m: None)
            tag = ""
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    rp, dp = save_results(res, f"view_records{tag}.json", f"view_results{tag}.jsonl")
    recs = records_of(res)
    return {"n_queries": len(res), "n_records": len(recs), "file": str(rp), "detail_file": str(dp), "records": recs}
