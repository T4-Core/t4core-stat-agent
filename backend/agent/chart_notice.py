"""
[NEW 11-20 KOS-41] 차트 지정 요청의 최종 결과와 사용자 안내 — 일반 경로(modules.py)가 부른다.
  QA 경로(qa/)는 QA 담당이 finalize 에서 finalize_chart_request() 를 같은 인자로 부르도록 연결한다 (전달 문서 KOS-41-qa-handoff)

  요청(모듈 2 가 해석해 charts[].request 에 담음) + 모듈 3 의 validation + 모듈 5 의 렌더링 결과
      ─▶ render_states()           차트별 렌더링 상태 (생략과 실패를 구분한다)
      ─▶ request_outcomes()        차트별 최종 결과 (honored · substituted · table_only · render_failed · not_rendered)
      ─▶ chart_notices()           사용자용 안내 문장

  원칙
    - 안내는 **최종 상태 기준**이고 이 파일에서만 문장으로 만든다. 모듈 2 의 경고(m2_warnings)와 모듈 6 의 답변은 차트 상태를 말하지 않는다.
      모듈 5 와 6 은 병렬이라 모듈 6 시점에는 렌더링 결과를 알 수 없기 때문이다.
    - 호출자가 의도한 생략(draw=False)과 QA 의 중단(중단 메시지가 이미 나간다)은 안내하지 않는다.
      요청을 충족하지 못해 차트 내용이 없는 경우(no_chart_content)는 사유를 안내한다.
    - 요청이 없는 차트에는 결과도 안내도 만들지 않는다.
"""
import re
from typing import Any

from backend.core.korean import josa
from backend.schemas.chart import (
    OUTCOME_REASONS, ChartRequest, ChartRequestOutcome, Module3Output, RenderState,
)

CHART_KO = {
    "line": "꺾은선 그래프", "bar": "막대 그래프", "stacked_bar": "누적 막대 그래프", "pyramid": "인구 피라미드", "area": "면적 그래프",
    "pie": "원그래프", "donut": "도넛 차트", "bubble": "버블 차트", "combo": "콤보 차트", "radar": "레이더 차트", "map": "지도",
    "heatmap": "히트맵", "treemap": "트리맵", "scatter": "산점도", "dumbbell": "덤벨 차트",
}
_M2_TABLE_REASONS = {"unsupported_type", "data_mismatch", "view_blocked", "no_candidate", "ambiguous_scope"}


def _as_chart(c: Any) -> ChartRequest:
    return c if isinstance(c, ChartRequest) else ChartRequest.model_validate(c)


def _get(obj: Any, key: str, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


# ── 렌더링 상태 ──────────────────────────────────────────────────────────────
def render_states(charts: list, m3: Module3Output | None, drawn: list | None, *, draw: bool = True,
                  error: str | None = None, stopped: bool = False, rejected: bool = False) -> dict[str, dict]:
    """차트별 렌더링 상태 {chart_id: RenderState}. drawn=[] 만으로는 생략과 실패를 구분할 수 없으므로 원인을 받는다.
      draw      호출자가 그림을 요청했는가 (False → draw_disabled)
      error     모듈 5 예외 요약 (→ failed/exception)
      stopped   QA 가 모듈 5 이전에 중단했는가 (→ skipped/qa_stopped)
      rejected  QA 의 M5-out 검증이 모듈 5 출력을 버렸는가 (→ failed/render_error)"""
    have = {c.chart_id for c in (m3.chart_contents if m3 is not None else [])}
    by_chart: dict[str, dict] = {}
    # [CHANGED 11-25] 차트 자신의 결과를 먼저 본다. 이전에는 drawn 순서대로 받아, 합친 차트가 맨 앞에 오면(모듈 5 5단계)
    #   c1 의 상태가 합친 차트(c1+c2)의 상태로 잡혔다
    for d in drawn or []:
        by_chart.setdefault(_get(d, "chart_id"), d)
    for d in drawn or []:
        for cid in _get(d, "merged_from") or []:
            by_chart.setdefault(cid, d)
    out: dict[str, dict] = {}
    for c in map(_as_chart, charts):
        cid = c.chart_id
        if stopped:
            st = RenderState(state="skipped", reason="qa_stopped")
        elif cid not in have:
            st = RenderState(state="skipped", reason="no_chart_content")
        elif not draw:
            st = RenderState(state="skipped", reason="draw_disabled")
        elif error:
            st = RenderState(state="failed", reason="exception", error=error)
        elif rejected:
            st = RenderState(state="failed", reason="render_error", error="모듈 5 출력 검증 실패")
        else:
            d = by_chart.get(cid)
            if d is not None and _get(d, "status") == "drawn":
                st = RenderState(state="drawn")
            else:
                st = RenderState(state="failed", reason="render_error", error=(_get(d, "reason") if d is not None else "그림 결과 없음"))
        out[cid] = st.model_dump(mode="json")
    return out


# ── 최종 결과 ────────────────────────────────────────────────────────────────
def _final_chart(cid: str, m3: Module3Output | None) -> str | None:
    if m3 is None:
        return None
    for c in m3.chart_contents:
        if c.chart_id == cid:
            return c.chart_type
    v = (m3.validation or {}).get(cid)
    return _get(v, "final_chart_type") if v is not None else None


def merged_types(drawn: list | None) -> dict[str, list[str]]:
    """[NEW 11-25 5단계] 합친 차트(모듈 5 겹쳐 그리기)에 들어가 그려진 차트 → [합친 차트 유형]. 그린 것(drawn)만"""
    out: dict[str, list[str]] = {}
    for d in drawn or []:
        if _get(d, "status") == "drawn":
            for cid in _get(d, "merged_from") or []:
                out.setdefault(cid, []).append(_get(d, "chart_type"))
    return out


def request_outcomes(charts: list, m3: Module3Output | None, states: dict[str, dict],
                     merged: dict[str, list[str]] | None = None) -> list[dict]:
    """요청이 있는 차트마다 최종 결과. 요청이 없는 차트(request=None)는 만들지 않는다
    merged: [NEW 11-25] merged_types(drawn). 요청한 차트가 합친 차트로 그려졌으면(시도별 출생아수 · 사망자수 → 산점도)
            그 차트의 결과는 honored 이고 final_chart 는 합친 차트 유형이다. 이전: 하위 차트(막대) 기준이라
            '이 자료로는 산점도를 그릴 수 없어 막대 그래프로 보여 드립니다' 가 합친 산점도와 함께 나갔다"""
    out = []
    for c in map(_as_chart, charts):
        req = c.request
        if req is None:
            continue
        cid, stage = c.chart_id, req.stage
        st = RenderState.model_validate(states.get(cid) or {"state": "skipped", "reason": "no_chart_content"})
        final = _final_chart(cid, m3)
        wanted = [n.code for n in req.preferred if n.supported and n.code]
        outcome, reason = _decide(stage.reason, stage.applied, stage.selected, wanted, bool(req.preferred), final, st)
        via = next((t for t in (merged or {}).get(cid, []) if t in wanted), None)
        if via and outcome in ("honored", "substituted"):
            outcome, reason, final = "honored", None, via
        assert reason in OUTCOME_REASONS[outcome], (outcome, reason)
        out.append(ChartRequestOutcome(chart_id=cid, outcome=outcome, reason=reason, final_chart=final).model_dump(mode="json"))
    return out


def _decide(stage_reason, applied, selected, wanted, has_preferred, final, st: RenderState) -> tuple[str, str | None]:
    if st.reason == "qa_stopped":
        return "not_rendered", "qa_stopped"
    if st.reason == "no_chart_content" or final is None:
        reason = stage_reason if stage_reason in _M2_TABLE_REASONS else "validation_failed"
        return "table_only", reason
    if st.reason == "draw_disabled":
        return "not_rendered", "draw_disabled"
    if st.state == "failed":
        return "render_failed", "render_error"
    # 렌더링 성공: 요청과 최종 유형을 견준다
    if not applied:
        return "substituted", "ambiguous_scope"
    if stage_reason == "unsupported_type":
        return "substituted", "unsupported_type"
    if not has_preferred or final in wanted:
        return "honored", None                     # 제외만 있었거나(제외는 지켜졌다) 요청한 차트가 그대로 나갔다
    if selected is not None and selected != final:
        return "substituted", "validation_fallback"           # 모듈 2 는 수락했는데 모듈 3 재검증에서 바뀜
    return "substituted", stage_reason if stage_reason in OUTCOME_REASONS["substituted"] else "data_mismatch"


# ── [NEW 11-25 6단계 6-4] 안내 문장의 이유 ─────────────────────────────────────────
#   이유를 알 수 있으면 문장에 넣고, 모르면 이전 문장 그대로 쓴다. 스키마는 그대로 — 이미 있는 두 곳에서 읽는다
#     모듈 2 단계 (data_mismatch · no_candidate · view_blocked): ChartRequest.m2_warnings (모듈 2 의 사용자용 경고)
#       - '요청한 {차트} 차트를 그릴 수 없음: {이유} → {고른 차트}'  (chart_type_nodes._request_warning)
#       - '차트 없음(표만): {이유}'                                  (chart_type_nodes.chart_select_node)
#     모듈 3 단계 (validation_fallback · validation_failed): Module3Output.validation[chart_id].original (실패 조건 · 개수)
#   이유는 두 종류: 차트를 주어로 쓰는 것('피라미드는 연령별 남녀 값이 있어야 해서 …')과 원인을 앞에 쓰는 것('값이 1개뿐이라 …')
_M2_REQUEST = re.compile(r"^요청한 (\S+) 차트를 그릴 수 없음: (.+?) → ")
_M2_TABLE_ONLY = "차트 없음(표만): "
_NEED = {        # 빈 좌표에서 떨어진 차트에 필요한 것 (모듈 2 chart_type_frames._frames 의 자리 설명을 사용자 말로)
    "line": "시점이 3개 이상 있어야 해서", "area": "시점이 3개 이상 있어야 해서", "bar": "비교할 값이 2개 이상 있어야 해서",
    "stacked_bar": "쌓을 계열이 2개 이상 있어야 해서", "pyramid": "연령별 남녀 값이 있어야 해서",
    "pie": "나눠 볼 항목(시점 제외)이 2개 이상 있어야 해서", "donut": "나눠 볼 항목(시점 제외)이 2개 이상 있어야 해서",
    "combo": "시점 3개 이상에 지표 2개가 있어야 해서", "scatter": "범주 5개 이상에 서로 다른 지표 2개가 있어야 해서",
    "bubble": "서로 다른 지표 3개가 있어야 해서", "dumbbell": "범주마다 비교할 두 값이 있어야 해서",
    "radar": "범주 3개 이상과 나눠 볼 계열이 있어야 해서", "map": "지역이 2곳 이상 있어야 해서",
    "heatmap": "나누는 기준이 2가지 있어야 해서", "treemap": "상위 · 하위 범주가 있어야 해서",
}
_PART_WHOLE = "전체를 나눈 부분을 보여 주는 차트라"
_COUNT_REASON = re.compile(r"^(\S+) (\d+)개 \((최소|최대) (\d+)개\)")     # 모듈 3 validate._count 의 문구
_CHECK_PHRASES = {      # 모듈 3 검증 조건 → 원인 ('…라' · '…어')
    "plan_present": "계산이 보류되어", "data_present": "그릴 값이 없어",
    "two_points_per_category": "범주마다 비교할 두 값이 다 있지 않아", "two_series_required": "나눠 볼 계열이 1개뿐이라",
    "time_axis_required": "시점이 여러 개 있지 않아", "parts_sum_to_total": "부분의 합이 전체와 맞지 않아",
    "non_negative": "음수 값이 있어", "two_measures_required": "서로 다른 지표가 부족해",
    "three_measures_required": "서로 다른 지표가 부족해", "two_dimensions_required": "나누는 기준이 부족해",
    "region_dimension_required": "지역 구분이 없어", "category_axis_required": "범주 구분이 없어",
}


def _m2_detail(c: ChartRequest, code: str | None) -> tuple[str, str] | None:
    """모듈 2 단계에서 떨어진 이유 → ("subject" | "cause", 문구). 모르면 None"""
    from backend.agent.chart_decision.chart_decision_module.chart_type_frames import SINGLE_VALUE
    for w in c.m2_warnings:
        if w.startswith(_M2_TABLE_ONLY):                     # View 적합도로 막힘 (view_blocked)
            why = w[len(_M2_TABLE_ONLY):]
            if m := re.match(r"추이를 물었지만 표의 시점이 (\d+)개", why):
                return "cause", f"추이를 물었지만 표의 시점이 {m.group(1)}개뿐이라"
            if why.startswith("표가 비어 있어"):
                return "cause", "표가 비어 있어"
            if why.startswith("요청한 지표가 표에 없어"):
                return "cause", "요청한 지표가 표에 없어"
            continue
        m = _M2_REQUEST.match(w)
        if not m or (code and m.group(1) != code):
            continue
        why, chart = m.group(2), m.group(1)
        if why.startswith(SINGLE_VALUE.split(" (")[0]):
            return "cause", "값이 1개뿐이라"
        if why.startswith("좌표가 맞지 않음") and chart in _NEED:
            return "subject", f"{_NEED[chart]} 이 자료로는 그릴 수 없어"
        if "부분이 시점" in why:
            return "subject", f"{_PART_WHOLE} 시점별 값으로는 그릴 수 없어"
        if why.startswith("부분-전체 차트인데 값이"):
            return "subject", f"{_PART_WHOLE} 더해서 전체가 되지 않는 값으로는 그릴 수 없어"
        if sm := re.match(r"요청한 (.+?) 구분이 표에 없음", why):
            return "cause", f"표에 {sm.group(1)} 구분이 없어"
    return None


def _m3_detail(m3: Module3Output | None, cid: str) -> str | None:
    """모듈 3 검증에서 요청한 차트(처음 시도한 차트)가 떨어진 이유 → 원인 문구. 모르면 None"""
    v = (m3.validation or {}).get(cid) if m3 is not None else None
    check = _get(v, "original") if v is not None else None
    if check is None:
        return None
    reasons = [str(r) for r in (_get(check, "reasons") or [])]
    for code in _get(check, "failed") or []:
        if code.startswith(("min_", "max_")):
            for r in reasons:
                if (m := _COUNT_REASON.match(r)) and (m.group(3) == "최소") == code.startswith("min_"):
                    label, got, bound = m.group(1), int(m.group(2)), m.group(4)
                    if code.startswith("max_"):
                        return f"항목이 {got}개로 많아({bound}개까지 그림)"
                    if got <= 1:
                        return "값이 1개뿐이라"
                    return f"{'비교할 항목' if label == '항목' else label}이 {got}개뿐이라({bound}개 이상 필요)"
            continue
        if code in _CHECK_PHRASES:
            return _CHECK_PHRASES[code]
    return None


def _detail(c: ChartRequest, o: dict, m3: Module3Output | None) -> tuple[str, str] | None:
    reason = o["reason"]
    if reason in ("data_mismatch", "no_candidate", "view_blocked"):
        codes = [n.code for n in (c.request.preferred if c.request else []) if n.code]
        return _m2_detail(c, codes[0] if codes else None)
    if reason in ("validation_fallback", "validation_failed"):
        text = _m3_detail(m3, c.chart_id)
        return ("cause", text) if text else None
    return None


# ── 사용자 안내 ──────────────────────────────────────────────────────────────
def _name_of(c: ChartRequest) -> str:
    names = [n.text for n in (c.request.preferred if c.request else [])]
    return names[0] if names else (CHART_KO.get(c.chart_type or "", "") or "요청한 차트")


def _sentence(c: ChartRequest, o: dict, detail: tuple[str, str] | None = None) -> str | None:
    """detail: [NEW 11-25 6-4] _detail 의 이유. 있으면 이유를 넣은 문장, 없으면 이전 문장"""
    name = _name_of(c)
    final = CHART_KO.get(o["final_chart"] or "", None)
    to = f"{josa(final, '으로')} 보여 드립니다" if final else "차트 없이 표로 보여 드립니다"
    reason = o["reason"]
    kind, why = detail or (None, None)
    if o["outcome"] in ("substituted", "table_only") and reason in ("data_mismatch", "no_candidate") and why:
        if kind == "subject":
            return f"{josa(name, '은')} {why} {to}."
        return f"{why} {josa(name, '을')} 그릴 수 없어 {to}."
    if o["outcome"] == "substituted":
        if reason == "unsupported_type":
            return f"{josa(name, '은')} 지원하지 않는 차트라 {to}."
        if reason == "data_mismatch":
            return f"이 자료로는 {josa(name, '을')} 그릴 수 없어 {to}."
        if reason == "validation_fallback":
            if why:
                return f"요청하신 {josa(name, '은')} {why} {to}."
            return f"요청하신 {josa(name, '은')} 계산 결과의 검증을 통과하지 못해 {to}."
        if reason == "ambiguous_scope":
            return f"차트 이름이 여러 개라 어느 질문에 적용할지 정하지 못해 요청을 적용하지 않고 {to}."
    if o["outcome"] == "table_only":
        if reason == "view_blocked" and why:
            return f"{why} 요청하신 {josa(name, '을')} 그리지 못하고 표로 보여 드립니다."
        if reason == "validation_failed" and why:
            return f"{why} 요청하신 {josa(name, '을')} 그리지 못했습니다."
        return {
            "unsupported_type": f"{josa(name, '은')} 지원하지 않는 차트라 차트 없이 표로 보여 드립니다.",
            "data_mismatch": f"이 자료로는 {josa(name, '을')} 그릴 수 없어 차트 없이 표로 보여 드립니다.",
            "view_blocked": f"질문의 조건과 맞는 자료 구성이 아니라 요청하신 {josa(name, '을')} 그리지 못하고 표로 보여 드립니다.",
            "validation_failed": f"계산이 보류되었거나 차트 검증에 실패해 요청하신 {josa(name, '을')} 그리지 못했습니다.",
            "ambiguous_scope": "차트 이름이 여러 개라 어느 질문에 적용할지 정하지 못해 요청을 적용하지 않았고, 차트 없이 표로 보여 드립니다.",
            "no_candidate": "요청하신 조건을 만족하는 차트가 없어 차트 없이 표로 보여 드립니다.",
        }.get(reason)
    if o["outcome"] == "render_failed":
        return f"{josa(name, '을')} 그리는 중 문제가 생겨 차트를 표시하지 못했습니다."
    return None            # honored · not_rendered 는 안내하지 않는다


def chart_notices(charts: list, outcomes: list[dict], titles: dict[str, str] | None = None,
                  m3: Module3Output | None = None) -> list[str]:
    """사용자용 안내 문장. 차트가 둘 이상이면 어느 차트의 안내인지 제목(없으면 chart_id)을 앞에 붙인다
    m3: [NEW 11-25 6-4] 모듈 3 출력 — 검증에서 떨어진 이유를 문장에 넣는다 (없어도 된다)"""
    by_id = {c.chart_id: c for c in map(_as_chart, charts)}
    multi = len(by_id) > 1
    notes: list[str] = []
    for o in outcomes:
        c = by_id[o["chart_id"]]
        s = _sentence(c, o, _detail(c, o, m3))
        if s:
            notes.append(f"[{(titles or {}).get(c.chart_id) or c.chart_id}] {s}" if multi else s)
    return list(dict.fromkeys(notes))


def finalize_chart_request(charts: list, m3: Module3Output | None, drawn: list | None, *, draw: bool = True,
                           error: str | None = None, stopped: bool = False, rejected: bool = False) -> dict[str, Any]:
    """일반 경로와 QA 경로가 같은 입력으로 부르는 단일 함수 → {render_status, request_outcomes, chart_notices}"""
    states = render_states(charts, m3, drawn, draw=draw, error=error, stopped=stopped, rejected=rejected)
    outcomes = request_outcomes(charts, m3, states, merged_types(drawn))       # [CHANGED 11-25] 합친 차트도 본다
    titles = {c.chart_id: c.title for c in (m3.chart_contents if m3 is not None else [])}
    return {"render_status": states, "request_outcomes": outcomes,
            "chart_notices": chart_notices(charts, outcomes, titles, m3)}         # [CHANGED 11-25 6-4] 검증 이유도 본다
