"""
검색 단위별 View 카드 — view_bundle → 단위마다 표 검색 → 상위 n_views 개 표를 슬롯대로 잘라 Record

  검색 단위 = 본 질의(main) + 서브쿼리 각각 (서브쿼리가 있으면 skip_main 으로 본 질의를 건너뛸 수 있음)
  결과 = {query_id, original, filters, units: [{unit_id, query, search_query, filters, candidates, views, notes}]}
  카드 id = view::표key::주기::질문ID-순위::종류  (서브쿼리는 질문ID 자리에 서브 ID, 예: q1-2)
"""
import time
import uuid

from backend.data_engine.duckdb_client import connect
from backend.rag.search.resolve import search_query
from backend.rag.view.build import build_view

TOP_K = 10
N_VIEWS = 3


def units_of(b, sub_ids=None):
    """view_bundle(dict) → [(unit_id, 자연어, 슬롯 dict)]"""
    qid = b.get("query_id")
    filters = b.get("filters") or {}
    units = [("main", b.get("search_text") or b["original"], filters)]
    subs, sfs = b.get("sub_questions") or [], b.get("sub_filters") or []
    for i, text in enumerate(subs):
        uid = (sub_ids[i] if sub_ids and i < len(sub_ids) else f"{qid}-{i + 1}")
        units.append((uid, text, (sfs[i] if i < len(sfs) else None) or filters))
    return units


def run_query(b, top_k=TOP_K, n_views=N_VIEWS, sub_ids=None, progress=None, search_fn=None, skip_main=False):
    """view_bundle 하나 → 단위별 결과 (카드는 units[].views[].record)
    search_fn(query, top_k, filters=, question=, unit=) 를 바꿔 끼울 수 있음 (기본 backend.rag.search)"""
    if search_fn is None:
        from backend.rag.search import search_fn as default
        search_fn = default()
    b = dict(b)
    b["query_id"] = b.get("query_id") or uuid.uuid4().hex[:8]
    con = connect()
    out_units = []
    try:
        units = units_of(b, sub_ids)
        for uid, text, f in units:
            if skip_main and uid == "main" and len(units) > 1:
                continue
            label = b["query_id"] if uid == "main" else uid
            notes = []
            sq = search_query(text, f)                     # 지역·시점 단어를 빼고 지표·대상 단어를 더함
            cands = search_fn(sq, top_k, filters=f, question=b.get("original"), unit=uid)
            views = []
            for c in cands[:n_views]:
                t0 = time.time()
                try:
                    rec, vnotes = build_view(c["tbl_id"], f, f"{label}-{c['rank']}", con)
                except Exception as e:  # noqa: BLE001  (View 하나 실패해도 나머지는 계속)
                    notes.append(f"{c['tbl_id']} View 생성 실패: {e.__class__.__name__}: {str(e)[:150]}")
                    continue
                rec["match"] = {"rank": c["rank"], "cover": c.get("cover"), "unmet": c.get("unmet") or []}
                views.append({"record": rec, "notes": [n["text"] for n in vnotes], "rank": c["rank"], "tbl_id": c["tbl_id"]})
                if progress:
                    progress(f"  [{label}] #{c['rank']} {c['tbl_id']} → {len(rec['table']['rows'])}행 ({time.time() - t0:.1f}초)")
            done = {v["tbl_id"] for v in views}
            for c in cands:
                c["has_view"] = c["tbl_id"] in done
            out_units.append({"unit_id": uid, "query": text, "search_query": sq, "filters": f, "candidates": cands,
                              "views": views, "notes": notes})
    finally:
        con.close()
    return {"query_id": b["query_id"], "original": b["original"], "filters": b.get("filters"), "units": out_units}


def records_of(results):
    """결과(들) → 카드 목록 하나"""
    results = results if isinstance(results, list) else [results]
    return [v["record"] for r in results for u in r["units"] for v in u["views"]]
