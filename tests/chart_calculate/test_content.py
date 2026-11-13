"""[NEW] content.py — ChartContent 구성, 대체 차트 재구성, validation 출력 (명세 5·7장)"""
from backend.agent.chart_calculate.content import build_chart, build_charts
from backend.agent.chart_calculate.display import make_display
from backend.schemas.chart import ChartPlan, Plan
from tests.chart_calculate._views import TRUNCATED, VID, view

YEARS = ["2021", "2022", "2023", "2024", "2025"]
NATION = {"행정구역별": ["전국"]}
REGION_COLS = ["시점", "행정구역별", "항목", "값"]


def plan(chart_type, fallback=None, measure="raw", select=None, steps=None, output=None, rid=VID, chart_id="c1"):
    return Plan.model_validate({
        "chart_id": chart_id, "record_id": rid, "chart_type": chart_type, "fallback_chart": fallback,
        "measure": measure, "select": select if select is not None else {**NATION, "항목": ["혼인건수(건)"], "시점": YEARS},
        "steps": steps or [{"step_id": "s1", "op": measure, "display_ref": "d1"}], "output": output})


def operand(item, select=None, rid=VID):
    return [{"role": "value", "record_id": rid, "item": item, "select": NATION if select is None else select}]


def regions(n, value=lambda i: 10.0 + i, item="인구수(명)", times=("2025",), **meta):
    return view([[t, f"지역{i:02d}", item, value(i)] for t in times for i in range(n)], REGION_COLS, **meta)


def test_line_matches_spec_c1():
    """명세 5장 예시 c1 과 같은 모양

    [CHANGED] y 축의 min · max 는 line 도 데이터 범위 + 여백 5% 를 보기 좋은 값으로 반올림해 채운다 (axis.py, 명세 10.6).
    실제 최솟값은 2022 년의 191,690 이라 180,000 ~ 250,000 이다. 명세 5장의 c1 예시와 8장 line 행도 2026-11-12 에
    이 값으로 고쳤다 (팀 합의 전). 처음 명세(2026-11-09)의 예시에는 y 축에 min · max 가 없었다.
    """
    content, v = build_chart(plan("line", "bar"), [view()], ["time_axis_required", "min_points_3"])
    assert content.model_dump(exclude_none=True) == {
        "chart_id": "c1", "chart_type": "line", "measure": "raw", "title": "2021~2025 혼인건수 연도별 추이",
        "encoding": {"x": "시점", "y": "값", "series": "항목"},
        "axis": {"x": {"label": "시점", "type": "time"},
                 "y": {"label": "혼인건수", "type": "numeric", "scale": "linear", "display_ref": "d1",
                       "min": 180000.0, "max": 250000.0}},
        "options": {}, "columns": ["시점", "항목", "값"],
        "rows": [["2021", "혼인건수", 192507.0], ["2022", "혼인건수", 191690.0], ["2023", "혼인건수", 193657.0],
                 ["2024", "혼인건수", 222412.0], ["2025", "혼인건수", 240326.0]],
        "record_ids": [VID], "warnings": []}
    assert v.model_dump() == {
        "original": {"chart_type": "line", "passed": True,
                     "checked": ["data_present", "required_roles", "time_axis_required", "min_points_3"],
                     "failed": [], "reasons": []},
        "fallback": None, "final_chart_type": "line", "content_built": True}


def test_pie_falls_back_to_bar_like_spec_c4():
    content, v = build_chart(plan("pie", "bar", select={}, steps=[
        {"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}]), [regions(17)])
    assert v.original.failed == ["max_categories_5"] and v.original.reasons == ["항목 17개 (최대 5개)"]
    assert v.fallback.passed and v.fallback.checked == ["data_present", "required_roles", "max_categories_20"]
    assert (v.final_chart_type, v.content_built) == ("bar", True)
    assert content.chart_type == "bar" and content.encoding == {"x": "행정구역별", "y": "값"}
    assert content.options == {"orientation": "vertical"} and content.axis["y"].min == 0
    assert content.title == "2025 인구수 행정구역별 비교"


def test_both_fail_builds_nothing():
    content, v = build_chart(plan("pie", "bar", select={}, steps=[
        {"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}]), [regions(25)])
    assert content is None and not v.fallback.passed
    assert (v.final_chart_type, v.content_built) == (None, False)


def test_no_fallback_chart():
    content, v = build_chart(plan("line", select={**NATION, "항목": ["혼인건수(건)"], "시점": ["2024", "2025"]}), [view()])
    assert content is None and v.fallback is None and v.original.failed == ["min_points_3"]


def test_data_error_skips_fallback():
    """① 실패는 차트를 바꿔도 해결되지 않는다"""
    content, v = build_chart(plan("line", "bar"), [view(notes=[TRUNCATED])])
    assert content is None and v.fallback is None
    assert v.original.failed == ["data_present"] and v.original.reasons[0].startswith("truncated")


def test_missing_values_become_warning():
    p = plan("bar", select={"항목": ["혼인건수(건)"], "시점": ["2025"]})          # 서울 2025 는 None
    content, _ = build_chart(p, [view()])
    assert content.rows == [["2025", "혼인건수", 240326.0]] and content.warnings == ["값이 비어 제외한 행 1개"]


def combo_plan(fallback="line"):
    sel = {**NATION, "시점": YEARS}
    return plan("combo", fallback, select={**sel, "항목": ["혼인건수(건)", "조혼인율(천명당)"]}, steps=[
        {"step_id": "s1", "op": "raw", "display_ref": "d1", "operands": operand("혼인건수(건)", sel)},
        {"step_id": "s2", "op": "raw", "display_ref": "d5", "operands": operand("출생아수(명)", sel)}],
        output=[{"step_id": "s1", "role": "y"}, {"step_id": "s2", "role": "y2"}])


def test_combo_two_axes():
    content, v = build_chart(combo_plan(), [view()])
    assert v.final_chart_type == "combo"
    assert content.encoding == {"x": "시점", "y": "값", "series": "항목", "y2": "값"}
    assert content.options == {"marks": {"y": "bar", "y2": "line"}, "series_axis": {"혼인건수": "y", "출생아수": "y2"}}
    assert (content.axis["y"].label, content.axis["y"].display_ref) == ("혼인건수", "d1")
    assert (content.axis["y2"].label, content.axis["y2"].display_ref) == ("출생아수", "d5")
    assert len(content.rows) == 10 and content.title == "2021~2025 혼인건수 · 출생아수 연도별 추이"


def test_combo_without_y2_falls_back_to_line():
    p = combo_plan()
    p.output = None                                    # 갈래 하나만 남는다 → y2 없음
    p.steps = [p.steps[0]]
    content, v = build_chart(p, [view()])
    assert v.original.failed == ["required_roles"] and v.final_chart_type == "line"
    assert "y2" not in content.encoding and content.options == {}


def test_one_branch_with_two_items_warns_mixed_units():
    """operands 없이 select 로 항목 둘을 고른 계획: 범례는 항목 이름, 단위가 다르면 경고"""
    two = plan("line", select={**NATION, "시점": YEARS, "항목": ["혼인건수(건)", "조혼인율(천명당)"]})
    content, _ = build_chart(two, [view()])
    assert content.title == "2021~2025 혼인건수 · 조혼인율 연도별 추이"
    assert content.rows[-1] == ["2025", "조혼인율", 4.7] and content.axis["y"].label == "값"
    assert content.warnings == ["단위가 다른 지표를 한 축에 그림"]


def test_rank_bar_is_horizontal_in_rank_order():
    p = plan("bar", measure="rank", select={}, steps=[
        {"step_id": "s1", "op": "rank", "top_n": 3, "operands": operand("인구수(명)", {})}])
    content, _ = build_chart(p, [regions(6)])
    assert content.options == {"orientation": "horizontal"}
    assert [r[content.columns.index("행정구역별")] for r in content.rows] == ["지역05", "지역04", "지역03"]
    assert content.title == "2025 인구수 행정구역별 순위"


def test_negative_change_area_falls_back_to_line():
    p = plan("area", "line", measure="change", steps=[{"step_id": "s1", "op": "change", "base": "prev"}])
    content, v = build_chart(p, [view()])
    assert v.original.failed == ["non_negative"] and content.chart_type == "line"
    assert content.rows[0] == ["2022", "혼인건수 증감", -817.0] and content.title == "2022~2025 혼인건수 연도별 증감"


def share_plan(chart, parts, denominator=None):
    step = {"step_id": "s1", "op": "share", "display_ref": "d3",
            "operands": [{"role": "part", "record_id": VID, "item": "인구수(명)", "select": {"행정구역별": parts}}]}
    if denominator:
        step["denominator"] = denominator
    return plan(chart, "bar", measure="share", select={}, steps=[step])


def test_share_of_selected_pie_has_scope_label():
    content, v = build_chart(share_plan("pie", ["지역00", "지역01", "지역02"]), [regions(4)])
    assert v.final_chart_type == "pie" and content.encoding == {"label": "행정구역별", "value": "값"}
    assert content.options == {"scope_label": "선택 항목 내 비중", "display_ref": "d3"} and content.axis == {}
    assert sum(r[-1] for r in content.rows) == 100.0


def test_share_of_question_total_must_sum_to_100():
    """전국 대비 비중인데 일부 지역만 고르면 원형 차트는 오해를 부른다 → 막대로 대체"""
    rows = [["2025", n, "인구수(명)", v] for n, v in [("전국", 100.0), ("가", 30.0), ("나", 20.0), ("다", 50.0)]]
    den = {"scope": "question", "label": "전국 대비 비중",
           "operand": {"record_id": VID, "item": "인구수(명)", "select": {"행정구역별": ["전국"]}}}
    rec = view(rows, REGION_COLS)
    whole, v1 = build_chart(share_plan("pie", ["가", "나", "다"], den), [rec])
    assert v1.final_chart_type == "pie" and whole.options["scope_label"] == "전국 대비 비중"
    part, v2 = build_chart(share_plan("pie", ["가", "나"], den), [rec])
    assert v2.original.failed == ["parts_sum_to_total"] and part.chart_type == "bar"
    assert part.axis["y"].scale == "percent"


def test_donut_center_text_uses_display():
    p = plan("donut", select={}, steps=[{"step_id": "s1", "op": "raw", "display_ref": "d1",
                                         "operands": operand("인구수(명)", {})}])
    content, _ = build_chart(p, [regions(3, value=lambda i: 1000.0 * (i + 1))], displays={"d1": make_display("명")})
    assert content.options == {"display_ref": "d1", "center_text": "합계 6,000명"}


def measures(roles):
    items = {"x": "혼인건수(건)", "y": "출생아수(명)", "size": "인구수(명)"}
    rows = [["2025", f"지역{i}", it, float((i + 1) * k)] for i in range(6) for k, it in enumerate(items.values(), 1)]
    steps = [{"step_id": f"s{n}", "op": "raw", "display_ref": f"d{n}", "operands": operand(items[r], {})}
             for n, r in enumerate(roles, 1)]
    out = [{"step_id": f"s{n}", "role": r} for n, r in enumerate(roles, 1)]
    return rows, steps, out


def test_scatter_and_bubble_join_measures_into_one_row():
    rows, steps, out = measures(["x", "y", "size"])
    content, v = build_chart(plan("bubble", select={}, steps=steps, output=out), [view(rows, REGION_COLS)])
    assert v.final_chart_type == "bubble"
    assert content.columns == ["시점", "행정구역별", "혼인건수", "출생아수", "인구수"]
    assert content.rows[0] == ["2025", "지역0", 1.0, 2.0, 3.0]
    assert content.encoding == {"x": "혼인건수", "y": "출생아수", "size": "인구수", "label": "행정구역별"}
    assert (content.axis["x"].display_ref, content.axis["y"].display_ref) == ("d1", "d2")
    rows, steps, out = measures(["x", "y"])
    scatter, v = build_chart(plan("scatter", select={}, steps=steps, output=out), [view(rows[:-2], REGION_COLS)])
    assert v.final_chart_type == "scatter" and len(scatter.rows) == 5
    assert scatter.warnings == ["한쪽 값이 없어 제외: {'시점': '2025', '행정구역별': '지역5'}"]


def test_dumbbell_pivots_first_and_last_period():
    p = plan("dumbbell", select={}, steps=[{"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}])
    content, v = build_chart(p, [regions(3, times=("2021", "2023", "2025"), value=lambda i: 10.0 * (i + 1))])
    assert v.final_chart_type == "dumbbell"
    assert content.columns == ["행정구역별", "2021", "2025"] and content.rows[0] == ["지역00", 10.0, 10.0]
    assert content.encoding == {"label": "행정구역별", "start": "2021", "end": "2025"}


def test_map_and_heatmap():
    p = plan("map", select={}, steps=[{"step_id": "s1", "op": "raw", "display_ref": "d1",
                                       "operands": operand("인구수(명)", {})}])
    content, _ = build_chart(p, [regions(3, geo_level="sido")])
    assert content.encoding == {"region": "행정구역별", "value": "값"}
    assert content.options == {"display_ref": "d1", "geo_level": "sido", "region_key": "name", "color_bins": None}
    p.chart_type = "heatmap"
    heat, v = build_chart(p, [regions(3, times=("2024", "2025"))])
    assert v.final_chart_type == "heatmap" and heat.encoding == {"x": "시점", "y": "행정구역별", "value": "값"}
    assert (heat.axis["x"].type, heat.axis["y"].type) == ("time", "category")


def test_build_charts_keeps_only_built_contents():
    ok = plan("line", "bar")
    bad = plan("line", chart_id="c2", select={**NATION, "항목": ["혼인건수(건)"], "시점": ["2025"]})
    contents, validation = build_charts(ChartPlan(plans=[ok, bad]), [view()],
                                        {"c1": ["time_axis_required"], "c2": ["min_points_3"]})
    assert [c.chart_id for c in contents] == ["c1"]
    assert set(validation) == {"c1", "c2"} and not validation["c2"].content_built


# ── [NEW] 이중 축 꺾은선: 단위가 다른 지표 2개 → 왼쪽(y)·오른쪽(y2) 축 ──────────────────
def two_item_line_plan(roles=("y", "y2"), items=("혼인건수(건)", "출생아수(명)")):
    sel = {**NATION, "시점": YEARS}
    return plan("line", "bar", select={**sel, "항목": list(items)}, steps=[
        {"step_id": "s1", "op": "raw", "display_ref": "d1", "operands": operand(items[0], sel)},
        {"step_id": "s2", "op": "raw", "display_ref": "d5", "operands": operand(items[1], sel)}],
        output=[{"step_id": "s1", "role": roles[0]}, {"step_id": "s2", "role": roles[1]}])


def test_line_with_different_units_uses_two_axes():
    content, v = build_chart(two_item_line_plan(), [view()], ["time_axis_required", "min_points_3"])
    assert v.final_chart_type == "line" and v.original.passed
    assert content.encoding == {"x": "시점", "y": "값", "series": "항목", "y2": "값"}
    assert content.options == {"marks": {"y": "line", "y2": "line"}, "series_axis": {"혼인건수": "y", "출생아수": "y2"}}
    assert (content.axis["y"].label, content.axis["y"].display_ref) == ("혼인건수", "d1")
    assert (content.axis["y2"].label, content.axis["y2"].display_ref) == ("출생아수", "d5")
    assert content.warnings == ["단위가 달라 지표별로 왼쪽(y)·오른쪽(y2) 축에 나눠 그림"]       # 예전의 '한 축에 그림' 경고는 없다
    assert len(content.rows) == 10


def test_dual_axis_follows_roles_hcx_gave():
    content, _ = build_chart(two_item_line_plan(roles=("y2", "y")), [view()])
    assert content.options["series_axis"] == {"혼인건수": "y2", "출생아수": "y"}


def test_dual_axis_falls_back_to_order_when_roles_overlap():
    content, _ = build_chart(two_item_line_plan(roles=("y", "y")), [view()])
    assert content.options["series_axis"] == {"혼인건수": "y", "출생아수": "y2"}


def test_same_units_stay_on_one_axis():
    """단위가 같으면 한 축이 비교에 정직하다 (두 축이면 범위가 제각각이라 크기 비교가 왜곡된다)"""
    rows = [[y, "전국", item, float(n)] for n, y in enumerate(YEARS, 1) for item in ("혼인건수(건)", "이혼건수(건)")]
    content, v = build_chart(two_item_line_plan(items=("혼인건수(건)", "이혼건수(건)")), [view(rows)])
    assert v.original.passed and "y2" not in content.encoding
    assert content.options == {} and content.warnings == []


def test_dual_axis_is_line_only_and_does_not_leak_into_fallback_bar():
    p = two_item_line_plan()
    p.chart_type, p.fallback_chart = "bar", None
    content, _ = build_chart(p, [view()])
    assert "y2" not in content.encoding and "marks" not in content.options


# ── [NEW] 축 범위 min · max (axis.py + specs.axis_rules) ─────────────────────
def two_series_rows():
    """같은 단위(건) 두 항목: 혼인 100~140, 이혼 90~110. 개별 최댓값 140, x별 합계의 최댓값 250"""
    return view([[y, "전국", item, float(v)] for item, vals in (("혼인건수(건)", [100, 110, 120, 130, 140]),
                                                                ("이혼건수(건)", [90, 95, 100, 105, 110]))
                 for y, v in zip(YEARS, vals)])


def two_series_plan(chart_type):
    sel = {**NATION, "시점": YEARS, "항목": ["혼인건수(건)", "이혼건수(건)"]}
    return plan(chart_type, select=sel)


def test_line_axis_has_free_range():
    content, _ = build_chart(plan("line", "bar"), [view()], ["time_axis_required", "min_points_3"])
    assert (content.axis["y"].min, content.axis["y"].max) == (180000, 250000)     # 실제 최솟값 191,690


def test_bar_axis_includes_zero_and_gets_a_max():
    p = plan("bar", select={}, steps=[{"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}])
    content, _ = build_chart(p, [regions(6, value=lambda i: 100.0 + 10 * i)])      # 100 ~ 150
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 200)
    negative, _ = build_chart(p, [regions(6, value=lambda i: i - 2.0)])            # -2 ~ 3: min 은 명세 그대로 min(0, 최솟값)
    assert (negative.axis["y"].min, negative.axis["y"].max) == (-2, 4)


def test_stacked_bar_max_is_the_largest_stack_total_not_the_largest_value():
    """지역별로 두 항목을 쌓는다: x = 지역, 층 = 항목. 지역마다 합계 190 · 205 · 220, 개별 최댓값은 120"""
    rows = [["2025", f"지역{i}", item, float(v)] for i in range(3)
            for item, v in (("혼인건수(건)", 100 + 10 * i), ("이혼건수(건)", 90 + 5 * i))]
    p = plan("stacked_bar", select={"항목": ["혼인건수(건)", "이혼건수(건)"]})
    content, v = build_chart(p, [view(rows, REGION_COLS)], ["non_negative", "parts_sum_to_total"])
    assert v.final_chart_type == "stacked_bar" and content.encoding["x"] == "행정구역별" and content.encoding["series"] == "항목"
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 250)              # 합계 220 → 250 (개별 120 이었다면 150)


def test_stacked_bar_max_follows_how_the_stack_is_actually_assembled():
    """범주가 있으면 범주를 x 축에 두므로(_assign), 시점과 항목이 함께 변하면 x = 항목, 층 = 시점이다.
    그때의 합계는 항목별 5개 시점의 합(혼인 600, 이혼 500) → 600 → 여백 후 800. max 는 그려지는 쌓임 기준이다"""
    content, _ = build_chart(two_series_plan("stacked_bar"), [two_series_rows()], ["non_negative", "parts_sum_to_total"])
    assert content.encoding["x"] == "항목" and content.encoding["series"] == "시점"
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 800)


def test_area_series_overlap_so_max_is_the_largest_value():
    content, v = build_chart(two_series_plan("area"), [two_series_rows()])
    assert v.final_chart_type == "area"
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 150)              # 겹침: 쌓은 합계(250)가 아니다


def test_combo_left_bar_axis_includes_zero_and_right_line_axis_is_free():
    content, _ = build_chart(combo_plan(), [view()])
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 300000)           # 막대: 0 부터
    assert (content.axis["y2"].min, content.axis["y2"].max) == (220000, 270000)    # 선: 데이터 범위


def test_dual_axis_line_ranges_are_independent():
    content, _ = build_chart(two_item_line_plan(), [view()])
    assert (content.axis["y"].min, content.axis["y"].max) == (180000, 250000)      # 혼인건수
    assert (content.axis["y2"].min, content.axis["y2"].max) == (220000, 270000)    # 출생아수 (서로 영향 없음)


def test_pyramid_value_axis_is_symmetric_under_x():
    cols = ["시점", "연령", "성별", "항목", "값"]
    rows = [["2025", age, sex, "인구수(명)", float(v)] for age, (m, f) in
            (("0~4세", (100, 110)), ("5~9세", (200, 190)), ("10~14세", (300, 310))) for sex, v in (("남자", m), ("여자", f))]
    p = plan("pyramid", select={}, steps=[{"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}])
    content, v = build_chart(p, [view(rows, cols)])
    assert v.final_chart_type == "pyramid"
    assert content.axis["y"].type == "category" and content.axis["x"].type == "numeric"
    assert (content.axis["x"].min, content.axis["x"].max) == (-400, 400)           # 310 → 대칭


def test_bubble_and_scatter_axes_get_free_ranges_from_their_own_columns():
    rows, steps, out = measures(["x", "y", "size"])
    content, _ = build_chart(plan("bubble", select={}, steps=steps, output=out), [view(rows, REGION_COLS)])
    assert (content.axis["x"].min, content.axis["x"].max) == (0, 7)                # 혼인 1~6
    assert (content.axis["y"].min, content.axis["y"].max) == (0, 14)               # 출생아 2~12
    assert "size" not in content.axis                                              # size 는 축이 아니다


def test_dumbbell_both_paths_have_the_same_x_axis_shape():
    p = plan("dumbbell", select={}, steps=[{"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}])
    pivot, _ = build_chart(p, [regions(3, times=("2021", "2023", "2025"), value=lambda i: 10.0 * (i + 1))])
    assert (pivot.axis["x"].min, pivot.axis["x"].max) == (5, 35)                   # 한 갈래를 두 시점으로 펼친 경로

    rows, steps, _ = measures(["x", "y"])
    out = [{"step_id": "s1", "role": "start"}, {"step_id": "s2", "role": "end"}]
    roles, _ = build_chart(plan("dumbbell", select={}, steps=steps, output=out), [view(rows, REGION_COLS)])
    assert roles.axis["x"].label == "혼인건수 · 출생아수" and roles.axis["x"].display_ref == "d1"
    assert (roles.axis["x"].min, roles.axis["x"].max) == (0, 15)                   # start·end 값 전체의 범위


def test_charts_without_value_axes_get_no_range():
    p = plan("heatmap", select={}, steps=[{"step_id": "s1", "op": "raw", "operands": operand("인구수(명)", {})}])
    heat, _ = build_chart(p, [regions(3, times=("2024", "2025"))])
    assert all(a.min is None and a.max is None for a in heat.axis.values())


def plotted_on(content, role):
    """그 축(role)에 그려지는 값들. 축이 둘인 차트(combo · 이중 축 line)는 series_axis 로 지표를 나눈다"""
    vi, ii = content.columns.index("값"), content.columns.index("항목")
    series_axis = content.options.get("series_axis")
    return [r[vi] for r in content.rows if not series_axis or series_axis.get(r[ii]) == role]


def test_range_always_covers_every_plotted_value_in_every_numeric_axis():
    """불변식: 어떤 차트든 숫자 축의 [min, max] 는 그 축에 그려지는 값을 모두 담는다 (누적 막대는 별도 시험이 합계로 본다)"""
    cases = [(plan("line", "bar"), [view()]), (combo_plan(), [view()]), (two_item_line_plan(), [view()]),
             (two_series_plan("area"), [two_series_rows()])]
    for p, recs in cases:
        content, _ = build_chart(p, recs)
        numeric = {role: ax for role, ax in content.axis.items() if ax.type == "numeric"}
        assert numeric, p.chart_type
        for role, ax in numeric.items():
            values = plotted_on(content, role)
            assert ax.min is not None and ax.max is not None and ax.min < ax.max, (p.chart_type, role)
            assert ax.min <= min(values) and ax.max >= max(values), (p.chart_type, role, ax.min, ax.max)
