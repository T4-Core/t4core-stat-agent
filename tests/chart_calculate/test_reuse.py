"""[NEW] 같은 계산은 한 번만 — 질문용 단계가 같은 세트의 차트 단계를 재사용한다 (HCX 없이, 결정은 손으로 적는다)"""
from unittest import mock

import pytest

from backend.agent.chart_calculate import calculate
from backend.agent.chart_calculate.calculate import step_key
from backend.agent.chart_calculate.pipeline import run_module3
from backend.agent.chart_calculate.planner import Decision
from backend.schemas.chart import ChartRequest, Module3Request, Operand, Plan, Step
from tests.chart_calculate._views import VID, view
from tests.chart_calculate.test_decide import BUNDLE
from tests.chart_calculate.test_planner import NATION, YEARS

ITEM = "혼인건수(건)"


def _pick(select=None, item=ITEM):
    return {"role": "value", "record_id": VID, "item": item, "select": NATION if select is None else select}


def _decision(answers, chart_select=None):
    return Decision.model_validate({
        "charts": [{"chart_id": "c1", "record_id": VID, "operands": [_pick({**NATION, "시점": YEARS})] if chart_select is None
                    else [_pick(chart_select)]}],
        "answers": answers})


def _request(subs=("27077dec-1",)):
    c = ChartRequest(chart_id="c1", sub_question_ids=list(subs), chart_type="line", measure="raw", fallback_chart="bar")
    return Module3Request(records=[view()], query_bundle=BUNDLE, charts=[c])


def _raw_answer(**kw):
    return {"sub_question_id": "27077dec-1", "op": "raw", "operands": [_pick({**NATION, "시점": YEARS})], **kw}


def test_same_calculation_is_reused_even_if_unused_args_differ():
    """raw 는 from·to 를 읽지 않는다 → 답변 쪽에만 from·to 가 있어도 같은 계산"""
    out = run_module3(_request(), _decision([_raw_answer(**{"from": "2021", "to": "2025"})]))
    assert out.chart_plan.answer_reuse == {"a1": "c1.s1"}
    assert not [n for n in out.chart_plan.notes if "따로 계산" in n]


def test_reused_numbers_equal_the_chart_numbers():
    out = run_module3(_request(), _decision([_raw_answer()]))
    chart_values = [r[-1] for r in out.chart_contents[0].rows]
    answer_values = [v["value"] for v in out.calc_results[0].value]
    assert answer_values == chart_values == [192507, 191690, 193657, 222412, 240326]
    assert (out.calc_results[0].step_id, out.calc_results[0].display_ref) == ("a1", out.chart_plan.answer_steps[0].display_ref)


def test_reused_step_is_not_executed_again():
    calls = []
    real = calculate.run_steps
    with mock.patch.object(calculate, "run_steps", side_effect=lambda steps, *a, **k: (calls.append([s.step_id for s in steps]), real(steps, *a, **k))[1]):
        run_module3(_request(), _decision([_raw_answer()]))
    assert calls == [[]]          # 질문용 쪽에서 실행한 단계가 하나도 없다 (차트 쪽은 content 모듈이 부른다)


def test_different_operation_is_calculated_separately():
    ans = {"sub_question_id": "27077dec-1", "op": "growth_rate", "operands": [_pick({**NATION, "시점": YEARS})]}
    out = run_module3(_request(), _decision([ans]))
    assert out.chart_plan.answer_reuse == {}
    assert out.calc_results[0].op == "growth_rate"


def test_other_set_is_not_reused():
    """차트가 다른 하위 질문의 세트면 계산이 같아 보여도 재사용하지 않는다"""
    out = run_module3(_request(subs=("27077dec-2",)), _decision([_raw_answer()]))
    assert out.chart_plan.answer_reuse == {}


def test_same_metric_but_different_rows_warns_and_runs_separately():
    narrow = _decision([_raw_answer()], chart_select={**NATION, "시점": YEARS[:3]})
    out = run_module3(_request(), narrow)
    assert out.chart_plan.answer_reuse == {}
    assert any("같은 지표인데 조건이 달라" in n and "c1.s1" in n for n in out.chart_plan.notes)
    assert len(out.calc_results[0].value) == 5          # 답변은 5개 시점 전부


def test_answer_survives_when_the_chart_fails_validation():
    """차트가 탈락(데이터 없음)해도 질문용 계산은 그대로 나간다 (명세 7장)"""
    c = ChartRequest(chart_id="c1", sub_question_ids=["27077dec-1"], chart_type="line", measure="raw", requirements=["min_points_9"])
    req = Module3Request(records=[view()], query_bundle=BUNDLE, charts=[c])
    out = run_module3(req, _decision([_raw_answer()]))
    assert out.calc_results and out.calc_results[0].value


def test_missing_chart_calc_falls_back_to_own_calculation():
    from backend.agent.chart_calculate.graph import answer_steps_node
    out = run_module3(_request(), _decision([_raw_answer()]))
    state = {"chart_plan": out.chart_plan, "request": _request(), "chart_calcs": {}}     # 차트 계산 결과가 없다
    results = answer_steps_node(state)["calc_results"]
    assert [v["value"] for v in results[0].value] == [192507, 191690, 193657, 222412, 240326]


def test_step_key_ignores_unused_args_but_not_used_ones():
    base = dict(step_id="s", op="raw", operands=[Operand(role="value", record_id=VID, item=ITEM, select=NATION)])
    assert step_key(Step(**base)) == step_key(Step(**base, **{"from": "2021", "to": "2025"}))
    growth = dict(base, op="growth_rate")
    assert step_key(Step(**growth)) != step_key(Step(**growth, **{"from": "2021"}))


def test_step_key_resolves_default_operand_and_skips_chained_steps():
    plan = Plan(chart_id="c1", record_id=VID, chart_type="line", measure="raw", select=NATION, steps=[])
    explicit = Step(step_id="s1", op="raw", operands=[Operand(role="value", record_id=VID, select=NATION)])
    assert step_key(Step(step_id="s1", op="raw"), plan) == step_key(explicit)
    assert step_key(Step(step_id="s2", op="raw", input="s1")) is None
    assert step_key(Step(step_id="s1", op="raw")) is None        # 피연산자도 기본 계획도 없다
