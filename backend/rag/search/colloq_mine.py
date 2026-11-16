"""[NEW 11-16] (P4) 일상어 사전 캐내기 — 합성 골든셋의 O(공식 용어) · P(일상어) 문항 쌍에서
'P 에만 있는 말 → O 에만 있고 정답 표 이름에도 있는 말' 짝을 세어 configs/colloquial.yaml 후보를 만든다

  과적합 방지: 캐내기는 dev 레코드에서만 (splits.py), 평가는 heldout 레코드로
  사람이 고른다: 후보 파일을 보고 맞는 줄만 colloquial.yaml 로 옮김 (자동으로 합치지 않음)

  1) 캐내기
     python -m backend.rag.search.colloq_mine mine --golden <합성 셋.jsonl> [--per-query <compare 폴더>/per_query.csv]
         --per-query 를 주면 P 문항이 1위를 놓친 레코드만 (없으면 dev 전부)
         → <out>/colloquial.candidates.yaml (짝 · 레코드 수 · 정밀도 · 예문)
  2) 보류 문항으로 확인 (검색 없이 빠르게: 일상어 사전이 더한 말이 정답 표 이름에 들어가는 문항 비율)
     python -m backend.rag.search.colloq_mine eval --golden <합성 셋.jsonl> [--extra <후보 yaml>]
  3) 진짜 확인 = compare 를 --split heldout 으로 (사전을 바꾸기 전 · 후)

정답 표 이름은 코퍼스(table_text)에서, 없으면 --refs (*_answers_references.csv 의 「표 이름」)에서 읽는다
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from backend.rag.search.splits import split_of
from backend.rag.search.text import norm

JOSA = re.compile(r"(?:들)?(?:에서의|에서는|에서|에게|에는|으로는|으로|로는|까지|부터|보다|처럼|마다|이나|이랑|과의|와의|의|에|은|는|"
                  r"이|가|을|를|도|과|와|만|로|요|죠)$")
STOP = set("""얼마나 얼마 몇 어떻게 되나요 될까요 되는지 무엇 무엇인가 인가요 이에요 일까요 알려주세요 알려줘 어느 어디 어디일까요
비교 비교해 비교하면 비교했을 비해 대비 기준 기준으로 경우 해당 해당하는 대한 관련 따르면 따른 결과 조사 통계 자료 표 수 수는
가장 많은 적은 높은 낮은 큰 작은 그 이 저 전체 모든 각 중 중에서 사이 동안 이후 이전 년 년도 해 년에 년과 한 하는 있는 있나요
증가 감소 변화 차이 비율 몇명 명 건 가구 호 퍼센트 %""".split())
TITLE_RE = re.compile(r"「([^」]+)」\((?:\d+_)?([A-Z0-9_]+)\)")


def tokens(text):
    out = []
    for t in str(text or "").split():
        t = re.sub(r"[^\w가-힣]", "", t)
        t = JOSA.sub("", t) if len(t) > 2 else t
        if len(t) < 2 or re.search(r"\d", t) or t in STOP:
            continue
        out.append(t)
    return out


def _region(t):
    try:
        from backend.rag.query_analyzer.v4.pipeline import region_shaped
        from backend.rag.ingestion.normalize import SIDO_ALIAS
        return region_shaped(t) or bool(SIDO_ALIAS.get(norm(t)))
    except Exception:  # noqa: BLE001
        return False


def load_records(golden):
    recs = []
    for line in Path(golden).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("answerability_type") != "ANSWERABLE":
            continue
        gold = [re.sub(r"^\d{2,4}_", "", t) for t in (r.get("retrieval_eval") or {}).get("golden_table_ids") or []]
        if r.get("question_original") and r.get("question_paraphrased") and gold:
            recs.append({"id": r["dataset_id"], "O": r["question_original"], "P": r["question_paraphrased"], "gold": gold,
                         "split": split_of(r["dataset_id"])})
    return recs


def load_titles(refs=()):
    """{tbl_id: '표 이름 + 항목 이름들'} — 코퍼스가 있으면 코퍼스, 그리고 refs"""
    out = {}
    try:
        from backend.rag.retrieval.factory import build_corpus
        for d in build_corpus({"type": "table_text"}).docs():
            p = d.meta.get("profile") or {}
            items = " ".join(i.get("name", "") for i in p.get("items") or [])
            out[d.id] = f"{d.meta.get('tbl_nm', '')} {items}"
    except Exception:  # noqa: BLE001  (코퍼스가 없는 곳에서는 refs 만)
        pass
    for f in refs or []:
        for x in csv.DictReader(open(f, encoding="utf-8-sig")):
            for m in TITLE_RE.finditer(x.get("gold_answer") or ""):
                out.setdefault(m.group(2), m.group(1))
    return out


def p_failures(per_query, config=None):
    """per_query.csv → {record_id: P 문항이 1위를 놓쳤는가} (완화 지표가 있으면 완화)"""
    rows = list(csv.DictReader(open(per_query, encoding="utf-8-sig")))
    cfgs = [r["config"] for r in rows]
    config = config or next((c for c in ("v5+llm[hcx]", "v5[hcx]") if c in cfgs), cfgs[0] if cfgs else None)
    out = {}
    for r in rows:
        if r["config"] == config and r["variant"] == "P":
            h = r.get("hit@1_alt") if r.get("hit@1_alt") not in (None, "") else r["hit@1"]
            out[r["record_id"]] = str(h) in ("0", "0.0")
    return out, config


def mine(recs, titles, fails=None, min_support=2, min_precision=0.4, max_n=2):
    pair, seen_c, ex = Counter(), Counter(), defaultdict(list)
    dev = [r for r in recs if r["split"] == "dev"]
    for r in dev:
        tt = norm(" ".join(titles.get(t, "") for t in r["gold"]))
        o, p = tokens(r["O"]), tokens(r["P"])
        on, pn = {norm(t) for t in o}, {norm(t) for t in p}
        grams = set()
        for n in range(1, max_n + 1):
            for i in range(len(p) - n + 1):
                g = p[i:i + n]
                if any(norm(x) in on for x in g) or any(_region(x) for x in g):
                    continue
                grams.add(" ".join(g))
        for g in grams:
            seen_c[g] += 1
        if fails is not None and not fails.get(r["id"]):
            continue
        if not tt:
            continue
        official = [t for t in dict.fromkeys(o) if norm(t) not in pn and norm(t) in tt and not _region(t)]
        for g in grams:
            for t in official:
                pair[(g, t)] += 1
                if len(ex[(g, t)]) < 2:
                    ex[(g, t)].append(r["P"][:80])
    out = []
    for (g, t), n in pair.most_common():
        prec = n / max(seen_c[g], 1)
        if n >= min_support and prec >= min_precision:
            out.append({"colloquial": g, "term": t, "support": n, "precision": round(prec, 2), "examples": ex[(g, t)]})
    return out, len(dev)


def to_yaml(cands):
    by = defaultdict(list)
    for c in cands:
        by[c["colloquial"]].append(c)
    lines = ["# P4 후보 — dev 레코드에서 캐냄. 맞는 줄만 configs/colloquial.yaml 로 옮기세요 (정규식은 다듬어서)",
             "# 형식: [정규식, [더할 통계어…]]  # 레코드 수 · 정밀도(그 일상어가 나온 dev P 문항 중 이 짝이 맞은 비율) · 예문"]
    for g, cs in sorted(by.items(), key=lambda x: -max(c["support"] for c in x[1])):
        pat = r"\s*".join(re.escape(w) for w in g.split())
        terms = ", ".join(c["term"] for c in cs[:3])
        meta = " / ".join(f"{c['term']} n={c['support']} p={c['precision']}" for c in cs[:3])
        lines.append(f"- ['{pat}', [{terms}]]   # {meta} · 예: {cs[0]['examples'][0]}")
    return "\n".join(lines) + "\n"


def coverage(recs, titles, extra=None, split="heldout"):
    """보류 문항 중 일상어 사전이 더한 말(하나라도)이 정답 표 이름·항목에 있는 비율 (검색 없이 보는 대리 지표)"""
    import backend.rag.search.query as Q
    Q._COLLOQUIAL = None
    Q.synonyms("")                                         # 기본 사전 읽기
    if extra:
        import yaml
        Q._COLLOQUIAL = Q._COLLOQUIAL + [(re.compile(p), list(t)) for p, t in
                                         yaml.safe_load(Path(extra).read_text(encoding="utf-8")) or []]
    n = hit = 0
    for r in recs:
        if r["split"] != split:
            continue
        tt = norm(" ".join(titles.get(t, "") for t in r["gold"]))
        if not tt:
            continue
        n += 1
        hit += any(norm(a) in tt for a in Q.synonyms(r["P"]))
    Q._COLLOQUIAL = None
    return {"split": split, "n": n, "covered": hit, "rate": round(hit / n, 3) if n else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["mine", "eval"])
    ap.add_argument("--golden", nargs="+", required=True)
    ap.add_argument("--per-query", nargs="*", default=[])
    ap.add_argument("--config", default=None, help="per_query 에서 볼 구성 (기본 v5+llm[hcx] → v5[hcx])")
    ap.add_argument("--refs", nargs="*", default=[], help="*_answers_references.csv (코퍼스가 없을 때 정답 표 이름)")
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-precision", type=float, default=0.4)
    ap.add_argument("--extra", default=None, help="eval: 기본 사전에 더해 볼 후보 yaml")
    ap.add_argument("--out", default="colloquial.candidates.yaml")
    a = ap.parse_args(argv)
    recs = [r for g in a.golden for r in load_records(g)]
    titles = load_titles(a.refs)
    if a.cmd == "eval":
        print(json.dumps({"base": coverage(recs, titles), "with_extra": coverage(recs, titles, a.extra) if a.extra else None},
                         ensure_ascii=False, indent=1))
        return
    fails = None
    for f in a.per_query:
        fx, cfg = p_failures(f, a.config)
        fails = {**(fails or {}), **fx}
        print(f"[P 실패] {sum(fx.values())}/{len(fx)} ← {f} ({cfg})")
    cands, n_dev = mine(recs, titles, fails, a.min_support, a.min_precision)
    Path(a.out).write_text(to_yaml(cands), encoding="utf-8")
    print(f"[dev] {n_dev}레코드 → 후보 {len(cands)}줄 → {a.out}")


if __name__ == "__main__":
    main()
