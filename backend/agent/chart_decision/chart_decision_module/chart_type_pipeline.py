"""통합 실행 (노트북 9번)

2~8번 함수를 하위질문마다 순서대로 호출해 chart_plan, filtered_views, errors를 만든다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
from .chart_type_chart_picker import attach_requirements, pick_chart
from .chart_type_frames import chart_measure
from .chart_type_matcher import match_units
from .chart_type_measure import decide_measure
from .chart_type_profiler import profile_data
from .chart_type_reason import make_reason
from .chart_type_nodes import CHART_KEYS, _request_info, _request_warning, chart_warnings
from .chart_type_preference import record_selection, requested_codes
from .chart_type_overlay import find_overlays
from .chart_type_schema import validate_plan
from .chart_type_view_check import block_reason, check_view, fit_warnings
from .chart_type_view_filter import filter_view


def decide_charts(query_bundle, view_input, use_llm=True):
    """2번 차트 유형 판단 모듈 전체 실행.
    순서: ① 짝짓기 → ①-1 필터링 → ①-2 View 적합도 → ② measure → ③ 데이터 모양 → combo 묶음 판단
          → ④ chart_type(소거법) → ⑤ requirements·fallback → ⑥ reason
    반환: (chart_plan, filtered_views, errors)
      chart_plan    : {"query_id", "charts": [...]}  (README 4장 출력 형식)
      filtered_views: 하위질문 조건으로 걸러진 View 목록 (3번 계산 모듈로 넘김)
      errors        : 짝 없음·필터 0행 등 건너뛴 하위질문 기록 + View 적합도 경고(level=warning)
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
        m["view_fit"] = check_view(m["view"])                         # ①-2 View 적합도 (고도화 1단계)
        errors += [{"node": "view_check", "chart_id": m["chart_id"], "level": "warning", "reason": w}
                   for w in fit_warnings(m["view_fit"])]
        m["measure_info"] = decide_measure(m["sub_question"], query_bundle, use_llm=use_llm)
        m["measure"] = m["measure_info"]["measure"]
        m["profile"] = profile_data(fv, m["sub_filter"], query_bundle["filters"], query_bundle.get("intent"))
        errors += [{"node": "profile", "chart_id": m["chart_id"], "level": "warning", "reason": t}
                   for t in m["profile"].get("axis_notes") or []]                  # 범주에서 뺀 열 (고도화 2단계)
        targets.append(m)
        filtered.append(fv)

    # combo 묶음 판단 → ④ 하위질문마다 소거법
    plans = []
    blocks = {m["chart_id"]: block_reason(m, query_bundle) for m in targets}     # (막을 이유, 뺄 차트, 뺀 이유)
    # [고도화 5단계] combo 로 묶지 않는다 — 차트는 하위질문마다 1개, 겹쳐 그리기는 아래 overlays 로 표시 (5번만 읽음)
    for m in targets:
        block, exclude, why = blocks[m["chart_id"]]
        info = _request_info(m, query_bundle)                              # [NEW 11-20 KOS-41] 차단 판정과 관계없이 요청을 먼저 해석
        measure, swap = chart_measure(m, query_bundle)                     # [NEW 11-24] 결과 1개인 차이 계산 → 비교한 값(raw)을 그림
        if swap:
            errors.append({"node": "chart_select", "chart_id": m["chart_id"], "level": "info", "reason": swap})
        base = {"chart_id": m["chart_id"], "sub_question_ids": [m["sub_question_id"]],
                "view_ids": [m["filtered_view"]["record"]["id"]], "measure": measure, "_ms": [m], "request": info,
                "measure_note": swap}
        if block:                                                         # View 가 질문에 맞지 않음 → 차트 없음 (표만)
            record_selection(info, None, block=block)
            plans.append({**base, "chart_type": None, "fallback_charts": []})
            errors.append({"node": "chart_select", "chart_id": m["chart_id"], "level": "warning",
                           "reason": f"차트 없음(표만): {block}"})
            continue
        codes, excl = requested_codes(info)
        r = pick_chart(measure, m["profile"], use_llm=use_llm, exclude=exclude, exclude_why=why,
                       requested=codes, excluded=excl)
        record_selection(info, r)
        errors += _request_warning(m["chart_id"], r)
        plans.append({**base, "chart_type": r["chart_type"], "fallback_charts": r["fallback_charts"]})

    # ⑤ requirements · fallback → ⑥ reason → README 4장 필드 순서로 정리
    charts = []
    for p in plans:
        attach_requirements(p)
        p["reason"] = make_reason([m["sub_filter"] for m in p["_ms"]], query_bundle,
                                  [m["sub_question"] for m in p["_ms"]])
        if p.get("measure_note"):
            p["reason"] = f"{p['reason']} · {p['measure_note']}"
        p["warnings"] = chart_warnings(errors, [m["chart_id"] for m in p["_ms"]])     # 사용자용 경고 (고도화 4단계)
        charts.append({k: p[k] for k in CHART_KEYS})

    overlays, notes = find_overlays([p["_ms"][0] for p in plans], charts, query_bundle)     # 겹쳐 그리기 (고도화 5단계)
    plan, schema_errors = validate_plan({"query_id": view_input["query_id"], "charts": charts, "overlays": overlays})
    errors += [{"node": "reason", "level": "info", "reason": t} for t in notes] + schema_errors
    return plan, filtered, errors
