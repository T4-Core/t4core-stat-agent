"""
통합 파이프라인 — POST /api/v1/chat

  질문 ─▶ ① 질의 분석 (query_analyzer.analyze: 재작성 HCX 1회 → CSV 값 사전 접지 → 시점 규칙 → 서브쿼리)
       ─▶ ② 검색·View (view.build_viewset: 단위별 표 검색 → View 카드 → Point 충돌 판정)
       ─▶ ③ 답변 (agent.answer: HCX 1회)
             answer_mode="modules" 이면 대신 모듈 2→3→5→6 (agent.modules: 차트 계획 → 계산 → 그림 → 답변 문장)

중간에 멈추는 경우 (status)
  needs_clarification  필수 슬롯(시점·지역·대상)이 없고 clarify_mode=strict → analysis.clarifications 중 골라
                       {previous: 이 응답, selections: {슬롯: [값]}} 로 다시 호출 (재작성 HCX 는 다시 안 부름)
  needs_selection      같은 교차점 값이 표마다 다르고 auto_select=false → views.pending[].options 중 골라
                       {previous: 이 응답, view_selections: [{selection_token, option_id}]} 로 다시 호출
  out_of_scope         통계 수치를 묻지 않는 질문 → 검색하지 않고 안내 답변
"""
import json
import time
from datetime import datetime

from backend.agent.answer import answer_from_records
from backend.core.config import ANSWERS_DIR

OUT_OF_SCOPE_RESULT = {
    "answer": "이 질문은 통계 수치를 묻는 질문이 아니어서 KOSIS 통계표를 찾지 않았습니다. "
              "시점·지역·찾을 값을 넣어 물어봐 주세요. (예: '2025년 서울 1인가구 수', '최근 5년 대전 출생아 수 추이')",
    "summary": "", "key_points": [], "insufficient": True, "unverified_numbers": [], "used_ids": [], "chart_id": None,
    "chart": None, "sources": [], "caveats": [], "calculations": []}


def _first_option(conf):
    return conf["options"][0]["option_id"] if conf.get("options") else None


def _missing_notes(vs):
    from backend.rag.view.viewset import missing_indicator_note
    return [m for u in vs.get("units") or [] if (m := missing_indicator_note(u))]


def _answer(question, analysis, vs, max_rows):
    units = vs.get("units") or []
    missing = _missing_notes(vs)
    if missing and not vs.get("records"):          # 요청 지표가 어느 표에도 없음 → 다른 지표 값으로 답하지 않음
        return {**OUT_OF_SCOPE_RESULT, "answer": f"{missing[0]}. 다른 지표의 값으로 대신 답하지 않았습니다.",
                "caveats": missing}
    by_view = {v["record"]["id"]: (u, v) for u in units for v in u["views"]}
    tbl_nm = {c["tbl_id"]: c.get("tbl_nm") for u in units for c in u.get("candidates") or []}
    records = vs.get("records") or []
    notes = {r["id"]: by_view[r["id"]][1]["notes"] for r in records if r["id"] in by_view}
    titles = {r["id"]: tbl_nm[t] for r in records if tbl_nm.get(t := (r.get("source") or {}).get("tbl_id"))}
    groups = {r["id"]: by_view[r["id"]][0]["unit_id"] for r in records if r["id"] in by_view}
    vb = (analysis or {}).get("view_bundle") or vs.get("view_bundle") or {}
    queries = [vb.get("search_text") or question] + list(vb.get("sub_questions") or [])
    return answer_from_records(question, records, notes, titles, max_rows, queries,
                               groups=groups if len(units) > 1 else None)


def run_chat(question, today=None, top_k=None, n_views=None, max_rows=40, auto_select=True, overrides=None,
             previous=None, selections=None, view_selections=None, save=False, answer_mode="default", draw=True):
    from backend.rag.query_analyzer.analyze import analyze
    from backend.rag.view.viewset import apply_selections, build_viewset
    timings, t0 = {}, time.time()
    prev = previous or {}
    out = {"question": question, "analysis": None, "views": None, "records": [], "result": None, "notes": [],
           "timings": timings, "saved": None}

    if view_selections and prev.get("views"):
        analysis = prev.get("analysis")
        t = time.time()
        sels = [s if isinstance(s, dict) else s.model_dump() for s in view_selections]
        vs, _ = apply_selections(prev["views"], sels)
        timings["select"] = round(time.time() - t, 2)
    else:
        t = time.time()
        analysis = analyze(question, today, overrides=overrides or None,
                           previous=prev.get("analysis") if selections else None, selections=selections)
        timings["analyze"] = round(time.time() - t, 2)
        out["analysis"] = analysis
        out["notes"] += analysis.get("notes") or []
        if analysis["status"] != "ok":
            out["status"] = analysis["status"]
            if analysis["status"] == "out_of_scope":
                out["result"] = dict(OUT_OF_SCOPE_RESULT)
            return _finish(out, t0, save)
        t = time.time()
        vs = build_viewset(analysis, top_k=top_k, n_views=n_views, overrides=overrides or None,
                           on_ambiguous=_first_option if auto_select else None)
        timings["views"] = round(time.time() - t, 2)

    out.update(analysis=analysis, views=vs, records=vs.get("records") or [])
    out["notes"] += [f"[{u['unit_id']}] {n}" for u in vs.get("units") or [] for n in u.get("notes") or []]
    if vs["status"] != "ok":
        out["status"] = vs["status"]
        return _finish(out, t0, save)
    t = time.time()
    if answer_mode == "modules":
        from backend.agent.modules import as_answer_result
        from backend.agent.qa import run_modules_with_qa      # QA: 모듈 사이마다 형식 검사·대응 (backend/agent/qa)
        out["modules"] = run_modules_with_qa(vs, draw=draw, max_rows=max_rows)
        qa = out["modules"]["qa"]
        if out["modules"].get("answer"):
            out["result"] = as_answer_result(out["modules"])
            if qa["message"]:                                  # 일부만 (예: 차트 없이 답변만)
                out["result"]["caveats"] = list(out["result"]["caveats"]) + [qa["message"]]
        else:                                                  # QA 중단 · 모듈 6 실패 → 멈춘 단계를 답변 칸에
            out["result"] = {**OUT_OF_SCOPE_RESULT, "answer": qa["message"] or "답변을 만들지 못했습니다.",
                             "caveats": []}
        if missing := _missing_notes(vs):
            out["result"]["caveats"] = list(dict.fromkeys(missing + out["result"]["caveats"]))
        out["notes"] += out["modules"]["notes"]
    else:
        out["result"] = _answer(question, analysis, vs, max_rows)
    timings["answer"] = round(time.time() - t, 2)
    out["status"] = "ok"
    return _finish(out, t0, save)


def _finish(out, t0, save):
    out["timings"]["total"] = round(time.time() - t0, 2)
    if save:
        ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
        p = ANSWERS_DIR / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_chat.json")
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        out["saved"] = str(p)
    return out
