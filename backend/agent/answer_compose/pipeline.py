"""
[NEW] 모듈 6 진입점 — Module6Request → Module6Output

  run_module6(request, chat=None)         graph.py 의 LangGraph 를 실행한다: build_tables → write → fill → check → assemble
  run_module6_trace(request, chat=None)   같은 일 + 시도별 중간 결과(Module6Trace). 두 함수가 같은 그래프를 타므로 trace.output 은 run_module6 의 결과와 같다.

  chat = core.llm.chat 과 같은 모양의 함수. 비우면 HCX 를 부르고, 테스트에서는 가짜 함수를 넣는다.
"""
from typing import Any, Callable

from backend.agent.answer_compose.graph import Attempt, Module6Trace, graph  # noqa: F401
from backend.schemas.answer import Module6Output, Module6Request


def _run(request: Module6Request, chat: Callable[..., Any] | None) -> Module6Trace:
    return graph.invoke({"request": request}, config={"configurable": {"chat": chat}})["trace"]


def run_module6(request: Module6Request, chat: Callable[..., Any] | None = None) -> Module6Output:
    return _run(request, chat).output


def run_module6_trace(request: Module6Request, chat: Callable[..., Any] | None = None) -> Module6Trace:
    return _run(request, chat)
