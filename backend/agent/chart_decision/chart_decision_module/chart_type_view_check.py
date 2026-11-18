"""①-2 View 적합도 (고도화 1단계) — 받은 View 가 질문에 맞는지 판단한다 (규칙, HCX 호출 없음)

View 모듈은 표를 만들며 맞추지 못한 조건을 record.notes 에 남긴다. 그 메모를 읽어
  check_view(view)        → view_fit   시점 · 나눔(성별·연령·지역) · 지표가 요청대로인지
  fit_warnings(view_fit)  → 경고 문장 목록 (errors 에 level=warning 으로 남긴다)
  block_reason(m, qb)     → (차트를 막을 이유 | None, 후보에서 뺄 차트 목록, 뺀 이유 {차트: 이유})

  - 추이를 물었는데 표의 시점이 TREND_MIN_POINTS 보다 적으면 → 차트 없음 (표만)
  - 표가 비었거나 요청한 지표가 없으면 → 차트 없음 (표만)
  - 차트에 올릴 값이 MIN_CHART_VALUES 보다 적으면 (예: 한 지역의 2015→2018 증감 = 값 1개) → 차트 없음 (표만)
    expected_values(measure, profile) 로 미리 센다. 미리 못 세는 경우는 requirements 의 min_categories_2 를 모듈 3 이 판정
  - 요청한 나눔이 표에 없으면 → 그 나눔이 꼭 필요한 차트(SPLIT_CHARTS)만 후보에서 뺀다

notes 한 개의 모양: {"slot", "dim", "type", "requested", "applied", "text"}
  type: missing(없음) · default(다른 값으로 대체) · latest_shift(최신 시점으로 옮김) · partial(일부만 맞음)
        truncated(행이 많아 잘림) · empty(빈 표)
"""
from .chart_type_measure import end_intent
from .chart_type_rules import (MIN_CHART_VALUES, SCALAR_MAX_POINTS, SCALAR_MEASURES, SPLIT_CHARTS, SPLIT_SLOTS,
                               TREND_INTENT, TREND_MIN_POINTS)

TIME_AXIS = "시점"                                # profile category_axis 의 axis 가 이것이면 범주 = 시점

REPLACED = ("default", "latest_shift")           # 요청 값 대신 다른 값을 쓴 경우


def _fmt(v):
    """메모 값 → 짧은 글. 연도 목록은 '2011~2025', 연령 범위 {'from','to'} 는 '65~'"""
    if isinstance(v, dict):
        lo, hi = v.get("from"), v.get("to")
        return f"{lo if lo is not None else ''}~{hi if hi is not None else ''}"
    if isinstance(v, (list, tuple)):
        vals = [str(x) for x in v]
        if len(vals) > 3 and all(x.isdigit() for x in vals):
            return f"{vals[0]}~{vals[-1]}"
        return ", ".join(vals)
    return "" if v is None else str(v)


def check_view(view):
    """View 의 record.notes → view_fit (dict)"""
    notes = ((view or {}).get("record") or {}).get("notes") or []
    fit = {"time": "ok", "time_requested": None, "time_applied": None,
           "missing_splits": [], "partial_splits": [], "split_requested": {},
           "indicator": "ok", "empty": False, "truncated": False,
           "notes": [n.get("text") for n in notes if n.get("text")]}
    for n in notes:
        slot, typ = n.get("slot"), n.get("type")
        if typ == "empty":
            fit["empty"] = True
        elif typ == "truncated":
            fit["truncated"] = True
        if slot == "시점":
            if n.get("requested") is not None:
                fit["time_requested"] = n["requested"]
            if typ in REPLACED and n.get("applied"):
                fit["time"], fit["time_applied"] = "replaced", n["applied"]
            elif typ == "missing" and fit["time"] == "ok":
                fit["time"] = "missing"
        elif slot in SPLIT_SLOTS:
            fit["split_requested"].setdefault(slot, n.get("requested"))
            key = {"missing": "missing_splits", "partial": "partial_splits"}.get(typ)
            if key and slot not in fit[key]:
                fit[key].append(slot)
        elif slot == "지표":
            if typ == "missing":
                fit["indicator"] = "missing"
            elif typ in REPLACED and fit["indicator"] == "ok":
                fit["indicator"] = "replaced"
    return fit


def fit_warnings(fit):
    """view_fit → 사람이 읽는 경고 문장 목록"""
    out = []
    if fit.get("time") == "replaced":
        out.append(f"요청 시점 {_fmt(fit.get('time_requested'))} → 표에는 {_fmt(fit.get('time_applied'))}만 있음")
    elif fit.get("time") == "missing":
        out.append(f"요청 시점 {_fmt(fit.get('time_requested'))}이 표에 없음")
    for slot in fit.get("missing_splits") or []:
        req = _fmt((fit.get("split_requested") or {}).get(slot))
        out.append(f"요청한 {slot}{f'({req})' if req else ''} 구분이 표에 없음")
    for slot in fit.get("partial_splits") or []:
        out.append(f"요청한 {slot} 조건이 표와 일부만 맞음")
    if fit.get("indicator") == "missing":
        out.append("요청한 지표가 표에 없음")
    elif fit.get("indicator") == "replaced":
        out.append("요청한 지표와 맞는 항목이 없어 표의 항목 전체를 씀")
    if fit.get("empty"):
        out.append("표가 비어 있음")
    if fit.get("truncated"):
        out.append("표의 행이 많아 일부만 들어옴")
    return out


def is_trend(sub_question, query_bundle):
    """추이를 묻는 질문인가. measure 규칙과 같은 순서: 하위질문 끝 → rewritten 끝 → intent 필드"""
    for text in (sub_question, query_bundle.get("rewritten")):
        kw = end_intent(text)
        if kw:
            return kw == TREND_INTENT
    return TREND_INTENT in (query_bundle.get("intent") or [])


def expected_values(measure, prof):
    """차트에 올라갈 값 수를 미리 센다 → (값 수, 설명) | None (세지 않는 measure)
    raw(또는 None): 범주 수 × 계열 수 / SCALAR_MEASURES: 시점을 접으므로 (시점이 아닌 범주 수) × 계열 수"""
    n_ser = max(prof.get("n_series") or 1, 1)
    cat = prof.get("category_axis") or {}
    if measure in (None, "raw"):
        n_cat = prof.get("n_categories") or 0
        if n_cat < 1:                               # profile 이 범주를 세지 못함 → 판단하지 않는다 (막지 않음)
            return None
        return n_cat * n_ser, f"범주 {n_cat}개 × 계열 {n_ser}개"
    if measure in SCALAR_MEASURES:
        # 시점이 3개 이상이면 해마다의 증감(값 여러 개)일 수도 있어 미리 세지 않는다 → 안전망(min_categories_2)이 모듈 3 결과로 판정
        if (prof.get("n_points") or 0) > SCALAR_MAX_POINTS:
            return None
        time_cat = not cat or cat.get("axis") == TIME_AXIS
        n_cat = 1 if time_cat else (cat.get("n") or prof.get("n_categories") or 1)
        what = "시점 말고 나누는 범주 없음" if time_cat else f"범주 {n_cat}개"
        return n_cat * n_ser, f"{measure} 결과 = {what} × 계열 {n_ser}개"
    return None


def block_reason(m, query_bundle):
    """짝 하나(m: view_fit · profile · sub_question 이 붙은 것) → (막을 이유 | None, 뺄 차트 목록, {차트: 뺀 이유})"""
    fit, prof = m.get("view_fit") or {}, m.get("profile") or {}
    if fit.get("empty"):
        return "표가 비어 있어 차트를 그릴 수 없음", [], {}
    if fit.get("indicator") == "missing":
        return "요청한 지표가 표에 없어 차트를 그릴 수 없음", [], {}
    n = prof.get("n_points", 0)
    if is_trend(m.get("sub_question"), query_bundle) and n < TREND_MIN_POINTS:
        pts = ", ".join(map(str, prof.get("periods") or fit.get("time_applied") or []))
        return f"추이를 물었지만 표의 시점이 {n}개{f'({pts})' if pts else ''}", [], {}
    counted = expected_values(m.get("measure"), prof)
    if counted and counted[0] < MIN_CHART_VALUES:
        return f"차트에 올릴 값이 {counted[0]}개뿐이라 표로 보여 줌 ({counted[1]})", [], {}
    exclude, why = [], {}
    for slot in fit.get("missing_splits") or []:
        for chart in SPLIT_CHARTS.get(slot, []):
            if chart not in exclude:
                exclude.append(chart)
                why[chart] = f"요청한 {slot} 구분이 표에 없음"
    return None, exclude, why
