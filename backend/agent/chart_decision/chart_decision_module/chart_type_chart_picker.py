"""④⑤ chart_type 소거법 · combo 묶음 · requirements (노트북 6·7번)

measure 후보를 우선순위 순서대로 보며 requirements를 못 지키는 차트를 지운다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
from .chart_type_preference import shape_score
from .chart_type_rules import (
    CHART_REQUIREMENTS, MEASURE_TO_CHARTS, OUT_OF_SCOPE, REQ_CHECKS, REQUEST_ONLY_CHARTS,
)


def check_chart(chart, profile):
    """차트 하나의 requirements를 모두 검사. 반환: (통과 여부, 못 지킨 조건 설명 목록)"""
    fails = []
    for req in CHART_REQUIREMENTS[chart]:
        ok, desc = REQ_CHECKS[req](profile)
        if not ok:
            fails.append(f"{req}: {desc}")
    return not fails, fails

def pick_chart_llm(measure, profile, log):
    """규칙 실패(후보가 모두 소거) 시 LLM 호출 자리 (B안). 지금은 호출하지 않고 None을 돌려준다."""
    return None, "LLM 자리만 (미구현)"

def pick_chart(measure, profile, use_llm=True, exclude=(), exclude_why=None, requested=None):
    """소거법 + 데이터 모양 점수로 chart_type 선택.
    exclude    : 검사 없이 후보에서 뺄 차트 (View 적합도 — 요청한 나눔이 표에 없을 때. chart_type_view_check.block_reason)
    exclude_why: {차트: 뺀 이유} (log 에 남긴다)
    requested  : 질문에서 사용자가 이름으로 요청한 차트 (고도화 3단계, chart_type_preference.requested_chart)
                 measure 후보에 없어도 requirements 만 통과하면 그 차트를 고른다
    순서: ① 요청한 차트 검사 → ② measure 후보를 검사(REQUEST_ONLY_CHARTS 는 요청할 때만) → 생존 후보를 점수순(같으면 기존 순서)
    반환: {"chart_type", "fallback_charts", "source", "log", "request"}
      source : "request" (요청한 차트) / "rule" (규칙으로 선택) / "llm" (규칙 실패 → LLM) / "none" (차트 없음, 표만)
      log    : [{"후보", "결과", "이유"}, ...]  후보마다 남음/소거와 그 이유 (남은 후보는 점수와 근거 포함)
      request: {"chart", "ok", "why"} 요청이 있었을 때만 (ok=False 면 why 에 못 그린 이유)
    """
    if measure in (None, OUT_OF_SCOPE):
        return {"chart_type": None, "fallback_charts": [], "source": "none", "request": None,
                "log": [{"후보": "-", "결과": "-", "이유": f"measure가 {measure!r} → 표만"}]}

    log, request = [], None
    # ① 사용자가 이름으로 요청한 차트
    if requested:
        if requested in exclude:
            why = (exclude_why or {}).get(requested, "View 적합도로 제외")
        else:
            ok, fails = check_chart(requested, profile)
            why = None if ok else " / ".join(fails)
        request = {"chart": requested, "ok": why is None, "why": why}
        log.append({"후보": f"{requested} (요청)", "결과": "남음" if why is None else "소거",
                    "이유": "질문에서 요청" if why is None else why})

    # ② measure 후보
    candidates = MEASURE_TO_CHARTS.get(measure, [])
    if not candidates and not (request and request["ok"]):
        log.append({"후보": "-", "결과": "-", "이유": f"{measure}는 맞는 차트 없음 → 표만"})
        return {"chart_type": None, "fallback_charts": [], "source": "none", "log": log, "request": request}

    survivors = []                                        # (점수, 기존 순서, 차트)
    for i, chart in enumerate(candidates):                # 우선순위 순서대로 검사
        if chart == requested:
            continue
        if chart in exclude:                              # View 적합도로 뺀 차트
            log.append({"후보": chart, "결과": "소거", "이유": (exclude_why or {}).get(chart, "View 적합도로 제외")})
            continue
        if chart in REQUEST_ONLY_CHARTS:                  # 지도 등: 요청할 때만
            log.append({"후보": chart, "결과": "소거", "이유": "요청할 때만 고르는 차트"})
            continue
        ok, fails = check_chart(chart, profile)
        if ok:
            score, basis = shape_score(chart, profile, measure)
            survivors.append((score, i, chart))
            log.append({"후보": chart, "결과": "남음",
                        "이유": ", ".join(REQ_CHECKS[r](profile)[1] for r in CHART_REQUIREMENTS[chart])
                              + f" · 점수 {score}" + (f" ({basis})" if basis else "")})
        else:
            log.append({"후보": chart, "결과": "소거", "이유": " / ".join(fails)})
    ranked = [c for _, _, c in sorted(survivors, key=lambda t: (-t[0], t[1]))]

    if request and request["ok"]:
        return {"chart_type": requested, "fallback_charts": ranked, "source": "request", "log": log, "request": request}
    if ranked:
        return {"chart_type": ranked[0], "fallback_charts": ranked[1:], "source": "rule", "log": log, "request": request}

    # 후보는 있었는데 모두 소거 → 규칙 실패
    chart, why = pick_chart_llm(measure, profile, log) if use_llm else (None, "LLM 사용 안 함")
    log.append({"후보": "(LLM)", "결과": chart or "None", "이유": why})
    return {"chart_type": chart, "fallback_charts": [], "source": "llm" if chart else "none", "log": log,
            "request": request}

def try_combo(ms, query_bundle):
    """하위질문 2개를 combo 1개로 묶을 수 있는지 검사. 반환: (묶을지, 이유 목록, combo용 profile)
    [고도화 5단계부터 쓰지 않음] 3번이 서로 다른 표의 하위질문 둘을 한 차트로 계산하지 못해 묶지 않는다.
    겹쳐 그리기는 chart_type_overlay.find_overlays 가 chart_plan.overlays 로 표시한다 (5번만 읽음)"""
    if len(ms) != 2:
        return False, [f"하위질문 {len(ms)}개 (2개 필요)"], None
    a, b = ms
    fa, fb = a["sub_filter"], b["sub_filter"]
    same_time = fa.get("시점") == fb.get("시점")
    same_axis = fa.get("비교축") == fb.get("비교축")
    intent_cmp = "비교" in (query_bundle.get("intent") or [])
    ua = a["filtered_view"]["filter_info"].get("unit")
    ub = b["filtered_view"]["filter_info"].get("unit")
    units_differ = bool(ua and ub and ua != ub)
    measure_ok = a.get("measure") == b.get("measure") and "combo" in MEASURE_TO_CHARTS.get(a.get("measure"), [])
    reasons = [f"시점 같음={same_time}", f"비교축 같음={same_axis}", f"의도 '비교'={intent_cmp}",
               f"단위 다름={units_differ} ({ua}/{ub})", f"measure 같고 combo 후보={measure_ok}"]
    if not (same_time and same_axis and intent_cmp and units_differ and measure_ok):
        return False, reasons, None
    pa, pb = a["profile"], b["profile"]
    combo_profile = dict(pa, n_series=2, n_measures=2, n_indicators=2,
                         indicators=pa["indicators"] + pb["indicators"], units_differ=True)
    ok, fails = check_chart("combo", combo_profile)
    reasons += fails or ["combo requirements 통과"]
    return ok, reasons, combo_profile


def attach_requirements(plan):
    """chart_type에 requirements를 붙이고 fallback_charts를 정리한다.
    - requirements = CHART_REQUIREMENTS[chart_type] (실제 검사는 3번 모듈이 한다)
    - fallback_charts = 6번 소거 후 남은 후보 중 chart_type 다음 순위들
      (3번은 chart_type이 조건을 못 지키면 이 목록을 차례로 내려가고, 끝나면 표만 보여준다)
    - chart_type이 None이면 requirements와 fallback_charts는 [] (표만 표시). None도 3번 calculation으로 간다.
    """
    chart_type = plan.get("chart_type")
    if chart_type is None:
        plan["requirements"], plan["fallback_charts"] = [], []
    else:
        plan["requirements"] = list(CHART_REQUIREMENTS.get(chart_type, []))
        plan["fallback_charts"] = [c for c in plan.get("fallback_charts", []) if c != chart_type]
    return plan
