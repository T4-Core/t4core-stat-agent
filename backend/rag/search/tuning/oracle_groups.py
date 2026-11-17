"""여러 표 질문의 상한 실험 — '질문을 근거 그룹대로 정확히 나눴다면' Groups@k 가 얼마나 되는가

합성 골든셋은 근거 그룹마다 설명을 갖고 있다 ('2015년 국제결혼 이주자 (부산진구, 합계)').
이 설명을 하위 검색 단위로 그대로 넣어(= 완벽한 분해) 검색하고, 실제 질의 분석이 만든 단위와 Groups@5·10 을 비교한다.
  actual   compare 가 쓴 검색 단위 (analysis_cache.jsonl)
  oracle   본 질의 단위 + 근거 그룹 설명 단위 (같은 설명은 연도를 빼고 한 번만)
  차이가 크면 '질문 나누기(계획)' 가 병목 → 여러 표 질문에 계획 단계를 붙일 가치가 있음
  차이가 작으면 나눠도 검색이 못 찾는 것 → 검색(색인·채널) 쪽 문제

설명에는 표의 항목 이름이 그대로 들어 있어 실제 사용자가 쓸 수 있는 문장보다 유리하다. 그래서 '상한' 으로만 읽는다.

  python -m backend.rag.search.tuning.oracle_groups --golden <합성 셋.jsonl> --cache <compare 폴더>/analysis_cache.jsonl
         [--dense hcx] [--llm] [--variants O P] [--multi-only] [--out <폴더>]
  → <out>/report.md · per_query.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

YEAR_RE = re.compile(r"(?:19|20)\d{2}년?")


def load_descriptions(path):
    """{dataset_id: {group: 설명}}"""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            g = (r.get("retrieval_eval") or {}).get("required_evidence_groups") or {}
            out[r["dataset_id"]] = {k: v.get("description") or "" for k, v in g.items()}
    return out


def load_cache(path):
    """analysis_cache.jsonl → {질문: 검색 단위 목록} (분석 방식·날짜와 상관없이 질문으로 찾음)"""
    out = {}
    if path and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["question"]] = r["units"]
    return out


def oracle_units(row, desc, actual):
    from backend.rag.search.resolve import search_query
    main = next((u for u in actual if u.get("unit") == "main"), None) or {
        "unit": "main", "text": row["question"], "search_query": row["question"], "filters": None}
    base = {k: v for k, v in (main.get("filters") or {}).items() if k in ("시점", "지역", "의도")} or None
    units, seen = [main], set()
    for g, text in desc.items():
        key = " ".join(YEAR_RE.sub("", text).split())
        if not text or key in seen:
            continue
        seen.add(key)
        units.append({"unit": f"G-{g}", "text": text, "filters": base,
                      "search_query": search_query(text, base) if base else text})
    return units


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.oracle_groups")
    ap.add_argument("--golden", required=True, help="합성 골든셋 (근거 그룹 설명이 있는 형식)")
    ap.add_argument("--cache", default=None, help="compare 실행 폴더의 analysis_cache.jsonl (없으면 질문마다 분석, HCX)")
    ap.add_argument("--dense", default="hcx", choices=["hcx", "hash", "none"])
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--multi-only", action="store_true", help="근거 그룹이 2개 이상인 문항만")
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    from backend.core.config import RUNS_DIR
    from backend.rag.search.tuning.compare import analyze_units, evaluate_one, get_search_for, load_golden
    out = Path(a.out) if a.out else Path(RUNS_DIR) / "search_compare" / f"{datetime.now():%Y%m%d_%H%M%S}_oracle"
    out.mkdir(parents=True, exist_ok=True)
    rows = load_golden(a.golden, tuple(a.variants))
    if a.multi_only:
        rows = [r for r in rows if len(r["groups"]) >= 2]
    desc, cache = load_descriptions(a.golden), load_cache(a.cache)
    pipe = get_search_for(a.dense, a.llm)
    print(f"[상한 실험] {len(rows)}문항 · 캐시 {sum(r['question'] in cache for r in rows)}개 · dense {a.dense}"
          f"{' · LLM' if a.llm else ''}", flush=True)
    per = []
    for i, r in enumerate(rows, 1):
        actual = cache.get(r["question"]) or analyze_units(r["question"], "analyze", a.today)
        orc = oracle_units(r, desc.get(r["record_id"], {}), actual)
        ra = evaluate_one(pipe, r, actual, a.top_k, 50)
        ro = evaluate_one(pipe, r, orc, a.top_k, 50)
        per.append({"qid": r["qid"], "record_id": r["record_id"], "variant": r["variant"], "hop_type": r["hop_type"],
                    "reasoning_type": r["reasoning_type"], "n_groups": len(r["groups"]), "question": r["question"],
                    "n_units_actual": len(actual), "n_units_oracle": len(orc),
                    **{f"{k}_actual": ra[k] for k in ("hit@1", "hit@5", "groups@5", "groups@10")},
                    **{f"{k}_oracle": ro[k] for k in ("hit@1", "hit@5", "groups@5", "groups@10")},
                    "oracle_units": " | ".join(u["search_query"] for u in orc[1:])})
        if i % 20 == 0:
            print(f"  {i}/{len(rows)}", flush=True)

    groups = defaultdict(list)
    for p in per:
        groups[("ALL", "ALL")].append(p)
        groups[("variant", p["variant"])].append(p)
        groups[("hop_type", p["hop_type"])].append(p)
        groups[("n_groups", str(p["n_groups"]))].append(p)
    lines = [f"# 여러 표 질문 상한 실험 — 실제 분해 vs 근거 그룹 설명으로 나눈 경우", "",
             f"- 실행 {datetime.now():%Y-%m-%d %H:%M} · 골든셋 `{a.golden}` · {len(per)}문항 · dense {a.dense}"
             f"{' · LLM 재정렬' if a.llm else ''} · 분석 캐시 `{a.cache or '-'}`",
             "- oracle = 본 질의 + 근거 그룹 설명 단위. 설명에 항목 이름이 들어 있어 실제보다 유리하므로 상한으로만 읽는다", "",
             "| 묶음 | 값 | n | groups@5 실제 → oracle | groups@10 실제 → oracle | hit@1 실제 → oracle | oracle 로 새로 맞음 / 잃음 (groups@5) |",
             "|---|---|---|---|---|---|---|"]
    for (g, v), ps in sorted(groups.items()):
        m = lambda k: sum(p[k] for p in ps) / len(ps)
        up = sum(p["groups@5_oracle"] > p["groups@5_actual"] for p in ps)
        dn = sum(p["groups@5_oracle"] < p["groups@5_actual"] for p in ps)
        lines.append(f"| {g} | {v} | {len(ps)} | {m('groups@5_actual'):.3f} → {m('groups@5_oracle'):.3f} | "
                     f"{m('groups@10_actual'):.3f} → {m('groups@10_oracle'):.3f} | "
                     f"{m('hit@1_actual'):.3f} → {m('hit@1_oracle'):.3f} | +{up} / −{dn} |")
    miss = [p for p in per if not p["groups@10_oracle"] and p["n_groups"] >= 2]
    lines += ["", f"## 근거 그룹대로 나눠도 상위 10 에 모든 그룹이 없는 문항 ({len(miss)}개, 최대 15개)", ""]
    for p in miss[:15]:
        lines.append(f"- **{p['qid']}** {p['question'][:90]}  \n  단위: {p['oracle_units'][:160]}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (out / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0]))
        w.writeheader()
        w.writerows(per)
    print("\n".join(lines[5:5 + 2 + len(groups)]))
    print(f"→ {out}")
    return out


if __name__ == "__main__":
    main()
