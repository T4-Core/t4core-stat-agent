"""
[NEW 11-17] 하이브리드 가중치 조정 — dev 로 맞추고, 다른 셋으로 확인

조정하는 값 (configs/hybrid.yaml 의 hybrid_all 기준)
  w_bm25   BM25 순위 목록의 RRF 가중치 (dense 는 1 고정)
  w_orig   원래 질문(orig) 순위 목록에 곱하는 가중치
  rrf_k    RRF 의 k (작을수록 1~2등에 힘을 더 줌)
  alpha    시점 외 조건 불일치 감점 (클수록 조건 안 맞는 표가 더 내려감)
  beta     요청 기간을 못 담은 만큼 감점

안전장치
  · 질의 분석은 compare 가 저장한 캐시만 읽음 — 없으면 멈춤 (HCX 분석 호출 없음)
  · 질문 임베딩은 한 번만 계산해 메모리에 둠 (설정을 몇 개 바꿔도 HCX 임베딩 호출은 질문 수만큼)

  python -m table_card_search.tune_hybrid --golden tests/retrieval_golden.jsonl --split dev \
      --analysis-cache table_card_search/runs/rg_dev/analysis_cache.jsonl --out table_card_search/runs/tune_dev
  python -m table_card_search.tune_hybrid ... --only "w_bm25=1,w_orig=0.5,rrf_k=60,alpha=0.5,beta=0.3"   (한 설정만)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import statistics
import sys
from pathlib import Path

from table_card_search.compare import evaluate_one, load_golden
from table_card_search.search import EMBEDDERS, get_pipeline_for

GRID = {"w_bm25": [0.5, 1.0, 1.5], "w_orig": [0.5, 1.0], "rrf_k": [20, 60], "alpha": [0.25, 0.5, 1.0],
        "beta": [0.1, 0.3, 0.5]}
BASE = {"w_bm25": 1.0, "w_orig": 1.0, "rrf_k": 60, "alpha": 0.5, "beta": 0.3}     # 조정 전 값 (비교 기준). 11-17 채택 = rrf_k 20
# [NEW 11-17] 리랭커 조정 (--grid rerank): 비교 기준 = 채택한 설정(rrf_k 20) + 리랭커 없음
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_BASE = {**BASE, "rrf_k": 20, "rerank_model": "", "rerank_mode": "", "rerank_query": "", "rerank_top": 0,
               "rerank_weight": 0.0}
RERANK_GRID = [{**RERANK_BASE, "rerank_model": RERANK_MODEL, "rerank_mode": m, "rerank_query": q, "rerank_top": n,
                "rerank_weight": w}
               for m, ws in (("ce", [1.0]), ("rrf", [1.0, 2.0])) for w in ws
               for q in ("orig", "sq") for n in (20, 30)]


def read_cache(path, rows, mode, today):
    """compare.analyze_all 과 같은 키로 캐시만 읽음. 하나라도 없으면 멈춤"""
    cache = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            cache[r["key"]] = r
    out, missing = {}, []
    for r in rows:
        key = hashlib.sha1(f"{mode}|{today}|{r['question']}".encode()).hexdigest()[:16]
        if key in cache:
            out[r["qid"]] = cache[key]["units"]
        else:
            missing.append(r["question"])
    if missing:
        sys.exit(f"분석 캐시에 없는 질문 {len(missing)}개 (HCX 를 부르지 않고 멈춤): {missing[:3]}")
    return out


def apply(pipe, p):
    lists = pipe.lists
    pipe.cfg.update(rrf_k=p["rrf_k"], alpha=p["alpha"], beta=p["beta"],
                    weights={s: (p["w_bm25"] if s.startswith("bm25") else 1.0) * (p["w_orig"] if s.endswith("orig") else 1.0)
                             for s in lists})
    for k in ("rerank_model", "rerank_mode", "rerank_query", "rerank_top", "rerank_weight"):   # 없으면 리랭커 끔
        pipe.cfg[k] = p.get(k) or None


def score(pipe, bm25, rows, analysis, top_k=10, pool=50):
    res = [evaluate_one(pipe, bm25, r, analysis[r["qid"]], top_k, pool) for r in rows]
    out = {f"hit@{k}": round(statistics.mean(x[f"hit@{k}"] for x in res), 3) for k in (1, 5, 10)}
    out["mrr"] = round(statistics.mean(x["mrr"] for x in res), 3)
    if res and "rank_alt" in res[0]:
        out["hit@5_alt"] = round(statistics.mean(bool(x["rank_alt"] and x["rank_alt"] <= 5) for x in res), 3)
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m table_card_search.tune_hybrid")
    ap.add_argument("--golden", required=True)
    ap.add_argument("--split", nargs="*", default=None)
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--alt", default=None)
    ap.add_argument("--analysis-cache", required=True)
    ap.add_argument("--analyze", default="v4c")
    ap.add_argument("--today", default="2026-11-17")
    ap.add_argument("--method", default="hybrid_all")
    ap.add_argument("--dense", default="hcx", choices=list(EMBEDDERS))
    ap.add_argument("--only", nargs="*", default=None, help='설정만 채점: "w_bm25=1,w_orig=0.5,..." (여러 개 가능, 빠진 값은 기본)')
    ap.add_argument("--grid", default="base", choices=["base", "rerank"], help="[NEW 11-17] base = RRF·감점 값 | rerank = 리랭커")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    rows = load_golden(a.golden, tuple(a.variants), split=a.split)
    if a.alt:
        from table_card_search.alt_gold import load_alt
        alt = load_alt(a.alt)
        for r in rows:
            r["alt_groups"] = alt.get(r["record_id"], {})
    analysis = read_cache(a.analysis_cache, rows, a.analyze, a.today)
    pipe = get_pipeline_for(a.method, a.dense)
    if pipe.dense is not None:                       # 질문 임베딩 메모 (HCX 임베딩 호출 줄이기)
        memo, f = {}, pipe.dense.scores
        pipe.dense.scores = lambda q: memo[q] if q in memo else memo.setdefault(q, f(q))
    bm25 = pipe.bm25
    base = RERANK_BASE if a.grid == "rerank" else BASE

    def _val(v):
        try:
            return float(v)
        except ValueError:
            return v
    if a.only:
        params = [{**base, **{k: _val(v) for k, v in (x.split("=") for x in s.split(","))}} for s in a.only]
        if a.grid == "rerank":
            params = [{**p, "rerank_model": p["rerank_model"] or RERANK_MODEL} for p in params]
    elif a.grid == "rerank":
        params = RERANK_GRID
    else:
        params = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    params = [base] + [p for p in params if p != base]                # 비교 기준은 늘 같이 채점
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, p in enumerate(params, 1):
        p = {**p, "rrf_k": int(p["rrf_k"])}
        apply(pipe, p)
        results.append({**p, **score(pipe, bm25, rows, analysis)})
        if i % 20 == 0 or i == len(params):
            print(f"  {i}/{len(params)}", flush=True)
    results.sort(key=lambda r: (-r["mrr"], -r["hit@5"]))
    with (out / "tune.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    ref = next(r for r in results if all(r[k] == base[k] for k in base))
    print(f"[{len(rows)}문항] 비교 기준  {ref}")
    for r in results[:8]:
        print("  ", r)
    print(f"→ {out / 'tune.csv'}")


if __name__ == "__main__":
    main()
