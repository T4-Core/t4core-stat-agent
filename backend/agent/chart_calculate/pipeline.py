"""
[NEW] 모듈 3 진입점 — Module3Request → Module3Output

  run_module3(request)
    graph.py 의 LangGraph 를 실행한다: decide(HCX) → plan → build_charts ∥ answer_steps → assemble

  run_module3_trace(request) 는 같은 일을 하면서 단계별 중간 결과(Module3Trace)를 함께 돌려준다 (테스트 화면 frontend/chart-lab).
  두 함수가 같은 그래프를 타므로 trace.output 은 run_module3 의 결과와 같다.

  [CHANGED] 이전: 이 파일이 단계를 직접 순서대로 호출했다. 노드·트레이스 모델은 graph.py 로 옮겼다.
            트레이스 모델은 아래에서 다시 내보내므로 `from ...pipeline import Module3Trace` 도 그대로 된다.
"""
from typing import Any, Callable

from backend.agent.chart_calculate.graph import (PLAN_PRESENT, Attempt, CalcView, ChartTrace, DecideTrace,  # noqa: F401
                                                 Module3Trace, graph)
from backend.agent.chart_calculate.planner import Decision
from backend.schemas.chart import Module3Output, Module3Request


def _run(request: Module3Request, decision: Decision | None, chat: Callable[..., Any] | None) -> Module3Trace:
    state = graph.invoke({"request": request, "decision": decision}, config={"configurable": {"chat": chat}})
    return state["trace"]


def run_module3(request: Module3Request, decision: Decision | None = None,
                chat: Callable[..., Any] | None = None) -> Module3Output:
    """decision 을 주면 HCX 를 부르지 않는다 (Swagger 시험·테스트·재실행용)"""
    return _run(request, decision, chat).output


def run_module3_trace(request: Module3Request, decision: Decision | None = None,
                      chat: Callable[..., Any] | None = None) -> Module3Trace:
    return _run(request, decision, chat)
