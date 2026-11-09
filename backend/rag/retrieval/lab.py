"""[NEW v4] 검색 실험실 — 같은 질의 묶음을 여러 구성으로 돌려 사람이 나란히 비교

정답셋 없이 쓰는 것이 기본: 구성별 상위 k 표를 한 화면(report.html)에 나란히 놓고, 사람이 (질의, 표) 쌍마다
관련도를 적으면(review.csv) 그 판정으로 구성별 점수를 계산한다. 같은 표는 어느 구성에서 나왔든 한 번만 판정.

  qs  = load_queries("bundles", limit=20)         # 질의 묶음 (아래 출처)
  res = run_compare(qs, ["baseline", "hybrid_rrf_hcx"], top_k=10)
  res["files"]["html"]                            # storage/runs/<run_id>/report.html  ← 브라우저로 열기
  # review.csv 의 label 칸 채움 (2 = 바로 답할 수 있는 표, 1 = 관련 있음·조건 일부, 0 = 무관; O/△/X 도 됨)
  score_review(res["run_id"])                     # → 구성별 P@k · MRR · nDCG@k · hit@1 · 판정 비율

질의 출처 (load_queries)
  bundles   eval/query_rewrite/outputs/query_bundles.json (재작성 80문항: 원문 + 슬롯) → views.run_query 와 같은 검색 단위
            (본 질의 + 하위 질의, resolve.search_query 로 다듬은 문장 + View 슬롯)  ← HCX 호출 없음
  golden    eval/golden_set/kosis_rag_eval_50.jsonl (질문만. gold_table_ids 가 채워져 있으면 자동 지표도)
  examples  쿼리 모듈 예시 12개 (query_bundle.example_queries)
  <경로>     yaml/json/jsonl: [{id, question, search_text?, filters?, gold?: [tbl_id]}]
  analyze="v4" 를 주면 filters 가 없는 질문은 v4 쿼리 모듈로 분석해서 슬롯·검색 문장을 만듦 (HCX 1회/질문)
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from backend.core.config import EVAL_DIR, RUNS_DIR

BUNDLES_PATH = EVAL_DIR / "query_rewrite" / "outputs" / "query_bundles.json"
GOLDEN_PATH = EVAL_DIR / "golden_set" / "kosis_rag_eval_50.jsonl"
LABELS = {"2": 2, "1": 1, "0": 0, "o": 2, "○": 2, "◯": 2, "△": 1, "x": 0, "×": 0, "y": 2, "n": 0}


# ── 질의 묶음 ────────────────────────────────────────────────────
def _units_from_bundle(b, qid, question=None):
    """재작성 bundle(dict) → views.run_query 와 같은 검색 단위들"""
    from backend.rag.ingestion.resolve import search_query
    from backend.rag.ingestion.views import units_of
    from backend.rag.query_analyzer.adapter import to_view_bundle
    vb = {k: v for k, v in b.items() if k != "_view"} if b.get("_view") else to_view_bundle(b, query_id=qid)[0]
    if vb.get("filters") is None:                                  # 범위 밖 질문 → 원문 그대로, 슬롯 없음
        return [{"id": qid, "question": question or b.get("original"), "text": vb.get("search_text") or b["original"],
                 "search_query": vb.get("search_text") or b["original"], "filters": None, "unit": "main",
                 "note": "범위 밖 또는 재작성 실패 (슬롯 없음)"}]
    out = []
    for uid, text, f in units_of(vb):
        out.append({"id": qid if uid == "main" else uid, "question": question or b.get("original"), "unit": uid,
                    "text": text, "search_query": search_query(text, f), "filters": f})
    return out


def queries_from_bundles(path=None, limit=None):
    data = json.loads(Path(path or BUNDLES_PATH).read_text(encoding="utf-8"))
    data = data if isinstance(data, list) else data.get("bundles") or data.get("queries") or []
    out = []
    for n, b in enumerate(data[:limit] if limit else data, 1):
        out += [{**u, "source": "bundles"} for u in _units_from_bundle(b, b.get("query_id") or f"B{n:02d}")]
    return out


def _from_questions(items, analyze=None, today=None, source="file"):
    out = []
    for n, it in enumerate(items, 1):
        qid = str(it.get("id") or f"Q{n:02d}")
        gold = list(it.get("gold") or [])
        q = it.get("question") or it.get("original") or it.get("search_text")
        if it.get("filters") is not None or it.get("search_text"):
            f = it.get("filters")
            text = it.get("search_text") or q
            if f is not None and it.get("prep", True):
                from backend.rag.ingestion.resolve import search_query
                sq = search_query(text, f)
            else:
                sq = text
            out.append({"id": qid, "question": q, "unit": "main", "text": text, "search_query": sq, "filters": f,
                        "gold": gold, "source": source})
        elif analyze == "v4":
            from backend.rag.query_analyzer.v4 import analyze as v4_analyze
            a = v4_analyze(q, today=today, query_id=qid)
            if a.get("view_bundle"):
                vb = {**a["view_bundle"], "_view": True}
                for u in _units_from_bundle(vb, qid, q):
                    out.append({**u, "gold": gold, "source": f"{source}+v4", "analysis_status": a["status"]})
            else:
                out.append({"id": qid, "question": q, "unit": "main", "text": q, "search_query": q, "filters": None,
                            "gold": gold, "source": f"{source}+v4", "analysis_status": a["status"],
                            "note": f"v4 분석 {a['status']} → 원문으로 검색"})
        else:
            out.append({"id": qid, "question": q, "unit": "main", "text": q, "search_query": q, "filters": None,
                        "gold": gold, "source": source, "note": "슬롯 없음 (원문 검색)"})
    return out


def queries_from_golden(path=None, limit=None, analyze=None, today=None):
    rows = [json.loads(x) for x in Path(path or GOLDEN_PATH).read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = rows[:limit] if limit else rows
    items = [{"id": r.get("id"), "question": r["question"], "gold": (r.get("review") or {}).get("gold_table_ids") or []}
             for r in rows]
    return _from_questions(items, analyze, today, "golden")


def queries_from_examples(limit=None):
    from backend.rag.query_analyzer.query_bundle import example_queries
    out = []
    for e in example_queries()[:limit] if limit else example_queries():
        b = {**e["bundle"], "_view": True}
        for u in _units_from_bundle(b, b["query_id"]):
            out.append({**u, "source": "examples"})
    return out


def queries_from_file(path, analyze=None, today=None, limit=None):
    p = Path(path)
    if p.suffix in (".yaml", ".yml"):
        import yaml
        items = yaml.safe_load(p.read_text(encoding="utf-8"))
    elif p.suffix == ".jsonl":
        items = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    else:
        items = json.loads(p.read_text(encoding="utf-8"))
    items = items.get("queries", items) if isinstance(items, dict) else items
    if items and "original" in items[0] and "filters" in items[0] and "question" not in items[0]:
        return queries_from_bundles(p, limit)                       # 재작성 bundle 목록 파일
    return _from_questions(items[:limit] if limit else items, analyze, today, p.stem)


def load_queries(source="bundles", limit=None, analyze=None, today=None):
    if isinstance(source, list):
        return _from_questions(source[:limit] if limit else source, analyze, today, "inline")
    if source == "bundles":
        return queries_from_bundles(limit=limit)
    if source == "golden":
        return queries_from_golden(limit=limit, analyze=analyze, today=today)
    if source == "examples":
        return queries_from_examples(limit)
    return queries_from_file(source, analyze, today, limit)


# ── 비교 ─────────────────────────────────────────────────────────
def _agree(ref, ids, k):
    a, b = ref[:k], ids[:k]
    if not a and not b:
        return {"top1": True, "overlap": 1.0, "jaccard": 1.0, "rank_shift": 0.0}
    inter = set(a) & set(b)
    shift = [abs(a.index(t) - b.index(t)) for t in inter]
    return {"top1": bool(a and b and a[0] == b[0]), "overlap": round(len(inter) / max(len(a), 1), 3),
            "jaccard": round(len(inter) / max(len(set(a) | set(b)), 1), 3),
            "rank_shift": round(sum(shift) / len(shift), 2) if shift else None}


def ranking_metrics(ids, labels, k):
    """ids: 순위 목록, labels: {tbl_id: 0|1|2} (없으면 미판정) → P@k·MRR·nDCG@k·hit@1·판정률"""
    top = ids[:k]
    judged = [t for t in top if t in labels]
    rel = [labels.get(t, 0) for t in top]
    first = next((i for i, g in enumerate(rel, 1) if g >= 1), None)
    dcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(rel, 1))
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return {"p_at_k": round(sum(g >= 1 for g in rel) / max(len(top), 1), 3),
            "p_at_k_strict": round(sum(g >= 2 for g in rel) / max(len(top), 1), 3),
            "mrr": round(1 / first, 3) if first else 0.0, "ndcg": round(dcg / idcg, 3) if idcg else 0.0,
            "hit1": bool(rel and rel[0] >= 1), "judged": round(len(judged) / max(len(top), 1), 3)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _slim(h):
    return {"rank": h["rank"], "tbl_id": h["tbl_id"], "tbl_nm": h.get("tbl_nm", ""), "survey_nm": h.get("survey_nm", ""),
            "score": h.get("score"), "cost": h.get("cost"), "unmet": [u.get("text") for u in h.get("unmet") or []],
            "stages": h.get("stages", {})}


def run_compare(queries, configs, top_k=10, reference=None, save=True, blind=False, overrides=None,
                run_name="compare", trace=False, progress=None):
    """queries: load_queries 결과, configs: [이름 | dict] → 구성별 결과 + 일치도(+ gold 지표) + 보고서 파일"""
    from backend.core.tracking import Tracer
    from backend.rag.retrieval.factory import config_hash, get_pipeline, load_config
    cfgs, pipes = [], {}
    for c in configs:
        try:
            cd = load_config(c, (overrides or {}).get(c if isinstance(c, str) else "", None))
        except Exception as e:  # noqa: BLE001
            cfgs.append({"name": str(c), "error": f"{e.__class__.__name__}: {e}"})
            continue
        entry = {"name": cd["name"], "description": cd.get("description", ""), "hash": config_hash(cd), "config": cd}
        try:
            t0 = time.time()
            pipes[cd["name"]] = get_pipeline(cd)
            entry["build_seconds"] = round(time.time() - t0, 2)
            entry["info"] = {k: v for k, v in pipes[cd["name"]].info().items() if k != "config"}
        except Exception as e:  # noqa: BLE001  (모델이 없는 구성 하나가 비교 전체를 막지 않게)
            entry["error"] = f"{e.__class__.__name__}: {str(e)[:300]}"
        cfgs.append(entry)
    names = [c["name"] for c in cfgs if "error" not in c]
    ref = reference if reference in names else (names[0] if names else None)
    rows = []
    for qn, q in enumerate(queries, 1):
        row = {k: q.get(k) for k in ("id", "question", "unit", "text", "search_query", "filters", "gold", "source",
                                      "note", "analysis_status") if q.get(k) is not None}
        row["results"] = {}
        for n in names:
            try:
                tr = Tracer(run_name=f"{n}") if trace else None
                r = pipes[n].search(q["search_query"], q.get("filters"), top_k, tracer=tr)
                row["results"][n] = {"hits": [_slim(h) for h in r["hits"]], "seconds": r["seconds"],
                                     **({"trace": r["trace"]} if trace else {})}
            except Exception as e:  # noqa: BLE001
                row["results"][n] = {"hits": [], "error": f"{e.__class__.__name__}: {str(e)[:300]}"}
        if ref:
            ref_ids = [h["tbl_id"] for h in row["results"][ref]["hits"]]
            row["agreement"] = {n: _agree(ref_ids, [h["tbl_id"] for h in row["results"][n]["hits"]], top_k)
                                for n in names if n != ref}
        if q.get("gold"):
            labels = {t: 2 for t in q["gold"]}
            row["gold_metrics"] = {n: ranking_metrics([h["tbl_id"] for h in row["results"][n]["hits"]], labels, top_k)
                                   for n in names}
        rows.append(row)
        if progress:
            progress(f"  {qn}/{len(queries)} {q['id']}")
    summary = {}
    for n in names:
        rs = [r["results"][n] for r in rows]
        s = {"n_ok": sum("error" not in x for x in rs), "n_error": sum("error" in x for x in rs),
             "mean_seconds": _mean([x.get("seconds") for x in rs])}
        if n != ref and ref:
            ag = [r["agreement"][n] for r in rows]
            s.update({f"vs_{ref}": {"top1_same": _mean([float(a["top1"]) for a in ag]),
                                     "overlap": _mean([a["overlap"] for a in ag]), "jaccard": _mean([a["jaccard"] for a in ag]),
                                     "rank_shift": _mean([a["rank_shift"] for a in ag])}})
        gm = [r["gold_metrics"][n] for r in rows if "gold_metrics" in r]
        if gm:
            s["gold"] = {"n": len(gm), **{m: _mean([float(x[m]) for x in gm]) for m in ("p_at_k", "mrr", "ndcg", "hit1")}}
        summary[n] = s
    run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{run_name}_{uuid.uuid4().hex[:6]}"
    labels_of = {n: (chr(65 + i) if blind else n) for i, n in enumerate(names)}
    res = {"run_id": run_id, "created": datetime.now().isoformat(timespec="seconds"), "top_k": top_k,
           "reference": ref, "blind": blind, "labels": labels_of, "configs": cfgs, "summary": summary,
           "n_queries": len(rows), "queries": rows, "files": {}}
    if save:
        res["files"] = write_outputs(res)
    return res


# ── 보고서 ───────────────────────────────────────────────────────
def run_dir(run_id):
    d = Path(RUNS_DIR) / run_id
    if not re.fullmatch(r"[\w\-]+", str(run_id)):
        raise ValueError(f"잘못된 run_id: {run_id}")
    return d


def review_rows(res):
    """(질의, 표) 쌍 하나에 한 줄 — 어느 구성이 몇 위로 냈는지 함께"""
    out = []
    for q in res["queries"]:
        found = {}
        for n, r in q["results"].items():
            for h in r.get("hits", []):
                f = found.setdefault(h["tbl_id"], {"tbl_nm": h["tbl_nm"], "survey_nm": h["survey_nm"], "by": [],
                                                    "best": h["rank"], "unmet": "; ".join(h.get("unmet") or [])})
                f["by"].append(f"{res['labels'][n]}#{h['rank']}")
                f["best"] = min(f["best"], h["rank"])
        for t, f in sorted(found.items(), key=lambda x: (x[1]["best"], x[0])):
            out.append({"query_id": q["id"], "question": q.get("question") or "", "search_query": q.get("search_query") or "",
                        "filters": json.dumps(q.get("filters"), ensure_ascii=False) if q.get("filters") is not None else "",
                        "tbl_id": t, "tbl_nm": f["tbl_nm"], "survey_nm": f["survey_nm"], "found_by": " ".join(f["by"]),
                        "best_rank": f["best"], "unmet": f["unmet"],
                        "gold": "Y" if t in (q.get("gold") or []) else "", "label": "", "comment": ""})
    return out


REVIEW_COLS = ["query_id", "question", "search_query", "filters", "tbl_id", "tbl_nm", "survey_nm", "found_by",
               "best_rank", "unmet", "gold", "label", "comment"]


def write_outputs(res):
    d = run_dir(res["run_id"])
    d.mkdir(parents=True, exist_ok=True)
    files = {"dir": str(d)}
    (d / "params.json").write_text(json.dumps({"top_k": res["top_k"], "reference": res["reference"], "blind": res["blind"],
                                               "labels": res["labels"], "configs": res["configs"]},
                                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps(res["summary"], ensure_ascii=False, indent=1), encoding="utf-8")
    with (d / "results.jsonl").open("w", encoding="utf-8") as f:
        for q in res["queries"]:
            f.write(json.dumps(q, ensure_ascii=False, default=str) + "\n")
    with (d / "review.csv").open("w", encoding="utf-8-sig", newline="") as f:     # 엑셀에서 바로 열리게
        w = csv.DictWriter(f, REVIEW_COLS)
        w.writeheader()
        w.writerows(review_rows(res))
    (d / "report.md").write_text(render_markdown(res), encoding="utf-8")
    (d / "report.html").write_text(render_html(res), encoding="utf-8")
    if res["blind"]:
        (d / "key.json").write_text(json.dumps(res["labels"], ensure_ascii=False, indent=1), encoding="utf-8")
    files.update({k: str(d / v) for k, v in [("params", "params.json"), ("summary", "summary.json"),
                                              ("results", "results.jsonl"), ("review", "review.csv"),
                                              ("markdown", "report.md"), ("html", "report.html")]})
    return files


def load_run(run_id):
    d = run_dir(run_id)
    if not (d / "params.json").exists():
        raise FileNotFoundError(f"실행 기록 없음: {d}")
    p = json.loads((d / "params.json").read_text(encoding="utf-8"))
    qs = [json.loads(x) for x in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return {**p, "run_id": run_id, "queries": qs,
            "summary": json.loads((d / "summary.json").read_text(encoding="utf-8"))}


def _label(v):
    v = "" if v is None else str(v).strip().lower()          # 숫자 0 도 판정 (0 or "" 로 빈칸이 되지 않게)
    return LABELS.get(v)


def score_review(run_id, judgments=None, review_path=None, k=None):
    """사람 판정 → 구성별 점수. judgments: [{query_id, tbl_id, label}] (없으면 review.csv 의 label 칸)"""
    res = load_run(run_id)
    k = k or res["top_k"]
    labels = {}
    if judgments:
        for j in judgments:
            g = _label(j.get("label"))
            if g is not None:
                labels.setdefault(str(j["query_id"]), {})[j["tbl_id"]] = g
    else:
        p = Path(review_path) if review_path else run_dir(run_id) / "review.csv"
        with p.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                g = _label(r.get("label"))
                if g is not None:
                    labels.setdefault(str(r["query_id"]), {})[r["tbl_id"]] = g
    per = {}
    for q in res["queries"]:
        lab = labels.get(str(q["id"]))
        if not lab:
            continue
        for n, r in q["results"].items():
            per.setdefault(n, []).append(ranking_metrics([h["tbl_id"] for h in r.get("hits", [])], lab, k))
    out = {n: {"n_queries": len(ms), **{m: _mean([float(x[m]) for x in ms])
                                         for m in ("p_at_k", "p_at_k_strict", "mrr", "ndcg", "hit1", "judged")}}
           for n, ms in per.items()}
    result = {"run_id": run_id, "k": k, "n_labeled_queries": len(labels),
              "n_labels": sum(len(v) for v in labels.values()), "by_config": out,
              "labels": res.get("labels"), "blind": res.get("blind")}
    (run_dir(run_id) / "review_scores.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _color(tbl_id):
    h = int(hashlib.md5(tbl_id.encode()).hexdigest()[:6], 16)
    return f"hsl({h % 360}, 70%, 92%)"


def render_markdown(res):
    L, names = res["labels"], list(res["labels"])
    out = [f"# 검색 구성 비교 `{res['run_id']}`", "",
           f"- 질의 {res['n_queries']}개 · top_k {res['top_k']} · 기준 구성 `{L.get(res['reference'], res['reference'])}`", ""]
    out += ["| 구성 | 설명 | 오류 | 평균 초 | 1위 일치 | 겹침 | Jaccard |", "|---|---|---|---|---|---|---|"]
    for c in res["configs"]:
        n = c["name"]
        if "error" in c:
            out.append(f"| {n} | {c.get('description', '')} | {c['error'][:80]} | | | | |")
            continue
        s = res["summary"].get(n, {})
        v = s.get(f"vs_{res['reference']}", {})
        out.append(f"| {L[n]} | {'' if res['blind'] else c.get('description', '')} | {s.get('n_error', 0)} | "
                   f"{s.get('mean_seconds')} | {v.get('top1_same', '-')} | {v.get('overlap', '-')} | {v.get('jaccard', '-')} |")
    for q in res["queries"]:
        out += ["", f"## {q['id']} — {q.get('question') or ''}", "",
                f"검색 문장 `{q.get('search_query')}` · 슬롯 `{json.dumps(q.get('filters'), ensure_ascii=False)}`", "",
                "| # | " + " | ".join(L[n] for n in names) + " |", "|---|" + "---|" * len(names)]
        k = max((len(q["results"][n].get("hits", [])) for n in names), default=0)
        for i in range(k):
            cells = []
            for n in names:
                hs = q["results"][n].get("hits", [])
                cells.append(f"{hs[i]['tbl_nm'][:24]} `{hs[i]['tbl_id']}`" if i < len(hs) else "")
            out.append(f"| {i + 1} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def render_html(res):
    e = html.escape
    L, names = res["labels"], list(res["labels"])
    ref = res["reference"]
    head = "".join(f"<th>{e(L[n])}</th>" for n in names)
    summ = []
    for c in res["configs"]:
        n = c["name"]
        if "error" in c:
            summ.append(f"<tr class=err><td>{e(n)}</td><td colspan=6>{e(c['error'])}</td></tr>")
            continue
        s = res["summary"].get(n, {})
        v = s.get(f"vs_{ref}", {})
        g = s.get("gold") or {}
        summ.append(f"<tr><td><b>{e(L[n])}</b></td><td>{'' if res['blind'] else e(c.get('description', ''))}</td>"
                    f"<td>{s.get('n_error', 0)}</td><td>{s.get('mean_seconds')}</td>"
                    f"<td>{'기준' if n == ref else v.get('top1_same', '-')}</td><td>{'' if n == ref else v.get('overlap', '-')}</td>"
                    f"<td>{'MRR ' + str(g.get('mrr')) if g else ''}</td></tr>")
    blocks = []
    for q in res["queries"]:
        k = max((len(q["results"][n].get("hits", [])) for n in names), default=0)
        gold = set(q.get("gold") or [])
        trs = []
        for i in range(k):
            tds = []
            for n in names:
                r = q["results"][n]
                hs = r.get("hits", [])
                if r.get("error") and i == 0:
                    tds.append(f"<td class=err>{e(r['error'][:200])}</td>")
                    continue
                if i >= len(hs):
                    tds.append("<td></td>")
                    continue
                h = hs[i]
                un = h.get("unmet") or []
                tds.append(f"<td style='background:{_color(h['tbl_id'])}' title='{e(json.dumps(h.get('stages'), ensure_ascii=False))}'>"
                           f"{'★ ' if h['tbl_id'] in gold else ''}<b>{e(h['tbl_nm'])}</b><br>"
                           f"<small>{e(h['tbl_id'])} · {e(h.get('survey_nm') or '')} · 점수 {h.get('score')}"
                           f"{' · 못 맞춘 조건 ' + e('; '.join(un)) if un else ''}</small></td>")
            trs.append(f"<tr><th>{i + 1}</th>{''.join(tds)}</tr>")
        ag = q.get("agreement") or {}
        agt = " · ".join(f"{e(L[n])}: 1위 {'같음' if a['top1'] else '다름'}, 겹침 {a['overlap']}" for n, a in ag.items())
        note = f"<div class=note>{e(q['note'])}</div>" if q.get("note") else ""
        blocks.append(f"<section><h3>{e(str(q['id']))} — {e(q.get('question') or '')}</h3>"
                      f"<div class=meta>검색 문장 <code>{e(q.get('search_query') or '')}</code> · 슬롯 "
                      f"<code>{e(json.dumps(q.get('filters'), ensure_ascii=False))}</code></div>{note}"
                      f"<table class=cmp><tr><th>#</th>{head}</tr>{''.join(trs)}</table>"
                      f"<div class=meta>{agt}</div></section>")
    return f"""<!DOCTYPE html><html lang=ko><head><meta charset=utf-8><title>검색 구성 비교 {e(res['run_id'])}</title>
<style>
body{{font-family:-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:24px;color:#1d1d1f;max-width:1600px}}
h1{{font-size:20px}} h3{{font-size:15px;margin:28px 0 6px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;font-size:13px;text-align:left}}
table.cmp td{{width:{max(100 // max(len(names), 1) - 1, 10)}%}} th{{background:#f5f5f7}} small{{color:#555}}
.meta{{color:#555;font-size:12px;margin:4px 0}} .note{{color:#a15c00;font-size:12px}} .err{{color:#b00020}}
code{{background:#f2f2f2;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>검색 구성 비교 <code>{e(res['run_id'])}</code></h1>
<p class=meta>질의 {res['n_queries']}개 · top_k {res['top_k']} · 기준 {e(L.get(ref, str(ref)))} · 같은 표는 같은 색 · 칸에 마우스를 올리면 단계별 순위
· ★ = gold · 판정은 review.csv 의 label 칸 (2 바로 답할 수 있는 표 / 1 관련·조건 일부 / 0 무관)</p>
<table><tr><th>구성</th><th>설명</th><th>오류</th><th>평균 초</th><th>1위 일치</th><th>겹침</th><th>gold</th></tr>{''.join(summ)}</table>
{''.join(blocks)}
</body></html>"""
