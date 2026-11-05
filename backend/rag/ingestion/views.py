"""
[엔드포인트 5] views — 질의(자연어 + 슬롯 dict, 서브쿼리 포함) → 검색 단위별 View 카드 → 카드 목록

  검색 단위 = 상위 질의(main) + 서브쿼리 각각
  단위마다:  자연어로 검색 (resolve.search_query 로 다듬은 문장 → search: BM25 50개 → 조건 확인 → 상위 top_k=10 → bge-m3 재정렬)
             → 상위 n_views=3 개 표로 View 카드 생성 (build_view, 슬롯 dict 조건)
  출력
    카드 목록   : [Record, …]  (판단·RAG 모듈로 넘기는 것. 질문 12개 → 한 목록)
    상세 결과   : {query_id, original, filters, units: [{unit_id, query, filters, candidates, views, notes}]}  (확인용)
    Record 의 notes(못 맞춘 조건 dict 목록)·match(rank, cover, unmet) 는 docs/view_model/build_view.md 2. Record 참고

  카드 id = view::표key::주기::질문ID-순위::종류  (서브쿼리는 질문ID 자리에 서브 ID, 예: 6-1-2)

실행  API : POST /views (질의 하나 → 카드 목록), POST /views/detail (상세), POST /pipeline/run (예시 12개)
      CLI : python -m backend.rag.ingestion.views          # 예시 12개 (저장소 루트에서)
      [CHANGED] 이전: cd view_model && ../.venv/Scripts/python.exe -m services.views
"""
import json
import sys
import time
import uuid

from backend.core.config import OUT
from backend.data_engine.duckdb_client import connect
from backend.rag.ingestion.build_view import build_view
from backend.rag.ingestion.resolve import search_query
from backend.rag.query_analyzer.query_bundle import example_queries, parse_slots
from backend.rag.retrieval.table_search import search
# [CHANGED] 이전: from config import OUT, connect
#                from services.build_view import build_view
#                from services.query_bundle import example_queries, parse_slots
#                from services.search import search

TOP_K = 10
N_VIEWS = 3


def units_of(b, sub_ids=None):
    # QueryBundle(dict) → 검색 단위 목록 [(unit_id, 자연어, 슬롯 dict)]
    qid = b.get("query_id")
    filters = b.get("filters")
    if filters is None and b.get("rewritten"):
        filters = parse_slots(b["rewritten"])[0]
    units = [("main", b.get("search_text") or b["original"], filters or {})]
    # [CHANGED] 이전: units = [("main", b["original"], filters or {})]
    #   통합 파이프라인에서 재작성 문장(예: '2025년 전국 1인가구 가구수')으로 검색할 수 있게 search_text 를 우선.
    #   search_text 가 없으면 예전과 똑같이 original 로 검색 (단독 /views 호출 동작은 그대로)
    subs, sfs = b.get("sub_questions") or [], b.get("sub_filters") or []
    for i, text in enumerate(subs):
        uid = (sub_ids[i] if sub_ids and i < len(sub_ids) else f"{qid}-{i + 1}")
        units.append((uid, text, (sfs[i] if i < len(sfs) else None) or filters or {}))
    return units


def run_query(b, top_k=TOP_K, n_views=N_VIEWS, sub_ids=None, progress=None):
    # 질의 하나 → 상세 결과 (카드는 units[].views[].record)
    b = dict(b)
    b["query_id"] = b.get("query_id") or uuid.uuid4().hex[:8]
    con = connect()
    out_units = []
    try:
        for uid, text, f in units_of(b, sub_ids):
            label = b["query_id"] if uid == "main" else uid
            notes = []
            sq = search_query(text, f)                    # 지역·시점 단어 빼고 지표·대상 단어 더함 (resolve.py)
            cands = search(sq, top_k, filters=f)          # BM25 50개 → 조건 확인 → 상위 top_k 만 dense
            # [CHANGED] 이전: cands = search(text, top_k)
            views = []
            for c in cands[:n_views]:
                t0 = time.time()
                try:
                    rec, vnotes = build_view(c["tbl_id"], f, f"{label}-{c['rank']}", con)
                except Exception as e:  # noqa: BLE001  (View 하나 실패해도 나머지는 계속)
                    notes.append(f"{c['tbl_id']} View 생성 실패: {e.__class__.__name__}: {str(e)[:150]}")
                    continue
                rec["match"] = {"rank": c["rank"], "cover": c.get("cover"), "unmet": c.get("unmet") or []}   # [NEW 11-03]
                views.append({"record": rec, "notes": [n["text"] for n in vnotes], "rank": c["rank"], "tbl_id": c["tbl_id"]})
                # [CHANGED 11-03] 이전: "notes": vnotes  — notes 가 dict 목록이 됨. 답변 모듈(light_agent)은 문장 목록을
                #   받으므로 여기는 text 만 (구조화된 notes 는 record["notes"])
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
    # 상세 결과(들) → 카드 목록 하나 (판단·RAG 모듈로 넘기는 모양)
    results = results if isinstance(results, list) else [results]
    return [v["record"] for r in results for u in r["units"] for v in u["views"]]


def run_examples(top_k=TOP_K, n_views=N_VIEWS, progress=print):
    results = []
    for e in example_queries():
        progress(f"[{e['bundle']['query_id']}] {e['bundle']['original']}")
        results.append(run_query(e["bundle"], top_k, n_views, e["sub_ids"], progress))
    return results


def save_results(results, records_name="view_records.json", detail_name="view_results.jsonl"):
    # 카드 목록(JSON 배열 하나) + 상세 결과(jsonl, 한 줄 = 질의 하나)
    rp, dp = OUT / records_name, OUT / detail_name
    rp.write_text(json.dumps(records_of(results), ensure_ascii=False, default=str), encoding="utf-8")
    with dp.open("w", encoding="utf-8") as fo:
        for r in results:
            fo.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return rp, dp


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    res = run_examples(progress=lambda m: print(m, flush=True))
    rp, dp = save_results(res)
    print(f"카드 {len(records_of(res))}장 → {rp}\n상세 → {dp}")


if __name__ == "__main__":
    main()
