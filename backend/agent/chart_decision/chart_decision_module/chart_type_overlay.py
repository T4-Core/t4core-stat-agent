"""⑥-1 겹쳐 그리기 표시 (고도화 5단계) — 하위질문 여러 개의 차트를 모듈 5 가 그림 하나로 합쳐 그려도 되는지 (규칙)

  find_overlays(ms, charts, query_bundle) → (overlays, 판단 기록)

  모듈 2 는 차트를 항상 하위질문마다 1개씩 만든다 (모듈 3 은 서로 다른 표의 하위질문 둘을 한 차트로 계산하지 못함).
  아래 조건을 **모두** 만족할 때만 chart_plan.overlays 에 표시하고, 모듈 5 가 원래 차트들은 그대로 두고 합친 그림 1개를 더한다.

  ① 관계 차트 — [NEW 11-25] 사용자가 산점도 · 버블 · 레이더를 요청했을 때만. 먼저 본다
    1. 모든 차트의 요청 1순위가 같은 관계 차트        2. 차트 수: 산점도 2 · 버블 3 · 레이더 3~8 (RELATION_OVERLAYS)
    3. 모든 차트 있음 (chart_type 있음)              4. measure 같음
    5. 시점이 하나이고 모두 같음                      6. 범주 축이 같음 (시점 축은 아님). 범주 개수는 달라도 된다
                                                       (모듈 5 가 범주 이름으로 짝짓고, 한쪽에만 있는 범주는 빼고 알린다)
       [NEW 11-27] 레이더는 5 · 6 대신 '범주 축이 모두 시점이고 시점 목록이 같음' 도 된다 (시점마다 다각형)
    7. 모두 계열 1개                                 8. 범주 수: 산점도 5개 이상 · 버블 3개 이상 · 레이더 8개 이하
    9. 레이더는 단위가 모두 같음 (반지름 축 하나). [NEW 11-27] measure 가 지수(index)면 보지 않는다 (같은 척도로 환산)
    axes: 산점도 {c1: x, c2: y} · 버블 {c1: x, c2: y, c3: size} (하위질문 순서) · 레이더는 없음 (지표가 축 이름)
    이전: 하위질문마다 막대 1개씩만 나가고 요청한 차트는 그려지지 않았다 (15유형 테스트 산점도 · 버블 · 레이더)
  ② 같은 x축 겹치기 — 지금까지의 규칙. [CHANGED 11-25] 차트 2개만 → 2개 이상
    1. 하위질문(차트) 2개 이상            2. 모든 차트 있음 (chart_type 있음)
    3. 의도가 추이 또는 비교               4. 차트 유형이 모두 같고 line 또는 bar
    5. measure 같음                       6. x축 같음 (기간 · 비교축 · 범주 축과 개수)
    7. 모든 차트 계열 1개
    그리는 방식 (2개)    최댓값 비율 ≥ OVERLAY_SCALE_RATIO 이거나 단위가 다르면, 또는 사용자가 콤보를 요청했으면
                         → combo (큰 값 막대 y · 작은 값 선 y2). 아니면 → lines / bars (축 하나)
               (3개 이상) 축이 하나뿐이라 단위가 같고 최댓값 비율 < OVERLAY_SCALE_RATIO 일 때만 lines / bars. 아니면 겹치지 않음
  (모듈 5 는 그린 차트들의 x 값이 맞는지 한 번 더 확인한다)
"""
from backend.agent.period_cycle import cycle_info

from .chart_type_rules import OVERLAY_INTENTS, OVERLAY_MODES, OVERLAY_SCALE_RATIO, RELATION_OVERLAYS

TIME = "시점"
RELATION_ROLES = {"scatter": ("x", "y"), "bubble": ("x", "y", "size")}     # 하위질문 순서대로 맡는 역할 (레이더는 없음)


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


def _unit(m):
    return ((m.get("filtered_view") or {}).get("filter_info") or {}).get("unit")


def _first_request(chart):
    """차트의 요청 1순위 (지원하는 차트 코드). 요청이 없거나, 어느 질문 것인지 몰라 적용하지 않은 요청이면 None"""
    req = chart.get("request") or {}
    if not (req.get("stage") or {}).get("applied", True):
        return None
    codes = [n.get("code") for n in req.get("preferred") or [] if n.get("supported") and n.get("code")]
    return codes[0] if codes else None


def _relation(ms, charts):
    """① 관계 차트 → (overlay | None, 판단 기록 | None). 관계 차트 요청이 없으면 (None, None) → ② 로"""
    codes = {_first_request(c) for c in charts}
    kind = next(iter(codes)) if len(codes) == 1 else None
    if kind not in RELATION_OVERLAYS or len(charts) < 2:       # 차트 1개는 합칠 것이 없다 (기록은 ② 가 남긴다)
        return None, None
    lo, hi, cat_lo, cat_hi = RELATION_OVERLAYS[kind]
    # [NEW 11-27] 한 해의 월 · 분기가 범주인 레이더 ('2025년 전국 월별 출생·사망·혼인·이혼'): 축 = 주기 칸(3~12), 다각형 = 차트(지표, 2~8개)
    first_periods = {tuple(str(x) for x in (m.get("profile") or {}).get("periods") or []) for m in ms}
    cyc = cycle_info(next(iter(first_periods))) if kind == "radar" and len(first_periods) == 1 else None
    by_cycle = bool(cyc) and len(cyc["years"]) == 1
    if by_cycle:                                              # 차트 수(다각형) 2~8 · 범주 수(축) 3~12 로 바꿔 본다
        lo, hi, cat_lo, cat_hi = 2, cat_hi, 3, hi

    def no(why):
        return None, f"{kind} 합치기 안 함: {why}"

    if not lo <= len(charts) <= hi or len(ms) != len(charts):
        return no(f"하위질문 {len(charts)}개 ({lo}개 필요)" if lo == hi else f"하위질문 {len(charts)}개 ({lo}~{hi}개 필요)")
    if any(not c.get("chart_type") for c in charts):
        return no("차트가 없는 하위질문이 있음 (표만)")
    if len({c.get("measure") for c in charts}) > 1:
        return no(f"measure 다름 {[c.get('measure') for c in charts]}")
    profiles = [m.get("profile") or {} for m in ms]
    periods = [tuple(str(p) for p in pr.get("periods") or []) for pr in profiles]
    cats = [pr.get("category_axis") or {} for pr in profiles]
    names = {x.get("axis") for x in cats}
    # [NEW 11-27] 레이더는 시점이 범주인 차트들도 합친다 (지역 하나 · 지표 하나씩, 시점이 모두 같음) → 시점마다 다각형.
    #   '전국의 1995·2000·2010·2020·2025년 6개 지표를 0~100 지수로 레이더' (레이더 20선 R10)
    by_time = kind == "radar" and names == {TIME} and len(set(periods)) == 1 and len(periods[0]) >= 2
    if not by_time:
        if any(len(p) != 1 for p in periods) or len(set(periods)) > 1:
            return no(f"시점이 하나가 아니거나 서로 다름 {[list(p) for p in periods]}")
        if len(names) != 1 or None in names or TIME in names:
            return no(f"범주 축이 다르거나 없음 {[x.get('axis') for x in cats]}")
    if any(pr.get("n_series", 1) != 1 for pr in profiles):
        return no("계열이 여러 개인 차트가 있음")
    ns = [x.get("n") or 0 for x in cats]
    if min(ns) < cat_lo or (cat_hi is not None and max(ns) > cat_hi):
        need = f"{cat_lo}개 이상" + (f" {cat_hi}개 이하" if cat_hi is not None else "")
        return no(f"범주 {min(ns)}~{max(ns)}개 ({need} 필요)")
    units = [_unit(m) for m in ms]
    # [CHANGED 11-27] 지수(index)는 모듈 3 이 단위 없는 같은 척도로 환산하므로 원래 단위가 달라도 된다 (천명당 · 명 · 합계출산율)
    indexed = charts[0].get("measure") == "index"
    if kind == "radar" and not indexed and (None in units or len(set(units)) > 1):
        return no(f"단위가 다르거나 모름 {units} (레이더는 반지름 축 하나)")
    ids = [c["chart_id"] for c in charts]
    axes = dict(zip(ids, RELATION_ROLES.get(kind, ())))
    what = " · ".join(f"{cid}={role}" for cid, role in axes.items()) if axes else f"지표 축 {len(ids)}개"
    when = f"시점 {periods[0][0]}~{periods[0][-1]} (시점마다 다각형)" if by_time else f"시점 {periods[0][0]}"
    if by_cycle:
        what, when = f"{cyc['col']} 축 {len(periods[0])}개 · 지표마다 다각형 {len(ids)}개", f"{cyc['years'][0]}년"
    reason = f"요청한 {kind} · {next(iter(names))} {min(ns)}~{max(ns)}개 · {when}{' · 지수(단위 없음)' if indexed else ''} → {what}"
    return {"overlay_id": "+".join(ids), "charts": ids, "mode": kind, "axes": axes, "reason": reason}, \
        f"합치기: {kind} — {reason}"


def _same_axis(ms, charts, query_bundle):
    """② 같은 x축 겹치기 → (overlay | None, 판단 기록)"""
    def no(why):
        return None, f"겹쳐 그리기 안 함: {why}"

    if len(ms) < 2 or len(charts) != len(ms):
        return no(f"하위질문 {len(ms)}개 (2개 이상 필요)")
    if any(not c.get("chart_type") for c in charts):
        return no("한쪽 차트가 없음 (표만)")
    intents = set(query_bundle.get("intent") or [])
    if not intents & set(OVERLAY_INTENTS) or intents - set(OVERLAY_INTENTS) - {"값 조회"}:
        return no(f"의도 {sorted(intents)} (추이 · 비교만)")
    types = [c["chart_type"] for c in charts]
    if len(set(types)) > 1 or types[0] not in OVERLAY_MODES:
        return no(f"차트 유형 {' · '.join(types)} (모두 line 이거나 모두 bar 여야 함)")
    if len({c.get("measure") for c in charts}) > 1:
        return no(f"measure {' · '.join(str(c.get('measure')) for c in charts)} 다름")
    filters = [m.get("sub_filter") or {} for m in ms]
    if any(f.get("시점") != filters[0].get("시점") for f in filters):
        return no("기간이 다름")
    if any(f.get("비교축") != filters[0].get("비교축") for f in filters):
        return no("비교축이 다름")
    profiles = [m.get("profile") or {} for m in ms]
    xs = [((pr.get("category_axis") or {}).get("axis"), (pr.get("category_axis") or {}).get("n")) for pr in profiles]
    if len(set(xs)) > 1:
        return no(f"x축이 다름 ({' · '.join(f'{a} {n}개' for a, n in xs)})")
    if any(pr.get("n_series", 1) != 1 for pr in profiles):
        return no("한쪽 차트에 계열이 여러 개")

    vals = [_max_abs(m) for m in ms]
    known = [v for v in vals if v]
    ratio = (max(known) / min(known)) if len(known) == len(vals) else None
    units = [_unit(m) for m in ms]
    units_differ = len({u for u in units if u}) > 1                   # 단위가 다르면 축 하나에 그릴 수 없음 (모르는 단위는 보지 않음)
    ids = [c["chart_id"] for c in charts]
    big_gap = ratio is not None and ratio >= OVERLAY_SCALE_RATIO
    if len(ids) == 2:
        wants_combo = all(_first_request(c) == "combo" for c in charts)
        if big_gap or units_differ or wants_combo:
            va, vb = vals
            big, small = (ids[0], ids[1]) if (va or 0) >= (vb or 0) else (ids[1], ids[0])
            mode, axes = "combo", {big: "y", small: "y2"}
            if big_gap:
                why = f"크기 차이 {ratio:,.0f}배 (≥ {OVERLAY_SCALE_RATIO})"
            elif units_differ:
                why = f"단위 다름 ({units[0]} · {units[1]})"
            else:
                why = "콤보 요청"
            reason = f"같은 x축 · {why} → 막대({big}) + 선({small})"
        else:
            mode, axes = OVERLAY_MODES[types[0]], {}
            reason = f"같은 x축 · 크기 차이 {ratio:,.1f}배 → {'선' if mode == 'lines' else '막대'} 2개" if ratio else "같은 x축"
    else:                                                             # 3개 이상: 축이 하나뿐 (combo 는 두 축이라 2개만)
        if units_differ:
            return no(f"차트 {len(ids)}개의 단위가 다름 {units} (3개 이상은 축 하나에만 그림)")
        if big_gap:
            return no(f"차트 {len(ids)}개의 크기 차이 {ratio:,.0f}배 (≥ {OVERLAY_SCALE_RATIO}, 3개 이상은 축 하나에만 그림)")
        mode, axes = OVERLAY_MODES[types[0]], {}
        reason = f"같은 x축 · 크기 차이 {ratio:,.1f}배 → {'선' if mode == 'lines' else '막대'} {len(ids)}개" if ratio \
            else f"같은 x축 · {'선' if mode == 'lines' else '막대'} {len(ids)}개"
    return {"overlay_id": "+".join(ids), "charts": ids, "mode": mode, "axes": axes, "reason": reason}, \
        f"겹쳐 그리기: {mode} — {reason}"


def find_overlays(ms, charts, query_bundle):
    """ms: 짝(하위질문) 목록, charts: 같은 순서의 차트 dict 목록 (chart_type · measure 확정 후)
    반환: (overlays [{"overlay_id", "charts", "mode", "axes", "reason"}], 판단 기록 [문장])
    [CHANGED 11-25] ① 관계 차트(요청한 산점도 · 버블 · 레이더)를 먼저 보고, 아니면 ② 같은 x축 겹치기 (2개 → N개)"""
    notes = []
    ov, note = _relation(ms, charts)
    if note:
        notes.append(note)
    if ov is None:
        ov, note = _same_axis(ms, charts, query_bundle)
        notes.append(note)
    return ([ov] if ov else []), notes
