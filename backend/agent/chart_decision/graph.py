"""Generator 그래프

START → chart_decision (2번 서브그래프) → calculation (3번) → chart_render (5번) → END
                                       └→ answer (차트 없이 답변) → END
3번·5번·answer는 아직 없어서 State를 그대로 넘기는 자리만 둔다.
"""
from langgraph.graph import END, START, StateGraph

from .chart_decision_module.chart_type_graph import build_chart_decision_graph
from .state import GeneratorState


def calculation_node(state):        # 3번 계산 (자리만)
    return {}


def chart_render_node(state):       # 5번 차트 생성 (자리만)
    return {}


def answer_node(state):             # 차트 없이 답변 (자리만)
    return {}


def route_after_chart(state):
    """chart_type이 None인 차트도 charts에 들어가므로 calculation으로 간다. charts가 비었을 때만 answer"""
    return "calculation" if (state.get("chart_plan") or {}).get("charts") else "answer"


def build_generator_graph():
    b = StateGraph(GeneratorState)
    b.add_node("chart_decision", build_chart_decision_graph())   # 컴파일한 서브그래프를 노드 하나로
    b.add_node("calculation", calculation_node)
    b.add_node("chart_render", chart_render_node)
    b.add_node("answer", answer_node)

    b.add_edge(START, "chart_decision")
    b.add_conditional_edges("chart_decision", route_after_chart,
                            {"calculation": "calculation", "answer": "answer"})
    b.add_edge("calculation", "chart_render")
    b.add_edge("chart_render", END)
    b.add_edge("answer", END)
    return b.compile()


graph = build_generator_graph()               # langgraph.json에서 쓰는 이름
