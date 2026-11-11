"""통합 실행 (노트북 9번)

2~8번 함수를 하위질문마다 순서대로 호출해 chart_plan, filtered_views, errors를 만든다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
from .chart_type_chart_picker import attach_requirements, pick_chart, try_combo
from .chart_type_matcher import match_units
from .chart_type_measure import decide_measure
from .chart_type_profiler import profile_data
from .chart_type_reason import make_reason
from .chart_type_view_filter import filter_view


def decide_charts(query_bundle, view_input, use_llm=True):
    """2번 차트 유형 판단 모듈 전체 실행.
    순서: ① 짝짓기 → ①-1 필터링 → ② measure → ③ 데이터 모양 → combo 묶음 판단
          → ④ chart_type(소거법) → ⑤ requirements·fallback → ⑥ reason
    반환: (chart_plan, filtered_views, errors)
      chart_plan    : {"query_id", "charts": [...]}  (README 4장 출력 형식)
      filtered_views: 하위질문 조건으로 걸러진 View 목록 (3번 계산 모듈로 넘김)
      errors        : 짝 없음·필터 0행 등 건너뛴 하위질문 기록
    """
    # ① 하위질문 ↔ View 짝짓기 (+ chart_id)
    ms, errors = match_units(query_bundle, view_input)

    # ①-1 필터링 → ② measure → ③ 데이터 모양
    targets, filtered = [], []
    for m in ms:
        fv = filter_view(m["view"], m["sub_filter"], query_bundle["filters"])
        if not fv["record"]["table"]["rows"]:
            errors.append({"chart_id": m["chart_id"], "unit_id": m["unit_id"], "reason": "필터 결과 0행"})
            continue
        m["filtered_view"] = fv
        m["measure_info"] = decide_measure(m["sub_question"], query_bundle, use_llm=use_llm)
        m["measure"] = m["measure_info"]["measure"]
        m["profile"] = profile_data(fv, m["sub_filter"], query_bundle["filters"])
        targets.append(m)
        filtered.append(fv)

    # combo 묶음 판단 → ④ 하위질문마다 소거법
    plans = []
    ok, reasons, _ = try_combo(targets, query_bundle)
    if ok:
        a, b = targets
        plans.append({"chart_id": a["chart_id"], "sub_question_ids": [a["unit_id"], b["unit_id"]],
                      "view_ids": [a["filtered_view"]["record"]["id"], b["filtered_view"]["record"]["id"]],
                      "measure": a["measure"], "chart_type": "combo", "fallback_charts": [], "_ms": [a, b]})
    else:
        for m in targets:
            r = pick_chart(m["measure"], m["profile"], use_llm=use_llm)
            plans.append({"chart_id": m["chart_id"], "sub_question_ids": [m["unit_id"]],
                          "view_ids": [m["filtered_view"]["record"]["id"]], "measure": m["measure"],
                          "chart_type": r["chart_type"], "fallback_charts": r["fallback_charts"], "_ms": [m]})

    # ⑤ requirements · fallback → ⑥ reason → README 4장 필드 순서로 정리
    charts = []
    for p in plans:
        attach_requirements(p)
        p["reason"] = make_reason([m["sub_filter"] for m in p["_ms"]], query_bundle,
                                  [m["sub_question"] for m in p["_ms"]])
        charts.append({k: p[k] for k in ["chart_id", "sub_question_ids", "view_ids", "chart_type",
                                         "requirements", "fallback_charts", "measure", "reason"]})

    return {"query_id": view_input["query_id"], "charts": charts}, filtered, errors
