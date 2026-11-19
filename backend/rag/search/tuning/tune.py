"""검색 가중치 맞추기 — 골든셋 dev 문항으로 채널 가중치·rrf_k 를 좌표 상승으로 고른다

채널 점수·구조 계수는 가중치와 무관하므로 문항마다 한 번만 계산해 두고, 가중치만 바꿔 가며 순위를 다시 매긴다 (수 초).
맞춘 값이 dev 에만 맞는 값인지 보도록 held-out 문항 점수를 같이 낸다 — held-out 이 떨어지면 쓰지 않는다.

  python -m backend.rag.search.tuning.tune --golden tests/retrieval_golden.jsonl --split dev                # 손 골든셋 (dev / test)
  python -m backend.rag.search.tuning.tune --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl --variants P
  python -m backend.rag.search.tuning.tune --golden <합성 셋> --dense arctic-ko --cache <compare 폴더>/analysis_cache.jsonl
  → configs/search.tuned.yaml  (dense none) · configs/search.tuned.<dense>.yaml  (확인 후 configs/search.yaml 로 옮김)
     compare --tuned 는 dense 마다 search.tuned.<dense>.yaml 을 읽어 그 모델에 맞춘 가중치로 비교한다

맞출 문항: --split 을 주면 그 split, 합성 셋은 splits.split_of 의 dev (compare --split heldout 과 겹치지 않음),
           그 밖에는 record_id 해시로 절반

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


def tuned_path(dense, configs_dir=None, docs=None):
    """dense 별 맞춘 가중치 파일 (none 은 예전 이름 그대로). dense 문서가 rule 이 아니면 이름에 붙임
    (search.tuned.bge-m3-ko.slot-def-rw.yaml)"""
    if configs_dir is None:
        from backend.core.config import CONFIGS_DIR as configs_dir
    if dense in (None, "none"):
        return Path(configs_dir) / "search.tuned.yaml"
    tail = f".{str(docs).replace('+', '-').replace(',', '_')}" if docs and docs != "rule" else ""
    return Path(configs_dir) / f"search.tuned.{dense}{tail}.yaml"


def load_tuned(dense, configs_dir=None, docs=None):
    """search.tuned.<dense>[.<docs>].yaml → {rrf_k, weights} (없으면 None — 문서별 파일이 없으면 dense 파일도 보지 않음:
    다른 문서로 맞춘 가중치를 섞지 않게)"""
    f = tuned_path(dense, configs_dir, docs)
    if not f.exists():
        return None
    import yaml
    d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {k: d[k] for k in ("rrf_k", "weights") if k in d} or None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.tune")
    ap.add_argument("--golden", default=None)
    ap.add_argument("--from-run", default=None, metavar="이름", help="이전 compare 실행의 골든셋 · 질의 분석 캐시를 씀 (compare --list-runs)")
    from backend.rag.search.index import dense_names
    ap.add_argument("--dense", default="none", choices=dense_names())
    ap.add_argument("--dense-docs", default="rule", help="dense 문서 (rule | def | slot | … '+' 로, +rw) — compare --dense-docs 와 같은 값")
    ap.add_argument("--cards", default=None, help="dense 카드 파일")
    ap.add_argument("--kos14", default=None, help="팀 카드 cards.jsonl")
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--split", nargs="*", default=None, help="맞출 문항 (retrieval_golden 의 split). 없으면 record_id 해시로 절반")
    ap.add_argument("--analyze", default="analyze", choices=["analyze", "none"])
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--cache", default=None, help="질의 분석 캐시 (compare 실행 폴더의 analysis_cache.jsonl 을 주면 HCX 를 다시 부르지 않음)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--raw-units", action="store_true", help="캐시된 질의 분석에 하위 질문 검증을 다시 적용하지 않음 (compare 와 맞춤)")
    ap.add_argument("--out", default=None, help="기본 configs/search.tuned.yaml (dense none) · search.tuned.<dense>.yaml")
    a = ap.parse_args(argv)
    if a.from_run:
        from backend.rag.search.tuning.compare import find_run
        prev = find_run(a.from_run)
        cfg = json.loads((prev / "config.json").read_text(encoding="utf-8")) if (prev / "config.json").exists() else {}
        a.golden = a.golden or cfg.get("golden")
        if a.cache is None and (prev / "analysis_cache.jsonl").exists():
            a.cache = str(prev / "analysis_cache.jsonl")
        print(f"[이전 실행] {prev.name} → golden {a.golden} · 캐시 {a.cache or '-'}", flush=True)
    if not a.golden:
        ap.error("--golden 또는 --from-run 이 필요합니다")
    from backend.core.config import CONFIGS_DIR
    a.out = a.out or str(tuned_path(a.dense, CONFIGS_DIR, a.dense_docs))

    from backend.rag.search import get_search
    from backend.rag.search.tuning.compare import analyze_all, load_golden
    rows = load_golden(a.golden, tuple(a.variants))
    cache = Path(a.cache) if a.cache else Path(a.out).with_suffix(".analysis_cache.jsonl")
    cache.parent.mkdir(parents=True, exist_ok=True)
    analysis = analyze_all(rows, a.analyze, a.today, cache)
    if not a.raw_units:  # compare 와 같은 단위 (하위 질문 검증 — query_analyzer/subcheck.py)
        from backend.rag.search.tuning.compare import prune_analysis
        analysis, _ = prune_analysis(rows, analysis)
    st = {"dense_docs": a.dense_docs, "dense_cards": a.cards, "kos14_cards": a.kos14} if a.dense_docs != "rule" else None
    s = get_search(dense=a.dense, settings=st)

    def is_dev(r):
        if a.split:
            return r.get("difficulty") in a.split
        if r.get("split") in ("dev", "heldout"):          # 합성 셋: compare --split heldout 과 같은 나누기
            return r["split"] == "dev"
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
