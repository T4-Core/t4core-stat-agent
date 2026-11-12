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
    아래는 손대지 않는다. 필드를 맞출 때 다시 본다.
    ③ sub_question_ids 의 'main'(하위 질문이 없을 때) — 모듈 3 은 '{query_id}-{순번}' 을 기대한다
    ④ view_ids, filtered_views — 모듈 3 은 쓰지 않는다 (records 는 걸러지지 않은 원본 View: 모듈 3 이 직접 행을 고른다)

  이 파일은 모듈 2 를 import 하지 않는다. dict 만 다룬다.
"""
from typing import Any

from backend.schemas.chart import ChartRequest, Module3Request
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

OUT_OF_SCOPE = "범위 밖"


def _note(reason: str | None, text: str) -> str:
    return f"{reason} ({text})" if reason else text


def to_chart_request(c: dict[str, Any]) -> ChartRequest:
    chart_type, measure, reason = c.get("chart_type"), c.get("measure"), c.get("reason")
    if measure == OUT_OF_SCOPE:
        chart_type, measure, reason = None, "raw", _note(reason, "모듈 2: 범위 밖 → 차트 없음")
    elif measure is None:
        measure, reason = "raw", _note(reason, "모듈 2 가 measure 를 정하지 못해 raw 로 둠")

    fallbacks = list(c.get("fallback_charts") or [])
    fallback = c.get("fallback_chart") or (fallbacks[0] if fallbacks else None)
    if len(fallbacks) > 1:
        reason = _note(reason, f"대체 차트 {fallbacks[1:]} 는 쓰지 않음")

    return ChartRequest(chart_id=c["chart_id"], sub_question_ids=list(c.get("sub_question_ids") or []),
                        chart_type=chart_type, measure=measure, requirements=list(c.get("requirements") or []),
                        fallback_chart=fallback, reason=reason)


def records_of(view_input: dict[str, Any]) -> list[Record]:
    """unit 마다 rank 가 가장 높은(숫자가 가장 작은) View 의 record"""
    return [Record.model_validate(min(u["views"], key=lambda v: v["rank"])["record"])
            for u in view_input.get("units") or [] if u.get("views")]


def to_module3_request(chart_plan: dict[str, Any], view_input: dict[str, Any],
                       query_bundle: QueryBundle | dict[str, Any]) -> Module3Request:
    return Module3Request(records=records_of(view_input), query_bundle=QueryBundle.model_validate(query_bundle),
                          charts=[to_chart_request(c) for c in chart_plan.get("charts") or []])
