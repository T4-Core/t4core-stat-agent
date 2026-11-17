"""⑥-1 겹쳐 그리기 표시 (고도화 5단계) — 하위질문 2개의 차트를 모듈 5 가 그림 하나로 겹쳐 그려도 되는지 (규칙)

  find_overlays(ms, charts, query_bundle) → (overlays, 판단 기록)

  모듈 2 는 차트를 항상 하위질문마다 1개씩 만든다 (모듈 3 은 서로 다른 표의 하위질문 둘을 한 차트로 계산하지 못함).
  아래 조건을 **모두** 만족할 때만 chart_plan.overlays 에 표시하고, 모듈 5 가 두 차트에 더해 겹친 그림 1개를 그린다.
    1. 하위질문(차트) 정확히 2개           2. 두 차트 모두 차트 있음 (chart_type 있음)
    3. 의도가 추이 또는 비교               4. 두 차트 유형이 같고 line 또는 bar
    5. measure 같음                       6. x축 같음 (기간 · 비교축 · 범주 축과 개수)
    7. 두 차트 모두 계열 1개
  그리는 방식: 두 값의 최댓값 비율 ≥ OVERLAY_SCALE_RATIO 이거나 단위가 다르면 → combo (큰 값 막대 y · 작은 값 선 y2)
              아니면 (크기 비슷 · 같은 단위) → lines / bars (축 하나)
  (모듈 5 는 그린 두 차트의 x 값이 정확히 같은지 한 번 더 확인한다)
"""
from .chart_type_rules import OVERLAY_INTENTS, OVERLAY_MODES, OVERLAY_SCALE_RATIO


def _max_abs(m):
    """걸러진 표의 값 열 최댓값 (절댓값). 값이 없으면 None"""
    t = (m.get("filtered_view") or {}).get("record", {}).get("table", {})
    cols, rows = t.get("columns") or [], t.get("rows") or []
    if "값" not in cols:
        return None
    i = cols.index("값")
    vals = []
    for r in rows:
        try:
            vals.append(abs(float(str(r[i]).replace(",", ""))))
        except (TypeError, ValueError):
            pass
    return max(vals) if vals else None


def find_overlays(ms, charts, query_bundle):
    """ms: 짝(하위질문) 목록, charts: 같은 순서의 차트 dict 목록 (chart_type · measure 확정 후)
    반환: (overlays [{"overlay_id", "charts", "mode", "axes", "reason"}], 판단 기록 [문장])"""
    def no(why):
        return [], [f"겹쳐 그리기 안 함: {why}"]

    if len(ms) != 2 or len(charts) != 2:
        return no(f"하위질문 {len(ms)}개 (정확히 2개 필요)")
    a, b = ms
    ca, cb = charts
    if not ca.get("chart_type") or not cb.get("chart_type"):
        return no("한쪽 차트가 없음 (표만)")
    intents = set(query_bundle.get("intent") or [])
    if not intents & set(OVERLAY_INTENTS) or intents - set(OVERLAY_INTENTS) - {"값 조회"}:
        return no(f"의도 {sorted(intents)} (추이 · 비교만)")
    if ca["chart_type"] != cb["chart_type"] or ca["chart_type"] not in OVERLAY_MODES:
        return no(f"차트 유형 {ca['chart_type']} · {cb['chart_type']} (둘 다 line 또는 bar 여야 함)")
    if ca.get("measure") != cb.get("measure"):
        return no(f"measure {ca.get('measure')} · {cb.get('measure')} 다름")
    fa, fb = a.get("sub_filter") or {}, b.get("sub_filter") or {}
    if fa.get("시점") != fb.get("시점"):
        return no("기간이 다름")
    if fa.get("비교축") != fb.get("비교축"):
        return no("비교축이 다름")
    pa, pb = a.get("profile") or {}, b.get("profile") or {}
    xa, xb = pa.get("category_axis") or {}, pb.get("category_axis") or {}
    if (xa.get("axis"), xa.get("n")) != (xb.get("axis"), xb.get("n")):
        return no(f"x축이 다름 ({xa.get('axis')} {xa.get('n')}개 · {xb.get('axis')} {xb.get('n')}개)")
    if pa.get("n_series", 1) != 1 or pb.get("n_series", 1) != 1:
        return no("한쪽 차트에 계열이 여러 개")

    va, vb = _max_abs(a), _max_abs(b)
    ratio = (max(va, vb) / min(va, vb)) if va and vb else None
    ua, ub = ((m.get("filtered_view") or {}).get("filter_info", {}).get("unit") for m in (a, b))
    units_differ = bool(ua and ub and ua != ub)                       # 단위가 다르면 축 하나에 그릴 수 없음
    ida, idb = ca["chart_id"], cb["chart_id"]
    if (ratio is not None and ratio >= OVERLAY_SCALE_RATIO) or units_differ:
        big, small = (ida, idb) if (va or 0) >= (vb or 0) else (idb, ida)
        mode, axes = "combo", {big: "y", small: "y2"}
        why = f"단위 다름 ({ua} · {ub})" if units_differ and not (ratio and ratio >= OVERLAY_SCALE_RATIO)             else f"크기 차이 {ratio:,.0f}배 (≥ {OVERLAY_SCALE_RATIO})"
        reason = f"같은 x축 · {why} → 막대({big}) + 선({small})"
    else:
        mode, axes = OVERLAY_MODES[ca["chart_type"]], {}
        reason = f"같은 x축 · 크기 차이 {ratio:,.1f}배 → {'선' if mode == 'lines' else '막대'} 2개" if ratio else "같은 x축"
    return [{"overlay_id": f"{ida}+{idb}", "charts": [ida, idb], "mode": mode, "axes": axes, "reason": reason}], \
        [f"겹쳐 그리기: {mode} — {reason}"]
