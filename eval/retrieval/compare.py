"""[NEW v4] 검색 구성 비교 CLI — backend/rag/retrieval/lab.py 를 그대로 부름 (API: POST /api/v1/retrieval-lab/compare)

실행 (저장소 루트에서)
  python eval/retrieval/compare.py list                                            # 구성 목록·설치 필요 패키지
  python eval/retrieval/compare.py run --configs baseline hybrid_rrf_hcx kiwi_lexicon --source bundles --limit 20
  python eval/retrieval/compare.py run --configs baseline st_bge_m3 --source eval/retrieval/queries_sample.yaml --blind
  python eval/retrieval/compare.py score <run_id>                                  # review.csv 의 label 칸 채운 뒤
  python eval/retrieval/compare.py search "1인가구 가구수" --config baseline --filters '{"시점":[2025],"지역":["전국"]}'

결과: storage/runs/<run_id>/ report.html(나란히 보기) · report.md · review.csv(판정표) · results.jsonl · summary.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--configs", nargs="+", default=["baseline", "bm25_only"])
    r.add_argument("--source", default="bundles", help="bundles | golden | examples | <yaml/json/jsonl 경로>")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--analyze", choices=["none", "v4"], default="none", help="v4: 슬롯 없는 질문을 v4 쿼리 모듈로 (HCX)")
    r.add_argument("--today", default=None)
    r.add_argument("--top-k", type=int, default=10)
    r.add_argument("--reference", default=None)
    r.add_argument("--blind", action="store_true", help="보고서·판정표에서 구성 이름을 A·B·C 로 가림")
    r.add_argument("--trace", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("run_id")
    s.add_argument("--review", default=None, help="채운 review.csv 경로 (기본: 실행 폴더의 review.csv)")
    s.add_argument("--k", type=int, default=None)
    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("--config", default="baseline")
    q.add_argument("--filters", default=None, help="JSON")
    q.add_argument("--top-k", type=int, default=10)
    q.add_argument("--prep", choices=["none", "resolve"], default=None)
    a = ap.parse_args()

    if a.cmd == "list":
        from backend.rag.retrieval.factory import list_configs
        for c in list_configs():
            miss = f"  [설치 필요: {', '.join(c['missing'])}]" if c.get("missing") else ""
            print(f"{c['name']:20s} {c.get('error') or c.get('description', '')}{miss}")
    elif a.cmd == "run":
        from backend.rag.retrieval import lab
        qs = lab.load_queries(a.source, limit=a.limit, analyze=a.analyze, today=a.today)
        print(f"질의 {len(qs)}개 × 구성 {a.configs}")
        res = lab.run_compare(qs, a.configs, top_k=a.top_k, reference=a.reference, blind=a.blind, trace=a.trace,
                              progress=lambda m: print(m, flush=True))
        for c in res["configs"]:
            if c.get("error"):
                print(f"  ✗ {c['name']}: {c['error']}")
        print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
        print("\n보고서:", res["files"]["html"], "\n판정표:", res["files"]["review"])
    elif a.cmd == "score":
        from backend.rag.retrieval.lab import score_review
        print(json.dumps(score_review(a.run_id, review_path=a.review, k=a.k), ensure_ascii=False, indent=1))
    elif a.cmd == "search":
        from backend.rag.retrieval.factory import get_pipeline
        p = get_pipeline(a.config, {"query.prep": a.prep} if a.prep else None)
        r = p.search(a.query, json.loads(a.filters) if a.filters else None, a.top_k)
        print(f"[{a.config}] {r['search_query']}  ({r['seconds']}초)")
        for h in r["hits"]:
            st = " ".join(f"{k}#{v['rank']}" for k, v in h["stages"].items())
            print(f"  {h['rank']:2d}. {h['tbl_id']:18s} {h['score']}  {h['survey_nm']} | {h['tbl_nm']}   ({st})")


if __name__ == "__main__":
    main()
