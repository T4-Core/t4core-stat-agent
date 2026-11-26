"""[NEW 11-25] 덤벨: 갈래마다 시점이 하나씩이고 서로 다르면 시점으로 짝짓지 않는다 (체크리스트 1-5)

15유형 테스트의 덤벨 질문 3건 모두 start = 2015 갈래, end = 2024 갈래로 계획됐는데, 결합 키에 시점이 들어가
(2015, 서울) 과 (2024, 서울) 이 다른 행이 됐다 → '두 값이 모두 있지 않은 범주 N개' 로 막대로 대체됐다.
"""
from backend.agent.chart_calculate.content import build_chart
from tests.chart_calculate._views import view
from tests.chart_calculate.test_content import REGION_COLS, operand, plan

REGIONS = ["서울특별시", "부산광역시", "대구광역시"]
TFR = {"2015": [1.001, 1.139, 1.216], "2024": [0.581, 0.683, 0.754]}
OUT = [{"step_id": "s1", "role": "start"}, {"step_id": "s2", "role": "end"}]


def _rows(values=TFR, item="합계출산율(명)"):
    return [[t, r, item, v] for t, vs in values.items() for r, v in zip(REGIONS, vs)]


def _year_step(step_id, year, item="합계출산율(명)"):
    return {"step_id": step_id, "op": "raw", "display_ref": "d1", "operands": operand(item, {"시점": [year]})}


def test_start_and_end_years_are_paired_by_region():
    p = plan("dumbbell", select={}, steps=[_year_step("s1", "2015"), _year_step("s2", "2024")], output=OUT)
    content, v = build_chart(p, [view(_rows(), REGION_COLS)])
    assert v.original.passed and v.final_chart_type == "dumbbell"
    assert content.columns == ["행정구역별", "2015", "2024"]
    assert content.rows == [[r, a, b] for r, a, b in zip(REGIONS, TFR["2015"], TFR["2024"])]
    assert content.encoding == {"start": "2015", "end": "2024", "label": "행정구역별"}
    assert content.axis["x"].label == "합계출산율"                     # 열 이름은 시점, 축 이름은 지표


def test_region_present_in_only_one_year_is_still_caught_by_validation():
    rows = _rows() + [["2024", "세종특별자치시", "합계출산율(명)", 1.0]]
    p = plan("dumbbell", select={}, steps=[_year_step("s1", "2015"), _year_step("s2", "2024")], output=OUT)
    content, v = build_chart(p, [view(rows, REGION_COLS)])          # 대체 후보가 없어 content 는 None
    assert content is None
    assert not v.original.passed and "two_points_per_category" in v.original.failed
    assert v.original.reasons == ["두 값이 모두 있지 않은 범주 1개"]     # 세종 하나만 (나머지 3곳은 짝지어짐)


def test_branches_of_the_same_year_are_still_paired_by_year():
    """start = 2024 출생아수, end = 2024 사망자수 → 시점이 같으니 지금처럼 시점 · 지역으로 짝짓는다"""
    rows = [["2024", r, it, v] for it, vs in (("출생아수(명)", [41.0, 13.0, 10.0]), ("사망자수(명)", [52.0, 26.0, 16.0]))
            for r, v in zip(REGIONS, vs)]
    steps = [_year_step("s1", "2024", "출생아수(명)"), _year_step("s2", "2024", "사망자수(명)")]
    content, v = build_chart(plan("dumbbell", select={}, steps=steps, output=OUT), [view(rows, REGION_COLS)])
    assert v.original.passed
    assert content.encoding["start"] == "출생아수" and content.encoding["end"] == "사망자수"
    assert "시점" in content.columns


def test_single_branch_with_two_years_keeps_the_pivot_path():
    p = plan("dumbbell", select={}, steps=[{"step_id": "s1", "op": "raw", "display_ref": "d1",
                                            "operands": operand("합계출산율(명)", {})}])
    content, v = build_chart(p, [view(_rows(), REGION_COLS)])
    assert v.original.passed and content.columns == ["행정구역별", "2015", "2024"]
