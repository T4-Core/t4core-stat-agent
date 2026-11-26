"""차트 지정 요청 (KOS-41): Request Parse · Outcome · Notice 정합 · 요청 오인식"""
from backend.schemas.chart import OUTCOME_REASONS
from eval.generator import trace
from eval.generator.binding import region_key
from eval.generator.claim import period_key
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
        st = states.get(o["chart_id"]) or {}
        # [CHANGED] 이전: expected_outcome 하나. allowed_outcomes 가 있으면 그중 하나와 맞으면 통과 (부분 차트 또는 표만)
        wants = [(e.outcome, e.reason, e.final_chart) for e in (spec.allowed_outcomes or [spec.expected_outcome])]
        if st.get("state") in ("failed", "skipped") and st.get("reason") in RENDER_OUTCOME:
            wants = [(*RENDER_OUTCOME[st["reason"]], None)]          # 렌더링 단계 결과는 실행 조건으로 정해진다
        ok = any(o.get("outcome") == w[0] and (w[1] is None or o.get("reason") == w[1]) and (w[2] is None or o.get("final_chart") == w[2])
                 for w in wants)
        out.append(Finding("request_outcome", "metric", "E2E", ok, f"{o.get('outcome')}/{o.get('reason')}/{o.get('final_chart')} "
                           f"/ 기대 {' | '.join(f'{w[0]}/{w[1]}/{w[2]}' for w in wants)}", detail={"chart_id": o["chart_id"]}))
        if o.get("final_chart") in want_e:
            out.append(Finding("excluded_used", "stage1", "M2", False, f"제외한 {o.get('final_chart')} 로 그림"))
    notices = mods.get("chart_notices") or []
    if spec.allowed_outcomes:                  # [NEW] 정답이 여럿이면 실제 결과로 정한다 (부분 차트로 honored 이면 안내 불필요)
        actual = [o.get("outcome") for o in mods.get("request_outcomes") or [] if o.get("chart_id") in req_ids]
        need = spec.notice_required and (not actual or any(x != "honored" for x in actual))
    else:
        need = spec.notice_required and spec.expected_outcome.outcome != "honored"
    out.append(Finding("notice", "metric", "E2E", bool(notices) == bool(need) or (need and bool(notices)),
                       "; ".join(notices) or "(안내 없음)"))
    return out


# ── [NEW] v2 required_chart.mode ─────────────────────────────────
def _final_types(run: dict) -> dict[str, str | None]:
    """chart_id → 최종 차트 유형 (module3.chart_contents). 내용이 없으면 None (표만)"""
    charts = trace.mods(run).get("charts") or []
    drawn = {c.get("chart_id"): c.get("chart_type") for c in trace.m3(run).get("chart_contents") or []}
    return {c.get("chart_id"): drawn.get(c.get("chart_id")) for c in charts}


def _key(v) -> str:
    t = str(v).strip()
    return period_key(t) or region_key(t) or t


def partial_chart(q: Question, run: dict) -> Finding:
    """[NEW] 부분 차트 허용 문항(partial_allowed): 확인된 점만 그렸는가
    기대 점은 expected_answer.points (원본 근거가 있는 점). 그린 행이 모두 그 점이어야 하고, 누락 대상(missing_target)은 없어야 한다.
    모듈 5 의 자체 검증과 무관하게 데이터셋의 점과 대조한다"""
    ans = (q.v2 or {}).get("expected_answer") or {}
    points = [(_key(p["label"]), float(p["value"])) for p in ans.get("points") or []]
    target = ans.get("missing_target")
    rows = [r for c in trace.m3(run).get("chart_contents") or [] for r in c.get("rows") or []]
    unmatched, hit_target = [], False
    for r in rows:
        cells = {_key(x) for x in r[:-1]}
        hit_target |= target is not None and _key(target) in cells
        val = r[-1] if isinstance(r[-1], (int, float)) else None
        if not any(k in cells and val is not None and abs(val - v) <= 1e-6 * max(1.0, abs(v)) for k, v in points):
            unmatched.append(r)
    if hit_target:
        return Finding("chart_mode", "metric", "M2", False, f"누락 대상 {target} 을 그림", detail={"partial": True})
    if unmatched:
        return Finding("chart_mode", "metric", "M2", False, f"원본 근거 점이 아닌 행 {len(unmatched)}개: {unmatched[:3]}", detail={"partial": True})
    return Finding("chart_mode", "metric", "M2", True, f"부분 차트: 확인된 점 {len(rows)}행만 그림 (누락 대상 {target})", detail={"partial": True})


def mode_check(q: Question, run: dict) -> list[Finding]:
    """v2 문항의 차트 요구 (required · forbidden · fallback · per_subquestion). optional 은 검사하지 않는다"""
    mode = q.chart_mode
    if mode in (None, "optional"):
        return []
    spec = (q.v2 or {}).get("required_chart") or {}
    final = _final_types(run)
    drawn = [t for t in final.values() if t]
    notices = trace.mods(run).get("chart_notices") or []
    out: list[Finding] = []
    if mode == "forbidden":
        partial = ((q.v2 or {}).get("chart_spec") or {}).get("partial_allowed")
        if drawn and partial is True:
            out.append(partial_chart(q, run))
        else:
            out.append(Finding("chart_mode", "metric", "M2", not drawn, f"차트 금지인데 {drawn}" if drawn else ""))
    elif mode == "required":
        ok = any(t in q.chart_types for t in drawn)
        out.append(Finding("chart_mode", "metric", "M2", ok, f"최종 {drawn or '없음'} / 허용 {q.chart_types}"))
        used = [t for t in drawn if t in (spec.get("excluded_types") or [])]
        if used:
            out.append(Finding("excluded_used", "stage1", "M2", False, f"제외한 {used} 로 그림"))
    elif mode == "fallback":
        ok = all(t in q.chart_types for t in final.values()) if final else None in q.chart_types
        out.append(Finding("chart_mode", "metric", "M2", ok, f"최종 {list(final.values()) or '없음'} / 허용 {q.chart_types}"))
        if q.chart_notice:
            out.append(Finding("notice", "metric", "E2E", bool(notices), "; ".join(notices) or "(안내 없음)"))
    elif mode == "per_subquestion":
        charts = trace.mods(run).get("charts") or []
        qid = trace.bundle(run).get("query_id") or ""
        for s in q.sub_questions:
            want = (spec.get("subquestions") or {}).get(s.key) or []
            sid = f"{qid}-{s.match_index}"
            got = [final.get(c.get("chart_id")) for c in charts if sid in (c.get("sub_question_ids") or [])]
            out.append(Finding("chart_mode", "metric", "M2", any(t in want for t in got), f"{s.key}: {got} / 허용 {want}", s.key))
    if "parts_sum_to_total" in (spec.get("requirements") or []):
        shares = [c for c in trace.m3(run).get("calc_results") or [] if c.get("op") == "share" and isinstance(c.get("value"), list)]
        for c in shares:
            total = sum(p.get("value") or 0 for p in c["value"] if isinstance(p, dict))
            out.append(Finding("share_denominator", "metric", "M3", abs(total - 100) < 0.05,
                               f"{c.get('step_id')} 구성비 합 {total:.2f}% (요청 범위 합계가 분모면 100)"))
    return out
