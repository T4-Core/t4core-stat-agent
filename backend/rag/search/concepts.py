"""개념 카탈로그 — '같은 통계를 주는 표 묶음'

같은 값을 주는 표가 여럿인 경우가 흔해, 표 하나하나를 맞히기보다 '어떤 통계(개념)인가' 를 먼저 맞히고
그 안의 표는 좌표로 고른다.
  씨앗 1) 대체 정답 (tuning/alt_gold.py 의 alt_positives.jsonl) — 같은 시점·지역·항목의 값이 정답 값과 같은 표들
       2) 형제 표 무리 (siblings.py) — 검색 때 바로 만들어짐 (파일에는 넣지 않음)
  과적합 방지: 기본은 dev 레코드(tuning/splits.py)의 대체 정답만 → 평가는 compare --split heldout
  쓰임: 상위 밖에 있는 같은 개념의 표를 LLM 후보로 끌어오고 카드에 같은 묶음으로 표시

  python -m backend.rag.search.concepts build --alt <alt_positives.jsonl…> --golden <합성 셋.jsonl…>
  python -m backend.rag.search.concepts build --per-query <compare 폴더>/per_query.csv
  python -m backend.rag.search.concepts show
  → <CSV 값 사전 폴더>/concepts.json   (끄기: configs/search.yaml 의 concepts: {enabled: false})
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from backend.rag.search.tuning.splits import split_of


def _tid(x):
    m = re.match(r"^\d{2,4}_(.+)$", str(x))
    return m.group(1) if m else str(x)


def catalog_path():
    from backend.rag.csv_index.store import index_dir
    return Path(index_dir()) / "concepts.json"


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _golden_groups(paths):
    """{dataset_id: {group: [acceptable tbl_id…]}}"""
    out = {}
    for f in paths or []:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                g = (r.get("retrieval_eval") or {}).get("required_evidence_groups") or {}
                out[r["dataset_id"]] = {k: [_tid(t) for t in v.get("acceptable_table_ids") or []] for k, v in g.items()}
    return out


def evidence(alt=(), golden=(), per_query=(), include_rounded=False, splits=("dev",)):
    """→ [(표 묶음, 근거 레코드)] 같은 값을 준 표들"""
    out = []
    groups = _golden_groups(golden)
    for f in alt or []:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if splits and split_of(r["dataset_id"]) not in splits:
                continue
            gold = [_tid(t) for t in r.get("gold_tables") or []]
            for g, v in (r.get("groups") or {}).items():
                alts = [a["tbl_id"] for a in v.get("alternatives") or [] if include_rounded or a.get("match") == "exact"]
                base = (groups.get(r["dataset_id"]) or {}).get(g) or (gold if len(gold) == 1 else [])
                if alts and base:
                    out.append((sorted(set(base) | set(alts)), r["dataset_id"]))
    for f in per_query or []:
        seen = set()
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            rid = r.get("record_id") or r.get("qid")
            gold = (r.get("gold") or "").split()
            alts = (r.get("alt_tables") or "").split()
            if rid in seen or len(gold) != 1 or not alts or (splits and split_of(rid) not in splits):
                continue
            seen.add(rid)
            out.append((sorted(set(gold) | set(alts)), rid))
    return out


def build(alt=(), golden=(), per_query=(), include_rounded=False, splits=("dev",), max_size=12, names=None):
    ev = evidence(alt, golden, per_query, include_rounded, splits)
    uf, cnt = _UF(), Counter()
    for tables, _ in ev:
        for t in tables[1:]:
            uf.union(tables[0], t)
        for t in tables:
            cnt[t] += 1
    by = defaultdict(set)
    for tables, _ in ev:
        for t in tables:
            by[uf.find(t)].add(t)
    concepts, n = [], 0
    for root, ts in sorted(by.items()):
        if len(ts) < 2 or len(ts) > max_size:
            continue
        n += 1
        nm = Counter((names or {}).get(t, t) for t in ts).most_common(1)[0][0]
        concepts.append({"id": f"C{n:03d}", "name": nm, "tables": sorted(ts), "n_evidence": sum(cnt[t] for t in ts)})
    return {"created": datetime.now().isoformat(timespec="seconds"), "splits": list(splits or []) or "all",
            "include_rounded": include_rounded, "n_evidence": len(ev), "concepts": concepts}


def load(path=None):
    p = Path(path) if path else catalog_path()
    if not p.exists():
        return []
    return [c["tables"] for c in json.loads(p.read_text(encoding="utf-8")).get("concepts") or []]


def _names():
    try:
        from backend.rag.search.index import table_corpus
        return {d.id: d.meta.get("tbl_nm", "") for d in table_corpus().docs()}
    except Exception:  # noqa: BLE001
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "show"])
    ap.add_argument("--alt", nargs="*", default=[])
    ap.add_argument("--golden", nargs="*", default=[], help="합성 셋 (근거 그룹별 정답 표를 알기 위해)")
    ap.add_argument("--per-query", nargs="*", default=[])
    ap.add_argument("--rounded", action="store_true", help="반올림 일치(rounded) 대체 정답도 씀")
    ap.add_argument("--all-splits", action="store_true", help="heldout 레코드까지 씀 (평가 문항과 겹침 — 운영용)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else catalog_path()
    if a.cmd == "show":
        d = json.loads(out.read_text(encoding="utf-8"))
        print(f"{len(d['concepts'])}개 · 근거 {d['n_evidence']} · splits {d['splits']}")
        for c in d["concepts"][:50]:
            print(f"  {c['id']} {c['name'][:40]:40s} {' '.join(c['tables'])}")
        return
    d = build(a.alt, a.golden, a.per_query, a.rounded, None if a.all_splits else ("dev",), names=_names())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"개념 {len(d['concepts'])}개 (근거 {d['n_evidence']}) → {out}")


if __name__ == "__main__":
    main()
