"""
[NEW] 모듈 3 그래프 (LangGraph) — Module3Request → Module3Output

  START → decide → plan → build_charts → answer_steps → assemble → END

  decide        HCX 가 무엇을 계산할지 정한다           (state 에 decision 이 있으면 건너뛴다)
  plan          ChartPlan + displays                   (규칙)
  build_charts  차트용 계산 → ChartContent · validation
  answer_steps  질문용 계산 → CalcResult               (차트 검증 결과와 관계없이 실행한다 — 명세 7장.
                                                       차트 단계와 같은 계산(plan.answer_reuse)은 다시 계산하지 않고 그 결과를 쓴다)
  assemble      Module3Output + 단계별 중간 결과(Module3Trace)

  - 노드는 state 를 읽고 바뀐 키만 돌려주는 함수다. 그래프 밖에서도 그대로 부를 수 있다.
  - [CHANGED] 이전: build_charts 와 answer_steps 가 병렬이었다. 같은 계산을 한 번만 하려고 answer_steps 가 build_charts 의 계산 결과
    (state["chart_calcs"])를 받는다 → 순서가 생겼다. 차트가 검증에서 탈락해도 계산 결과는 남아 있으므로 CalcResult 는 영향이 없다.
  - HCX 호출 함수(chat)는 state 가 아니라 config["configurable"]["chat"] 로 받는다. state 에 함수를 두면 직렬화가 막힌다.
  - 진입점은 pipeline.run_module3 · run_module3_trace. 다른 그래프에 붙일 때는 graph(또는 build_module3_graph())를 노드로 넣는다.
"""
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from backend.agent.chart_calculate.calculate import Calc, run_answer_steps
from backend.agent.chart_calculate.content import build_chart
from backend.agent.chart_calculate.decide import decide_trace
from backend.agent.chart_calculate.display import format_value
from backend.agent.chart_calculate.planner import Decision, make_plan
from backend.agent.chart_calculate.specs import requirements_for
from backend.schemas.chart import (CalcResult, ChartContent, ChartPlan, ChartValidation, CheckResult, Display,
                                   Module3Output, Module3Request, Plan)

PLAN_PRESENT = "plan_present"     # [명세 외] 계획을 세우지 못한 차트를 validation 에 남길 때 쓰는 검증 코드


# ── 중간 결과 (테스트 화면용 계약. 모듈 간 계약이 아니라 schemas/ 에 두지 않는다) ──
class DecideTrace(BaseModel):
    skipped: bool = Field(False, description="decision 을 직접 받아 HCX 를 부르지 않았다")
    messages: list[dict[str, str]] = Field(default_factory=list, description="HCX 에 보낸 system · user 메시지")
    raw: Any = Field(None, description="HCX 원 응답 (JSON 으로 읽은 것)")
    notes: list[str] = Field(default_factory=list, description="호출 실패 · 파싱하며 버린 항목")
    decision: Decision


class Attempt(BaseModel):
    content: ChartContent
    check: CheckResult


class ChartTrace(BaseModel):
    plan: Plan
    requirements: list[str] = Field(..., description="원래 차트를 검증한 조건 (모듈 2 가 넘긴 것 + 차트 기본 조건)")
    attempts: list[Attempt] = Field(default_factory=list, description="원래 차트 → 대체 차트 순서. 실패한 시도도 담긴다")
    validation: ChartValidation


class CalcView(BaseModel):
    result: CalcResult
    display_text: str | list[str | None] | None = Field(None, description="displays 를 적용한 표시값 (format_value)")


class Module3Trace(BaseModel):
    decide: DecideTrace
    chart_plan: ChartPlan
    displays: dict[str, Display]
    charts: dict[str, ChartTrace] = Field(default_factory=dict)
    calcs: list[CalcView] = Field(default_factory=list)
    output: Module3Output


# ── State ────────────────────────────────────────────────────────
class Module3Input(TypedDict, total=False):
    request: Module3Request | dict      # dict 로 와도 된다 (Studio · 다른 모듈의 JSON). decide 노드가 객체로 바꾼다
    decision: Decision | dict | None    # 주면 HCX 를 부르지 않는다 (Swagger 시험 · 테스트 · 재실행용)


class Module3Result(TypedDict, total=False):
    output: Module3Output
    trace: Module3Trace


class Module3State(Module3Input, Module3Result, total=False):
    decide: DecideTrace
    chart_plan: ChartPlan
    displays: dict[str, Display]
    charts: dict[str, ChartTrace]
    contents: list[ChartContent]
    validation: dict[str, ChartValidation]
    calc_results: list[CalcResult]
    chart_calcs: dict[str, Calc]          # '{chart_id}.{step_id}' → 차트용 단계의 계산 결과 (질문용 계산이 재사용한다)


# ── 노드 ─────────────────────────────────────────────────────────
def decide_node(state: Module3State, config: RunnableConfig) -> dict:
    request = Module3Request.model_validate(state["request"])
    decision = state.get("decision")
    if decision is None:
        chat = (config.get("configurable") or {}).get("chat")
        t = decide_trace(request.query_bundle, request.records, request.charts, chat)
        dt = DecideTrace(messages=t["messages"], raw=t["raw"], notes=t["notes"], decision=t["decision"])
    else:
        dt = DecideTrace(skipped=True, decision=Decision.model_validate(decision))
    return {"request": request, "decide": dt}


def plan_node(state: Module3State) -> dict:
    request, dt = state["request"], state["decide"]
    plan, displays = make_plan(request.charts, request.records, dt.decision, request.query_bundle)
    plan.notes = dt.notes + plan.notes
    return {"chart_plan": plan, "displays": displays}


def build_charts_node(state: Module3State) -> dict:
    request, dt, plan, displays = state["request"], state["decide"], state["chart_plan"], state["displays"]
    reqs = {c.chart_id: c.requirements for c in request.charts}
    contents, validation, traces, chart_calcs = [], {}, {}, {}
    for p in plan.plans:
        attempts: list = []
        content, validation[p.chart_id] = build_chart(p, request.records, reqs.get(p.chart_id), displays, attempts, chart_calcs)
        if content is not None:
            contents.append(content)
        traces[p.chart_id] = ChartTrace(plan=p, requirements=requirements_for(p.chart_type, reqs.get(p.chart_id)),
                                        attempts=[Attempt(content=c, check=k) for c, k in attempts],
                                        validation=validation[p.chart_id])
    # 모듈 2 가 요청했는데 계획을 세우지 못한 차트도 validation 에 실패로 남긴다.
    # 명세는 "plans 가 없으면 validation 에도 없다"지만, 그러면 Decision(모듈 4)이 차트가 왜 없는지 알 수 없다.
    for c in request.charts:
        if c.chart_type and c.chart_id not in traces:
            why = [n.split(": ", 1)[1] for n in plan.notes if n.startswith(f"{c.chart_id}: ")]
            validation[c.chart_id] = ChartValidation(original=CheckResult(
                chart_type=c.chart_type, passed=False, checked=[PLAN_PRESENT], failed=[PLAN_PRESENT],
                reasons=why or list(dt.notes) or ["차트 계획 없음"]))
    return {"charts": traces, "contents": contents, "validation": validation, "chart_calcs": chart_calcs}


def answer_steps_node(state: Module3State) -> dict:
    plan, done = state["chart_plan"], state.get("chart_calcs") or {}
    # 같은 계산의 차트 단계 결과가 없으면(계산 전에 오류 등) 재사용하지 않고 따로 계산한다
    reuse = {sid: done[ref] for sid, ref in plan.answer_reuse.items() if ref in done}
    return {"calc_results": run_answer_steps(plan.answer_steps, state["request"].records, reuse)}


def _display_text(r: CalcResult, displays: dict[str, Display]) -> str | list[str | None] | None:
    d = displays.get(r.display_ref or "")
    if d is None or r.value is None:
        return None
    if isinstance(r.value, list):
        return [format_value(v.get("value"), d) if isinstance(v, dict) else None for v in r.value]
    return format_value(r.value, d)


def assemble_node(state: Module3State) -> dict:
    request, plan, displays = state["request"], state["chart_plan"], state["displays"]
    results = state["calc_results"]
    output = Module3Output(query_id=request.query_bundle.query_id, chart_plan=plan, chart_contents=state["contents"],
                           calc_results=results, displays=displays, validation=state["validation"])
    trace = Module3Trace(decide=state["decide"], chart_plan=plan, displays=displays, charts=state["charts"],
                         output=output, calcs=[CalcView(result=r, display_text=_display_text(r, displays)) for r in results])
    return {"output": output, "trace": trace}


# ── 연결 ─────────────────────────────────────────────────────────
def build_module3_graph():
    b = StateGraph(Module3State, input_schema=Module3Input, output_schema=Module3Result)
    b.add_node("decide", decide_node)
    b.add_node("plan", plan_node)
    b.add_node("build_charts", build_charts_node)
    b.add_node("answer_steps", answer_steps_node)
    b.add_node("assemble", assemble_node)

    b.add_edge(START, "decide")
    b.add_edge("decide", "plan")
    b.add_edge("plan", "build_charts")
    b.add_edge("build_charts", "answer_steps")                    # 같은 계산은 차트 쪽 결과를 받는다
    b.add_edge("answer_steps", "assemble")
    b.add_edge("assemble", END)
    return b.compile()


graph = build_module3_graph()          # LangGraph Studio(langgraph.json) 에서 쓰는 이름
