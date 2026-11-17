"""[NEW 11-13] 비율(%)끼리의 change · diff 는 %p, growth_rate · cagr · share 는 % 그대로"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.content import _scale
from backend.agent.chart_calculate.display import default_digits, format_value, make_display, result_unit
from backend.schemas.chart import Step
from tests.chart_calculate._views import view

RATE = [["2021", "전국", "고령인구비율(%)", 15.2], ["2025", "전국", "고령인구비율(%)", 17.8],
        ["2021", "서울특별시", "고령인구비율(%)", 14.0], ["2025", "서울특별시", "고령인구비율(%)", 16.9]]
ITEM = "고령인구비율(%)"
NATION, SEOUL = {"행정구역별": ["전국"]}, {"행정구역별": ["서울특별시"]}


def run(step: dict):
    rec = view(RATE, ["시점", "행정구역별", "항목", "값"])
    return run_answer_steps([Step.model_validate({"step_id": "a1", **step})], [rec])[0]


def operand(role, select):
    return {"role": role, "record_id": view().id, "item": ITEM, "select": select}


def test_result_unit_rule():
    assert [result_unit(op, "%") for op in ("change", "diff", "growth_rate", "cagr", "share", "raw")] == [
        "%p", "%p", "%", "%", "%", "%"]
    assert [result_unit(op, u) for op, u in (("change", "명"), ("diff", "건"), ("change", "%p"), ("diff", None))] == [
        "명", "건", "%p", None]                                                    # 비율이 아니면 그대로


def test_change_of_a_rate_is_percent_point():
    r = run({"op": "change", "from": "2021", "to": "2025", "operands": [operand("value", NATION)]})
    assert r.unit == "%p" and r.value == pytest.approx(2.6)
    assert r.inputs[0].unit == "%"                                               # 근거 값은 원래 단위 그대로


def test_growth_rate_and_cagr_of_a_rate_stay_percent():
    g = run({"op": "growth_rate", "from": "2021", "to": "2025", "operands": [operand("value", NATION)]})
    c = run({"op": "cagr", "from": "2021", "to": "2025", "operands": [operand("value", NATION)]})
    assert (g.unit, c.unit) == ("%", "%") and g.value == pytest.approx((17.8 - 15.2) / 15.2 * 100)


def test_diff_of_two_rates_is_percent_point():
    r = run({"op": "diff", "join_on": ["시점"],
             "operands": [operand("a", {**SEOUL, "시점": ["2025"]}), operand("b", {**NATION, "시점": ["2025"]})]})
    assert r.unit == "%p" and r.value == pytest.approx(16.9 - 17.8)


def test_display_and_axis():
    d = make_display("%p")
    assert default_digits("%p") == 1 and format_value(2.6, d) == "2.6%p" and format_value(-0.9, d) == "-0.9%p"
    assert _scale("%p") == "percent"
