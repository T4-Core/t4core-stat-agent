"""
[NEW] 모듈 3 진입점 — Module3Request → Module3Output

  run_module3(request)
    decide        HCX 가 무엇을 계산할지 정한다           (decision 을 직접 주면 건너뛴다)
    make_plan     ChartPlan + displays                   (규칙)
    build_chart   차트용 계산 → ChartContent · validation
    run_answer_steps  질문용 계산 → CalcResult            (차트 검증 결과와 관계없이 실행)

  run_module3_trace(request) 는 같은 일을 하면서 단계별 중간 결과(Module3Trace)를 함께 돌려준다 (테스트 화면 frontend/chart-lab).
  두 함수가 같은 _run 을 타므로 trace.output 은 run_module3 의 결과와 같다.
"""
from typing import Any, Callable

from pydantic import BaseModel, Field

from backend.agent.chart_calculate.calculate import run_answer_steps
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


def _display_text(r: CalcResult, displays: dict[str, Display]) -> str | list[str | None] | None:
    d = displays.get(r.display_ref or "")
    if d is None or r.value is None:
        return None
    if isinstance(r.value, list):
        return [format_value(v.get("value"), d) if isinstance(v, dict) else None for v in r.value]
    return format_value(r.value, d)


def _run(request: Module3Request, decision: Decision | None, chat: Callable[..., Any] | None) -> Module3Trace:
    if decision is None:
        t = decide_trace(request.query_bundle, request.records, request.charts, chat)
        dt = DecideTrace(messages=t["messages"], raw=t["raw"], notes=t["notes"], decision=t["decision"])
    else:
        dt = DecideTrace(skipped=True, decision=decision)
    plan, displays = make_plan(request.charts, request.records, dt.decision, request.query_bundle)
    plan.notes = dt.notes + plan.notes

    reqs = {c.chart_id: c.requirements for c in request.charts}
    contents, validation, traces = [], {}, {}
    for p in plan.plans:
        attempts: list = []
        content, validation[p.chart_id] = build_chart(p, request.records, reqs.get(p.chart_id), displays, attempts)
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

    calc_results = run_answer_steps(plan.answer_steps, request.records)
    output = Module3Output(query_id=request.query_bundle.query_id, chart_plan=plan, chart_contents=contents,
                           calc_results=calc_results, displays=displays, validation=validation)
    return Module3Trace(decide=dt, chart_plan=plan, displays=displays, charts=traces, output=output,
                        calcs=[CalcView(result=r, display_text=_display_text(r, displays)) for r in calc_results])


def run_module3(request: Module3Request, decision: Decision | None = None,
                chat: Callable[..., Any] | None = None) -> Module3Output:
    """decision 을 주면 HCX 를 부르지 않는다 (Swagger 시험·테스트·재실행용)"""
    return _run(request, decision, chat).output


def run_module3_trace(request: Module3Request, decision: Decision | None = None,
                      chat: Callable[..., Any] | None = None) -> Module3Trace:
    return _run(request, decision, chat)
