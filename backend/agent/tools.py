"""
[NEW] Agent 가 부르는 도구 — 각 파트 모듈을 한 줄로 부를 수 있게 감싼 것 (로직은 각 모듈에 그대로)

  tool_rewrite         ① 질의 재작성 (query_analyzer.run_pipeline) + View 입력으로 변환 (adapter)
  tool_views           ② 검색 단위별 표 검색 + View 카드 생성 (ingestion.views.run_query)
  tool_hybrid_search   (legacy) records.jsonl 하이브리드 검색 (retrieval.fusion.Index)
  tool_record_data     좌표 → DuckDB 재조회 (data_engine.duckdb_client.load_record_data)
"""
import time
from dataclasses import asdict
from datetime import date

from backend.data_engine.duckdb_client import load_record_data
from backend.rag.ingestion.views import N_VIEWS, TOP_K, records_of, run_query
from backend.rag.query_analyzer.adapter import to_view_bundle
from backend.rag.query_analyzer.bundle import QueryBundle as RewriterQueryBundle

_INDEX_CACHE = {}


def tool_rewrite(question, today=None, query_id=None, search_with="rewritten", use_rewrite=True):
    """→ (rewriter_bundle dict | None, view_bundle dict, notes, run_pipeline 결과 | None)"""
    if not use_rewrite:
        b = RewriterQueryBundle(original=question, rewritten=question)
        vb, notes = to_view_bundle(b, query_id, "original")
        return None, vb, ["재작성 생략 (use_rewrite=false)"] + notes, None
    from backend.rag.query_analyzer import run_pipeline     # HCX 호출 (질문당 1회)
    d = date.fromisoformat(today) if isinstance(today, str) and today else today
    res = run_pipeline(question, d)
    notes = []
    if not res["slot"].get("parsed"):
        notes.append(f"재작성 HCX 응답 실패 → 코드 추출 값만 사용: {res['slot'].get('error')}")
    vb, n2 = to_view_bundle(res["bundle"], query_id, search_with)
    return asdict(res["bundle"]), vb, notes + n2, res


def tool_views(view_bundle, top_k=TOP_K, n_views=N_VIEWS):
    """→ (ViewResult dict, Record 목록)"""
    res = run_query(view_bundle, top_k, n_views)
    return res, records_of(res)


def tool_hybrid_search(query, k=10, variant="base", doc_type=None):
    from backend.rag.retrieval.fusion import Index
    if variant not in _INDEX_CACHE:
        _INDEX_CACHE[variant] = Index(variant)
    return _INDEX_CACHE[variant].search(query, k=k, doc_type=doc_type)


def tool_record_data(record_or_source, limit=500):
    t0 = time.time()
    df = load_record_data(record_or_source, limit=limit)
    return df, round(time.time() - t0, 3)
