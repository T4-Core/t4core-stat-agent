"""python -m backend.rag.search "질문" [--dense hcx|arctic-ko|bge-m3-ko|ens-ko|none|hash] [--dense-docs slot+def+rw] [--llm]
                                   [--top-k 10] [--no-analyze]
질문 하나를 검색해 순위·채널별 순위·구조 계수가 깎인 이유를 보여 준다 (왜 그 순위인지 확인용)"""
import argparse
import json
import sys


def main(argv=None):
    from backend.rag.search.index import dense_names
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--dense", default=None, choices=dense_names())
    ap.add_argument("--dense-docs", default=None, help="dense 문서: rule | def | slot | tmpl | tslot | kos14 ('+' 로 여러 개, +rw)")
    ap.add_argument("--cards", default=None, help="dense 카드 파일 (기본 storage/indices/dense_cards/cards.jsonl)")
    ap.add_argument("--kos14", default=None, help="팀 카드 cards.jsonl (dense-docs kos14)")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--no-analyze", action="store_true", help="질의 분석(HCX)을 거치지 않고 원문만으로")
    a = ap.parse_args(argv)
    from backend.rag.search import get_search
    from backend.rag.search.tuning.compare import analyze_units
    q = " ".join(a.question)
    st = {k: v for k, v in {"dense_docs": a.dense_docs, "dense_cards": a.cards, "kos14_cards": a.kos14}.items() if v}
    s = get_search(dense=a.dense, llm_rerank=a.llm, settings=st or None)
    for u in analyze_units(q, "none" if a.no_analyze else "analyze"):
        r = s.search(u["search_query"], u["filters"], a.top_k, question=q, unit=u["unit"])
        print(f"\n[{s.name}] 단위 {u['unit']} ({u.get('status')}) | 재작성: {u['search_query']} | 슬롯: {u['filters']}")
        print("  읽어 낸 조건:", json.dumps(r["parsed"], ensure_ascii=False, default=str)[:400])
        for h in r["hits"]:
            st = " ".join(f"{k}#{v['rank']}" for k, v in h["stages"].items())
            print(f"  {h['rank']:2d}. {h['tbl_id']:20s} {h['score']:.4f} ×{h['feas']:<5} {h['survey_nm']} | {h['tbl_nm'][:44]}"
                  f"\n        {st}" + (f"  ⚠ {', '.join(h['feas_notes'])}" if h.get("feas_notes") else ""))


if __name__ == "__main__":
    main()
