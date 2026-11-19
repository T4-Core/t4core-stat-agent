"""
검색 비교 — 같은 질문·같은 질의 분석으로 검색 설정(dense 종류 · LLM 재정렬)을 나란히 돌려 차이를 본다

입력  골든셋: tests/retrieval_golden.jsonl (손으로 만든 셋) 또는 synthetic_gold_pipeline 산출물
        synthetic_gold_dataset.jsonl (권장: 근거 그룹·홉 종류까지) / synthetic_gold_queries.csv + …answers_references.csv
      질문 변형  O = 원문(표 이름이 들어 있음 — 쉬움), P = 일상어(실제 사용자에 가까움 — 주 지표)

순서
  1) 질의 분석 한 번만 (analyze → 검색 단위 → search_query) → analysis_cache.jsonl (모든 구성이 같은 입력을 받음)
  2) 구성마다 검색. 단위가 여러 개(서브쿼리)면 단위별 순위 중 가장 좋은 순위로 합침
  3) 지표 — Hit@1·3·5·10, Groups@5·10 (모든 근거 그룹이 상위 k 안에), MRR, pool@50 (합친 후보 50 안에 정답),
     정답 표의 조건 불일치, 코퍼스 포함 여부, 형제 표 혼동
  4) Hit@5 실패 원인: 코퍼스 없음 · 합친 후보 밖 · 구조 계수로 밀림 · 상위 10 안이지만 5 밖

출력  <out>/report.md · summary.json · per_query.csv · analysis_cache.jsonl · config.json

  python -m backend.rag.search.tuning.compare --golden tests/retrieval_golden.jsonl --dense hcx --llm
  python -m backend.rag.search.tuning.compare --golden <합성 셋.jsonl> --dense hcx none --variants P
  python -m backend.rag.search.tuning.compare --golden <셋> --dense hcx arctic-ko bge-m3-ko ens-ko   # 임베딩 모델 비교
      (첫 dense 가 기준 → report.md 'dense 비교' 에 질문별 득실 · 부호 검정 p. 로컬 모델은 search/embedders.py)
  python -m backend.rag.search.tuning.compare --golden <합성 셋> --alt <alt_positives.jsonl> --split heldout
  python -m backend.rag.search.tuning.compare --from-run docs_hard --dense bge-m3-ko --dense-docs "rule,def" --ce
      (교차 인코더 재정렬 'search+ce' 를 'search' 와 나란히 — '방법 비교' 절에 질문별 득실·부호 검정)
  python -m backend.rag.search.tuning.compare --list-runs                       # 이전 실행 (골든셋·alt 경로가 기록돼 있음)
  python -m backend.rag.search.tuning.compare --from-run 0d8556bd --dense bge-m3-ko --dense-docs rule def   # 그 실행의 셋·alt·캐시로
  python -m backend.rag.search.tuning.compare --golden <셋> --dense bge-m3-ko --dense-docs rule tmpl def slot+def+rw
      (dense 문서 비교: 같은 모델에 문서만 바꿈 — ingestion/dense_cards.py. 첫 구성이 기준.
       dense@10·50 = dense 채널 혼자의 정답 순위, rwdense@10 = 검색 문장(재작성)으로 dense 를 돌렸을 때, +rw 구성만)
  python -m backend.rag.search.tuning.compare --from-run docs_hard --dense bge-m3-ko --dense-docs "rule,def" --arms off units move cond all
      (앞단 수정을 하나씩 켜 본 구성 — ARMS. 첫 arm 이 기준 → 'dense 비교' 절에 질문별 득실·부호 검정. off = 수정 전과 같음)

하위 질문 검증: 캐시된 질의 분석에도 query_analyzer/subcheck.prune_units 를 다시 적용 (뜻 없는 '수(水)' · 분모처럼 붙은
'인구' 단위를 뺌). --raw-units 면 캐시 그대로 (arm 'off' 도 그대로)
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


def get_search_for(dense="hcx", llm=False, settings=None):
    from backend.rag.search import get_search
    return get_search(dense=dense, llm_rerank=llm, settings=settings)


def analyze_units(question, mode="analyze", today=None):
    """질문 → 검색 단위 [{unit, text, search_query, filters, status}] (analyze → run.units_of → search_query)"""
    if mode == "none":
        return [{"unit": "main", "text": question, "search_query": question, "filters": None, "status": "none"}]
    from backend.rag.query_analyzer.analyze import analyze
    from backend.rag.search.resolve import search_query
    from backend.rag.view.run import units_of
    a = analyze(question, today=today)
    vb = a.get("view_bundle")
    if not vb or vb.get("filters") is None:
        return [{"unit": "main", "text": question, "search_query": question, "filters": None, "status": a["status"]}]
    return [{"unit": uid, "text": text, "search_query": search_query(text, f), "filters": f, "status": a["status"],
             "notes": a.get("notes", []), "assumed": bool(a.get("clarifications"))} for uid, text, f in units_of(vb)]


# 앞단 수정 켜고 끄기 (engine.DEFAULTS['feas'] 의 새 계수 + 하위 질문 검증). 값 1.0 = 끔
FRONT_OFF = {"cycle_derived": 1.0, "move_miss": 1.0, "move_derived": 1.0, "geo_finer": 1.0, "cond_miss": 1.0}
ARMS = {
    "off": ({**FRONT_OFF}, False),                                     # 수정 전과 같음
    "units": ({**FRONT_OFF}, True),                                    # 하위 질문 검증만
    "cycle": ({**FRONT_OFF, "cycle_derived": None}, True),            # + 분기 ← 월 계산 감점
    "move": ({**FRONT_OFF, "move_miss": None, "move_derived": None}, True),
    "geo": ({**FRONT_OFF, "geo_finer": None}, True),
    "cond": ({**FRONT_OFF, "cond_miss": None}, True),
    "all": ({}, True),                                                 # 전부 (기본값)
}


def arm_settings(name):
    """arm 이름 → (feas 덮어쓰기, 하위 질문 검증 여부). None = 기본값 그대로"""
    feas, prune = ARMS[name]
    return {k: v for k, v in feas.items() if v is not None}, prune


def prune_analysis(rows, analysis, log=print):
    """캐시된 질의 분석 단위에 하위 질문 검증을 다시 적용 → (새 분석, 바뀐 문항 수)"""
    from backend.rag.query_analyzer.subcheck import prune_units
    out, n = dict(analysis), 0
    for r in rows:
        units = analysis.get(r["qid"])
        if not units:
            continue
        new, why = prune_units(r["question"], units)
        n += len(new) != len(units)
        out[r["qid"]] = new
    log(f"[하위 질문 검증] {n}/{len(rows)}문항에서 단위를 뺌")
    return out, n


KS = (1, 3, 5, 10)
FAIL_LABEL = {"not_in_corpus": "코퍼스에 정답 표 없음", "pool_miss": "합친 후보(50)에 없음",
              "condition_cut": "구조 계수로 상위 top_k 밖으로 밀림", "rank_6_10": "상위 10 안이지만 5 밖",
              "no_filters_cut": "슬롯 없음 — 상위 top_k 밖"}


# ── 골든셋 ───────────────────────────────────────────────────────
def _tid(x):
    """'101_DT_1IN1502' → 'DT_1IN1502' (기관 접두어 제거)"""
    m = re.match(r"^\d{2,4}_(.+)$", str(x))
    return m.group(1) if m else str(x)


def _manual_row(r, answerable_only=True, split=None):
    """retrieval_golden.jsonl 형식 한 줄 → 평가 행
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
            if "required" in r or ("qid" in r and "dataset_id" not in r):  # 손으로 만든 검색 골든셋
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
            from backend.rag.search.tuning.splits import split_of
            sp = split_of(r["dataset_id"])  # dev / heldout (사전·카탈로그를 캐낸 문항과 평가 문항을 가름)
            if split and sp not in split:
                continue
            for v in variants:
                if qs.get(v):
                    rows.append({"qid": (r.get("question_ids") or {}).get({"O": "original", "P": "paraphrased"}[v])
                                 or f"{r['dataset_id']}-{v}", "record_id": r["dataset_id"], "variant": v,
                                 "question": qs[v], "gold": gold, "groups": groups, "hop_type": r.get("hop_type") or "",
                                 "reasoning_type": r.get("reasoning_type") or "", "subtype": r.get("subtype") or "",
                                 "survey": ",".join(r.get("survey_names") or []), "difficulty": r.get("difficulty") or "",
                                 "split": sp})
    else:  # queries CSV + 같은 이름의 *_answers_references.csv
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


def _title_sim(a, b):
    A, B = ({x[i:i + 2] for i in range(len(x) - 1)} for x in (a, b))
    return len(A & B) / len(A | B) if A | B else 0.0


def dense_only(pipe, row, units, acceptable, depth=200):
    """dense 채널 혼자의 정답 순위 (단위·dense 채널 중 가장 좋은 것). dense 가 없으면 None
    dense@k = 원 질문(하위 단위는 그 문장)으로, rwdense@10 = 본 질의의 검색 문장으로 (+rw 구성만)"""
    import numpy as np
    out = {"dense_rank": None, "dense@10": None, "dense@50": None, "rwdense@10": None}
    if getattr(getattr(pipe, "ch", None), "dense", None) is None or not hasattr(pipe, "dense_scores"):
        return out
    best = {"q": None, "rw": None}
    ids = [d.id for d in pipe.docs]
    for u in units:
        ds = pipe.dense_scores(u["search_query"], row["question"], u.get("unit") or "main")
        pairs = [("q", x) for x in (ds["q"] or [])] + [("rw", ds["rw"])]   # 채널이 여럿이면 그중 가장 좋은 순위
        for key, sc in pairs:
            if sc is None:
                continue
            order = np.argsort(-sc, kind="stable")[:depth]
            pos = next((i for i, ix in enumerate(order, 1) if ids[ix] in acceptable), None)
            if pos and (not best[key] or pos < best[key]):
                best[key] = pos
            elif best[key] is None:
                best[key] = 0  # 계산은 했지만 depth 안에 없음
    q = best["q"] or None
    out.update({"dense_rank": q, "dense@10": int(bool(q and q <= 10)), "dense@50": int(bool(q and q <= 50))})
    if getattr(pipe, "dense_rw", False) and best["rw"] is not None:
        out["rwdense@10"] = int(bool(best["rw"] and best["rw"] <= 10))
    return out


def gold_profile(pipe, tid):
    d = pipe.docs_by_id.get(tid)
    if d is None:
        return None
    if d.meta.get("profile"):
        return d.meta["profile"]
    from backend.rag.search.resolve import profile
    return profile(tid)


SEX_SPLIT = re.compile(r"\((?:남|여|남자|여자)\)|[_\-](?:남|여)$")


def label_suspect(pipe, row, gold_ids):
    """정답 표시가 의심스러운 문항: 정답 표가 모두 성별로 나뉜 표('…(여)')인데 질문에 성별 말이 없고,
    나뉘지 않은 형제('…(계)')가 있음 → 그 형제 표 (질문이 성별 조건을 잃은 생성 결함일 가능성). 아니면 ''"""
    from backend.rag.search.query import WANT_SEX_RE
    if not gold_ids or WANT_SEX_RE.search(row["question"]) or not hasattr(pipe, "sib"):
        return ""
    name = lambda t: pipe.docs_by_id[t].meta.get("tbl_nm", "") if t in pipe.docs_by_id else ""
    out = []
    for g in gold_ids:
        if not SEX_SPLIT.search(name(g)):
            return ""
        out += [t for t in pipe.sib.siblings(g) if t not in gold_ids and not SEX_SPLIT.search(name(t))]
    return " ".join(dict.fromkeys(out))


def evaluate_one(pipe, row, units, top_k, pool):
    from backend.rag.search.resolve import unmet
    best, pool_ids, n_filters = {}, set(), 0
    for ui, u in enumerate(units):
        r = pipe.search(u["search_query"], u.get("filters"), top_k, question=row["question"], unit=u.get("unit") or "main")
        for h in r["hits"]:
            k = (h["rank"], ui)
            if h["tbl_id"] not in best or k < best[h["tbl_id"]][0]:
                best[h["tbl_id"]] = (k, h)
        pool_ids |= set(r["pool_ids"][:pool])
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
    res["pool@k"] = int(bool(acceptable & pool_ids))
    res["pool_groups@k"] = int(all(set(v) & pool_ids for v in row["groups"].values()))
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
    res.update(dense_only(pipe, row, units, acceptable))
    top1 = ranking[0] if ranking else ""
    res["top1"] = top1
    res["top1_nm"] = pipe.docs_by_id[top1].meta.get("tbl_nm", "") if top1 in pipe.docs_by_id else ""
    gold_nm = {_core(pipe.docs_by_id[t].meta.get("tbl_nm", "")) for t in in_corpus}
    res["sibling_confusion"] = int(bool(top1 and top1 not in acceptable and _core(res["top1_nm"]) in gold_nm))
    # 이름이 비슷한 표(글자쌍 자카드 ≥ 0.5)를 1위로 — 형제 표보다 넓은 '거의 같은 표' 혼동 (혼인 ↔ 초혼, 시도 ↔ 시군구판)
    res["near_confusion"] = int(bool(top1 and top1 not in acceptable
                                     and any(_title_sim(_core(res["top1_nm"]), g) >= 0.5 for g in gold_nm)))
    if res["hit@5"]:
        res["fail"] = ""
    elif not in_corpus:
        res["fail"] = "not_in_corpus"
    elif not res["pool@k"]:
        res["fail"] = "pool_miss"
    elif pos and pos <= 10:
        res["fail"] = "rank_6_10"
    elif n_filters:
        res["fail"] = "condition_cut"
    else:
        res["fail"] = "no_filters_cut"
    res["top5"] = " ".join(ranking[:5])
    res["n_units"] = len(units)
    res["label_suspect"] = label_suspect(pipe, row, in_corpus)
    # 완화 기준: 정답 표 + 같은 값을 가진 대체 정답 표 (alt_gold.py). --alt 가 없으면 None
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


METRICS = ["hit@1", "hit@3", "hit@5", "hit@10", "groups@5", "groups@10", "mrr", "pool@k", "pool_groups@k",
           "gold_unmet_any", "sibling_confusion", "near_confusion", "in_corpus", "dense@10", "dense@50", "rwdense@10"]
ALT_METRICS = ["hit@1_alt", "hit@3_alt", "hit@5_alt", "hit@10_alt", "groups@5_alt", "groups@10_alt", "mrr_alt"]


def aggregate(recs):
    out = {"n": len(recs), **{m: _mean([r.get(m) for r in recs]) for m in METRICS}}
    if any(r.get("mrr_alt") is not None for r in recs):
        out.update({m: _mean([r.get(m) for r in recs]) for m in ALT_METRICS})
        out["with_alt"] = _mean([int(bool(r.get("alt_tables"))) for r in recs])
    return out


def run(rows, analysis, denses, llm, top_k, pool, log=print, tuned=None, docs=("rule",), cards=None, kos14=None, ce=None,
        arms=None, raw_analysis=None):
    """tuned: 폴더 — dense(·문서)마다 <폴더>/search.tuned.<dense>[.<docs>].yaml 의 가중치로 (없으면 기본 가중치, 이름에 * 없음)
    docs: dense 문서 구성 목록 (index.parse_docs). 두 개 이상이거나 rule 이 아니면 구성 이름이 '<dense>|<docs>'
    ce: 교차 인코더 재정렬 설정(dict) — 주면 방법 'search+ce' 를 함께 (ce_rerank.py)
    arms: ARMS 이름 목록 — 구성마다 arm 을 붙여 나란히 (이름 '<dense>|<docs>|<arm>'). raw_analysis = 검증 전 단위 (arm off)"""
    from backend.rag.search.tuning.tune import load_tuned, tuned_path
    per, info = [], {}
    docs = list(docs or ["rule"])
    label_docs = len(docs) > 1 or docs != ["rule"]
    for dense0 in denses:
        for dd in (docs if dense0 != "none" else docs[:1]):
            st = load_tuned(dense0, tuned, dd) if tuned else None
            base = f"{dense0}|{dd}" if label_docs and dense0 != "none" else dense0
            dense = f"{base}*" if st else base               # * = 그 모델(·문서)에 맞춘 가중치
            if tuned:
                log(f"  {base}: " + (f"맞춘 가중치 {tuned_path(dense0, tuned, dd).name}" if st else "맞춘 가중치 없음 → 기본 가중치"))
            settings = dict(st or {})
            if dd != "rule":
                settings.update({"dense_docs": dd, "dense_cards": cards, "kos14_cards": kos14})
            methods = [("search", False, None)] + ([("search+ce", False, ce)] if ce else []) \
                + ([("search+llm", True, None)] if llm else [])
            for m, use_llm, ce_cfg in methods:
                st_m = dict(settings)
                if ce_cfg:
                    st_m["ce_rerank"] = {**ce_cfg, "enabled": True}
                try:
                    pipe0 = get_search_for(dense0, use_llm, st_m or None)
                except Exception as e:  # noqa: BLE001  (구성 하나가 비교 전체를 막지 않게)
                    name = f"{m}[{dense}]"
                    info[name] = {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}
                    log(f"  ✗ {name}: {info[name]['error']}")
                    continue
                for arm in (arms or [None]):
                    label = f"{dense}|{arm}" if arm else dense
                    name = f"{m}[{label}]"
                    t0 = time.time()
                    pipe, units_of_row = pipe0, analysis
                    if arm:
                        feas, prune = arm_settings(arm)
                        pipe = with_feas(pipe0, feas)
                        units_of_row = analysis if prune else (raw_analysis or analysis)
                    for row in rows:
                        res = evaluate_one(pipe, row, units_of_row[row["qid"]], top_k, pool)
                        per.append({"method": m, "dense": label, "config": name, **{k: row[k] for k in (
                            "qid", "record_id", "variant", "hop_type", "reasoning_type", "subtype", "survey", "difficulty")},
                            "split": row.get("split") or (row["difficulty"] if row["difficulty"] in ("dev", "test", "train") else ""),
                            "question": row["question"], "gold": " ".join(row["gold"]), **res})
                    info[name] = {"n_docs": len(pipe.docs), "corpus": pipe.corpus.signature()[:120],
                                  "seconds": round(time.time() - t0, 1), "dense_docs": dd, **({"tuned": st} if st else {}),
                                  **({"arm": arm, "feas": arm_settings(arm)[0], "prune_units": arm_settings(arm)[1]} if arm else {})}
                    log(f"  {name}: 문서 {len(pipe.docs)} · {info[name]['seconds']}초")
    return per, info


def with_feas(pipe, feas):
    """같은 채널(BM25·dense)을 쓰고 가능성 계수만 바꾼 검색기 (색인을 다시 만들지 않음)"""
    import copy as _copy
    import threading
    if not feas:
        return pipe
    p = _copy.copy(pipe)
    p.s = _copy.deepcopy(pipe.s)
    p.s["feas"].update(feas)
    p._qcache, p._lock = {}, threading.Lock()
    return p


def summarize(per):
    by = defaultdict(list)
    for r in per:
        by[(r["config"], "ALL", "ALL")].append(r)
        by[(r["config"], "variant", r["variant"])].append(r)
        by[(r["config"], "hop_type", r["hop_type"] or "-")].append(r)
        by[(r["config"], "reasoning_type", r["reasoning_type"] or "-")].append(r)
        if r.get("split"):  # retrieval_golden 의 split · 합성 셋 dev/heldout
            by[(r["config"], "split", r["split"])].append(r)
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


def sign_test(a_only, b_only):
    """한쪽만 맞힌 질문 수로 양측 부호 검정 p 값 (같은 질문을 두 설정으로 — 맥니마 검정과 같음)"""
    from math import comb
    n, k = a_only + b_only, min(a_only, b_only)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def method_vs_base(per, metrics=("hit@1", "hit@3", "hit@5", "groups@5", "groups@10", "mrr")):
    """같은 dense 구성에서 방법(search+ce · search+llm)을 'search' 와 견줌 → 질문별 득실 · 부호 검정"""
    idx = defaultdict(dict)
    for r in per:
        idx[(r["dense"], r["qid"])][r["method"]] = r
    methods = [m for m in dict.fromkeys(r["method"] for r in per) if m != "search"]
    out = []
    for dense in dict.fromkeys(r["dense"] for r in per):
        for m in methods:
            pairs = [(d["search"], d[m]) for (dd, _), d in idx.items() if dd == dense and "search" in d and m in d]
            if not pairs:
                continue
            for metric in metrics:
                if metric == "mrr":
                    a = sum(float(x["mrr"]) for x, _ in pairs) / len(pairs)
                    b = sum(float(y["mrr"]) for _, y in pairs) / len(pairs)
                    out.append({"dense": dense, "method": m, "metric": "mrr", "base_value": a, "value": b, "delta": b - a,
                                "base_only": None, "only": None, "p": None})
                    continue
                vx = [x.get(metric) for x, _ in pairs]
                vy = [y.get(metric) for _, y in pairs]
                if any(v is None for v in vx + vy):
                    continue
                bo = sum(1 for x, y in zip(vx, vy) if x and not y)
                mo = sum(1 for x, y in zip(vx, vy) if y and not x)
                out.append({"dense": dense, "method": m, "metric": metric, "base_value": sum(vx) / len(vx),
                            "value": sum(vy) / len(vy), "delta": (sum(vy) - sum(vx)) / len(vx), "base_only": bo, "only": mo,
                            "p": sign_test(bo, mo)})
    return out


def dense_vs_base(per):
    """같은 방법(search / search+llm)에서 dense 를 바꿨을 때, 첫 dense(기준) 대비 질문별 득실
    → [{method, base, dense, metric, base_only, dense_only, p, base_value, dense_value, delta}]"""
    order = list(dict.fromkeys(r["dense"] for r in per))
    if len(order) < 2:
        return []
    base, out = order[0], []
    idx = defaultdict(dict)
    for r in per:
        idx[(r["method"], r["qid"])][r["dense"]] = r
    methods = list(dict.fromkeys(r["method"] for r in per))
    for m in methods:
        rows = [d for (mm, _), d in idx.items() if mm == m and base in d]
        for dn in order[1:]:
            pairs = [(d[base], d[dn]) for d in rows if dn in d]
            if not pairs:
                continue
            alt = [m + "_alt" for m in ("hit@1", "hit@5") if any(x.get(m + "_alt") is not None for x, _ in pairs)]
            extra = [m for m in ("dense@10", "dense@50", "near_confusion")
                     if all(x.get(m) is not None and y.get(m) is not None for x, y in pairs)]
            for metric in ("hit@1", "hit@5", "hit@10", "groups@5", "groups@10", *extra, *alt):  # _alt = 대체 정답 포함
                bo = sum(bool(x.get(metric)) and not y.get(metric) for x, y in pairs)
                do = sum(bool(y.get(metric)) and not x.get(metric) for x, y in pairs)
                bv = sum(bool(x.get(metric)) for x, _ in pairs) / len(pairs)
                dv = sum(bool(y.get(metric)) for _, y in pairs) / len(pairs)
                out.append({"method": m, "base": base, "dense": dn, "metric": metric, "n": len(pairs),
                            "base_only": bo, "dense_only": do, "p": round(sign_test(bo, do), 4),
                            "base_value": round(bv, 3), "dense_value": round(dv, 3), "delta": round(dv - bv, 3)})
            bm = sum(x["mrr"] for x, _ in pairs) / len(pairs)
            dm = sum(y["mrr"] for _, y in pairs) / len(pairs)
            out.append({"method": m, "base": base, "dense": dn, "metric": "mrr", "n": len(pairs), "base_only": None,
                        "dense_only": None, "p": None, "base_value": round(bm, 3), "dense_value": round(dm, 3),
                        "delta": round(dm - bm, 3)})
    return out


def _cell(x):
    """표 칸 안의 '|' (구성 이름 'bge-m3-ko|def') 가 칸 나누기로 읽혀 행이 한 칸씩 밀리지 않게"""
    return str(x).replace("|", "\\|")


def _fmt(x):
    return "-" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def report_md(meta, table, fails, wins, per):
    L = ["# 검색 비교", "",
         f"- 실행: {meta['created']} · 골든셋 `{meta['golden']}` · 질문 {meta['n_rows']}개 (변형 {meta['variants']})",
         f"- 질의 분석: `{meta['analyze']}` (상태 {meta['analysis_status']}) · top_k {meta['top_k']} · 합친 후보 {meta['pool']}",
         f"- dense: {meta['dense']} · dense 문서: {meta.get('dense_docs') or ['rule']}",
         f"- 하위 질문 검증(subcheck): {'적용' if meta.get('prune_units', False) else '안 함'}"
         + (f" — 단위를 뺀 문항 {meta.get('n_pruned')}" if meta.get('prune_units') else "")
         + (f" · arms {meta['arms']} (첫 arm 이 기준, off = 수정 전)" if meta.get("arms") else ""),
         "- 정답 = golden_table_ids ∪ 근거 그룹의 acceptable_table_ids. Hit@k = 하나라도 상위 k, Groups@k = 모든 근거 그룹이 상위 k",
         ""]
    for name, i in meta["configs"].items():
        L.append(f"- `{name}`: " + (f"오류 {i['error']}" if "error" in i else f"문서 {i['n_docs']} · {i['seconds']}초"))
    if any("mrr_alt" in t for t in table):  # 엄격 / 완화 나란히
        L += ["", "## 엄격 · 완화 (완화 = 정답 표 + 같은 값을 가진 대체 정답 표, alt_gold.py)", "",
              f"- 대체 정답 파일: `{meta.get('alt')}` · 대체 정답이 하나라도 있는 질문 비율 = with_alt", "",
              "| 구성 | 값 | n | with_alt | hit@1 → 완화 | hit@5 → 완화 | hit@10 → 완화 | groups@5 → 완화 | mrr → 완화 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for t in table:
            if t["group"] in ("ALL", "variant") and "mrr_alt" in t:
                L.append(f"| {_cell(t['config'])} | {_cell(t['value'])} | {t['n']} | {_fmt(t.get('with_alt'))} | "
                         + " | ".join(f"{_fmt(t[m])} → {_fmt(t[m + '_alt'])}" for m in ("hit@1", "hit@5", "hit@10", "groups@5", "mrr"))
                         + " |")
    cols = ["n", "hit@1", "hit@3", "hit@5", "hit@10", "groups@5", "groups@10", "mrr", "dense@10", "dense@50", "rwdense@10",
            "pool@k", "gold_unmet_any", "sibling_confusion", "near_confusion", "in_corpus"]
    for group in ("ALL", "variant", "hop_type", "reasoning_type", "split"):
        if not any(t["group"] == group for t in table):
            continue
        L += ["", f"## {'전체' if group == 'ALL' else group + '별'}", "",
              "| 구성 | 값 | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 2)]
        for t in table:
            if t["group"] == group:
                L.append(f"| {_cell(t['config'])} | {_cell(t['value'])} | " + " | ".join(_fmt(t[c]) for c in cols) + " |")
    L += ["", "## Hit@5 실패 원인", "", "| 구성 · 변형 | " + " | ".join(FAIL_LABEL[k] for k in FAIL_LABEL) + " |",
          "|" + "---|" * (len(FAIL_LABEL) + 1)]
    for k, v in sorted(fails.items()):
        L.append(f"| {_cell(k)} | " + " | ".join(str(v.get(f, 0)) for f in FAIL_LABEL) + " |")
    dv = dense_vs_base(per)
    if dv:
        L += ["", f"## dense 비교 (기준 = 첫 dense '{dv[0]['base']}', 같은 질문·같은 질의 분석)", "",
              "한쪽만 맞힌 질문 수와 부호 검정 p (p < 0.05 이면 우연으로 보기 어려운 차이). 문항이 적으면 몇 문항 차이는 잡음일 수 있음",
              "dense@k = dense 채널 혼자의 정답 순위 · near_confusion 은 낮을수록 좋음 (이름이 비슷한 표를 1위로)", "",
              "| 방법 | dense | 지표 | 기준 | dense | 차이 | 기준만 | dense만 | p |", "|---|---|---|---|---|---|---|---|---|"]
        for d in dv:
            L.append(f"| {d['method']} | {_cell(d['dense'])} | {d['metric']} | {_fmt(d['base_value'])} | {_fmt(d['dense_value'])} | "
                     f"{d['delta']:+.3f} | {_fmt(d['base_only'])} | {_fmt(d['dense_only'])} | {_fmt(d['p'])} |")
    mv = method_vs_base(per)
    if mv:
        L += ["", "## 방법 비교 (기준 = search, 같은 dense 구성·같은 질문)", "",
              "| dense | 방법 | 지표 | search | 방법 | 차이 | search만 | 방법만 | p |", "|---|---|---|---|---|---|---|---|---|"]
        for d in mv:
            L.append(f"| {_cell(d['dense'])} | {d['method']} | {d['metric']} | {_fmt(d['base_value'])} | {_fmt(d['value'])} | "
                     f"{d['delta']:+.3f} | {d['base_only'] if d['base_only'] is not None else '-'} | "
                     f"{d['only'] if d['only'] is not None else '-'} | {_fmt(d['p']) if d['p'] is not None else '-'} |")
    if wins:  # search 와 다른 방법을 같이 돌렸을 때 (--llm · --ce)
        L += ["", "## 같은 질문에서 한쪽만 Hit@5 (search ↔ search+llm)", "", "| dense | A | B | A만 | B만 | 같음 |",
              "|---|---|---|---|---|---|"]
        for w in wins:
            L.append(f"| {_cell(w['dense'])} | {w['a']} | {w['b']} | {w['a_only']} | {w['b_only']} | {w['same']} |")
    first = next(iter(dict.fromkeys(r["config"] for r in per)), None)
    sus = [r for r in per if r["config"] == first and r.get("label_suspect")]
    if sus:  # 생성 결함 의심 (성별 조건이 질문에서 빠짐)
        L += ["", f"## 정답 표시 의심 — 성별로 나뉜 정답 표인데 질문에 성별 말이 없음 ({len(sus)}문항, 기준 구성 {first})", "",
              "나뉘지 않은 형제 표(계)가 질문에 더 맞는 답일 수 있음 — 레코드를 고치거나 빼는 것을 검토. "
              f"이 문항들에서 형제 표가 1위: {sum(r['top1'] in r['label_suspect'].split() for r in sus)}", "",
              "| 질문 | 변형 | 정답 | 형제(계) | 순위 | top1 |", "|---|---|---|---|---|---|"]
        for r in sus:
            L.append(f"| {_cell(r['qid'])} {_cell(r['question'][:50])} | {r['variant']} | {r['gold']} | {r['label_suspect']} | "
                     f"{r['rank'] or '-'} | {r['top1']} |")
    # 결과가 갈린 질문 예 — 방법(search·search+llm)이 둘이면 방법 사이, 아니면 구성(dense·문서) 사이. P 변형 우선
    methods = list(dict.fromkeys(r["method"] for r in per))
    configs = list(dict.fromkeys(r["config"] for r in per))
    by_q = defaultdict(dict)
    if len(methods) > 1:
        for r in per:
            by_q[(r["dense"], r["qid"])][r["method"]] = r
        title, key = "방법 사이", "hit@5"
    else:
        for r in per:
            by_q[("", r["qid"])][r["config"]] = r
        title, key = "구성 사이 (Hit@1 이 갈린 질문)", "hit@1"
    diff = [(k, d) for k, d in by_q.items() if len({x[key] for x in d.values()}) > 1]
    diff.sort(key=lambda x: (x[0][1][-1] != "P", x[0]))
    if diff and len(configs) > 1:
        L += ["", f"## 결과가 갈린 질문 — {title} · {len(diff)}문항 중 최대 15개", ""]
        for (dense, qid), d in diff[:15]:
            any_r = next(iter(d.values()))
            L.append(f"- **{qid}**{f' [{dense}]' if dense else ''} {any_r['question'][:90]}  — 정답 {any_r['gold']}")
            for name, x in d.items():
                L.append(f"  - {name}: 순위 {x['rank'] or '-'}"
                         + (f" · dense 혼자 {x['dense_rank'] or '-'}" if x.get("dense_rank") not in (None, "") else "")
                         + f" · top1 {x['top1']} {x['top1_nm'][:30]}"
                         + (f" · 실패: {FAIL_LABEL.get(x['fail'], x['fail'])}" if x["fail"] else ""))
    return "\n".join(L) + "\n"


def _runs_dir():
    from backend.core.config import RUNS_DIR
    return Path(RUNS_DIR) / "search_compare"


def list_runs():
    """이전 compare 실행 → [{name, path, golden, alt, dense, n}] (최근 것 먼저)"""
    out = []
    d = _runs_dir()
    for f in sorted(d.glob("*/config.json"), key=lambda x: x.stat().st_mtime, reverse=True) if d.exists() else []:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n = None
        sm = f.parent / "summary.json"
        if sm.exists():
            try:
                n = json.loads(sm.read_text(encoding="utf-8"))["meta"]["n_rows"]
            except Exception:  # noqa: BLE001
                pass
        out.append({"name": f.parent.name, "path": f.parent, "golden": c.get("golden"), "alt": c.get("alt"),
                    "dense": c.get("dense"), "n": n})
    return out


NUM_TEXT = {"question", "gold", "top1", "top1_nm", "top5", "fail", "gold_unmet", "alt_tables", "qid", "record_id", "variant",
            "hop_type", "reasoning_type", "subtype", "survey", "difficulty", "split", "method", "dense", "config"}


def load_per_query(path):
    """per_query.csv → per 행 목록 (숫자 칸은 숫자로, 빈 칸은 None)"""
    out = []
    for r in csv.DictReader(Path(path).open(encoding="utf-8-sig")):
        for k, v in r.items():
            if k in NUM_TEXT:
                continue
            if v in ("", None):
                r[k] = None
            else:
                try:
                    r[k] = int(v)
                except ValueError:
                    try:
                        r[k] = float(v)
                    except ValueError:
                        pass
        out.append(r)
    return out


def rebuild_report(run_dir):
    """실행 폴더의 report.md 를 per_query.csv · summary.json 으로 다시 씀 (보고서 형식을 고친 뒤 옛 실행에)"""
    run_dir = Path(run_dir)
    per = load_per_query(run_dir / "per_query.csv")
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["meta"]
    table, fails, wins = summarize(per)
    out = run_dir / "report.md"
    out.write_text(report_md(meta, table, fails, wins, per), encoding="utf-8")
    return out


def find_run(key):
    """폴더 경로 또는 이름 일부 → 가장 최근 실행 폴더"""
    p = Path(key)
    if p.is_dir():
        return p
    hits = [r["path"] for r in list_runs() if key in r["name"]]
    if not hits:
        raise SystemExit(f"이전 실행을 찾지 못함: '{key}' — python -m backend.rag.search.tuning.compare --list-runs 로 이름 확인")
    return hits[0]


def main(argv=None):
    from backend.rag.search.index import dense_names
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.compare")
    ap.add_argument("--golden", default=None,
                    help="기본 synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl (--from-run 이면 그 실행의 셋)")
    ap.add_argument("--from-run", default=None, metavar="이름",
                    help="이전 compare 실행 폴더(이름 일부 또는 경로)의 골든셋 · 변형 · alt · 질의 분석 캐시를 그대로 씀. 직접 준 값이 우선")
    ap.add_argument("--rebuild-report", default=None, metavar="폴더",
                    help="이미 돌린 실행 폴더의 per_query.csv · summary.json 으로 report.md 만 다시 씀 (검색을 다시 돌리지 않음)")
    ap.add_argument("--list-runs", action="store_true", help="이전 compare 실행 목록 (폴더 · 골든셋 · alt · dense) 만 보여 주고 끝")
    ap.add_argument("--variants", nargs="*", default=["O", "P"])
    ap.add_argument("--llm", action="store_true", help="LLM 재정렬(HCX)을 붙인 구성도 함께 (search+llm)")
    ap.add_argument("--dense", nargs="*", default=["hcx"], choices=dense_names())
    ap.add_argument("--dense-docs", nargs="*", default=["rule"],
                    help="dense 문서 구성: rule | def | slot | tmpl | tslot | kos14 ('+' 로 여러 개 = 최댓값, 끝에 +rw). 첫 구성이 기준")
    ap.add_argument("--cards", default=None, help="dense 카드 파일 (기본 storage/indices/dense_cards/cards.jsonl)")
    ap.add_argument("--kos14", default=None, help="팀 카드 cards.jsonl (dense-docs kos14)")
    ap.add_argument("--ce", action="store_true", help="교차 인코더 재정렬 'search+ce' 도 함께 (ce_rerank.py, 로컬 모델)")
    ap.add_argument("--ce-model", default="bge-reranker-ko", help="bge-reranker-ko | bge-reranker | 허깅페이스 모델 이름")
    ap.add_argument("--ce-mode", default="blend", choices=["blend", "replace"])
    ap.add_argument("--ce-top-n", type=int, default=20)
    ap.add_argument("--ce-doc", default="struct+def", choices=["struct", "struct+def"])
    ap.add_argument("--ce-k", type=float, default=5.0, help="blend 의 순위 융합 상수")
    ap.add_argument("--ce-weight", type=float, default=1.0, help="blend 에서 교차 인코더 순위의 가중치 (원래 순위 = 1)")
    ap.add_argument("--analyze", default="analyze", choices=["analyze", "none"], help="none = 원문만 (HCX 없음)")
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--pool", type=int, default=50)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=None)
    ap.add_argument("--name", default="compare")
    ap.add_argument("--alt", default=None, help="대체 정답 파일 (alt_gold.py 의 alt_positives.jsonl) → 엄격/완화 지표")
    ap.add_argument("--alt-exact-only", action="store_true", help="반올림 일치(rounded)는 대체 정답으로 치지 않음")
    ap.add_argument("--cache", default=None, help="다른 compare 폴더의 analysis_cache.jsonl — 같은 질의 분석을 다시 씀")
    ap.add_argument("--tuned", nargs="?", const="configs", default=None, metavar="폴더",
                    help="dense 마다 <폴더>/search.tuned.<dense>.yaml (tune 결과) 가중치로. 폴더 기본 configs. 이름 뒤 * = 맞춘 가중치")
    ap.add_argument("--split", nargs="*", default=None,
                    help="retrieval_golden: dev / test · 합성 셋: dev / heldout (splits.py)")
    ap.add_argument("--arms", nargs="*", default=None, choices=list(ARMS),
                    help="앞단 수정을 켜고 끈 구성을 나란히: off(수정 전) units cycle move geo cond all. 첫 arm 이 기준")
    ap.add_argument("--raw-units", action="store_true", help="캐시된 질의 분석에 하위 질문 검증을 다시 적용하지 않음")
    a = ap.parse_args(argv)
    if a.rebuild_report:
        f = rebuild_report(find_run(a.rebuild_report))
        print(f"[보고서] 다시 씀 → {f}")
        return
    if a.list_runs:
        for r in list_runs():
            print(f"{r['name']:44s} n={r['n'] or '-':>4} dense={r['dense']}\n    golden={r['golden']}  alt={r['alt'] or '-'}")
        return
    if a.from_run:
        prev = find_run(a.from_run)
        cfg = json.loads((prev / "config.json").read_text(encoding="utf-8")) if (prev / "config.json").exists() else {}
        given = set(argv if argv is not None else sys.argv[1:])
        a.golden = a.golden or cfg.get("golden")
        if a.alt is None and cfg.get("alt"):
            a.alt = cfg["alt"]
        if "--variants" not in given and cfg.get("variants"):
            a.variants = cfg["variants"]
        if a.cache is None and (prev / "analysis_cache.jsonl").exists():
            a.cache = str(prev / "analysis_cache.jsonl")
        print(f"[이전 실행] {prev.name} → golden {a.golden} · alt {a.alt or '-'} · 변형 {a.variants} · 캐시 {a.cache or '-'}",
              flush=True)
    a.golden = a.golden or "synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl"

    from backend.core.config import RUNS_DIR
    out = Path(a.out) if a.out else Path(RUNS_DIR) / "search_compare" / f"{datetime.now():%Y%m%d_%H%M%S}_{a.name}"
    out.mkdir(parents=True, exist_ok=True)
    rows = load_golden(a.golden, tuple(a.variants), limit=a.limit, split=a.split)
    print(f"[골든셋] {len(rows)}문항 ← {a.golden}", flush=True)
    if a.alt:  # 판정 안 된 레코드는 대체 정답 없음으로
        from backend.rag.search.tuning.alt_gold import load_alt
        alt = load_alt(a.alt, include_rounded=not a.alt_exact_only)
        for r in rows:
            r["alt_groups"] = alt.get(r["record_id"], {})
        print(f"[대체 정답] {sum(bool(any(v.values())) for v in alt.values())}/{len(alt)} 레코드 ← {a.alt}", flush=True)
    cache = out / "analysis_cache.jsonl"
    if a.cache and Path(a.cache).resolve() != cache.resolve() and not cache.exists():
        import shutil
        shutil.copyfile(a.cache, cache)           # 다른 실행의 질의 분석을 그대로 (HCX 를 다시 부르지 않음)
    analysis = analyze_all(rows, a.analyze, a.today, cache)
    raw_analysis, n_pruned = analysis, 0
    if not a.raw_units:
        analysis, n_pruned = prune_analysis(rows, analysis)
    if a.tuned == "configs":
        from backend.core.config import CONFIGS_DIR
        a.tuned = str(CONFIGS_DIR)
    from backend.rag.search.index import parse_docs
    for d in a.dense_docs:
        parse_docs(d)                              # 잘못 쓴 이름은 돌리기 전에 알림
    ce = {"model": a.ce_model, "mode": a.ce_mode, "top_n": a.ce_top_n, "doc": a.ce_doc, "k": a.ce_k,
          "weight": a.ce_weight} if a.ce else None
    per, info = run(rows, analysis, a.dense, a.llm, a.top_k, a.pool, tuned=a.tuned, docs=a.dense_docs, cards=a.cards,
                    kos14=a.kos14, ce=ce, arms=a.arms, raw_analysis=raw_analysis)
    table, fails, wins = summarize(per)
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "golden": a.golden, "n_rows": len(rows),
            "variants": a.variants, "analyze": a.analyze, "today": a.today, "top_k": a.top_k, "pool": a.pool,
            "dense": a.dense, "dense_docs": a.dense_docs, "ce": ce, "configs": info, "alt": a.alt,
            "arms": a.arms, "prune_units": not a.raw_units, "n_pruned": n_pruned,
            "analysis_status": dict(Counter(u[0].get("status") for u in analysis.values()))}
    (out / "summary.json").write_text(json.dumps({"meta": meta, "table": table, "fails": fails, "wins": wins,
                                                  "dense_vs_base": dense_vs_base(per)},
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
                  f"groups@5={_fmt(t['groups@5'])} mrr={_fmt(t['mrr'])} pool@{a.pool}={_fmt(t['pool@k'])}"
                  + (f" | 완화 hit@5={_fmt(t['hit@5_alt'])} mrr={_fmt(t['mrr_alt'])}" if "mrr_alt" in t else ""))
    print(f"보고서 → {out / 'report.md'}")
    return out


if __name__ == "__main__":
    main()
