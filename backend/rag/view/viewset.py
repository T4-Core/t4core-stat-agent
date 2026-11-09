"""[NEW v4] 2-2 ViewSet — 검색 단위(본 질의 + 서브쿼리)마다 View 묶음 + 2-3 Point 충돌 판정 + 선택

  vs = build_viewset(analysis)                         # v4 analyze 결과 (status=ok) 또는 view_bundle 또는 질문 문자열
  vs["status"]   ok | needs_selection | needs_clarification | out_of_scope
  vs["records"]  답변 모듈로 넘길 Record 목록 (선택이 필요한 단위는 고른 뒤에 들어감)
  vs["pending"]  [{unit_id, selection_token, options}]  ← 선택이 필요한 단위
  vs2 = apply_selections(vs, {"opt-1": token} 또는 [{selection_token, option_id}])

  노트북·CLI 에서는 build_viewset(…, on_ambiguous=lambda conflict: "opt-1") 로 바로 고를 수 있음

검색·View 생성은 기존 views.run_query 를 그대로 쓴다 (retrieval_config 를 주면 Step 3 검색 구성으로 검색)
"""
from __future__ import annotations

import json
import time
import uuid

from backend.core.tracking import maybe_step
from backend.rag.view import selection
from backend.rag.view.conflict import detect


def _settings(overrides=None):
    from backend.core.settings_v4 import with_overrides
    return with_overrides(overrides)


# ── 선택지 설명 ─────────────────────────────────────────────────
def _csv_table(tbl_id):
    try:
        from backend.rag.csv_index import load_index
        return load_index().table(tbl_id)
    except FileNotFoundError:
        return None


def _meta_footnotes(record):
    from backend.core.config import KOSIS_DATA_DIR
    from backend.rag.csv_index.scanner import footnotes_of
    src = record.get("source") or {}
    for p in [KOSIS_DATA_DIR / "meta" / f"{src.get('org_id')}_{src.get('tbl_id')}.json"]:
        if p.exists():
            try:
                return footnotes_of(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                return []
    return []


def footnotes_for(record, limit=8):
    """표 주석 중 이 View 에 해당하는 것: 통계표 주석 + View 의 항목·분류 값을 가리키는 주석"""
    t = _csv_table((record.get("source") or {}).get("tbl_id"))
    notes = (t or {}).get("footnotes") if t else None
    if notes is None:
        notes = _meta_footnotes(record)
    rows = (record.get("table") or {}).get("rows") or []
    labels = {str(x) for r in rows for x in r[:-1] if x is not None} | set((record.get("metadata") or {}).get("items") or [])
    labels |= set(((record.get("metadata") or {}).get("dims")) or [])
    keep = [n for n in notes if n.get("type") == "통계표" or not n.get("target") or n.get("target") in labels]
    keep.sort(key=lambda n: (n.get("type") != "통계표", n.get("type") or ""))
    return keep[:limit]


def describe(record):
    """표 설명: CSV 값 사전 설명문 → 표 색인 설명문 → Record lexical_text"""
    tid = (record.get("source") or {}).get("tbl_id")
    t = _csv_table(tid)
    if t:
        from backend.rag.retrieval.corpus import csv_table_text
        return csv_table_text({**t, "footnotes": []})
    try:
        from backend.rag.ingestion.table_text import INDEX
        for line in (INDEX / "texts.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["tbl_id"] == tid:
                return r["text"]
    except (FileNotFoundError, ValueError):
        pass
    return record.get("lexical_text") or ""


def _tbl_nm(record):
    t = _csv_table((record.get("source") or {}).get("tbl_id"))
    return (t or {}).get("tbl_nm") or (record.get("lexical_text") or "").split(" ")[0]


def build_options(conf, views_by_id, settings):
    opts = []
    diffs = conf["differing_points"]
    for i, group in enumerate(conf["clusters"], 1):
        v = views_by_id[group[0]]
        rec, meta = v["record"], v["record"].get("metadata") or {}
        preview = []
        for d in diffs[: settings.conflict_preview_points]:
            hit = next((x for x in d["values"] if x["record_id"] in group), None)
            others = [{"tbl_id": x["tbl_id"], "value": x["value"], "unit": x["unit"]} for x in d["values"]
                      if x["record_id"] not in group]
            if hit:
                preview.append({"key": d["key"], "key_str": d["key_str"], "value": hit["value"], "unit": hit["unit"],
                                "others": others})
        basis = {"조사": meta.get("survey_nm"), "주기": meta.get("prd_se"),
                 "기간": f"{meta.get('prd_from')}~{meta.get('prd_to')}", "단위": meta.get("unit"),
                 "항목": meta.get("items"), "검색 순위": v.get("rank"),
                 "View 메모": [n.get("text") if isinstance(n, dict) else str(n) for n in rec.get("notes") or []]}
        opts.append({"option_id": f"opt-{i}", "record_ids": group, "tbl_ids": [views_by_id[r]["tbl_id"] for r in group],
                     "tbl_nm": _tbl_nm(rec), "survey_nm": meta.get("survey_nm"), "value_preview": preview,
                     "footnotes": footnotes_for(rec, settings.conflict_max_footnotes), "description": describe(rec),
                     "basis": basis, "kosis_url": (rec.get("source") or {}).get("kosis_url"),
                     "same_value_tables": [views_by_id[r]["tbl_id"] for r in group[1:]]})
    return opts


# ── 묶음 만들기 ─────────────────────────────────────────────────
def _view_bundle(source, today=None, overrides=None, tracer=None):
    """질문 문자열 | QueryAnalysis(dict) | view_bundle(dict) → (view_bundle | None, analysis | None)"""
    if isinstance(source, str):
        from backend.rag.query_analyzer.v4 import analyze
        source = analyze(source, today, overrides=overrides, tracer=tracer)
    if isinstance(source, dict) and "status" in source and ("bundle" in source or "state" in source):
        vb = source.get("view_bundle") if source["status"] == "ok" else None
        return (dict(vb, query_id=vb.get("query_id") or source.get("query_id")) if vb else None), source
    return dict(source), None


def build_viewset(source, *, today=None, retrieval_config=None, top_k=None, n_views=None, overrides=None,
                  on_ambiguous=None, tracer=None, progress=None):
    s = _settings(overrides)
    t0 = time.time()
    vb, analysis = _view_bundle(source, today, overrides, tracer)
    base = {"query_id": None, "status": None, "units": [], "records": [], "pending": [], "notes": [],
            "analysis_status": analysis.get("status") if analysis else None,
            "clarifications": (analysis or {}).get("clarifications") or [], "retrieval_config": None}
    if vb is None:
        return {**base, "status": analysis["status"], "query_id": analysis.get("query_id"),
                "notes": ["쿼리 분석이 끝나지 않아 검색하지 않음 (되묻기 또는 범위 밖)"], "seconds": round(time.time() - t0, 3)}
    vb = {**vb, "query_id": vb.get("query_id") or uuid.uuid4().hex[:8]}
    if vb.get("filters") is None:
        return {**base, "status": "out_of_scope", "query_id": vb["query_id"], "notes": ["슬롯 없음 (범위 밖)"],
                "seconds": round(time.time() - t0, 3)}
    cfg = retrieval_config or s.view_retrieval_config
    search_fn = None
    if cfg:
        from backend.rag.retrieval.factory import get_pipeline
        search_fn = get_pipeline(cfg).search_compat
    from backend.rag.ingestion.views import run_query
    with maybe_step(tracer, "2-1·2-2 검색 + View", top_k=top_k or s.view_top_k, n_views=n_views or s.view_n_views,
                    retrieval_config=cfg) as st:
        res = run_query(vb, top_k or s.view_top_k, n_views or s.view_n_views, progress=progress, search_fn=search_fn,
                        skip_main=not s.view_main_with_subs)
        st.output = {u["unit_id"]: [v["tbl_id"] for v in u["views"]] for u in res["units"]}
    units, records, pending = [], [], []
    for u in res["units"]:
        uid = u["unit_id"]
        with maybe_step(tracer, f"2-3 Point 비교:{uid}", rel_tol=s.conflict_rel_tol, abs_tol=s.conflict_abs_tol,
                        allow_partial=s.conflict_allow_partial) as st:
            conf = detect(u["views"], u["filters"], s, uid)
            views_by_id = {v["record"]["id"]: v for v in u["views"]}
            if conf["status"] == "ambiguous":
                conf["options"] = build_options(conf, views_by_id, s)
                involved = {r for o in conf["options"] for r in o["record_ids"]}
                keep = [rid for rid in views_by_id if rid not in involved]
                conf["selection_token"] = selection.issue(uid, vb["query_id"], u["filters"], conf["options"], keep,
                                                          s.selection_ttl_hours)
            else:
                conf["options"], conf["selection_token"] = [], None
            st.output = {"status": conf["status"], "n_compared_keys": conf["n_compared_keys"],
                         "n_differ": len(conf["differing_points"]), "clusters": conf["clusters"]}
        unit = {"unit_id": uid, "query": u["query"], "search_query": u["search_query"], "filters": u["filters"],
                "candidates": u["candidates"], "views": u["views"], "notes": u["notes"], "conflict": conf,
                "selected": None, "keep_unusable": s.view_keep_unusable}
        if conf["status"] == "ambiguous":
            choice = on_ambiguous(conf) if on_ambiguous else None
            if choice:
                _apply(unit, selection.resolve(conf["selection_token"], choice, [v["record"] for v in u["views"]]))
            else:
                pending.append({"unit_id": uid, "selection_token": conf["selection_token"], "options": conf["options"]})
        units.append(unit)
    for unit in units:
        records += unit_records(unit)
    status = "needs_selection" if pending else "ok"
    return {**base, "status": status, "query_id": vb["query_id"], "original": vb.get("original"), "units": units,
            "records": records, "pending": pending, "retrieval_config": cfg, "view_bundle": vb,
            "seconds": round(time.time() - t0, 3)}


def unit_records(unit):
    """단위 하나가 답변 모듈로 넘길 Record: 선택이 끝났거나 충돌이 없으면 View 전부 (선택된 무리 + 충돌과 무관한 View)"""
    c = unit["conflict"]
    if c["status"] == "ambiguous" and not unit.get("selected"):
        return []
    drop = set(unit["selected"]["dropped_ids"]) if unit.get("selected") else set()
    if not unit.get("keep_unusable", True) and any(v["usable"] for v in c["views"]):
        drop |= {v["record_id"] for v in c["views"] if not v["usable"]}       # 다 맞은 View 가 있을 때만 못 쓴 View 를 뺌
    recs = [v["record"] for v in unit["views"] if v["record"]["id"] not in drop]
    if unit.get("selected"):
        have = {r["id"] for r in recs}
        recs += [r for r in unit["selected"]["records"] if r["id"] not in have]
    return recs


def _apply(unit, sel):
    unit["selected"] = {k: sel[k] for k in ("option_id", "dropped_ids", "rebuilt", "records")}
    unit["conflict"]["selected_option"] = sel["option_id"]


def apply_selections(viewset, selections, con=None):
    """viewset(이전 응답) + 선택들 → 새 viewset. selections: [{selection_token, option_id}] 또는 {token: option_id}"""
    if isinstance(selections, dict):
        selections = [{"selection_token": k, "option_id": v} for k, v in selections.items()]
    vs = json.loads(json.dumps(viewset, default=str))                   # 원본은 그대로 두기
    by_unit = {u["unit_id"]: u for u in vs.get("units") or []}
    applied = []
    for sel in selections:
        prev = None
        p = selection.verify(sel["selection_token"])
        unit = by_unit.get(p["u"])
        if unit is not None:
            if unit["conflict"].get("selection_token") != sel["selection_token"]:
                raise ValueError(f"단위 {p['u']} 의 선택 토큰이 이 응답의 것과 다름")
            prev = [v["record"] for v in unit["views"]]
        r = selection.resolve(sel["selection_token"], sel["option_id"], prev, con)
        if unit is not None:
            _apply(unit, r)
        applied.append(r)
    vs["records"] = [rec for u in vs.get("units") or [] for rec in unit_records(u)]
    vs["pending"] = [p for p in vs.get("pending") or [] if not by_unit.get(p["unit_id"], {}).get("selected")]
    if vs.get("units"):
        vs["status"] = "needs_selection" if vs["pending"] else "ok"
    return vs, applied
