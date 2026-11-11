"""2번 차트 유형 판단 서브그래프

    from <module 폴더 이름>.chart_decision.chart_type_graph import build_chart_decision_graph
    sub = build_chart_decision_graph()
    out = sub.invoke({"query_bundle": ..., "view_input": ...})   # → chart_plan, filtered_views, errors
    out = sub.invoke({})                                          # 입력 비우면 기본 시나리오
    out = sub.invoke({"scenario": "27077dec"})                    # 시나리오 이름으로
"""
from langgraph.graph import END, START, StateGraph

from . import chart_type_nodes as n
from .chart_type_state import ChartDecisionInput, ChartDecisionOutput, ChartDecisionState


def build_chart_decision_graph():
    b = StateGraph(ChartDecisionState, input_schema=ChartDecisionInput, output_schema=ChartDecisionOutput)

    b.add_node("load_input", n.load_input_node)       # ⓪ 입력 준비 (비우면 시나리오)
    b.add_node("match", n.match_node)                 # ① 짝짓기
    b.add_node("filter", n.filter_node)               # ①-1 필터링
    b.add_node("measure_rule", n.measure_rule_node)   # ② measure 규칙
    b.add_node("measure_llm", n.measure_llm_node)     # ② measure LLM (확신 없을 때만)
    b.add_node("profile", n.profile_node)             # ③ 데이터 모양
    b.add_node("chart_select", n.chart_select_node)   # ④ combo + 소거법
    b.add_node("chart_llm", n.chart_llm_node)         # ④ LLM (규칙 실패 시, 자리만)
    b.add_node("requirements", n.requirements_node)   # ⑤ requirements · fallback
    b.add_node("reason", n.reason_node)               # ⑥ reason → chart_plan

    b.add_edge(START, "load_input")
    b.add_conditional_edges("load_input", n.route_after_load, {"match": "match", "end": END})
    b.add_conditional_edges("match", n.route_after_match, {"filter": "filter", "end": END})
    b.add_conditional_edges("filter", n.route_after_filter, {"measure_rule": "measure_rule", "end": END})
    b.add_conditional_edges("measure_rule", n.route_after_measure_rule,
                            {"measure_llm": "measure_llm", "profile": "profile"})
    b.add_edge("measure_llm", "profile")
    b.add_edge("profile", "chart_select")
    b.add_conditional_edges("chart_select", n.route_after_chart_select,
                            {"chart_llm": "chart_llm", "requirements": "requirements"})
    b.add_edge("chart_llm", "requirements")
    b.add_edge("requirements", "reason")
    b.add_edge("reason", END)
    return b.compile()


graph = build_chart_decision_graph()          # langgraph.json에서 쓰는 이름
