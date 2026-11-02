"""평가 질문 파일(CSV)의 question 열을 모두 재작성 → QueryBundle·대시보드 데이터 저장
노트북의 1단계(질문 입력) + 2-3 실행(병렬 호출) + 4단계 저장 + 5단계(대시보드용 중간 결과)를 합친 것

실행 (eval/query_rewrite 폴더에서. 저장소 루트에서는 python eval/query_rewrite/scripts/run_eval.py)
    [CHANGED] 이전: Rewritten_fastapi 폴더에서 실행
    python scripts/run_eval.py                    # 80개 전체 (HCX 80회)
    python scripts/run_eval.py --n 5              # 앞에서 5개만
    python scripts/run_eval.py --today 2026-11-02 # 상대 시점 기준일 지정

저장
    outputs/query_bundles.json            QueryBundle 목록
    dashboard/rewrite_trace.json, .js     대시보드용 중간 결과 → dashboard/rewrite_pipeline_dashboard.html 로 보기
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent           # eval/query_rewrite  (data/ outputs/ dashboard/ 가 있는 곳 — 구조는 예전과 같음)
sys.path.insert(0, str(ROOT.parents[1]))                # [CHANGED] 이전: sys.path.insert(0, str(ROOT))  → 저장소 루트 (backend 패키지)

from backend.rag.query_analyzer import build_trace, run_pipeline, save_bundles, save_trace   # noqa: E402
from backend.rag.query_analyzer.config import DATA_DIR, settings                              # noqa: E402
# [CHANGED] 이전: from rewriter import ... / from rewriter.config import DATA_DIR, settings


def _nonempty(s):
    return {k: v for k, v in (s or {}).items() if v not in ([], "", None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DATA_DIR / "kosis_rag_eval_80_queries.csv"), help="질문 CSV (question 열만 읽음)")
    ap.add_argument("--n", type=int, default=None, help="앞에서부터 쓸 질문 수 (기본: 전체)")
    ap.add_argument("--today", default=None, help="상대 시점 기준일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--workers", type=int, default=4, help="동시에 보내는 HCX 호출 수 (429가 많으면 줄임)")
    ap.add_argument("--bundles", default=None, help="QueryBundle 저장 경로 (기본: outputs/query_bundles.json)")
    ap.add_argument("--trace-dir", default=None, help="대시보드용 중간 결과 저장 폴더 (기본: dashboard/)")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else None
    df = pd.read_csv(args.csv, encoding="utf-8-sig", usecols=["question"])   # question 열만
    questions = df["question"].astype(str).str.strip().tolist()
    questions = questions if args.n is None else questions[:args.n]
    s = settings()
    print(f"질문 {len(questions)}개 | 모델 {s['model']} | 기준일 {today or date.today()} | API 키 {'있음' if s['has_api_key'] else '없음'}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_pipeline, q, today) for q in questions]
        results = []
        for i, f in enumerate(futs, 1):                  # 질문 순서대로 받음
            res = f.result()
            results.append(res)
            r, b = res["slot"], res["bundle"]
            state = "" if r["parsed"] else f"  [HCX 실패: {r['error']}]"
            print(f"[{i}/{len(questions)}] {r['elapsed_s']:>5}초 | {b.original}\n          → {b.rewritten}"
                  + (f"  ▸하위 {b.sub_questions}" if b.sub_questions else "") + state)

    fail = [i for i, res in enumerate(results, 1) if not res["slot"]["parsed"]]
    fixed = sum(1 for res in results if res["valid"]["log"])
    print(f"\n완료: {len(results)}개, {time.time() - t0:.1f}초 | HCX 실패 {len(fail)}개 {fail or ''} | 검증에서 고친 질문 {fixed}개")

    bundles = [res["bundle"] for res in results]
    save_bundles(bundles, args.bundles) if args.bundles else save_bundles(bundles)   # 저장 경로를 출력함
    trace = build_trace(results, today, source=Path(args.csv).name)
    pj, pjs = save_trace(trace, Path(args.trace_dir)) if args.trace_dir else save_trace(trace)
    print(f"저장: {pj}\n저장: {pjs}\n대시보드: {ROOT / 'dashboard' / 'rewrite_pipeline_dashboard.html'}"
          + ("  (다른 폴더에 저장했다면 그 폴더에 대시보드 html 을 함께 두고 열기)" if args.trace_dir else ""))


if __name__ == "__main__":
    main()
