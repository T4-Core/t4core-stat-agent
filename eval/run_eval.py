"""[NEW] 검색 성능 평가 진입점 (구조안의 eval/run_eval.py)

현재 있는 평가 두 가지를 한 곳에서 부른다 (로직은 각 모듈 그대로):
  retrieval : 하이브리드 인덱스 Recall@k·MRR  = 구 python kosis_rag_qa.py eval   (variant 여러 개 → 임베딩/보강 비교)
  rewrite   : 질의 재작성 80문항 일괄 실행     = eval/query_rewrite/scripts/run_eval.py

실행 (저장소 루트에서)
  python eval/run_eval.py retrieval --variants base enriched --qa eval/golden_set/<gold>.jsonl
  python eval/run_eval.py rewrite --n 5 --today 2026-11-02
"""
import argparse
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["retrieval", "rewrite"])
    ap.add_argument("--variants", nargs="*", default=["base"])
    ap.add_argument("--qa", default=None, help="jsonl: {question, gold: [id …]} (없으면 뷰 템플릿 질문 자동 생성)")
    ap.add_argument("--n", type=int, default=200)
    args, rest = ap.parse_known_args()
    if args.what == "retrieval":
        from backend.agent.light_agent import stage_eval
        for v in args.variants:
            stage_eval(argparse.Namespace(variant=v, qa=args.qa, n=args.n))
    else:
        sys.argv = [str(ROOT / "eval/query_rewrite/scripts/run_eval.py"), *rest] + (["--n", str(args.n)] if "--n" in sys.argv else [])
        runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
