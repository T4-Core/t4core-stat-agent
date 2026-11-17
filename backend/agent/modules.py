"""
②의 ViewSet → 모듈 2 → 3 → 5 → 6 연결

  ViewSet (POST /api/v1/rag/views 응답 · /chat 의 views)
    ─▶ 모듈 2  chart_decision   하위 질문마다 차트 유형·measure (규칙 + 선택적 HCX)
    ─▶ 모듈 3  chart_calculate  계산 계획(HCX) → 계산 → 차트 내용 구성·검증
    ─▶ 모듈 5  draw_chart       차트 그림 (plotly, 선택)
    ─▶ 모듈 6  answer_compose   답변 문장(HCX) · 근거 표 · 주의사항

검색·View 쪽과 모듈 2·3 의 약속을 여기서 맞춘다 (모듈 코드는 건드리지 않음)
  · View 입력: 충돌 선택이 끝난 카드(ViewSet.records)만 남긴다. 모듈 2·3 은 단위마다 순위가 가장 높은 View 를 쓰므로,
    선택에서 빠진 표가 다시 쓰이지 않게 하고, 선택으로 다시 만든 카드는 그 단위의 View 로 넣는다.
  · 역할 단위(분모·조건, query_analyzer/roles.py): 검색을 위한 단위이지 따로 답할 질문이 아니다.
    모듈 2·3 에 넘기는 질문에서는 빼고, 그 단위의 View 는 다른 모든 세트(view_ids)에 붙인다.
    모듈 3 은 세트 밖 View 를 분모로 쓰면 비중 계산을 보류하므로, 붙이지 않으면 분모 표를 찾아 놓고도 쓰지 못한다.
"""
from typing import Any, Callable

from backend.schemas.chart import ChartRequest, Module3Output, Module3Request
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

ROLE_KEY = "역할"


def _role(f):
    return (f or {}).get(ROLE_KEY) if isinstance(f, dict) else None


def view_input_of(vs: dict[str, Any]) -> dict[str, Any]:
    """ViewSet → 모듈 2 입력 {query_id, original, units[].views[]}. records 가 있으면 선택된 카드만 남긴다"""
    keep = {r["id"]: r for r in vs.get("records") or []} if vs.get("records") is not None else None
    units = []
    for u in vs.get("units") or []:
        views = [dict(v) for v in u.get("views") or []]
        if keep is not None and "conflict" in u:            # ViewSet(충돌 판정 결과)일 때만 거른다
            have = {v["record"]["id"] for v in views}
            views = [v for v in views if v["record"]["id"] in keep]
            for rec in (u.get("selected") or {}).get("records") or []:   # 선택으로 다시 만든 카드
                if rec["id"] not in have and rec["id"] in keep:
                    rank = ((rec.get("match") or {}).get("rank")) or 99
                    views.append({"record": rec, "notes": [], "rank": rank,
                                  "tbl_id": (rec.get("source") or {}).get("tbl_id", "")})
        units.append({**{k: u.get(k) for k in ("unit_id", "query", "filters", "candidates", "notes")},
                      "candidates": u.get("candidates") or [], "notes": u.get("notes") or [], "views": views})
    return {"query_id": vs.get("query_id"), "original": vs.get("original"), "filters": vs.get("filters"), "units": units}


def split_roles(bundle: dict[str, Any], view_input: dict[str, Any]):
    """역할 단위를 질문에서 뺀다 → (모듈용 bundle, 모듈용 view_input, 역할 단위의 View 들)"""
    subs, sfs = list(bundle.get("sub_questions") or []), list(bundle.get("sub_filters") or [])
    roles = [i for i in range(len(subs)) if i < len(sfs) and _role(sfs[i])]
    if not roles:
        return bundle, view_input, []
    qid = bundle.get("query_id")
    role_units = {f"{qid}-{i + 1}" for i in roles}
    keep = [i for i in range(len(subs)) if i not in roles]
    if keep != list(range(len(keep))):      # 역할 단위는 add_role_units 가 맨 뒤에 붙인다 — 아니면 ID 가 어긋나므로 그대로 둔다
        return bundle, view_input, []
    b = {**bundle, "sub_questions": [subs[i] for i in keep], "sub_filters": [sfs[i] for i in keep] if sfs else sfs}
    units = [u for u in view_input["units"] if u.get("unit_id") not in role_units]
    extra = [min(u["views"], key=lambda v: v["rank"]) for u in view_input["units"]
             if u.get("unit_id") in role_units and u.get("views")]
    if not b["sub_questions"]:              # 역할 단위뿐이면 (그럴 일은 없지만) 손대지 않는다
        return bundle, view_input, []
    return b, {**view_input, "units": units}, extra


def decide_charts(bundle: QueryBundle, view_input: dict[str, Any], use_llm: bool = True) -> dict[str, Any]:
    """모듈 2 실행 + 모듈 3 입력으로 바꾸기 → {charts, errors, records, chart_plan} (POST /api/v1/chart/decide 와 같음)"""
    from backend.agent.chart_calculate.from_module2 import records_of, skipped_sets, to_chart_requests, unknown_view_ids
    from backend.agent.chart_decision import run_chart_decision
    out = run_chart_decision(bundle.model_dump(mode="json", by_alias=True), view_input, use_llm=use_llm)
    plan, errors = out["chart_plan"], list(out["errors"])
    if view_input.get("query_id") and bundle.query_id != view_input.get("query_id"):
        # 모듈 3 은 '{QueryBundle.query_id}-{순번}' 으로 하위 질문을 찾는다 → 다르면 시점·지역 같은 고정 조건이 적용되지 않는다
        errors.append({"reason": f"QueryBundle.query_id({bundle.query_id}) 와 View 의 query_id"
                                 f"({view_input.get('query_id')}) 가 달라 모듈 3 이 하위 질문을 찾지 못할 수 있음"})
    charts = to_chart_requests(plan or {}, bundle)
    records = records_of(view_input)
    errors += unknown_view_ids(charts, records)
    charts += skipped_sets(out["errors"], bundle, charts, view_input)
    return {"charts": charts, "errors": errors, "records": records, "chart_plan": plan}


def _figure_json(fig):
    try:
        import json
        return json.loads(fig.to_json()) if fig is not None else None
    except Exception:  # noqa: BLE001
        return None


def _draw(plan, m3: Module3Output, notes: list[str]):
    try:
        from backend.agent.draw_chart import run_module5
        out = run_module5(chart_plan=plan or {"query_id": m3.query_id, "charts": []}, module3_output=m3, save=False)
    except Exception as e:  # noqa: BLE001  (그림이 실패해도 답변은 낸다)
        notes.append(f"모듈 5 실패: {e.__class__.__name__}: {str(e)[:200]}")
        return []
    return [{"chart_id": r.chart_id, "chart_type": r.chart_type, "status": r.status, "title": r.title,
             "reason": r.reason, "warnings": list(r.warnings), "merged_from": list(r.merged_from),
             "figure": _figure_json(r.figure)} for r in out.get("results") or []]


def run_modules(vs: dict[str, Any], use_llm_chart: bool = True, draw: bool = True, max_rows: int = 50,
                decision=None, chat: Callable[..., Any] | None = None) -> dict[str, Any]:
    """ViewSet(status=ok) → {charts, chart_errors, chart_plan, module3, drawn, answer, notes}
    chat = core.llm.chat 과 같은 모양 (모듈 3·6). decision 을 주면 모듈 3 은 HCX 를 부르지 않는다"""
    from backend.agent.answer_compose.pipeline import run_module6
    from backend.agent.chart_calculate.pipeline import run_module3
    from backend.schemas.answer import Module6Request
    notes: list[str] = []
    vb = dict(vs.get("view_bundle") or {})
    vb.setdefault("query_id", vs.get("query_id"))
    vb.setdefault("original", vs.get("original") or "")
    vb, view_input, role_views = split_roles(vb, view_input_of(vs))
    bundle = QueryBundle.model_validate(vb)
    d = decide_charts(bundle, view_input, use_llm=use_llm_chart)
    charts: list[ChartRequest] = d["charts"]
    records: list[Record] = list(d["records"])
    if role_views:
        have = {r.id for r in records}
        extra_ids = [v["record"]["id"] for v in role_views]
        records += [Record.model_validate(v["record"]) for v in role_views if v["record"]["id"] not in have]
        for c in charts:
            if c.view_ids:
                c.view_ids = list(dict.fromkeys([*c.view_ids, *extra_ids]))
        notes.append(f"역할 단위(분모·조건)의 View 를 세트에 붙임: {extra_ids}")
    m3 = run_module3(Module3Request(records=records, query_bundle=bundle, charts=charts), decision=decision, chat=chat)
    drawn = _draw(d["chart_plan"], m3, notes) if draw and m3.chart_contents else []
    m6 = run_module6(Module6Request(query_bundle=bundle, records=records, calc_results=m3.calc_results,
                                    displays=m3.displays, answer_steps=m3.chart_plan.answer_steps,
                                    plan_warnings=m3.chart_plan.warnings, max_rows=max_rows), chat=chat)
    return {"charts": [c.model_dump(mode="json") for c in charts], "chart_errors": d["errors"],
            "chart_plan": d["chart_plan"], "records": [r.model_dump(mode="json") for r in records],
            "module3": m3.model_dump(mode="json"), "drawn": drawn, "answer": m6.model_dump(mode="json"), "notes": notes}


def as_answer_result(mods: dict[str, Any]) -> dict[str, Any]:
    """모듈 6 출력 → 예전 /chat result 모양 (AnswerResult). 화면이 바뀌지 않게 같은 칸에 넣는다"""
    a = mods["answer"]
    by_id = {r["id"]: r for r in mods["records"]}
    used = list(dict.fromkeys(rid for t in a["tables"] for rid in t.get("record_ids") or []))
    urls = [u for rid in used if (u := (by_id.get(rid, {}).get("source") or {}).get("kosis_url"))]
    return {"answer": a["answer"], "summary": "", "key_points": [], "insufficient": a["insufficient"],
            "unverified_numbers": [], "used_ids": used, "chart_id": None, "chart": None,
            "sources": list(dict.fromkeys(urls)), "caveats": [c["text"] for c in a["caveats"]],
            "calculations": mods["module3"]["calc_results"]}
