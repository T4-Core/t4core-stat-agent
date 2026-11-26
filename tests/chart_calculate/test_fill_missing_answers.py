"""[NEW 11-25] HCX 가 질문용 계산(answers)을 비우면 차트 단계로 채운다 (체크리스트 1-9)

'~를 그래프로 보여줘' 처럼 차트만 요청한 질문에서 HCX 가 answers 를 비워(저장된 실행 37건 중 14건)
질문용 계산이 0개 → 모듈 6 이 '계산된 결과가 없어 수치 답변을 만들 수 없습니다' 를 냈다.
"""
from backend.agent.chart_calculate.pipeline import run_module3
from backend.agent.chart_calculate.planner import ChartDecision, Decision, Pick, _Planner, make_plan
from backend.schemas.chart import ChartRequest, Module3Request
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

SELECT = {"행정구역별": ["전국"], "항목": ["혼인건수(건)"]}


def _bundle(n_subs=1):
    return QueryBundle(query_id="q", original="2021~2025년 혼인건수 추이를 꺾은선 그래프로 보여줘",
                       sub_questions=[f"하위 {i}" for i in range(1, n_subs + 1)])


def _line(sub_ids=("q-1",)):
    return ChartRequest(chart_id="c1", sub_question_ids=list(sub_ids), chart_type="line", measure="raw")


def _decision(answers=()):
    return Decision(charts=[ChartDecision(chart_id="c1", record_id=VID, select=SELECT)], answers=list(answers))


def test_empty_answers_are_filled_from_the_chart_step_and_reuse_its_result():
    cp, _ = make_plan([_line()], [view()], _decision(), _bundle())
    assert [(a.step_id, a.op, a.sub_question_id) for a in cp.answer_steps] == [("a1", "raw", "q-1")]
    op = cp.answer_steps[0].operands[0]
    assert (op.role, op.record_id, op.select) == ("value", VID, cp.plans[0].select)
    assert cp.answer_reuse == {"a1": "c1.s1"}                       # 다시 계산하지 않고 차트 결과를 쓴다
    assert any("HCX 가 질문용 계산을 비워 차트 계산 c1.s1" in n for n in cp.notes)


def test_filled_answer_carries_the_chart_values_to_calc_results():
    req = Module3Request(records=[view()], query_bundle=_bundle(), charts=[_line()])
    out = run_module3(req, _decision())
    assert len(out.calc_results) == 1
    r = out.calc_results[0]
    assert r.step_id == "a1" and r.sub_question_id == "q-1"
    assert [p["value"] for p in r.value] == [192507.0, 191690.0, 193657.0, 222412.0, 240326.0]
    assert [row[-1] for row in out.chart_contents[0].rows] == [p["value"] for p in r.value]   # 차트와 같은 값


def test_answers_given_by_hcx_are_left_alone():
    hcx = {"sub_question_id": "q-1", "op": "change", "from": "2021", "to": "2025",
           "operands": [{"role": "value", "record_id": VID, "item": "혼인건수(건)", "select": {"행정구역별": ["전국"]}}]}
    cp, _ = make_plan([_line()], [view()], _decision([hcx]), _bundle())
    assert [(a.step_id, a.op) for a in cp.answer_steps] == [("a1", "change")]
    assert not any("비워" in n for n in cp.notes)


def test_sub_question_that_hcx_answered_but_was_dropped_is_not_filled():
    """HCX 가 결정을 냈는데 피연산자가 없어 생략된 경우 → 이유가 있으므로 채우지 않는다"""
    hcx = {"sub_question_id": "q-1", "op": "raw", "operands": []}
    cp, _ = make_plan([_line()], [view()], _decision([hcx]), _bundle())
    assert cp.answer_steps == []


def test_only_the_empty_sub_question_is_filled():
    charts = [_line(["q-1"]), ChartRequest(chart_id="c2", sub_question_ids=["q-2"], chart_type="line", measure="raw")]
    dec = Decision(charts=[ChartDecision(chart_id="c1", record_id=VID, select=SELECT),
                           ChartDecision(chart_id="c2", record_id=VID, select={"행정구역별": ["전국"], "항목": ["출생아수(명)"]})],
                   answers=[{"sub_question_id": "q-1", "op": "raw",
                             "operands": [{"role": "value", "record_id": VID, "item": "혼인건수(건)", "select": {"행정구역별": ["전국"]}}]}])
    cp, _ = make_plan(charts, [view()], dec, _bundle(2))
    assert [(a.step_id, a.sub_question_id) for a in cp.answer_steps] == [("a1", "q-1"), ("a2", "q-2")]
    assert cp.answer_reuse.get("a2") == "c2.s1"


def test_multi_branch_chart_is_filled_branch_by_branch():
    chart = ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="combo", measure="raw")
    dec = Decision(charts=[ChartDecision(chart_id="c1", record_id=VID, operands=[
        Pick(role="y", record_id=VID, item="혼인건수(건)", select={"행정구역별": ["전국"]}),
        Pick(role="y2", record_id=VID, item="출생아수(명)", select={"행정구역별": ["전국"]})])], answers=[])
    cp, _ = make_plan([chart], [view()], dec, _bundle())
    assert [a.step_id for a in cp.answer_steps] == ["a1-1", "a1-2"]
    assert [a.operands[0].item for a in cp.answer_steps] == ["혼인건수(건)", "출생아수(명)"]
    assert cp.answer_reuse == {"a1-1": "c1.s1", "a1-2": "c1.s2"}


def test_chart_spanning_two_sub_questions_is_not_filled():
    cp, _ = make_plan([_line(["q-1", "q-2"])], [view()], _decision(), _bundle(2))
    assert cp.answer_steps == [] and any("걸쳐 있어 채우지 않음" in n for n in cp.notes)


def test_no_chart_plan_means_nothing_to_copy():
    p = _Planner([view()])
    assert p.fill_missing_answers([], [], set(), 1) == []
