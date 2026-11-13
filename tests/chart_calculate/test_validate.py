"""[NEW] specs.py · validate.py — 차트 15종 표와 requirements 판정 (명세 7·8장)"""
import pytest

from backend.agent.chart_calculate.specs import SPECS, requirements_for
from backend.agent.chart_calculate.validate import check_chart
from backend.schemas.chart import ChartContent, ChartType
from typing import get_args


def content(chart_type, columns, rows, encoding, axis=None):
    return ChartContent(chart_id="c1", chart_type=chart_type, measure="raw", title="t", columns=columns, rows=rows,
                        encoding=encoding, axis=axis or {})


def check(c, given=None, **kw):
    return check_chart(c, requirements_for(c.chart_type, given), **kw)


LONG = ["시점", "항목", "값"]
TIME = {"x": {"type": "time"}, "y": {"type": "numeric"}}
XY = {"x": "시점", "y": "값", "series": "항목"}


def trend(n, chart="line", value=lambda i: 100.0 + i):
    return content(chart, LONG, [[str(2020 + i), "혼인건수", value(i)] for i in range(n)], XY, TIME)


def parts(n, chart="pie", values=None, labels=None):
    labels = labels or [f"항목{i}" for i in range(n)]
    return content(chart, ["항목", "값"], [[l, (values or [10.0] * n)[i]] for i, l in enumerate(labels)],
                   {"label": "항목", "value": "값"})


def test_specs_cover_all_15_chart_types():
    assert set(SPECS) == set(get_args(ChartType))
    assert all(set(s.non_negative) <= set(s.required) for s in SPECS.values())


def test_requirements_for_merges_given_and_defaults():
    assert requirements_for("line", ["min_points_3", "custom_x"]) == ["min_points_3", "custom_x", "time_axis_required"]
    assert requirements_for("bar") == ["max_categories_20"]


def test_line_passes_like_spec_c1():
    r = check(trend(5), ["time_axis_required", "min_points_3"])
    assert r.passed and r.checked == ["data_present", "required_roles", "time_axis_required", "min_points_3"]
    assert r.failed == [] and r.reasons == []


def test_line_too_few_points():
    r = check(trend(2))
    assert not r.passed and r.failed == ["min_points_3"] and r.reasons == ["점 2개 (최소 3개)"]


def test_pie_too_many_categories_like_spec_c4():
    r = check(parts(17))
    assert r.failed == ["max_categories_5"] and r.reasons == ["항목 17개 (최대 5개)"]
    assert r.checked == ["data_present", "required_roles", "non_negative", "parts_sum_to_total", "max_categories_5"]
    bar = content("bar", ["항목", "값"], parts(17).rows, {"x": "항목", "y": "값"})    # 대체 차트는 통과
    assert check(bar).passed and check(bar).checked == ["data_present", "required_roles", "max_categories_20"]


def test_data_errors_stop_before_chart_checks():
    r = check(trend(5), data_errors=["truncated: 행이 2000개를 넘어 앞부분만 사용"])
    assert r.failed == ["data_present"] and r.checked == ["data_present"] and r.reasons[0].startswith("truncated")
    assert check(trend(0)).reasons == ["행이 없음"]


def test_required_roles():
    c = content("stacked_bar", LONG, trend(3).rows, {"x": "시점", "y": "값"})
    r = check(c)
    assert r.failed == ["required_roles"] and r.reasons == ["필수 역할 없음: ['series']"]
    assert r.checked == ["data_present", "required_roles"]            # 역할이 없으면 나머지는 판정하지 않는다
    bad = content("line", LONG, trend(3).rows, {"x": "연도", "y": "값"}, TIME)
    assert check(bad).reasons == ["없는 열을 가리킴: ['x→연도']"]


def test_bar_does_not_require_category_type_on_x():
    """line → bar 대체: 가로축이 시점이어도 막대는 그릴 수 있다"""
    assert check(trend(5, "bar")).passed


@pytest.mark.parametrize("chart", ["area", "stacked_bar"])
def test_negative_values_fail(chart):
    r = check(trend(4, chart, value=lambda i: -5.0 if i == 1 else 10.0))
    assert "non_negative" in r.failed and "y에 음수 1개" in r.reasons


def test_negative_allowed_on_line_and_bar():
    assert check(trend(4, "line", value=lambda i: -5.0)).passed and check(trend(4, "bar", value=lambda i: -5.0)).passed


def test_bubble_only_size_must_be_non_negative():
    cols, enc = ["지역", "혼인건수", "출생아수", "인구수"], {"x": "혼인건수", "y": "출생아수", "size": "인구수", "label": "지역"}
    assert check(content("bubble", cols, [["서울", -1.0, -2.0, 3.0]], enc)).passed
    assert check(content("bubble", cols, [["서울", 1.0, 2.0, -3.0]], enc)).failed == ["non_negative"]
    same = content("bubble", cols, [["서울", 1.0, 2.0, 3.0]], {**enc, "size": "혼인건수"})
    assert same and check(same).failed == ["three_measures_required"]


def test_parts_duplicate_and_total_label():
    assert check(parts(3, labels=["가", "가", "나"])).reasons == ["구성 항목 중복: 가"]
    assert check(parts(3, labels=["가", "나", "계"])).reasons == ["구성 항목에 총계가 섞임: ['계']"]


def test_parts_compared_with_question_total():
    pie = parts(3, values=[50.0, 30.0, 20.0])
    assert check(pie, totals={None: 100.3}).passed                       # 오차 0.3% → 허용
    assert check(pie, totals={None: 120.0}).reasons == ["구성 항목의 합 100 ≠ 총계 120"]
    assert check(pie).passed                                            # 총계 없음(scope=selected) → 중복만 확인


def test_stacked_bar_parts_are_checked_within_same_x():
    rows = [["2024", "남", 60.0], ["2024", "여", 40.0], ["2025", "남", 55.0], ["2025", "여", 40.0]]
    c = content("stacked_bar", LONG, rows, XY)
    assert check(c).passed                                              # 같은 '남' 이 시점마다 있어도 중복이 아니다
    r = check(c, totals={"2024": 100.0, "2025": 100.0})
    assert r.failed == ["parts_sum_to_total"] and r.reasons == ["구성 항목의 합 95 ≠ 총계 100 (2025)"]


def test_combo_needs_two_measures():
    enc = {"x": "시점", "y": "값", "y2": "값", "series": "항목"}      # long 형식: 지표는 series 로 구분
    rows = [[str(2021 + i), name, v] for i in range(3) for name, v in [("혼인건수", 100.0 + i), ("조혼인율", 4.0)]]
    assert check(content("combo", LONG, rows, enc, TIME)).passed
    one = content("combo", LONG, rows[::2], enc, TIME)
    assert check(one).failed == ["two_series_required"]


def test_pyramid_needs_two_groups_and_category_axis():
    cols, enc = ["연령", "성별", "값"], {"y": "연령", "group": "성별", "value": "값"}
    rows = [["0-9세", "남", 10.0], ["0-9세", "여", 9.0], ["10-19세", "남", 12.0], ["10-19세", "여", 11.0]]
    assert check(content("pyramid", cols, rows, enc, {"y": {"type": "category"}})).passed
    one = content("pyramid", cols, rows[::2], enc)
    assert check(one).failed == ["two_series_required", "category_axis_required"]


def test_scatter_dumbbell_radar_map():
    pts = [["지역%d" % i, float(i), float(i * 2)] for i in range(4)]
    scatter = content("scatter", ["지역", "가", "나"], pts, {"x": "가", "y": "나", "label": "지역"})
    assert check(scatter).reasons == ["점 4개 (최소 5개)"]
    dumb = content("dumbbell", ["지역", "2021", "2025"], [["서울", 1.0, 2.0], ["부산", 1.0, None]],
                   {"label": "지역", "start": "2021", "end": "2025"})
    assert check(dumb).reasons == ["두 값이 모두 있지 않은 범주 1개"]
    radar = content("radar", ["지표", "지역", "값"], [["가", "서울", 1.0], ["나", "서울", 2.0]],
                    {"label": "지표", "series": "지역", "value": "값"})
    assert check(radar).reasons == ["항목 2개 (최소 3개)"]
    geo = content("map", ["지역", "값"], [["서울", 1.0]], {"region": "지역", "value": "값"})
    assert check(geo).passed


def test_unknown_requirement_is_reported_not_failed():
    r = check(trend(5), ["brand_new_rule"])
    assert r.passed and "brand_new_rule" not in r.checked
    assert r.reasons == ["알 수 없는 조건: brand_new_rule (판정하지 않음)"]
