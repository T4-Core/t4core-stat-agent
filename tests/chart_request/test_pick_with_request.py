"""T-2 ~ T-6 · T-15(M2 부분): pick_chart 가 제외 · 대안 · 미지원 요청을 처리한다 (지원하지 않는 코드에서 KeyError 가 나지 않는다)"""
from backend.agent.chart_decision.chart_decision_module.chart_type_chart_picker import pick_chart
from backend.agent.chart_decision.chart_decision_module.chart_type_preference import (
    parse_chart_request, record_selection, requested_codes,
)

# 범주 17개 · 시점 1개 · 연령/성별 구분 없음: 막대는 되고 피라미드·꺾은선은 안 되는 모양
PROFILE = {"has_time": False, "n_points": 1, "n_categories": 17, "n_series": 1, "n_measures": 1, "n_dims": 1,
           "dims": [{"col": "행정구역별", "axis": "지역", "n": 17}], "non_negative": True, "has_total": False,
           "has_region": True, "n_regions": 17, "two_points_per_category": False,
           "category_axis": {"axis": "지역", "n": 17}, "series_axis": {}}


def pick(measure="raw", **kw):
    return pick_chart(measure, PROFILE, use_llm=False, **kw)


def test_unknown_code_does_not_raise():
    r = pick(requested="histogram")
    assert r["chart_type"] in ("bar", "line", None, "scatter", "bubble", "combo", "pyramid", "heatmap", "map")
    assert r["request"]["ok"] is False and "지원" in r["request"]["why"]


def test_supported_and_feasible_request_is_honored():
    r = pick(requested="bar")
    assert r["chart_type"] == "bar" and r["source"] == "request" and r["request"]["ok"] is True


def test_infeasible_request_is_reported_with_reason():
    r = pick(requested="pyramid")
    assert r["request"]["ok"] is False and r["request"]["why"]
    assert r["chart_type"] != "pyramid"


def test_excluded_chart_is_never_selected_or_fallback():
    r = pick(excluded={"bar"})
    assert r["chart_type"] != "bar" and "bar" not in r["fallback_charts"]


def test_excluded_chart_not_used_as_fallback_when_preferred_is_infeasible():
    """막대 말고 원그래프로: 원그래프가 부적합해도 제외한 막대로 대체되지 않는다 (T-6)"""
    r = pick(measure="raw", requested=["pie"], excluded={"bar"})
    assert r["chart_type"] != "bar" and "bar" not in r["fallback_charts"]


def test_alternatives_use_first_feasible():
    r = pick(requested=["pyramid", "bar"])
    assert r["chart_type"] == "bar" and r["request"]["chart"] == "pyramid" and r["request"]["ok"] is False


# ── record_selection: 구조화된 중간 사유 ──────────────────────────────────────────
def _info(text):
    return parse_chart_request("", text, "")


def test_selection_records_data_mismatch():
    info = _info("인구 피라미드로 보여줘")
    codes, excluded = requested_codes(info)
    r = pick(requested=codes, excluded=excluded)
    record_selection(info, r)
    assert info["stage"]["reason"] == "data_mismatch" and info["stage"]["selected"] == r["chart_type"]


def test_selection_keeps_unsupported_reason_and_substitutes():
    info = _info("시도별 인구를 히스토그램으로 보여줘")
    codes, _ = requested_codes(info)
    assert codes == ["bar"]
    r = pick(requested=codes)
    record_selection(info, r)
    assert info["stage"]["reason"] == "unsupported_type" and info["stage"]["selected"] == "bar"


def test_selection_view_blocked_is_recorded_without_pick():
    info = _info("인구 피라미드로 보여줘")
    record_selection(info, None, block="요청한 나눔이 표에 없음")
    assert info["stage"]["reason"] == "view_blocked" and info["stage"]["selected"] is None


def test_selection_no_candidate_when_nothing_left():
    info = _info("막대 말고 원그래프로 보여줘")
    record_selection(info, {"chart_type": None, "request": None})
    assert info["stage"]["reason"] == "no_candidate"


def test_selection_without_request_is_none():
    assert record_selection(None, {"chart_type": "bar"}) is None


def test_no_request_keeps_old_behavior():
    r = pick()
    assert r["chart_type"] is not None and r["request"] is None
