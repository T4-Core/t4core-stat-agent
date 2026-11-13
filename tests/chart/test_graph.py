"""모듈 3 LangGraph 전환 시험 — HCX 없이 돈다

기준값(baseline/)은 LangGraph 로 바꾸기 전 코드에서 HCX 를 한 번 불러 저장한 것이다.
  request.json · decision.json · decide_raw.json(HCX 원 응답) → output.json
전환 뒤에도 같은 입력이 같은 출력을 내야 한다.
"""
import json
from pathlib import Path

import pytest

from backend.agent.chart_calculate.graph import PLAN_PRESENT, build_module3_graph
from backend.agent.chart_calculate.pipeline import run_module3, run_module3_trace
from backend.agent.chart_calculate.planner import Decision
from backend.schemas.chart import Module3Request

BASE = Path(__file__).parent / "baseline"


def _load(name):
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def _dump(model):
    return json.loads(json.dumps(model.model_dump(mode="json", by_alias=True), ensure_ascii=False))


@pytest.fixture(scope="module")
def req():
    return Module3Request.model_validate(_load("request.json"))


@pytest.fixture(scope="module")
def decision():
    return Decision.model_validate(_load("decision.json"))


@pytest.fixture(scope="module")
def expected():
    return _load("output.json")


def test_decision_given_matches_baseline(req, decision, expected):
    assert _dump(run_module3(req, decision)) == expected


def test_trace_output_equals_run(req, decision):
    assert _dump(run_module3_trace(req, decision).output) == _dump(run_module3(req, decision))


def test_chat_reaches_decide_through_config(req, expected):
    """HCX 대신 저장된 원 응답을 돌려주는 가짜 chat. config 로 넘긴 chat 이 decide 에서 쓰여야 한다"""
    calls = []

    def fake_chat(messages, **kw):
        calls.append(kw)
        return _load("decide_raw.json")["raw"]

    trace = run_module3_trace(req, chat=fake_chat)
    assert len(calls) == 1
    assert trace.decide.skipped is False
    assert _dump(trace.output) == expected


def test_decision_given_skips_chat(req, decision):
    def boom(*a, **kw):
        raise AssertionError("decision 을 줬는데 chat 을 불렀다")

    trace = run_module3_trace(req, decision, chat=boom)
    assert trace.decide.skipped is True


def test_dict_input_is_accepted(req, decision, expected):
    """Studio · 다른 모듈의 JSON 처럼 dict 로 와도 객체로 바꿔 같은 결과를 낸다"""
    g = build_module3_graph()
    out = g.invoke({"request": req.model_dump(mode="json", by_alias=True),
                    "decision": decision.model_dump(mode="json", by_alias=True)})["output"]
    assert _dump(out) == expected


def test_chat_failure_keeps_going_and_records_why(req):
    """HCX 호출이 실패해도 예외를 던지지 않는다. 차트는 만들어지지 않고 validation 에 사유가 남는다"""
    def broken(*a, **kw):
        raise RuntimeError("연결 실패")

    out = run_module3(req, chat=broken)
    assert out.chart_contents == []
    assert {k: v.original.failed for k, v in out.validation.items()} == {"c1": [PLAN_PRESENT], "c2": [PLAN_PRESENT]}


def test_missing_key_system_exit_is_not_swallowed(req):
    """키가 없을 때 core.llm 이 내는 SystemExit 는 설정 오류라 그래프를 거쳐도 그대로 올라와야 한다"""
    def no_key(*a, **kw):
        raise SystemExit(".env 에 HCX_API_KEY 를 넣어 주세요.")

    with pytest.raises(SystemExit):
        run_module3(req, chat=no_key)


def test_answer_steps_come_after_build_charts_to_reuse_their_calculations():
    """같은 계산을 한 번만 하려고 answer_steps 가 build_charts 의 결과를 받는다 (병렬이었다가 순서가 생겼다)"""
    edges = {(e.source, e.target) for e in build_module3_graph().get_graph().edges}
    assert {("plan", "build_charts"), ("build_charts", "answer_steps"), ("answer_steps", "assemble")} <= edges
    assert ("plan", "answer_steps") not in edges
