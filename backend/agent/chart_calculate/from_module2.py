"""
[NEW] 모듈 2 → 모듈 3 어댑터 (임시) — 모듈 2 의 chart_plan 을 Module3Request 로 바꾼다

  to_module3_request(chart_plan, view_input, query_bundle) → Module3Request
    chart_plan   모듈 2 출력 {"query_id", "charts": [...]}
    view_input   모듈 2 입력 (units[].views[].record). records 는 unit 마다 rank 가 가장 높은 View 의 record 를 쓴다
    query_bundle QueryBundle 또는 그 dict

  TODO(임시): 모듈 2 와 필드 이름·값을 아직 맞추지 않았다. 안 맞으면 터지거나 조용히 사라지는 것만 막는다.
    ① fallback_charts(목록) → ChartRequest.fallback_chart(하나). 첫 값만 쓰고, 버린 값은 reason 에 남긴다
       (모듈 3 은 대체 차트를 하나만 시도한다 — content.build_chart)
    ② measure 가 None → 'raw' 로 두고 reason 에 남긴다 / '범위 밖' → 차트 없음(chart_type None)
    ③ sub_question_ids 의 'main'(하위 질문이 없을 때) → '{query_id}-1'. 모듈 3 은 이 ID 로 시점·지역 같은 고정 조건을 찾는다.
       안 바꾸면 그 차트에는 고정 조건이 조용히 적용되지 않는다. 하위 질문이 있을 때는 'main' 이 나오지 않으므로 건드리지 않는다.
       (모듈 2 담당자 답을 기다리는 중: 모듈 2 가 직접 '{query_id}-1' 을 내면 이 변환은 아무것도 바꾸지 않는다)
    아래는 손대지 않는다. 필드를 맞출 때 다시 본다.
    ④ filtered_views — 모듈 3 은 쓰지 않는다 (records 는 걸러지지 않은 원본 View: 모듈 3 이 직접 행을 고른다)
    [CHANGED] view_ids 는 이제 ChartRequest.view_ids 로 그대로 전달한다 (세트 = 질문 · 차트 유형 · View).
              길이는 검사하지 않는다 (일반 차트 1개, combo 는 여러 개). records 의 구성은 그대로다 (단위마다 rank 1 View 하나씩)

  이 파일은 모듈 2 를 import 하지 않는다. dict 만 다룬다.
"""
from typing import Any

from backend.agent.chart_calculate.planner import sub_question_ids
from backend.schemas.chart import ChartRequest, Module3Request
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

OUT_OF_SCOPE = "범위 밖"
MAIN = "main"      # 모듈 2 가 하위 질문이 없을 때 원 질문 unit 에 붙이는 이름


def _note(reason: str | None, text: str) -> str:
    return f"{reason} ({text})" if reason else text


def to_chart_request(c: dict[str, Any], main_id: str | None = None) -> ChartRequest:
    """main_id: 'main' 을 바꿀 ID (모듈 3 이 원 질문에 붙이는 '{query_id}-1'). 없으면 'main' 을 그대로 둔다"""
    chart_type, measure, reason = c.get("chart_type"), c.get("measure"), c.get("reason")
    sub_ids = list(c.get("sub_question_ids") or [])
    if main_id and MAIN in sub_ids:
        sub_ids = [main_id if s == MAIN else s for s in sub_ids]
        reason = _note(reason, f"모듈 2 의 하위 질문 ID '{MAIN}' → '{main_id}'")
    if measure == OUT_OF_SCOPE:
        chart_type, measure, reason = None, "raw", _note(reason, "모듈 2: 범위 밖 → 차트 없음")
    elif measure is None:
        measure, reason = "raw", _note(reason, "모듈 2 가 measure 를 정하지 못해 raw 로 둠")

    fallbacks = list(c.get("fallback_charts") or [])
    fallback = c.get("fallback_chart") or (fallbacks[0] if fallbacks else None)
    if len(fallbacks) > 1:
        reason = _note(reason, f"대체 차트 {fallbacks[1:]} 는 쓰지 않음")

    return ChartRequest(chart_id=c["chart_id"], sub_question_ids=sub_ids,
                        chart_type=chart_type, measure=measure, requirements=list(c.get("requirements") or []),
                        fallback_chart=fallback, reason=reason, view_ids=list(c.get("view_ids") or []))


def records_of(view_input: dict[str, Any]) -> list[Record]:
    """unit 마다 rank 가 가장 높은(숫자가 가장 작은) View 의 record"""
    return [Record.model_validate(min(u["views"], key=lambda v: v["rank"])["record"])
            for u in view_input.get("units") or [] if u.get("views")]


def unknown_view_ids(charts: list[ChartRequest], records: list[Record]) -> list[dict[str, Any]]:
    """[NEW] 차트의 view_ids 중 records 에 없는 것. 모듈 2 가 거른 View 는 view_input 에서 왔으므로 보통 비어 있다.
    입력이 어긋났을 때 HCX 를 부르기 전에 알아챈다 (→ /decide 의 errors)"""
    have = {r.id for r in records}
    return [{"chart_id": c.chart_id, "reason": f"view_ids 의 View 가 records 에 없음: {missing}"}
            for c in charts if (missing := [v for v in c.view_ids if v not in have])]


def _squash(text: str) -> str:
    return "".join(str(text).split())


def skipped_sets(errors: list[dict[str, Any]], bundle: QueryBundle, charts: list[ChartRequest],
                 view_input: dict[str, Any] | None = None) -> list[ChartRequest]:
    """[NEW] 모듈 2 가 건너뛴 하위 질문 → 차트 유형 없는 세트 (chart_id x1, x2 …).
    모듈 2 는 건너뛴 질문을 chart_plan 에 넣지 않고 errors 에만 남긴다. 이대로면 모듈 3 은 그 질문의 존재를 모른 채
    다른 View 로 답을 만들 수 있다.
    세트는 '같은 순서'다: 하위 질문 i ↔ view_input 의 unit '{query_id}-{i}' (모듈 2 의 순서 짝짓기와 같다).
    그 unit 에 View 가 있으면 가장 높은 rank 의 View 를 세트에 붙여 질문용 계산만 하게 하고,
    View 가 없으면 view_ids 를 비워 '계산 안 함 + 사유' 로 넘긴다.
    연결할 수 없는 오류(입력 문제·경고·이미 차트가 있는 질문)는 만들지 않는다 (errors 에 그대로 남아 있다)"""
    subs = sub_question_ids(bundle)
    by_unit, by_text = {sid for sid, _ in subs}, {_squash(t): sid for sid, t in subs}
    if not bundle.sub_questions:
        by_unit.add(MAIN)
    units = {u.get("unit_id"): u for u in (view_input or {}).get("units") or []}
    covered = {s for c in charts for s in c.sub_question_ids}
    out: list[ChartRequest] = []
    for e in errors:
        if e.get("level") == "warning":
            continue
        sid = e.get("unit_id") or by_text.get(_squash(e.get("sub_question") or ""))
        if sid == MAIN and not bundle.sub_questions:
            sid = subs[0][0]
        if sid not in by_unit or sid in covered:
            continue
        covered.add(sid)
        why = f"모듈 2 가 건너뜀: {e.get('reason') or '이유 없음'}"
        unit = units.get(sid) or (units.get(MAIN) if not bundle.sub_questions else None)
        view_ids = [min(unit["views"], key=lambda v: v["rank"])["record"]["id"]] if unit and unit.get("views") else []
        out.append(ChartRequest(chart_id=f"x{len(out) + 1}", sub_question_ids=[sid], chart_type=None, measure="raw",
                                view_ids=view_ids, reason=why + (" → 같은 순서의 View 로 질문용 계산만" if view_ids else "")))
    return out


def to_chart_requests(chart_plan: dict[str, Any], bundle: QueryBundle) -> list[ChartRequest]:
    # 하위 질문이 없을 때만 'main' 이 나온다. 그때 모듈 3 의 하위 질문 ID 는 원 질문 하나 = sub_question_ids(bundle)[0]
    main_id = None if bundle.sub_questions else sub_question_ids(bundle)[0][0]
    return [to_chart_request(c, main_id) for c in chart_plan.get("charts") or []]


def to_module3_request(chart_plan: dict[str, Any], view_input: dict[str, Any],
                       query_bundle: QueryBundle | dict[str, Any]) -> Module3Request:
    bundle = QueryBundle.model_validate(query_bundle)
    return Module3Request(records=records_of(view_input), query_bundle=bundle, charts=to_chart_requests(chart_plan, bundle))
