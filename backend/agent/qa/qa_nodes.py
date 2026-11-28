"""QA 그래프 노드 · 분기 (qa_graph.py 가 이어 붙인다)

  노드는 state 를 읽고 바뀐 키만 돌려준다. 모듈은 실행 노드(module2 · module3 · module6)에서 부르고,
  검사 노드(check_*)가 결과를 보고 routes[지점] 에 다음 갈 곳을 적는다 → 분기 함수(route_*)가 읽는다.

  검사 노드의 판단 (judge)
    통과            → ok (보정이 있었으면 보정한 값)
    틀림 · 재시도 남음 → retry (실행 노드로 돌아감, LLM 모듈만 1번)
    틀림 · 재시도 끝   → 그 항목만 뺄 수 있으면 partial, 아니면 fail (stop · skip)
  run_modules 와 같은 순서 · 같은 공개 함수를 부른다 (backend/agent/modules.py 는 고치지 않는다).
"""
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from .qa_check import ERROR, INFO, WARNING, Issue, check, drop_items, path_str
from .qa_policy import MAX_RETRY, NO_DATA_MESSAGE, RETRY_NOTES, RULES, chart_dropped_message, no_indicator_message
from .qa_schemas import draw_result_raw
from .qa_semantic import meaning_issues, unanswerable
from .qa_state import QAState, mark, summarize

M2, M3, M6 = "M2-out", "M3-out", "M6-out"


# ── 공통 ────────────────────────────────────────────────────────
def mods_of(mods: dict | None) -> dict:
    """모듈 실행 함수. 시험에서는 config['configurable']['mods'] 로 바꿔 끼운다"""
    from backend.agent.answer_compose.pipeline import run_module6
    from backend.agent.chart_calculate.pipeline import run_module3
    from backend.agent.chart_decision import run_chart_decision
    from backend.agent.draw_chart import run_module5
    out = {"chart_decision": run_chart_decision, "module3": run_module3, "module5": run_module5, "module6": run_module6}
    out.update(mods or {})
    return out


def _cfg(config: RunnableConfig | None):
    c = (config or {}).get("configurable") or {}
    return c.get("chat"), mods_of(c.get("mods"))


def dump(m):
    # warnings=False: 타입이 틀린 값을 직렬화할 때 pydantic 이 내는 경고는 끈다 — 그 값은 바로 뒤 check 가 잡는다
    return m.model_dump(mode="json", by_alias=True, warnings=False)


def exc_issue(point, e) -> Issue:
    return Issue(point, "", "exception", ERROR, f"모듈 실행 실패: {e.__class__.__name__}: {str(e)[:200]}")


def note_hits(m3, patterns) -> list[str]:
    """모듈 3 출력의 메모(chart_plan.notes · calc_results[].note) 중 patterns 가 들어 있는 것"""
    notes = list(getattr(getattr(m3, "chart_plan", None), "notes", None) or [])
    notes += [c.note for c in getattr(m3, "calc_results", None) or [] if getattr(c, "note", None)]
    return [n for n in notes if any(p in n for p in patterns)]


def _add(upd: dict, **lists) -> dict:
    """upd 의 목록 키에 이어 붙인다 (같은 노드가 issues 를 여러 번 만들 때)"""
    for k, v in lists.items():
        upd[k] = list(upd.get(k) or []) + list(v or [])
    return upd


def _run(state: QAState, point: str, fn) -> dict:
    """모듈을 한 번 실행 → outs · excs · tries 갱신 (예외는 잡아서 검사 노드가 판단)"""
    n = (state.get("tries") or {}).get(point, 0) + 1
    try:
        return {"outs": {point: fn()}, "excs": {point: None}, "tries": {point: n}}
    except Exception as e:  # noqa: BLE001
        return {"outs": {point: None}, "excs": {point: e}, "tries": {point: n}}


def judge(state: QAState, point: str, to_raw, rebuild, can_retry: bool, value=None, ctx: dict | None = None) -> tuple[dict, Any]:
    """검사 → (state 갱신, 다음에 넘길 값). routes[point] = ok | partial | retry | fail
    value 를 주면 실행 노드 없이 그 값을 검사한다 (입력 검사 · 재시도 없음). ctx = id 짝 참조 목록 (qa_rules)"""
    rule = RULES[point]
    n = (state.get("tries") or {}).get(point, 1)
    last = n >= 1 + (MAX_RETRY if (rule.retry and can_retry) else 0)
    why = (state.get("pending") or {}).get(point)
    upd: dict = {"checked": [point]} if n == 1 else {}

    def close(result):
        if why:
            _add(upd, retries=[{"point": point, "why": why, "result": result}])
            upd["pending"] = {point: None}

    fail_action = "stop" if rule.on_fail == "stop" else "skip"
    exc = None if value is not None else (state.get("excs") or {}).get(point)
    if exc is not None:
        if not last:
            _add(upd, issues=mark([exc_issue(point, exc)], "retry"))
            return {**upd, "pending": {point: "exception"}, "routes": {point: "retry"}}, None
        close("failed")
        _add(upd, issues=mark([exc_issue(point, exc)], fail_action))
        return {**upd, "routes": {point: "fail"}}, None
    out = value if value is not None else (state.get("outs") or {}).get(point)
    raw = to_raw(out)
    c = check(point, raw, ctx)
    if c.ok:
        close("passed")
        _add(upd, issues=mark(c.issues))
        return {**upd, "routes": {point: "ok"}}, (rebuild(c.value) if c.changed else out)
    if not last:
        _add(upd, issues=mark(c.issues, "retry"))
        return {**upd, "pending": {point: "schema"}, "routes": {point: "retry"}}, None
    close("failed")
    d = drop_items(raw, c.error_locs, rule.drop) if rule.drop else None
    if d is not None:
        c2 = check(point, d[0], ctx)
        if c2.ok:
            _add(upd, issues=mark(c.issues, "drop") + mark(c2.issues),
                 dropped=[{"point": point, "path": p} for p in d[1]])
            return {**upd, "routes": {point: "partial"}}, rebuild(c2.value)
    _add(upd, issues=mark(c.issues, fail_action))
    return {**upd, "routes": {point: "fail"}}, None


def _stage2_charts(m3) -> set[str]:
    """[NEW 11-27] 모듈 3 이 모듈 2 계획 밖에서 만든 차트 id — 2차 결과 차트(options.stage2) · [NEW 11-28] 비중 차트의 수치 차트
    (options.source_of). 정상이라 chart_ids 에 더한다"""
    contents = (m3.get("chart_contents") if isinstance(m3, dict) else getattr(m3, "chart_contents", None)) or []
    out = set()
    for c in contents:
        opt, cid = (c.get("options"), c.get("chart_id")) if isinstance(c, dict) else (c.options, c.chart_id)
        if (opt or {}).get("stage2") or (opt or {}).get("source_of"):
            out.add(cid)
    return out


def ref_ctx(state: QAState, point: str) -> dict:
    """id 짝을 볼 참조 목록 (qa_rules.rule_issues 의 ctx)"""
    if point == M2:
        vi = state.get("view_input") or {}
        return {"view_ids": {v["record"]["id"] for u in vi.get("units") or [] for v in u.get("views") or []}}
    if point == "M3-in":
        from backend.agent.chart_calculate.planner import sub_question_ids
        return {"record_ids": {r.id for r in state.get("records") or []},
                "sub_ids": {sid for sid, _ in sub_question_ids(state["bundle"])},
                "role_unit_ids": set(state.get("role_unit_ids") or [])}
    if point == M3:
        from backend.agent.chart_calculate.planner import sub_question_ids
        req3 = state["req3"]
        m3 = (state.get("outs") or {}).get(M3) or state.get("m3")
        return {"chart_ids": {c.chart_id for c in req3.charts} | _stage2_charts(m3), "record_ids": {r.id for r in req3.records},
                "sub_ids": {sid for sid, _ in sub_question_ids(req3.query_bundle)}}
    if point == "M5-out":
        m3, plan = state["m3"], state.get("plan") or {}
        return {"drawn_ids": {c.chart_id for c in m3.chart_contents} | {c.get("chart_id") for c in plan.get("charts") or []}
                | {o.get("overlay_id") for o in plan.get("overlays") or []}}
    if point == "M6-in":
        from backend.agent.chart_calculate.planner import sub_question_ids
        return {"record_ids": {r.id for r in state.get("records") or []},
                "sub_ids": {sid for sid, _ in sub_question_ids(state["bundle"])},
                "chart_ids": {c.chart_id for c in state["req3"].charts} | _stage2_charts(state.get("m3")),
                "role_unit_ids": set(state.get("role_unit_ids") or [])}
    if point == M6:
        req6 = state["req6"]
        # withheld_ids: 모듈 6 이 보류 사유 caveat 의 ref 로 쓰는 범위 (하위 질문 ID · 차트 ID, KOS-38)
        return {"record_ids": {r.id for r in req6.records}, "step_ids": {c.step_id for c in req6.calc_results},
                "withheld_ids": {x for w in req6.withheld for x in (w.sub_question_id, w.chart_id) if x}}
    return {}


def _route(state: QAState, point: str) -> str:
    return (state.get("routes") or {}).get(point, "fail")


def _dropped_request(point: str, chart, index: int) -> dict | None:
    """뺀 차트가 사용자가 지정한 차트(request 있음)면 안내용 기록. 틀린 값 때문에 빠졌을 수 있어 모양을 믿지 않는다"""
    c = dump(chart) if hasattr(chart, "model_dump") else chart
    if not isinstance(c, dict) or not c.get("request"):
        return None
    req = c["request"]
    names = req.get("preferred") if isinstance(req, dict) else None
    name = next((n["text"] for n in names if isinstance(n, dict) and n.get("text")), None) if isinstance(names, list) else None
    return {"point": point, "chart_id": str(c.get("chart_id") or f"?{index}"), "name": name}


def requested_drops(point: str, prefix: str, items: list, dropped: list | None) -> list[dict]:
    """dropped 의 경로(예: charts[1]) 중 prefix 목록의 원소를 찾아 사용자가 지정한 차트만 고른다"""
    out = []
    for d in dropped or []:
        path = d.get("path", "")
        if not (path.startswith(f"{prefix}[") and path.endswith("]")):
            continue
        i = int(path[len(prefix) + 1:-1])
        if i < len(items) and (r := _dropped_request(point, items[i], i)):
            out.append(r)
    return out


# ── A0 · M2-in ─────────────────────────────────────────────────
def check_input(state: QAState) -> dict:
    """A0 에이전트 입력: ViewSet + view_bundle(QueryBundle). status 가 ok 가 아니면 중단
    형식 오류가 아닌 중단: records 가 비어 있음(no_data) · 사전에도 표에도 없는 지표(indicator_not_found) → 알맞은 안내 문구로 끝낸다"""
    vs = state.get("viewset")
    upd, val = judge(state, "A0", lambda v: {"viewset": v, "view_bundle": (v or {}).get("view_bundle")},
                     lambda c: {**c["viewset"], "view_bundle": c["view_bundle"]}, False, value=vs or {})
    if upd["routes"]["A0"] != "ok":
        errors = [i for i in upd.get("issues") or [] if i.severity == ERROR]
        if len(errors) == 1 and errors[0].path == "viewset.records" and errors[0].kind == "empty":
            errors[0].kind, errors[0].message = "no_data", NO_DATA_MESSAGE
            return {**upd, "stopped_at": "A0", "stop_note": NO_DATA_MESSAGE}
        return {**upd, "stopped_at": "A0"}
    if val.get("status") != "ok":
        _add(upd, issues=mark([Issue("A0", "viewset.status", "enum", ERROR,
                                     f"status 가 ok 가 아님 ({val.get('status')}) — 되묻기·선택은 Retriever 에서 먼저 끝내야 함",
                                     repr(val.get("status")))], "stop"))
        return {**upd, "routes": {"A0": "fail"}, "stopped_at": "A0"}
    if names := unanswerable(val, state.get("analysis_notes")):
        msg = no_indicator_message(names)
        _add(upd, issues=[Issue("A0", "viewset.units", "indicator_not_found", INFO, msg, ", ".join(names), action="stop")])
        return {**upd, "routes": {"A0": "fail"}, "stopped_at": "A0", "stop_note": msg}
    return {**upd, "viewset": val}


def prepare_m2(state: QAState) -> dict:
    """ViewSet → 모듈 2 입력 (run_modules 와 같은 변환: view_input_of · split_roles_linked) + M2-in 검사
    role_links: 질문에서 뺀 역할 단위(분모·조건)가 어느 본 질문을 지원하는지 — 모듈 3 · 6 에 그대로 넘긴다 (KOS-26)"""
    from backend.agent.modules import split_roles_linked, view_input_of
    from backend.schemas.query import QueryBundle
    vs = state["viewset"]
    vb = dict(vs.get("view_bundle") or {})
    vb.setdefault("query_id", vs.get("query_id"))
    vb.setdefault("original", vs.get("original") or "")
    all_sub_ids = {f"{vb.get('query_id')}-{i}" for i in range(1, len(vb.get("sub_questions") or []) + 1)}
    vb, view_input, role_views, role_links = split_roles_linked(vb, view_input_of(vs))
    kept_sub_ids = {f"{vb.get('query_id')}-{i}" for i in range(1, len(vb.get("sub_questions") or []) + 1)}
    upd, val = judge(state, "M2-in", lambda v: v, lambda v: v, False, value={"query_bundle": vb, "view_input": view_input})
    if upd["routes"]["M2-in"] != "ok":
        return {**upd, "stopped_at": "M2-in"}
    return {**upd, "bundle": QueryBundle.model_validate(val["query_bundle"]), "view_input": val["view_input"],
            "role_views": role_views, "role_links": role_links, "role_unit_ids": sorted(all_sub_ids - kept_sub_ids)}


# ── 모듈 2 ──────────────────────────────────────────────────────
def module2(state: QAState, config: RunnableConfig) -> dict:
    _, m = _cfg(config)
    return _run(state, M2, lambda: m["chart_decision"](state["bundle"].model_dump(mode="json", by_alias=True),
                                                        state["view_input"], use_llm=state.get("use_llm_chart", True)))


def check_m2(state: QAState) -> dict:
    upd, val = judge(state, M2, lambda o: {"chart_plan": o.get("chart_plan"), "filtered_views": o.get("filtered_views"),
                                           "errors": o.get("errors") or []},
                     lambda v: v, can_retry=state.get("use_llm_chart", True), ctx=ref_ctx(state, M2))
    route = upd["routes"][M2]
    if route == "fail":
        return {**upd, "stopped_at": M2}
    if route in ("ok", "partial"):
        upd.update(out2=val, plan=val.get("chart_plan"))
    if route == "partial":                  # 뺀 차트의 request 는 원래 출력에만 남아 있다
        raw = (state.get("outs") or {}).get(M2) or {}
        items = (raw.get("chart_plan") or {}).get("charts") or []
        _add(upd, dropped_requests=requested_drops(M2, "chart_plan.charts", items, upd.get("dropped")))
    return upd


# ── 어댑터 · M3-in ──────────────────────────────────────────────
def adapt(state: QAState) -> dict:
    """모듈 2 출력 → Module3Request (decide_charts · run_modules 와 같은 순서) + M3-in 검사 (차트 하나씩 뺄 수 있음)"""
    from backend.agent.chart_calculate.from_module2 import records_of, skipped_sets, to_chart_request, unknown_view_ids
    from backend.agent.chart_calculate.planner import sub_question_ids
    from backend.schemas.chart import Module3Request
    from backend.schemas.record import Record

    bundle, view_input, out2, plan = state["bundle"], state["view_input"], state["out2"], state.get("plan")
    upd: dict = {}
    errors = list(out2["errors"] or [])
    if view_input.get("query_id") and bundle.query_id != view_input.get("query_id"):
        errors.append({"reason": f"QueryBundle.query_id({bundle.query_id}) 와 View 의 query_id"
                                 f"({view_input.get('query_id')}) 가 달라 모듈 3 이 하위 질문을 찾지 못할 수 있음"})
    main_id = None if bundle.sub_questions else sub_question_ids(bundle)[0][0]
    charts = []
    for i, c in enumerate((plan or {}).get("charts") or []):
        try:
            charts.append(to_chart_request(c, main_id))
        except (ValidationError, KeyError, TypeError) as e:     # 차트 하나가 틀리면 그 차트만 뺀다 (M3-in)
            _add(upd, issues=mark([Issue("M3-in", f"charts[{i}]", "type", ERROR,
                                         f"모듈 3 입력으로 바꾸지 못함: {e.__class__.__name__}: {str(e)[:150]}")], "drop"),
                 dropped=[{"point": "M3-in", "path": f"charts[{i}]"}])
            if r := _dropped_request("M3-in", c, i):
                _add(upd, dropped_requests=[r])
    records = records_of(view_input)
    errors += unknown_view_ids(charts, records)
    charts += skipped_sets(out2["errors"], bundle, charts, view_input)
    role_views = state.get("role_views") or []
    if role_views:
        have = {r.id for r in records}
        extra_ids = [v["record"]["id"] for v in role_views]
        records += [Record.model_validate(v["record"]) for v in role_views if v["record"]["id"] not in have]
        for c in charts:
            if c.view_ids:
                c.view_ids = list(dict.fromkeys([*c.view_ids, *extra_ids]))
        _add(upd, notes=[f"역할 단위(분모·조건)의 View 를 세트에 붙임: {extra_ids}"])
    upd.update(charts=charts, records=records, chart_errors=errors, charts_dump=[c.model_dump(mode="json") for c in charts])
    req3 = Module3Request.model_construct(records=records, query_bundle=bundle, charts=charts,
                                          role_links=state.get("role_links") or [])
    j, val = judge(state, "M3-in", dump, Module3Request.model_validate, False, value=req3,
                   ctx=ref_ctx({**state, "records": records}, "M3-in"))
    dropped_now = j.pop("dropped", [])
    _add(upd, issues=j.pop("issues", []), dropped=dropped_now, checked=j.pop("checked", []))
    upd.update(j)
    route = j["routes"]["M3-in"]
    if route == "fail":
        return {**upd, "stopped_at": "M3-in"}
    if route == "partial":
        _add(upd, dropped_requests=requested_drops("M3-in", "charts", charts, dropped_now))
        upd["charts_dump"] = [c.model_dump(mode="json") for c in val.charts]
        upd["role_links"] = list(val.role_links)       # 뺀 role_links 가 모듈 6 으로 넘어가지 않게
    return {**upd, "req3": val}


# ── 모듈 3 (+ 메모 재시도) ───────────────────────────────────────
def module3(state: QAState, config: RunnableConfig) -> dict:
    chat, m = _cfg(config)
    return _run(state, M3, lambda: m["module3"](state["req3"], decision=state.get("decision"), chat=chat))


def check_m3(state: QAState) -> dict:
    from backend.schemas.chart import Module3Output
    if state.get("note_mode"):                      # 메모 재시도의 결과 → 처음 결과와 견준다
        return _note_compare(state)
    upd, val = judge(state, M3, dump, Module3Output.model_validate, can_retry=state.get("decision") is None,
                     ctx=ref_ctx(state, M3))
    route = upd["routes"][M3]
    if route == "fail":
        return {**upd, "stopped_at": M3}
    if route in ("ok", "partial"):
        upd["m3"] = val
    return upd


def check_notes(state: QAState) -> dict:
    """[형식 밖 예외] 형식은 맞지만 메모에 RETRY_NOTES 문구('열 없음' · 'HCX 호출 실패')가 있으면 모듈 3 을 1번 다시.
    형식 오류로 이미 재시도했거나(합쳐 MAX_RETRY 번) decision 고정 실행이면 경고만"""
    if state.get("note_mode"):                      # 재시도 결과는 check_m3 가 이미 골랐다
        return {"routes": {"notes": "ok"}}
    pats = RETRY_NOTES.get(M3) or ()
    m3 = state["m3"]
    hits = note_hits(m3, pats)
    if not hits:
        return {"routes": {"notes": "ok"}}
    why = next(p for p in pats if any(p in h for h in hits))
    issue = Issue(M3, "chart_plan.notes", "note", WARNING,
                  f"모듈 메모 '{why}': {hits[0][:150]}" + (f" 외 {len(hits) - 1}건" if len(hits) > 1 else ""))
    used = (state.get("tries") or {}).get(M3, 1) - 1          # 이미 한 재시도 수
    if state.get("decision") is not None or used >= MAX_RETRY:
        issue.action = "warn"
        return {"issues": [issue], "routes": {"notes": "ok"}}
    issue.action = "retry"
    return {"issues": [issue], "routes": {"notes": "retry"}, "note_mode": True, "m3_first": m3,
            "note_hits": hits, "note_why": why}


def _note_compare(state: QAState) -> dict:
    """메모 재시도 결과 → 메모가 적은 쪽을 m3 로 (같으면 처음 결과). 재시도가 터지거나 형식이 틀리면 처음 결과"""
    from backend.schemas.chart import Module3Output
    first, hits = state["m3_first"], state.get("note_hits") or []
    rec = {"point": M3, "why": f"note: {state.get('note_why')}"}
    upd: dict = {"routes": {M3: "ok"}}
    exc = (state.get("excs") or {}).get(M3)
    if exc is not None:
        return {**upd, "issues": mark([exc_issue(M3, exc)], "warn"), "m3": first,
                "retries": [{**rec, "result": "failed", "kept": "first"}]}
    out = (state.get("outs") or {}).get(M3)
    c = check(M3, dump(out), ref_ctx(state, M3))
    if not c.ok:
        for i in c.issues:
            i.action = i.action or "warn"
        return {**upd, "issues": c.issues, "m3": first, "retries": [{**rec, "result": "failed", "kept": "first"}]}
    new = Module3Output.model_validate(c.value) if c.changed else out
    hits2 = note_hits(new, RETRY_NOTES.get(M3) or ())
    kept = "retry" if len(hits2) < len(hits) else "first"
    return {**upd, "issues": mark(c.issues), "m3": new if kept == "retry" else first,
            "retries": [{**rec, "result": "passed" if not hits2 else "failed", "kept": kept}]}


# ── 모듈 5 (병렬 갈래 1) ─────────────────────────────────────────
def draw(state: QAState, config: RunnableConfig) -> dict:
    """modules._draw 와 같은 결과 (drawn[]) + M5-out 검사. 틀린 차트는 failed 로, 전체가 틀리면 차트 없이 (답변은 계속)"""
    from backend.agent.modules import _figure_json
    m3 = state["m3"]
    if not (state.get("draw", True) and m3.chart_contents):
        return {"drawn": []}
    _, m = _cfg(config)
    plan = state.get("plan")
    try:
        out = m["module5"](chart_plan=plan or {"query_id": m3.query_id, "charts": []}, module3_output=m3, save=False)
    except Exception as e:  # noqa: BLE001  (그림이 실패해도 답변은 낸다 — modules._draw 와 같은 메모)
        return {"drawn": [], "notes": [f"모듈 5 실패: {e.__class__.__name__}: {str(e)[:200]}"], "checked": ["M5-out"],
                "issues": mark([exc_issue("M5-out", e)], "skip"), "skipped": ["M5-out"],
                "render_error": f"{e.__class__.__name__}: {str(e)[:200]}"}
    results = list(out.get("results") or [])
    raw = {"results": [draw_result_raw(r) for r in results], "html": out.get("html"),
           "load_errors": out.get("load_errors") or {}}
    upd: dict = {"checked": ["M5-out"]}
    c = check("M5-out", raw, ref_ctx(state, "M5-out"))
    bad: set[int] = set()
    if not c.ok:
        d = drop_items(raw, c.error_locs, RULES["M5-out"].drop)
        if d is None or not check("M5-out", d[0], ref_ctx(state, "M5-out")).ok:
            return {**upd, "drawn": [], "issues": mark(c.issues, "skip"), "skipped": ["M5-out"], "render_rejected": True}
        bad = {loc[1] for loc in c.error_locs}
        upd.update(issues=mark(c.issues, "drop"),
                   dropped=[{"point": "M5-out", "path": path_str(("results", i)), "as": "failed"} for i in sorted(bad)])
    else:
        upd["issues"] = mark(c.issues)
    drawn = []
    for i, r in enumerate(results):
        if i in bad:
            drawn.append({"chart_id": str(getattr(r, "chart_id", f"?{i}")), "chart_type": None, "status": "failed",
                          "title": None, "reason": "QA: 모듈 5 출력 형식 오류", "warnings": [], "merged_from": [],
                          "figure": None})
            continue
        drawn.append({"chart_id": r.chart_id, "chart_type": r.chart_type, "status": r.status, "title": r.title,
                      "reason": r.reason, "warnings": list(r.warnings), "merged_from": list(r.merged_from),
                      "figure": _figure_json(r.figure)})
    return {**upd, "drawn": drawn}


# ── 모듈 6 (병렬 갈래 2) ─────────────────────────────────────────
def build_m6(state: QAState) -> dict:
    """모듈 3 출력 → Module6Request (run_modules 와 같은 값) + M6-in 검사. 틀리면 답변 없이 (차트는 계속)"""
    from backend.schemas.answer import Module6Request
    m3 = state["m3"]
    try:
        req6 = Module6Request(query_bundle=state["bundle"], records=state["records"], calc_results=m3.calc_results,
                              displays=m3.displays, answer_steps=m3.chart_plan.answer_steps,
                              plan_warnings=m3.chart_plan.warnings, withheld=m3.chart_plan.withheld,
                              role_links=state.get("role_links") or [], max_rows=state.get("max_rows", 50))
    except Exception as e:  # noqa: BLE001
        return {"checked": ["M6-in"], "issues": mark([exc_issue("M6-in", e)], "skip"), "skipped": ["M6-in"],
                "routes": {"M6-in": "fail"}}
    upd, val = judge(state, "M6-in", dump, Module6Request.model_validate, False, value=req6,
                     ctx=ref_ctx(state, "M6-in"))
    if upd["routes"]["M6-in"] == "fail":
        return {**upd, "skipped": ["M6-in"]}
    return {**upd, "req6": val}


def module6(state: QAState, config: RunnableConfig) -> dict:
    chat, m = _cfg(config)
    return _run(state, M6, lambda: m["module6"](state["req6"], chat=chat))


def check_m6(state: QAState) -> dict:
    from backend.schemas.answer import Module6Output
    upd, val = judge(state, M6, dump, Module6Output.model_validate, can_retry=True, ctx=ref_ctx(state, M6))
    route = upd["routes"][M6]
    if route == "fail":
        return {**upd, "skipped": [M6]}
    if route in ("ok", "partial"):
        upd["m6"] = val
    return upd


# ── 마무리 ──────────────────────────────────────────────────────
def chart_status(state: QAState, m3, drawn: list, stopped: str | None) -> tuple[dict, list[Issue]]:
    """KOS-41 차트 요청의 최종 결과 + QA 가 뺀 요청 차트의 안내. 여기서 실패해도 답변은 그대로 나간다
    charts_dump 를 쓴다: state 의 charts 에는 M3-in 에서 뺀 차트가 남아 있어 응답의 charts 와 달라진다
    QA 가 중단하면 중단 메시지가 이미 나가므로 뺀 차트의 안내를 더하지 않는다"""
    from backend.schemas.chart import ChartRequestOutcome, RenderState
    issues: list[Issue] = []
    try:
        from backend.agent.chart_notice import finalize_chart_request
        out = finalize_chart_request(state.get("charts_dump") or [], m3, drawn, draw=state.get("draw", True),
                                     error=state.get("render_error"), stopped=bool(stopped),
                                     rejected=bool(state.get("render_rejected")))
    except Exception as e:  # noqa: BLE001
        out = {"render_status": {}, "request_outcomes": [], "chart_notices": []}
        issues = mark([Issue("A9", "chart_status", "exception", ERROR,
                             f"차트 요청 결과 확정 실패: {e.__class__.__name__}: {str(e)[:200]}")], "warn")
    if stopped:
        return out, issues
    have = {o["chart_id"] for o in out["request_outcomes"]}
    for d in state.get("dropped_requests") or []:
        cid = d["chart_id"]
        if cid in have:
            continue
        have.add(cid)
        out["render_status"].setdefault(cid, RenderState(state="skipped", reason="no_chart_content").model_dump(mode="json"))
        out["request_outcomes"].append(ChartRequestOutcome(chart_id=cid, outcome="table_only",
                                                           reason="validation_failed").model_dump(mode="json"))
        out["chart_notices"] = list(dict.fromkeys([*out["chart_notices"], chart_dropped_message(d.get("name"))]))
    return out, issues


def finalize(state: QAState) -> dict:
    """run_modules 와 같은 11개 키 + qa. 중단하지 않았으면 A9(최종 결과) 검사 (경고만)"""
    m3, m6 = state.get("m3"), state.get("m6")
    result = {"charts": state.get("charts_dump") or [], "chart_errors": state.get("chart_errors") or [],
              "chart_plan": state.get("plan"), "records": [r.model_dump(mode="json") for r in state.get("records") or []],
              "module3": m3.model_dump(mode="json") if m3 is not None else None, "drawn": state.get("drawn") or [],
              "answer": m6.model_dump(mode="json") if m6 is not None else None, "notes": list(state.get("notes") or [])}
    issues, checked = list(state.get("issues") or []), list(state.get("checked") or [])
    stopped = state.get("stopped_at")
    status, status_issues = chart_status(state, m3, result["drawn"], stopped)
    result.update(status)
    issues += status_issues
    if not stopped:
        c = check("A9", result)
        checked.append("A9")
        issues += mark(c.issues, "warn") if not c.ok else mark(c.issues)
    # 내용 경고: 최종 결과를 읽기만 한다 (대응 없음)
    issues += mark(meaning_issues(m3, m6, state.get("bundle"), result["charts"], result["drawn"]))
    result["qa"] = summarize(issues, state.get("retries") or [], state.get("dropped") or [],
                             state.get("skipped") or [], checked, stopped, state.get("stop_note"))
    return {"result": result}


# ── 분기 ────────────────────────────────────────────────────────
def route_input(state: QAState) -> str:
    return "finalize" if state.get("stopped_at") else "prepare_m2"


def route_prepare(state: QAState) -> str:
    return "finalize" if state.get("stopped_at") else "module2"


def route_m2(state: QAState) -> str:
    return {"retry": "module2", "fail": "finalize"}.get(_route(state, M2), "adapt")


def route_adapt(state: QAState) -> str:
    return "finalize" if state.get("stopped_at") else "module3"


def route_m3(state: QAState) -> str:
    return {"retry": "module3", "fail": "finalize"}.get(_route(state, M3), "check_notes")


def route_notes(state: QAState):
    """메모 재시도면 모듈 3 으로, 아니면 모듈 5 · 6 을 동시에 (서로를 읽지 않는다)"""
    return "module3" if _route(state, "notes") == "retry" else ["draw", "answer"]


# 모듈 6 갈래 서브그래프 안의 분기 (END = 갈래 끝 → 부모의 finalize 에서 모듈 5 갈래와 만난다)
def route_build_m6(state) -> str:
    return "end" if _route(state, "M6-in") == "fail" else "module6"


def route_m6(state) -> str:
    return "module6" if _route(state, M6) == "retry" else "end"
