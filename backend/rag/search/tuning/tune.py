"""검색 가중치 맞추기 — 골든셋 dev 문항으로 채널 가중치·rrf_k 를 좌표 상승으로 고른다

채널 점수·구조 계수는 가중치와 무관하므로 문항마다 한 번만 계산해 두고, 가중치만 바꿔 가며 순위를 다시 매긴다 (수 초).
맞춘 값이 dev 에만 맞는 값인지 보도록 held-out 문항 점수를 같이 낸다 — held-out 이 떨어지면 쓰지 않는다.

  python -m backend.rag.search.tuning.tune --golden tests/retrieval_golden.jsonl --split dev                # 손 골든셋 (dev / test)
  python -m backend.rag.search.tuning.tune --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl --variants P
  → configs/search.tuned.yaml  (확인 후 configs/search.yaml 로 옮김)

목표 = MRR + Hit@5 + 0.5 × Groups@5 (compare.py 와 같은 정의: 단위별 순위를 (순위, 단위 순서)로 합침)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

STEPS = (0.0, 0.5, 0.75, 1.25, 1.5, 2.0)
RRF_KS = (10, 20, 40, 60)


def _ranking(s, preps, weights, rrf_k, top_k):
    best = {}
    for ui, p in enumerate(preps):
        final, _, order = s.fuse(p, weights, rrf_k)
        for r, i in enumerate(order[:top_k], 1):
            if final[i] <= 0:
                break
            t = s.docs[i].id
            if t not in best or (r, ui) < best[t]:
                best[t] = (r, ui)
    return [t for t, _ in sorted(best.items(), key=lambda x: x[1])]


def metrics(s, data, weights, rrf_k, top_k=10):
    mrr = h1 = h5 = g5 = 0.0
    for row, preps in data:
        rk = _ranking(s, preps, weights, rrf_k, top_k)
        acc = set(row["gold"]) | {t for v in row["groups"].values() for t in v}
        pos = next((i for i, t in enumerate(rk, 1) if t in acc), None)
        mrr += 1 / pos if pos else 0
        h1 += bool(pos and pos <= 1)
        h5 += bool(pos and pos <= 5)
        g5 += all(set(v) & set(rk[:5]) for v in row["groups"].values())
    n = max(len(data), 1)
    out = {"n": len(data), "mrr": round(mrr / n, 4), "hit@1": round(h1 / n, 4), "hit@5": round(h5 / n, 4),
           "groups@5": round(g5 / n, 4)}
    out["score"] = round(out["mrr"] + out["hit@5"] + 0.5 * out["groups@5"], 4)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.tune")
    ap.add_argument("--golden", required=True)
    ap.add_argument("--dense", default="none", choices=["none", "hcx", "hash"])
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--split", nargs="*", default=None, help="맞출 문항 (retrieval_golden 의 split). 없으면 record_id 해시로 절반")
    ap.add_argument("--analyze", default="analyze", choices=["analyze", "none"])
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--cache", default=None, help="질의 분석 캐시 (compare 실행 폴더의 analysis_cache.jsonl 을 주면 HCX 를 다시 부르지 않음)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out", default=None, help="기본 configs/search.tuned.yaml")
    a = ap.parse_args(argv)
    from backend.core.config import CONFIGS_DIR
    a.out = a.out or str(CONFIGS_DIR / "search.tuned.yaml")

    from backend.rag.search import get_search
    from backend.rag.search.tuning.compare import analyze_all, load_golden
    rows = load_golden(a.golden, tuple(a.variants))
    cache = Path(a.cache) if a.cache else Path(a.out).with_suffix(".analysis_cache.jsonl")
    cache.parent.mkdir(parents=True, exist_ok=True)
    analysis = analyze_all(rows, a.analyze, a.today, cache)
    s = get_search(dense=a.dense)

    def is_dev(r):
        if a.split:
            return r.get("difficulty") in a.split
        return int(hashlib.sha1(str(r["record_id"]).encode()).hexdigest(), 16) % 2 == 0
    data = [(r, [s.prepare(u["search_query"], u.get("filters"), r["question"], u.get("unit") or "main", a.today)
                 for u in analysis[r["qid"]]]) for r in rows]
    dev, held = [d for d in data if is_dev(d[0])], [d for d in data if not is_dev(d[0])]
    if not dev:
        dev, held = data, []
    w, k = copy.deepcopy(s.s["weights"]), s.s["rrf_k"]
    before = {"dev": metrics(s, dev, w, k), "held_out": metrics(s, held, w, k) if held else None}
    best = before["dev"]["score"]
    for _ in range(a.rounds):
        moved = False
        for name in sorted(w):
            base = w[name] or 1.0
            for m in STEPS:
                trial = {**w, name: round(base * m, 3)}
                sc = metrics(s, dev, trial, k)["score"]
                if sc > best + 1e-9:
                    best, w, moved = sc, trial, True
        for kk in RRF_KS:
            sc = metrics(s, dev, w, kk)["score"]
            if sc > best + 1e-9:
                best, k, moved = sc, kk, True
        if not moved:
            break
    after = {"dev": metrics(s, dev, w, k), "held_out": metrics(s, held, w, k) if held else None}
    import yaml
    Path(a.out).write_text(
        f"# python -m backend.rag.search.tuning.tune --golden {a.golden}  ({date.today()})\n"
        f"# dev {before['dev']} → {after['dev']}\n# held-out {before['held_out']} → {after['held_out']}\n"
        + yaml.safe_dump({"rrf_k": k, "weights": w}, allow_unicode=True, sort_keys=True), encoding="utf-8")
    res = {"before": before["dev"], "after": after["dev"], "held_out_before": before["held_out"],
           "held_out_after": after["held_out"], "rrf_k": k, "weights": w, "out": a.out}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
