"""남은 실패 점검표 — compare 결과에서 Hit@1 을 놓친 문항을 사람이 판정하기 좋게 모으고, 판정으로 '실제' 지표를 다시 계산

합성 골든셋의 정답 표는 생성기가 사실을 뽑은 표 하나다. 다른 표도 질문에 답하거나(출처가 다른 같은 통계), 질문이 표를 정하지
못하거나((계)/(남)/(여) 중 어느 것인지), 질문 문장이 깨진 경우가 섞여 있어 지표가 실제보다 낮게 나온다.

판정 (판정 열에 한 글자)
  A  진짜 실패 — 정답 표가 맞고 1위 표로는 답할 수 없음
  B  1위 표도 답이 됨 — 출처·표는 달라도 질문에 답함 (정답 목록이 좁음)
  C  정답 라벨 이상 — 질문 문장이 깨졌거나 정답 표가 질문과 맞지 않음 (평가에서 뺄 문항)
  D  질문이 표를 정하지 못함 — 여러 표가 각각 다른 값을 주는데 질문만으로 고를 수 없음 (평가에서 뺄 문항)

  python -m backend.rag.search.tuning.audit make  --per-query <compare 폴더>/per_query.csv [--golden <합성 셋.jsonl>]
         [--config search+llm[hcx]] [--out audit.csv]
  (엑셀 등에서 판정·메모 열을 채운 뒤)
  python -m backend.rag.search.tuning.audit score --per-query <compare 폴더>/per_query.csv --audit audit.csv
         → 판정 반영 Hit@1 = (맞힌 문항 + B) / (전체 − C − D)

  make 는 1위 표가 질문의 연도·지역을 담는지(top1_years_ok · top1_region_ok)를 표 구조로 미리 채운다 (B 판정 참고용)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

COLS = ["qid", "variant", "hop_type", "question", "rank", "gold", "gold_names", "groups_desc", "top1", "top1_name",
        "top1_years_ok", "top1_region_ok", "top2", "top2_name", "top3", "top3_name", "auto", "판정", "메모"]


def _rows(path, config=None):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    cfgs = list(dict.fromkeys(r["config"] for r in rows))
    config = config or next((c for c in ("search+llm[hcx]", "search[hcx]") if c in cfgs), cfgs[0] if cfgs else None)
    return [r for r in rows if r["config"] == config], config


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _hit1(r):
    v = r.get("hit@1_alt")
    return _num(v if v not in (None, "") else r.get("hit@1"))


def _family(t):
    return re.sub(r"(_[A-Z])?$", "", re.sub(r"\d{1,2}(_[A-Z])?$", "", t))


def _descriptions(path):
    out = {}
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                g = (r.get("retrieval_eval") or {}).get("required_evidence_groups") or {}
                out[r["dataset_id"]] = " / ".join(v.get("description") or "" for v in g.values())
    return out


def make(per_query, golden=None, config=None, out="audit.csv", dense="none"):
    from backend.rag.search.query import parse_question
    from backend.rag.search.siblings import core_title, question_sex, table_sex
    from backend.rag.search.tuning.compare import get_search_for
    rows, config = _rows(per_query, config)
    pipe = get_search_for(dense, False)
    nm = lambda t: (pipe.docs_by_id[t].meta.get("tbl_nm", "") if t in pipe.docs_by_id else "")
    desc = _descriptions(golden)
    recs = []
    for r in rows:
        if _hit1(r):
            continue
        gold = r["gold"].split()
        top = (r.get("top5") or "").split()[:3] + ["", "", ""]
        qv = parse_question(r["question"], None, None, pipe.ch.region_dict)
        f = pipe.facets.get(top[0])
        years_ok = "" if not (f and qv.years) else round(f.year_cover(qv.years), 2)
        named = [x for x in qv.subs if x not in ("동부", "읍부", "면부")]
        region_ok = "" if not (f and named) else int(all(x in f.regions for x in named))
        auto = "다른 계열"
        same = [g for g in gold if core_title(nm(g)) and core_title(nm(g)) == core_title(nm(top[0]))]
        if same:
            want = question_sex(r["question"])
            gs = table_sex(nm(same[0]))
            auto = ("형제 표: 질문이 성별을 정하지 않음" if gs in ("남", "여") and want not in ("남", "여")
                    else "형제 표")
        elif any(_family(top[0]) == _family(g) for g in gold):
            auto = "같은 계열 다른 표"
        recs.append({"qid": r["qid"], "variant": r["variant"], "hop_type": r["hop_type"], "question": r["question"],
                     "rank": r.get("rank_alt") or r.get("rank") or "", "gold": " ".join(gold),
                     "gold_names": " / ".join(nm(g) for g in gold[:4]), "groups_desc": desc.get(r["record_id"], ""),
                     "top1": top[0], "top1_name": nm(top[0]), "top1_years_ok": years_ok, "top1_region_ok": region_ok,
                     "top2": top[1], "top2_name": nm(top[1]), "top3": top[2], "top3_name": nm(top[2]),
                     "auto": auto, "판정": "", "메모": ""})
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(recs)
    print(f"[점검표] {config} · Hit@1 놓친 문항 {len(recs)}/{len(rows)} → {out}")
    print("  자동 분류:", dict(Counter(x["auto"] for x in recs)))
    return out


def score(per_query, audit, config=None):
    rows, config = _rows(per_query, config)
    lab = {r["qid"]: (r.get("판정") or "").strip().upper()[:1] for r in csv.DictReader(open(audit, encoding="utf-8-sig"))}
    out = {}
    for name, sel in (("ALL", lambda r: True), ("O", lambda r: r["variant"] == "O"), ("P", lambda r: r["variant"] == "P")):
        rs = [r for r in rows if sel(r)]
        if not rs:
            continue
        c = Counter(lab.get(r["qid"], "?") for r in rs if not _hit1(r))
        hits = sum(_hit1(r) for r in rs)
        valid = len(rs) - c["C"] - c["D"]
        out[name] = {"n": len(rs), "hit@1": round(hits / len(rs), 3),
                     "hit@1_judged": round((hits + c["B"]) / valid, 3) if valid else None,
                     "A": c["A"], "B": c["B"], "C": c["C"], "D": c["D"], "unlabeled": c["?"] + c[""]}
    print(f"[판정 반영] {config}")
    for k, v in out.items():
        print(f"  {k:3s} n={v['n']} hit@1 {v['hit@1']} → {v['hit@1_judged']}  "
              f"(A {v['A']} · B {v['B']} · C {v['C']} · D {v['D']} · 미판정 {v['unlabeled']})")
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.audit")
    ap.add_argument("cmd", choices=["make", "score"])
    ap.add_argument("--per-query", required=True)
    ap.add_argument("--golden", default=None, help="합성 셋 (근거 그룹 설명을 같이 보여 줌)")
    ap.add_argument("--config", default=None, help="per_query 의 구성 (기본 search+llm[hcx] → search[hcx])")
    ap.add_argument("--audit", default="audit.csv")
    ap.add_argument("--out", default="audit.csv")
    ap.add_argument("--dense", default="none", choices=["none", "hcx", "hash"], help="표 이름·구조만 읽으므로 none 이면 충분")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        return make(a.per_query, a.golden, a.config, a.out, a.dense)
    return score(a.per_query, a.audit, a.config)


if __name__ == "__main__":
    main()
