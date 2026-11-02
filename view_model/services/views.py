"""
[엔드포인트 5] views — 질의(자연어 + 슬롯 dict, 서브쿼리 포함) → 검색 단위별 View 카드 → 카드 목록

  검색 단위 = 상위 질의(main) + 서브쿼리 각각
  단위마다:  자연어로 검색 (search: BM25 상위 top_k=10 → bge-m3 재정렬)
             → 상위 n_views=3 개 표로 View 카드 생성 (build_view, 슬롯 dict 조건)
  출력
    카드 목록   : [Record, …]  (판단·RAG 모듈로 넘기는 것. 질문 12개 → 한 목록)
    상세 결과   : {query_id, original, filters, units: [{unit_id, query, filters, candidates, views, notes}]}  (확인용)

  카드 id = view::표key::주기::질문ID-순위::종류  (서브쿼리는 질문ID 자리에 서브 ID, 예: 6-1-2)

실행  API : POST /views (질의 하나 → 카드 목록), POST /views/detail (상세), POST /pipeline/run (예시 12개)
      CLI : cd view_model && ../.venv/Scripts/python.exe -m services.views          # 예시 12개
"""
import json
import sys
import time
import uuid

from config import OUT, connect
from services.build_view import build_view
from services.query_bundle import example_queries, parse_slots
from services.search import search

TOP_K = 10
N_VIEWS = 3


def units_of(b, sub_ids=None):
    # QueryBundle(dict) → 검색 단위 목록 [(unit_id, 자연어, 슬롯 dict)]
    qid = b.get("query_id")
    filters = b.get("filters")
    if filters is None and b.get("rewritten"):
        filters = parse_slots(b["rewritten"])[0]
    units = [("main", b["original"], filters or {})]
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
            cands = search(text, top_k)
            views = []
            for c in cands[:n_views]:
                t0 = time.time()
                try:
                    rec, vnotes = build_view(c["tbl_id"], f, f"{label}-{c['rank']}", con)
                except Exception as e:  # noqa: BLE001  (View 하나 실패해도 나머지는 계속)
                    notes.append(f"{c['tbl_id']} View 생성 실패: {e.__class__.__name__}: {str(e)[:150]}")
                    continue
                views.append({"record": rec, "notes": vnotes, "rank": c["rank"], "tbl_id": c["tbl_id"]})
                if progress:
                    progress(f"  [{label}] #{c['rank']} {c['tbl_id']} → {len(rec['table']['rows'])}행 ({time.time() - t0:.1f}초)")
            done = {v["tbl_id"] for v in views}
            for c in cands:
                c["has_view"] = c["tbl_id"] in done
            out_units.append({"unit_id": uid, "query": text, "filters": f, "candidates": cands,
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
