"""QA 그래프 (LangGraph) — ViewSet → 모듈 2 → 3 → (5 ∥ 6), 지점마다 형식 검사 · 대응

  START → check_input(A0) → prepare_m2(M2-in) → module2 ⇄ check_m2(M2-out) → adapt(M3-in)
        → module3 ⇄ check_m3(M3-out) → check_notes ('열 없음' · 'HCX 호출 실패' → module3 1번 더)
        ─┬→ draw (모듈 5 + M5-out) ─────────────────────────────────┐
         └→ answer [서브그래프: build_m6(M6-in) → module6 ⇄ check_m6(M6-out)] ┴→ finalize (A9 + result) → END
  어느 검사에서든 '중단' 이면 바로 finalize 로 간다 (멈춘 단계를 qa.stopped_stage 에 남김).

  ⇄ = 재시도 (LLM 모듈만 1번). 모듈 5 · 6 은 서로를 읽지 않으므로 동시에 돈다 (모듈 코드는 그대로).
  모듈 6 갈래를 서브그래프로 묶은 이유: LangGraph 는 단계(superstep)마다 그 단계의 노드가 다 끝나야 다음으로 간다.
  갈래를 노드 여러 개로 두면 module6 이 draw 가 끝날 때까지 기다린다 → 갈래 전체를 노드 하나(서브그래프)로.
  HCX 함수는 config["configurable"]["chat"], 시험용 모듈 바꿔 끼우기는 config["configurable"]["mods"].
"""
from langgraph.graph import END, START, StateGraph

from . import qa_nodes as n
from .qa_state import AnswerInput, AnswerOutput, AnswerState, QAInput, QAResult, QAState


def build_answer_graph():
    """모듈 6 갈래: build_m6(M6-in) → module6 ⇄ check_m6(M6-out). 실패하면 답변 없이 (차트는 계속)"""
    b = StateGraph(AnswerState, input_schema=AnswerInput, output_schema=AnswerOutput)
    for name in ("build_m6", "module6", "check_m6"):
        b.add_node(name, getattr(n, name))
    b.add_edge(START, "build_m6")
    b.add_conditional_edges("build_m6", n.route_build_m6, {"module6": "module6", "end": END})
    b.add_edge("module6", "check_m6")
    b.add_conditional_edges("check_m6", n.route_m6, {"module6": "module6", "end": END})
    return b.compile()


def build_qa_graph():
    b = StateGraph(QAState, input_schema=QAInput, output_schema=QAResult)
    for name in ("check_input", "prepare_m2", "module2", "check_m2", "adapt", "module3", "check_m3", "check_notes",
                 "draw", "finalize"):
        b.add_node(name, getattr(n, name))
    b.add_node("answer", build_answer_graph())                                                # 모듈 6 갈래

    b.add_edge(START, "check_input")
    b.add_conditional_edges("check_input", n.route_input, ["prepare_m2", "finalize"])
    b.add_conditional_edges("prepare_m2", n.route_prepare, ["module2", "finalize"])
    b.add_edge("module2", "check_m2")
    b.add_conditional_edges("check_m2", n.route_m2, ["module2", "adapt", "finalize"])
    b.add_conditional_edges("adapt", n.route_adapt, ["module3", "finalize"])
    b.add_edge("module3", "check_m3")
    b.add_conditional_edges("check_m3", n.route_m3, ["module3", "check_notes", "finalize"])
    b.add_conditional_edges("check_notes", n.route_notes, ["module3", "draw", "answer"])       # 모듈 5 ∥ 6
    b.add_edge(["draw", "answer"], "finalize")                                                 # 두 갈래가 다 끝나면
    b.add_edge("finalize", END)
    return b.compile()


graph = build_qa_graph()
