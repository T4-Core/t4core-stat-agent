"""차트 지정 요청 (KOS-41): Request Parse · Outcome · Notice 정합 · 요청 오인식"""
from backend.schemas.chart import OUTCOME_REASONS
from eval.generator import trace
from eval.generator.findings import Finding
from eval.generator.schema import Question

RENDER_OUTCOME = {"draw_disabled": ("not_rendered", "draw_disabled"), "qa_stopped": ("not_rendered", "qa_stopped"),
                  "exception": ("render_failed", "render_error"), "render_error": ("render_failed", "render_error")}


def _names(xs) -> list[str]:
    return [(x.get("code") or x.get("text")) if isinstance(x, dict) else (x.code or x.text) for x in xs or []]


def check(q: Question, run: dict) -> list[Finding]:
    mods = trace.mods(run)
    charts = mods.get("charts") or []
    reqs = [c for c in charts if c.get("request")]
    out: list[Finding] = []
    if "request_outcomes" not in mods:            # 11-20 이전 trace
        return out
    if q.chart_request is None:
        out.append(Finding("request_misparse", "metric", "M2", not reqs, f"요청 없는 질문에 요청 {len(reqs)}건",
                           detail={"requests": [c["request"] for c in reqs]}))
        notices = mods.get("chart_notices") or []
        out.append(Finding("notice", "metric", "E2E", not notices, "; ".join(notices)))
        return out
    spec = q.chart_request
    if not reqs:
        out.append(Finding("request_parse", "metric", "M2", False, "요청을 해석하지 못함"))
        return out
    pref = [n for c in reqs for n in _names(c["request"].get("preferred"))]
    excl = [n for c in reqs for n in _names(c["request"].get("excluded"))]
    want_p, want_e = _names([p.model_dump() for p in spec.preferred]), _names([e.model_dump() for e in spec.excluded])
    out.append(Finding("request_parse", "metric", "M2", set(want_p) <= set(pref) and set(want_e) <= set(excl),
                       f"preferred {pref} / 기대 {want_p}, excluded {excl} / 기대 {want_e}"))
    states = mods.get("render_status") or {}
    req_ids = {c["chart_id"] for c in reqs}
    for o in mods.get("request_outcomes") or []:
        if o.get("chart_id") not in req_ids:
            continue
        allowed = OUTCOME_REASONS.get(o.get("outcome"), ())
        out.append(Finding("outcome_combo", "metric", "E2E", o.get("reason") in allowed,
                           f"{o.get('outcome')}/{o.get('reason')}", detail=o))
        exp = spec.expected_outcome
        st = states.get(o["chart_id"]) or {}
        want = (exp.outcome, exp.reason)
        if st.get("state") in ("failed", "skipped") and st.get("reason") in RENDER_OUTCOME:
            want = RENDER_OUTCOME[st["reason"]]          # 렌더링 단계 결과는 실행 조건으로 정해진다
        ok = o.get("outcome") == want[0] and (want[1] is None or o.get("reason") == want[1]) and \
            (exp.final_chart is None or want[0] != exp.outcome or o.get("final_chart") == exp.final_chart)
        out.append(Finding("request_outcome", "metric", "E2E", ok, f"{o.get('outcome')}/{o.get('reason')}/{o.get('final_chart')} "
                           f"/ 기대 {want[0]}/{want[1]}/{exp.final_chart}", detail={"chart_id": o["chart_id"]}))
        if o.get("final_chart") in want_e:
            out.append(Finding("excluded_used", "stage1", "M2", False, f"제외한 {o.get('final_chart')} 로 그림"))
    notices = mods.get("chart_notices") or []
    need = spec.notice_required and spec.expected_outcome.outcome != "honored"
    out.append(Finding("notice", "metric", "E2E", bool(notices) == bool(need) or (need and bool(notices)),
                       "; ".join(notices) or "(안내 없음)"))
    return out
