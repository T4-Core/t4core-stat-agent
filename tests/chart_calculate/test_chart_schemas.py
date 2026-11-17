"""[NEW] 모듈 3 스키마 — 명세(docs/discussions/2026-11-09-차트-계산-명세.md)의 JSON 예시가 그대로 파싱되는지 확인"""
import pytest
from pydantic import ValidationError

from backend.schemas.chart import (CalcResult, ChartContent, ChartPlan, ChartRequest, ChartValidation, Display,
                                   Module3Output, Step)

V1 = "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
V2 = "view::101_DT_1B8000G::Y::27077dec-2-1::trend"
YEARS = ["2021", "2022", "2023", "2024", "2025"]

# 명세 4장 "예시: 명세서 시나리오" + "갈래가 있는 계획 (combo)"
PLAN = {
    "plans": [
        {"chart_id": "c1", "sub_question_ids": ["27077dec-1"], "record_id": V1, "chart_type": "line",
         "fallback_chart": "bar", "measure": "raw",
         "select": {"행정구역별": ["전국"], "종류별": ["혼인건수(건)"], "시점": YEARS},
         "steps": [{"step_id": "s1", "op": "raw", "display_ref": "d1"}]},
        {"chart_id": "c3", "sub_question_ids": ["27077dec-1"], "record_id": V1, "chart_type": "combo",
         "fallback_chart": "line", "measure": "raw",
         "select": {"행정구역별": ["전국"], "종류별": ["혼인건수(건)", "조혼인율(천명당)"], "시점": YEARS},
         "steps": [
             {"step_id": "s1", "op": "raw", "display_ref": "d1",
              "operands": [{"role": "value", "record_id": V1, "item": "혼인건수(건)",
                            "select": {"행정구역별": ["전국"]}, "unit": "건"}]},
             {"step_id": "s2", "op": "raw", "display_ref": "d5",
              "operands": [{"role": "value", "record_id": V1, "item": "조혼인율(천명당)",
                            "select": {"행정구역별": ["전국"]}, "unit": "천명당"}]}],
         "output": [{"step_id": "s1", "role": "y"}, {"step_id": "s2", "role": "y2"}]},
    ],
    "answer_steps": [
        {"step_id": "a1", "op": "growth_rate", "from": "2021", "to": "2025", "display_ref": "d3",
         "operands": [{"role": "value", "record_id": V1, "item": "혼인건수(건)",
                       "select": {"행정구역별": ["전국"]}, "unit": "건"}]},
        {"step_id": "a3", "op": "diff", "join_on": ["시점"], "display_ref": "d4",
         "operands": [
             {"role": "a", "record_id": V1, "item": "인구수(명)", "select": {"행정구역별": ["서울특별시"]}, "unit": "명"},
             {"role": "b", "record_id": V2, "item": "인구수(명)", "select": {"행정구역별": ["부산광역시"]}, "unit": "명"}]},
    ],
}

# 명세 5장 c1
CONTENT_C1 = {
    "chart_id": "c1", "chart_type": "line", "measure": "raw", "title": "2021~2025 혼인건수 연도별 추이",
    "encoding": {"x": "시점", "y": "값", "series": "항목"},
    "axis": {"x": {"label": "시점", "type": "time"},
             "y": {"label": "혼인건수", "type": "numeric", "scale": "linear", "display_ref": "d1"}},
    "options": {}, "columns": ["시점", "항목", "값"],
    "rows": [["2021", "혼인건수", 192507], ["2025", "혼인건수", 240326]],
    "record_ids": [V1], "warnings": [],
}

# 명세 6장 a1
CALC_A1 = {
    "step_id": "a1", "op": "growth_rate", "value": 24.84013568337775, "unit": "%", "display_ref": "d3",
    "inputs": [
        {"role": "value", "record_id": V1, "item": "혼인건수(건)", "key": {"시점": "2021"}, "value": 192507, "unit": "건"},
        {"role": "value", "record_id": V1, "item": "혼인건수(건)", "key": {"시점": "2025"}, "value": 240326, "unit": "건"}],
    "record_ids": [V1], "scope_label": None, "note": None,
}

# 명세 7장 validation
VALIDATION = {
    "c1": {"original": {"chart_type": "line", "passed": True,
                        "checked": ["data_present", "required_roles", "time_axis_required", "min_points_3"],
                        "failed": [], "reasons": []},
           "fallback": None, "final_chart_type": "line", "content_built": True},
    "c4": {"original": {"chart_type": "pie", "passed": False,
                        "checked": ["data_present", "required_roles", "non_negative", "parts_sum_to_total",
                                    "max_categories_5"],
                        "failed": ["max_categories_5"], "reasons": ["항목 17개 (최대 5개)"]},
           "fallback": {"chart_type": "bar", "passed": True,
                        "checked": ["data_present", "required_roles", "max_categories_20"], "failed": [], "reasons": []},
           "final_chart_type": "bar", "content_built": True},
}

DISPLAYS = {"d1": {"source_unit": "건", "display_unit": "건", "unit_scale": 1},
            "d3": {"source_unit": "%", "display_unit": "%", "unit_scale": 1}}


def test_chart_plan_parses_spec_examples():
    plan = ChartPlan.model_validate(PLAN)
    c1, c3 = plan.plans
    assert c1.steps[0].operands is None and c1.output is None       # 생략 = 상위 record_id·select, 마지막 단계
    assert [(o.step_id, o.role) for o in c3.output] == [("s1", "y"), ("s2", "y2")]
    a1, a3 = plan.answer_steps
    assert (a1.from_, a1.to) == ("2021", "2025")
    assert a3.join_on == ["시점"] and [o.role for o in a3.operands] == ["a", "b"]


def test_step_from_alias_round_trip():
    """from 은 예약어 → from_ 으로 받고, by_alias 로 내보내면 명세 키 그대로"""
    step = Step.model_validate(PLAN["answer_steps"][0])
    dumped = step.model_dump(by_alias=True, exclude_none=True)
    assert dumped["from"] == "2021" and "from_" not in dumped
    assert Step(step_id="a9", op="change", from_="2021").from_ == "2021"   # 코드에서는 이름으로도 만들 수 있다


def test_step_keeps_undefined_op_args():
    """연산별 인자는 후속 명세 → 모르는 인자도 버리지 않는다"""
    step = Step.model_validate({"step_id": "s1", "op": "extreme", "kind": "max"})
    assert step.model_dump(exclude_none=True)["kind"] == "max"


def test_denominator_operand_without_role():
    step = Step.model_validate({
        "step_id": "a4", "op": "share",
        "denominator": {"scope": "question", "basis": "질문의 '전국 대비'", "label": "전국 대비 비중",
                        "operand": {"record_id": V2, "item": "출생아수(명)", "select": {"행정구역별": ["전국"]}}}})
    assert step.denominator.operand.role is None


def test_content_calc_validation_parse():
    content = ChartContent.model_validate(CONTENT_C1)
    assert content.axis["y"].display_ref == "d1" and content.axis["x"].scale is None
    assert CalcResult.model_validate(CALC_A1).value == pytest.approx(24.84013568337775)
    v = {k: ChartValidation.model_validate(x) for k, x in VALIDATION.items()}
    assert v["c1"].fallback is None and v["c4"].fallback.chart_type == "bar"
    assert Display.model_validate(DISPLAYS["d1"]).digits is None


def test_module3_output_whole_shape():
    out = Module3Output.model_validate({
        "query_id": "27077dec", "chart_plan": PLAN, "chart_contents": [CONTENT_C1], "calc_results": [CALC_A1],
        "displays": DISPLAYS, "validation": VALIDATION})
    assert set(out.validation) == {"c1", "c4"} and out.chart_plan.notes == []


@pytest.mark.parametrize("model, bad", [
    (ChartRequest, {"chart_id": "c1", "chart_type": "sankey"}),                     # 15종 밖의 차트
    (Step, {"step_id": "s1", "op": "median"}),                                      # 11종 밖의 연산
    (ChartContent, {**CONTENT_C1, "encoding": {"color": "값"}}),                    # 역할 코드가 아님
    (Display, {"source_unit": "건", "display_unit": "만 건", "unit_scale": 0}),     # 0 으로 나누게 됨
])
def test_rejects_unknown_codes(model, bad):
    with pytest.raises(ValidationError):
        model.model_validate(bad)


def test_chart_request_allows_no_chart():
    """모듈 2 가 차트 없음으로 판단한 하위질문: chart_type None"""
    assert ChartRequest(chart_id="c2").chart_type is None
