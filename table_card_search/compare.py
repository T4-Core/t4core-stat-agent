"""
세 방법 검색 비교 — 기존(baseline) · table_card · table_card_expend 를 같은 질문·같은 질의 분석으로 돌려 유용성 차이를 본다

입력  골든셋 (synthetic_gold_pipeline 산출물)
        outputs/datasets/synthetic_gold_dataset.jsonl          (권장: 근거 그룹·홉 종류까지)
        또는 synthetic_gold_queries.csv + synthetic_gold_answers_references.csv
      질문 변형  O = 원문(표 이름이 들어 있음 — 쉬움), P = 일상어(실제 사용자에 가까움 — 주 지표)

순서
  1) 질의 분석 한 번만 (기존 lab 과 같은 처리: v4 분석 → 검색 단위 → resolve.search_query)
     → analysis_cache.jsonl 에 저장해 세 방법이 '같은 검색 문장·같은 슬롯'을 받게 함 (HCX 호출도 한 번)
     HCX 키가 없으면 v4 분석은 코드 추출 값만으로 진행됨 (기존 동작) — 보고서에 분석 상태 분포를 남김
  2) 방법 × dense 마다 같은 단계로 검색 (BM25 50 → 조건 → top_k → dense)
     단위가 여러 개(서브쿼리)면 단위별 순위 중 가장 좋은 순위로 합침 (views.run_query 가 단위마다 표를 고르는 것과 같은 효과)
  3) 지표 — 정답 표 = 골든셋 golden_table_ids, 근거 그룹 = required_evidence_groups 의 acceptable_table_ids
       Hit@1·3·5·10 (정답 표 하나라도), AllGroups@5·10 (모든 근거 그룹이 상위 k 안에), MRR
       BM25@50 (1단계 후보 안에 정답이 있는가 — 카드 글 품질), 정답 표의 조건 불일치(조건표 품질), 코퍼스 포함 여부
  4) 실패 원인 (Hit@5 실패만): 코퍼스 없음 · BM25 단계 누락 · 조건 단계에서 밀림 · 상위 10 안이지만 5 밖
     · 같은 이름의 다른 표(다른 연도판 등)와 혼동

출력  <out>/report.md · summary.json · per_query.csv · analysis_cache.jsonl · config.json

실행 (저장소 루트, PC 의 실제 데이터 기준)
  python -m table_card_search.compare --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl
  python -m table_card_search.compare --golden … --dense hcx none --variants P      # dense 비교, 일상어만
  python -m table_card_search.compare --golden … --table-card-dir table_cards/full --expend-dir table_card_expend/out/full
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import table_card_search  # noqa: F401
from table_card_search.search import METHODS, analyze_units, get_pipeline_for

PACKAGE = Path(__file__).resolve().parent
KS = (1, 3, 5, 10)
FAIL_LABEL = {"not_in_corpus": "코퍼스에 정답 표 없음", "bm25_miss": "BM25 1단계 후보(50)에 없음",
              "condition_cut": "조건 단계에서 상위 top_k 밖으로 밀림", "rank_6_10": "상위 10 안이지만 5 밖",
              "no_filters_cut": "슬롯 없음 — BM25 상위 top_k 밖"}


# ── 골든셋 ───────────────────────────────────────────────────────
def _tid(x):
    """'101_DT_1IN1502' → 'DT_1IN1502' (기관 접두어 제거)"""
    m = re.match(r"^\d{2,4}_(.+)$", str(x))
    return m.group(1) if m else str(x)


def _manual_row(r, answerable_only=True, split=None):
    """[NEW 11-12] retrieval_golden.jsonl 형식 한 줄 → 평가 행
    {"qid", "split", "qtype", "source", "question", "required": [[그룹1 후보 표…], [그룹2 …]], "answerable": false?}
      · required 의 각 안쪽 목록 = 근거 그룹 하나 (그 안의 표 중 하나만 찾으면 됨) → groups G1, G2 …
      · gold = 모든 그룹 표의 합집합 → Hit@k = 하나라도, Groups@k = 그룹마다 하나씩
      · answerable false (no_answer) 는 표 정답이 없어 건너뜀
    """
    if split and r.get("split") not in split:
        return None
    groups = {f"G{i}": sorted({_tid(t) for t in g}) for i, g in enumerate(r.get("required") or [], 1) if g}
    if not groups or (answerable_only and r.get("answerable") is False):
        return None
    gold = sorted({t for v in groups.values() for t in v})
    return {"qid": r["qid"], "record_id": r["qid"], "variant": "O", "question": r["question"], "gold": gold,
            "groups": groups, "hop_type": "SINGLE" if len(groups) == 1 else f"MULTI_{len(groups)}",
            "reasoning_type": r.get("qtype") or "", "subtype": r.get("source") or "",
            "survey": "", "difficulty": r.get("split") or ""}


def load_golden(path, variants=("O", "P"), answerable_only=True, limit=None, split=None):
    p = Path(path)
    rows = []
    if p.suffix == ".jsonl":
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "required" in r or ("qid" in r and "dataset_id" not in r):   # [NEW 11-12] 손으로 만든 검색 골든셋
                row = _manual_row(r, answerable_only, split)
                if row:
                    rows.append(row)
                continue
            if answerable_only and r.get("answerability_type") != "ANSWERABLE":
                continue
            re_ = r.get("retrieval_eval") or {}
            gold = [_tid(t) for t in re_.get("golden_table_ids") or []]
            if not gold:
                continue
            groups = {g: sorted({_tid(t) for t in v.get("acceptable_table_ids") or []})
                      for g, v in (re_.get("required_evidence_groups") or {}).items()}
            groups = {g: v for g, v in groups.items() if v} or {f"T{i}": [t] for i, t in enumerate(gold, 1)}
            qs = {"O": r.get("question_original"), "P": r.get("question_paraphrased")}
            for v in variants:
                if qs.get(v):
                    rows.append({"qid": (r.get("question_ids") or {}).get({"O": "original", "P": "paraphrased"}[v])
                                 or f"{r['dataset_id']}-{v}", "record_id": r["dataset_id"], "variant": v,
                                 "question": qs[v], "gold": gold, "groups": groups, "hop_type": r.get("hop_type") or "",
                                 "reasoning_type": r.get("reasoning_type") or "", "subtype": r.get("subtype") or "",
                                 "survey": ",".join(r.get("survey_names") or []), "difficulty": r.get("difficulty") or ""})
    else:                                                     # queries CSV + 같은 이름의 *_answers_references.csv
        ref = p.with_name(p.name.replace("_queries", "_answers_references"))
        refs = {x["id"]: x for x in csv.DictReader(ref.open(encoding="utf-8-sig"))} if ref.exists() else {}
        for q in csv.DictReader(p.open(encoding="utf-8-sig")):
            a = refs.get(q["id"], {})
            v = a.get("question_variant") or q["id"].rsplit("-", 1)[-1]
            if v not in variants or (answerable_only and a.get("answerability") not in ("", None, "ANSWERABLE")):
                continue
            gold = [_tid(t.strip()) for t in re.split(r"[,;]", a.get("gold_table_ids") or "") if t.strip()]
            if gold:
                rows.append({"qid": q["id"], "record_id": a.get("dataset_id") or q["id"], "variant": v,
                             "question": q["question"], "gold": gold, "groups": {f"T{i}": [t] for i, t in enumerate(gold, 1)},
                             "hop_type": "", "reasoning_type": q.get("test_type", ""), "subtype": "",
                             "survey": q.get("survey", ""), "difficulty": ""})
    return rows[:limit] if limit else rows


# ── 질의 분석 (한 번만) ───────────────────────────────────────────
def analyze_all(rows, mode, today, cache_path: Path, log=print):
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["key"]] = r
    out, n_new, t0 = {}, 0, time.time()
    with cache_path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            key = hashlib.sha1(f"{mode}|{today}|{r['question']}".encode()).hexdigest()[:16]
            if key not in cache:
                try:
                    units = analyze_units(r["question"], mode, today)
                except Exception as e:  # noqa: BLE001  (분석 실패 → 원문 검색)
                    units = [{"unit": "main", "text": r["question"], "search_query": r["question"], "filters": None,
                              "status": f"error:{e.__class__.__name__}"}]
                cache[key] = {"key": key, "question": r["question"], "mode": mode, "today": today, "units": units}
                f.write(json.dumps(cache[key], ensure_ascii=False, default=str) + "\n")
                f.flush()
                n_new += 1
                if n_new % 20 == 0:
                    log(f"  분석 {i}/{len(rows)} ({time.time() - t0:.0f}초)")
            out[r["qid"]] = cache[key]["units"]
    log(f"[분석] {len(rows)}문항 (새로 {n_new}, 캐시 {len(rows) - n_new}) · 상태 "
        f"{dict(Counter(u[0].get('status') for u in out.values()))}")
    return out


# ── 평가 ─────────────────────────────────────────────────────────
def _core(name):
    return re.sub(r"[\s()（）,·/\-–_]+", "", re.sub(r"\([^()]*\)|\d{4}\s*년?", "", str(name or "")))


def gold_profile(pipe, tid):
    d = pipe.docs_by_id.get(tid)
    if d is None:
        return None
    if d.meta.get("profile"):
        return d.meta["profile"]
    from backend.rag.ingestion.resolve import profile
    return profile(tid)


def evaluate_one(pipe, bm25, row, units, top_k, pool):
    from backend.rag.ingestion.resolve import unmet
    best, bm25_ids, n_filters = {}, set(), 0
    for ui, u in enumerate(units):
        r = pipe.search(u["search_query"], u.get("filters"), top_k)
        for h in r["hits"]:
            k = (h["rank"], ui)
            if h["tbl_id"] not in best or k < best[h["tbl_id"]][0]:
                best[h["tbl_id"]] = (k, h)
        bm25_ids |= {pipe.docs[i].id for i, _ in bm25.search(u["search_query"], pool)}
        n_filters += u.get("filters") is not None
    ranking = [t for t, _ in sorted(best.items(), key=lambda x: x[1][0])]
    gold = set(row["gold"])
    acceptable = gold | {t for v in row["groups"].values() for t in v}
    pos = next((i for i, t in enumerate(ranking, 1) if t in acceptable), None)
    res = {"rank": pos, "mrr": round(1 / pos, 4) if pos else 0.0}
    for k in KS:
        res[f"hit@{k}"] = int(bool(pos and pos <= k))
    for k in (5, 10):
        top = set(ranking[:k])
        res[f"groups@{k}"] = int(all(set(v) & top for v in row["groups"].values()))
    res["bm25@pool"] = int(bool(acceptable & bm25_ids))
    res["bm25_groups@pool"] = int(all(set(v) & bm25_ids for v in row["groups"].values()))
    in_corpus = [t for t in acceptable if t in pipe.docs_by_id]
    res["in_corpus"] = int(bool(in_corpus))
    # 정답 표의 조건 불일치 (슬롯이 있는 단위 기준) — 조건표가 정답을 잘못 '못 맞춤'으로 보는지
    unmet_txt = []
    for u in units:
        if u.get("filters") is None:
            continue
        for t in in_corpus[:2]:
            p = gold_profile(pipe, t)
            if p:
                unmet_txt += [x["text"] for x in unmet(p, u["filters"])]
    res["gold_unmet"] = "; ".join(dict.fromkeys(unmet_txt))[:200]
    res["gold_unmet_any"] = int(bool(unmet_txt))
    top1 = ranking[0] if ranking else ""
    res["top1"] = top1
    res["top1_nm"] = pipe.docs_by_id[top1].meta.get("tbl_nm", "") if top1 in pipe.docs_by_id else ""
    gold_nm = {_core(pipe.docs_by_id[t].meta.get("tbl_nm", "")) for t in in_corpus}
    res["sibling_confusion"] = int(bool(top1 and top1 not in acceptable and _core(res["top1_nm"]) in gold_nm))
    if res["hit@5"]:
        res["fail"] = ""
    elif not in_corpus:
        res["fail"] = "not_in_corpus"
    elif not res["bm25@pool"]:
        res["fail"] = "bm25_miss"
    elif pos and pos <= 10:
        res["fail"] = "rank_6_10"
    elif n_filters:
        res["fail"] = "condition_cut"
    else:
        res["fail"] = "no_filters_cut"
    res["top5"] = " ".join(ranking[:5])
    res["n_units"] = len(units)
    # [NEW 11-12] 완화 기준: 정답 표 + 같은 값을 가진 대체 정답 표 (alt_gold.py). --alt 가 없으면 None
    alt = row.get("alt_groups")
    if alt is not None:
        acc2 = acceptable | {t for v in alt.values() for t in v}
        pos2 = next((i for i, t in enumerate(ranking, 1) if t in acc2), None)
        res["rank_alt"] = pos2
        res["mrr_alt"] = round(1 / pos2, 4) if pos2 else 0.0
        for k in KS:
            res[f"hit@{k}_alt"] = int(bool(pos2 and pos2 <= k))
        for k in (5, 10):
            top = set(ranking[:k])
            res[f"groups@{k}_alt"] = int(all((set(v) | set(alt.get(g, [])) | set(alt.get("ALL", []))) & top
                                                 for g, v in row["groups"].items()))
        res["alt_tables"] = " ".join(sorted(acc2 - acceptable))
    return res


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


METRICS = ["hit@1", "hit@3", "hit@5", "hit@10", "groups@5", "groups@10", "mrr", "bm25@pool", "bm25_groups@pool",
           "gold_unmet_any", "sibling_confusion", "in_corpus"]
ALT_METRICS = ["hit@1_alt", "hit@3_alt", "hit@5_alt", "hit@10_alt", "groups@5_alt", "groups@10_alt", "mrr_alt"]   # [NEW 11-12]


def aggregate(recs):
    out = {"n": len(recs), **{m: _mean([r[m] for r in recs]) for m in METRICS}}
    if any(r.get("mrr_alt") is not None for r in recs):
        out.update({m: _mean([r.get(m) for r in recs]) for m in ALT_METRICS})
        out["with_alt"] = _mean([int(bool(r.get("alt_tables"))) for r in recs])
    return out


def run(rows, analysis, methods, denses, set_name, dirs, top_k, pool, log=print):
    per, info = [], {}
    for dense in denses:
        for m in methods:
            name = f"{m}[{dense}]"
            t0 = time.time()
            try:
                pipe = get_pipeline_for(m, dense, set_name, dirs.get(m))
            except Exception as e:  # noqa: BLE001  (데이터가 없는 방법 하나가 비교 전체를 막지 않게)
                info[name] = {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}
                log(f"  ✗ {name}: {info[name]['error']}")
                continue
            bm25 = next(r for r in pipe.retrievers if type(r).__name__ == "BM25Retriever")
            for row in rows:
                res = evaluate_one(pipe, bm25, row, analysis[row["qid"]], top_k, pool)
                per.append({"method": m, "dense": dense, "config": name, **{k: row[k] for k in (
                    "qid", "record_id", "variant", "hop_type", "reasoning_type", "subtype", "survey", "difficulty")},
                    "question": row["question"], "gold": " ".join(row["gold"]), **res})
            info[name] = {"n_docs": len(pipe.docs), "corpus": pipe.corpus.signature()[:120],
                          "seconds": round(time.time() - t0, 1), "rerank": [r.name for r in pipe.rerankers]}
            log(f"  {name}: 문서 {len(pipe.docs)} · {info[name]['seconds']}초")
    return per, info


def summarize(per):
    by = defaultdict(list)
    for r in per:
        by[(r["config"], "ALL", "ALL")].append(r)
        by[(r["config"], "variant", r["variant"])].append(r)
        by[(r["config"], "hop_type", r["hop_type"] or "-")].append(r)
        by[(r["config"], "reasoning_type", r["reasoning_type"] or "-")].append(r)
        if r.get("difficulty") in ("dev", "test", "train"):    # [NEW 11-12] retrieval_golden 의 split
            by[(r["config"], "split", r["difficulty"])].append(r)
    table = [{"config": c, "group": g, "value": v, **aggregate(rs)} for (c, g, v), rs in sorted(by.items())]
    fails = defaultdict(Counter)
    for r in per:
        if r["fail"]:
            fails[(r["config"], r["variant"])][r["fail"]] += 1
    # 두 방법 비교: 같은 질문에서 한쪽만 Hit@5
    wins = defaultdict(lambda: [0, 0, 0])
    idx = defaultdict(dict)
    for r in per:
        idx[(r["dense"], r["qid"])][r["method"]] = r["hit@5"]
    for (dense, _), d in idx.items():
        ms = sorted(d)
        for i, a in enumerate(ms):
            for b in ms[i + 1:]:
                w = wins[(dense, a, b)]
                w[0] += d[a] and not d[b]
                w[1] += d[b] and not d[a]
                w[2] += d[a] == d[b]
    return table, {f"{c}|{v}": dict(x) for (c, v), x in fails.items()}, \
        [{"dense": k[0], "a": k[1], "b": k[2], "a_only": v[0], "b_only": v[1], "same": v[2]} for k, v in wins.items()]


def _fmt(x):
    return "-" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def report_md(meta, table, fails, wins, per):
    L = [f"# 검색 비교 — 기존 · table_card · table_card_expend", "",
         f"- 실행: {meta['created']} · 골든셋 `{meta['golden']}` · 질문 {meta['n_rows']}개 (변형 {meta['variants']})",
         f"- 질의 분석: `{meta['analyze']}` (상태 {meta['analysis_status']}) · top_k {meta['top_k']} · BM25 후보 {meta['pool']}",
         f"- dense: {meta['dense']} · 카드 묶음: {meta['set']}",
         "- 정답 = golden_table_ids ∪ 근거 그룹의 acceptable_table_ids. Hit@k = 하나라도 상위 k, Groups@k = 모든 근거 그룹이 상위 k",
         ""]
    for name, i in meta["configs"].items():
        L.append(f"- `{name}`: " + (f"오류 {i['error']}" if "error" in i else f"문서 {i['n_docs']} · 재정렬 {i['rerank']}"))
    if any("mrr_alt" in t for t in table):                     # [NEW 11-12] 엄격 / 완화 나란히
        L += ["", "## 엄격 · 완화 (완화 = 정답 표 + 같은 값을 가진 대체 정답 표, alt_gold.py)", "",
              f"- 대체 정답 파일: `{meta.get('alt')}` · 대체 정답이 하나라도 있는 질문 비율 = with_alt", "",
              "| 구성 | 값 | n | with_alt | hit@1 → 완화 | hit@5 → 완화 | hit@10 → 완화 | groups@5 → 완화 | mrr → 완화 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for t in table:
            if t["group"] in ("ALL", "variant") and "mrr_alt" in t:
                L.append(f"| {t['config']} | {t['value']} | {t['n']} | {_fmt(t.get('with_alt'))} | "
                         + " | ".join(f"{_fmt(t[m])} → {_fmt(t[m + '_alt'])}" for m in ("hit@1", "hit@5", "hit@10", "groups@5", "mrr"))
                         + " |")
    cols = ["n", "hit@1", "hit@3", "hit@5", "hit@10", "groups@5", "mrr", "bm25@pool", "gold_unmet_any", "sibling_confusion",
            "in_corpus"]
    for group in ("ALL", "variant", "hop_type", "reasoning_type", "split"):
        if not any(t["group"] == group for t in table):
            continue
        L += ["", f"## {'전체' if group == 'ALL' else group + '별'}", "",
              "| 구성 | 값 | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 2)]
        for t in table:
            if t["group"] == group:
                L.append(f"| {t['config']} | {t['value']} | " + " | ".join(_fmt(t[c]) for c in cols) + " |")
    L += ["", "## Hit@5 실패 원인", "", "| 구성 · 변형 | " + " | ".join(FAIL_LABEL[k] for k in FAIL_LABEL) + " |",
          "|" + "---|" * (len(FAIL_LABEL) + 1)]
    for k, v in sorted(fails.items()):
        L.append(f"| {k} | " + " | ".join(str(v.get(f, 0)) for f in FAIL_LABEL) + " |")
    L += ["", "## 같은 질문에서 한쪽만 Hit@5", "", "| dense | A | B | A만 | B만 | 같음 |", "|---|---|---|---|---|---|"]
    for w in wins:
        L.append(f"| {w['dense']} | {w['a']} | {w['b']} | {w['a_only']} | {w['b_only']} | {w['same']} |")
    # 방법 간 결과가 갈린 질문 예 (P 변형 우선)
    by_q = defaultdict(dict)
    for r in per:
        by_q[(r["dense"], r["qid"])][r["method"]] = r
    diff = [(k, d) for k, d in by_q.items() if len({x["hit@5"] for x in d.values()}) > 1]
    diff.sort(key=lambda x: (x[0][1][-1] != "P", x[0]))
    if diff:
        L += ["", "## 결과가 갈린 질문 (최대 12개)", ""]
        for (dense, qid), d in diff[:12]:
            any_r = next(iter(d.values()))
            L.append(f"- **{qid}** [{dense}] {any_r['question'][:90]}  — 정답 {any_r['gold']}")
            for m in METHODS:
                if m in d:
                    x = d[m]
                    L.append(f"  - {m}: 순위 {x['rank'] or '-'} · top1 {x['top1']} {x['top1_nm'][:30]}"
                             + (f" · 실패: {FAIL_LABEL.get(x['fail'], x['fail'])}" if x["fail"] else "")
                             + (f" · 정답 조건 불일치: {x['gold_unmet']}" if x["gold_unmet"] else ""))
    return "\n".join(L) + "\n"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m table_card_search.compare")
    ap.add_argument("--golden", default="synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl")
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--methods", nargs="*", default=list(METHODS), choices=list(METHODS))
    ap.add_argument("--dense", nargs="*", default=["hcx"], choices=["hcx", "hash", "none"])
    ap.add_argument("--set", dest="set_name", default="full", choices=["full", "sample", "both"])
    ap.add_argument("--table-card-dir", nargs="*", default=None)
    ap.add_argument("--expend-dir", nargs="*", default=None)
    ap.add_argument("--analyze", default="v4", choices=["v4", "none"])
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--pool", type=int, default=50)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=None)
    ap.add_argument("--name", default="compare")
    ap.add_argument("--alt", default=None, help="[NEW 11-12] 대체 정답 파일 (alt_gold.py 의 alt_positives.jsonl) → 엄격/완화 지표")
    ap.add_argument("--alt-exact-only", action="store_true", help="반올림 일치(rounded)는 대체 정답으로 치지 않음")
    ap.add_argument("--split", nargs="*", default=None, help="[NEW 11-12] retrieval_golden 형식: dev / test 만 (기본 전부)")
    a = ap.parse_args(argv)

    out = Path(a.out) if a.out else PACKAGE / "runs" / f"{datetime.now():%Y%m%d_%H%M%S}_{a.name}"
    out.mkdir(parents=True, exist_ok=True)
    rows = load_golden(a.golden, tuple(a.variants), limit=a.limit, split=a.split)
    print(f"[골든셋] {len(rows)}문항 ← {a.golden}", flush=True)
    if a.alt:                                                     # [NEW 11-12] 판정 안 된 레코드는 대체 정답 없음으로
        from table_card_search.alt_gold import load_alt
        alt = load_alt(a.alt, include_rounded=not a.alt_exact_only)
        for r in rows:
            r["alt_groups"] = alt.get(r["record_id"], {})
        print(f"[대체 정답] {sum(bool(any(v.values())) for v in alt.values())}/{len(alt)} 레코드 ← {a.alt}", flush=True)
    analysis = analyze_all(rows, a.analyze, a.today, out / "analysis_cache.jsonl")
    dirs = {"table_card": a.table_card_dir, "table_card_expend": a.expend_dir}
    per, info = run(rows, analysis, a.methods, a.dense, a.set_name, dirs, a.top_k, a.pool)
    table, fails, wins = summarize(per)
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "golden": a.golden, "n_rows": len(rows),
            "variants": a.variants, "analyze": a.analyze, "today": a.today, "top_k": a.top_k, "pool": a.pool,
            "dense": a.dense, "set": a.set_name, "configs": info, "alt": a.alt,
            "analysis_status": dict(Counter(u[0].get("status") for u in analysis.values()))}
    (out / "summary.json").write_text(json.dumps({"meta": meta, "table": table, "fails": fails, "wins": wins},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    if per:
        with (out / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(per[0]))
            w.writeheader()
            w.writerows(per)
    (out / "report.md").write_text(report_md(meta, table, fails, wins, per), encoding="utf-8")
    (out / "config.json").write_text(json.dumps(vars(a), ensure_ascii=False, indent=1), encoding="utf-8")
    for t in table:
        if t["group"] in ("ALL", "variant"):
            print(f"  {t['config']:28s} {t['value']:4s} n={t['n']:3d} hit@1={_fmt(t['hit@1'])} hit@5={_fmt(t['hit@5'])} "
                  f"groups@5={_fmt(t['groups@5'])} mrr={_fmt(t['mrr'])} bm25@{a.pool}={_fmt(t['bm25@pool'])}"
                  + (f" | 완화 hit@5={_fmt(t['hit@5_alt'])} mrr={_fmt(t['mrr_alt'])}" if "mrr_alt" in t else ""))
    print(f"보고서 → {out / 'report.md'}")
    return out


if __name__ == "__main__":
    main()
