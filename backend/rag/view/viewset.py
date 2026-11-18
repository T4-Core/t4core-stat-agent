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


def _hybrid_search_fn(cfg, original):
    """[NEW 11-18] 검색 구성 이름이 하이브리드(table_card_search/configs/hybrid.yaml)면 그 검색 함수, 아니면 None.
    원래 질문(original)을 함께 넘김 — 하이브리드는 분석 문장과 원래 질문으로 각각 BM25·dense 순위를 냄"""
    if not isinstance(cfg, str):
        return None
    try:
        from table_card_search.search import get_pipeline_for, hybrid_methods
    except ImportError:
        return None
    if cfg not in hybrid_methods():
        return None
    p = get_pipeline_for(cfg, "hcx")
    return lambda q, top_k=10, filters=None, pool=None: p.search_compat(q, top_k, filters=filters, original=original)


def _first_only(views, filters, conf):
    """[NEW 11-18] 1순위만 넘길까: 두 View 가 겹치는 교차점에서 값이 모두 같고(status ok + 비교한 교차점 있음),
    2순위에만 있는 교차점이 없을 때. 비교 불가(겹치는 교차점 없음)·값 다름은 둘 다"""
    if len(views) != 2 or conf["status"] != "ok" or not conf["n_compared_keys"]:        # View 2개일 때만 (n_views=2)
        return False
    from backend.rag.view.points import record_points

    def keys(v):
        return {p.key_str() for p in record_points(v["record"], filters)[0] if p.value is not None}
    return not (keys(views[1]) - keys(views[0]))


# ── [NEW 11-18] 기간 이어붙이기 ─────────────────────────────────
def _stitch_of(candidates, tbl_id):
    """검색 결과에서 이 표의 이어붙이기 계획 (하이브리드 검색 + 묶음이 있을 때만, 아니면 None)"""
    return next((c.get("stitch") for c in candidates if c["tbl_id"] == tbl_id), None)


def _merge_same_group(u):
    """2순위가 1순위와 같은 묶음(같은 통계의 다른 연도 표)이면 경쟁 표가 아니라 이어붙일 조각 → 비교 전에 뺌"""
    if len(u["views"]) < 2:
        return
    st = _stitch_of(u["candidates"], u["views"][0]["tbl_id"])
    parts = {t["tbl_id"] for t in (st or {}).get("tables") or []}
    gone = [v for v in u["views"][1:] if v["tbl_id"] in parts]
    if gone:
        u["views"] = [v for v in u["views"] if v not in gone]
        u["notes"].append(f"{', '.join(v['tbl_id'] for v in gone)} 는 1순위 {u['views'][0]['tbl_id']} 와 같은 통계의 "
                          f"다른 연도 표 → 비교하지 않고 이어붙임")


def _yr(ys):
    """[2006,2007,2008,2011] → '2006~2008, 2011'"""
    out, s = [], None
    for i, y in enumerate(ys):
        s = y if s is None else s
        if i + 1 == len(ys) or ys[i + 1] != y + 1:
            out.append(str(y) if s == y else f"{s}~{y}")
            s = None
    return ", ".join(out)


def _add_stitched(u, label):
    """남은 View 마다 stitch 를 읽어 묶음의 다른 표를 '그 표가 맡은 연도'로 View 를 만듦 → u["stitched"][부모 tbl_id]
    부모 Record 에 이어붙인 표·없는 연도 메모를 붙임. 이어붙인 View 는 비교(선택) 대상이 아님"""
    from backend.rag.ingestion.build_view import build_view, note
    u.setdefault("stitched", {})
    have = {v["tbl_id"] for v in u["views"]}
    for v in u["views"]:
        st = _stitch_of(u["candidates"], v["tbl_id"])
        if not st:
            continue
        parts = []
        for j, t in enumerate(st["tables"], 1):
            if t["tbl_id"] == v["tbl_id"] or t["tbl_id"] in have:
                continue
            try:
                rec, vnotes = build_view(t["tbl_id"], {**u["filters"], "시점": t["years"]}, f"{label}-{v['rank']}s{j}")
            except Exception as e:  # noqa: BLE001  (이어붙일 표 하나 실패해도 계속)
                u["notes"].append(f"이어붙일 표 {t['tbl_id']} View 생성 실패: {e.__class__.__name__}: {str(e)[:150]}")
                continue
            rec["stitch"] = {"of": v["tbl_id"], "group": st["group"], "years": t["years"]}
            parts.append({"record": rec, "tbl_id": t["tbl_id"], "years": t["years"],
                          "notes": [n["text"] for n in vnotes]})
            have.add(t["tbl_id"])
        if not parts:
            continue
        u["stitched"][v["tbl_id"]] = parts
        own = next((t["years"] for t in st["tables"] if t["tbl_id"] == v["tbl_id"]), [])
        text = (f"같은 통계를 연도별로 나눈 표를 이어붙임: {v['tbl_id']}({_yr(own)}) + "
                + " + ".join(f"{p['tbl_id']}({_yr(p['years'])})" for p in parts))
        if st["years_missing"]:
            text += f". 이어붙여도 없는 연도: {_yr(st['years_missing'])}"
        if st.get("mixed_cycle"):
            text += ". 표마다 주기(년·월 등)가 다름"
        rec = v["record"]
        note(rec.setdefault("notes", []), "시점", "stitched", text, requested=st["years_have"] + st["years_missing"],
             applied=st["years_have"])
        v["notes"].append(text)
        v["stitch"] = {"group": st["group"], "tables": [v["tbl_id"]] + [p["tbl_id"] for p in parts],
                       "years_have": st["years_have"], "years_missing": st["years_missing"]}


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
        search_fn = _hybrid_search_fn(cfg, vb.get("original"))          # [NEW 11-18] 하이브리드 구성
        if search_fn is None:
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
            if s.view_stitch:                                                  # [NEW 11-18]
                _merge_same_group(u)
            conf = detect(u["views"], u["filters"], s, uid)
            if s.view_first_only_when_same and _first_only(u["views"], u["filters"], conf):   # [NEW 11-18]
                u["views"] = u["views"][:1]
                conf["first_only"] = True
                conf["notes"].append(f"2순위 표 {conf['views'][1]['tbl_id']} 와 겹치는 교차점 값이 모두 같아 1순위만 넘김")
            if s.view_stitch:                                                  # [NEW 11-18] 비교가 끝난 뒤 → 선택 대상 아님
                _add_stitched(u, vb["query_id"] if uid == "main" else uid)
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
                "selected": None, "keep_unusable": s.view_keep_unusable,
                "stitched": u.get("stitched") or {}}                         # [NEW 11-18] {부모 tbl_id: [이어붙인 View]}
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
    # [NEW 11-18] 넘기는 표에 이어붙인 View 가 있으면 바로 뒤에 같이 (부모 표가 빠지면 같이 빠짐)
    out = []
    for r in recs:
        out.append(r)
        out += [p["record"] for p in (unit.get("stitched") or {}).get((r.get("source") or {}).get("tbl_id"), [])]
    return out


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
