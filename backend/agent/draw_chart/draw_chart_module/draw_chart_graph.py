"""
모듈 5 그래프 (LangGraph) — 입력 4개 → DrawResult[] (+ 파일)

  START → load → prepare ─┬─ Send(draw) × 차트 수 ─┬→ save → END
                          └──── (차트 없음) ────────┘

  load     ① 입력 로드: 모듈 2·3 출력 (또는 입력 4개 직접) → 모듈 3 스키마로 파싱
  prepare  ② DrawJob 만들기 (차트 하나당 하나, ChartPlan 순서)
  draw     ③ draw_chart(job) — 차트 하나 그리기. Send로 차트마다 따로 실행된다 (fan-out, 병렬)
  save     ④ 결과 모으기(fan-in) → ChartPlan 순서로 정렬 → json · PNG 일괄 · 질문 HTML

  - 노드는 state를 읽고 바뀐 키만 돌려주는 함수다 (모듈 3 그래프와 같은 방식). 그래프 밖에서도 그대로 부를 수 있다.
  - draw는 Send로 받은 {index, job}만 보고, 결과를 drawn 목록에 더한다 (operator.add). save가 index로 순서를 되돌린다.
  - 진입점은 draw_chart_run.run_module5. 다른 그래프에 붙일 때는 graph(또는 build_module5_graph())를 노드로 넣는다.
"""
import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .draw_chart_load import parse_inputs, resolve_inputs
from .draw_chart_prepare import build_jobs
from .draw_chart_save import fan_in
from .draw_chart_schema import OUTPUT_ROOT, DrawJob, DrawResult
from .draw_chart_tool import draw_chart


# ── State ────────────────────────────────────────
class Module5Input(TypedDict, total=False):
    # 입력은 둘 중 하나 (module3_output이 있으면 1)
    chart_plan: Any                        # 모듈 2 출력 {"query_id", "charts"} (모듈 2 그래프 state 전체도 된다)
    module3_output: Any                    # 1) 모듈 3 출력: Module3Output · dict · Module3Trace · 그래프 결과 {"output", "trace"}
    chart_contents: list                   # 2) 4개 직접: ChartContent[] (dict 또는 객체)
    calc_results: list                     #    CalcResult[]
    displays: dict                         #    {display_ref: Display}
    validation: dict                       #    (선택) 모듈 3 validation — 차트가 없는 이유를 찾을 때만 쓴다
    out_dir: str | Path                    # 저장 위치 (없으면 output/{query_id}/)
    save: bool                             # False면 파일을 쓰지 않고 그리기만 (기본 True)
    # [시나리오] 시나리오 폴더 입력 — 모듈 2·3 연결에서는 쓰지 않아 주석 처리
    # scenario_dir: str | Path             # data/{query_id}/ JSON 4개


class Module5Result(TypedDict, total=False):
    query_id: str
    results: list[DrawResult]              # ChartPlan 순서
    html: str | None                       # 질문 HTML 경로 (save=False면 None)
    load_errors: dict                      # 스키마 오류 {위치: 이유}


class DrawTask(TypedDict):
    """Send로 draw 노드에 넘기는 값 (차트 하나)"""
    index: int
    job: DrawJob


class Module5State(Module5Input, Module5Result, total=False):
    plan: dict                             # 파싱한 ChartPlan
    contents: dict                         # {chart_id: ChartContent | None}
    calcs: list                            # CalcResult[] (아직 쓰지 않음)
    display_map: dict                      # {display_ref: Display}
    checks: dict                           # 모듈 3 validation {chart_id: dict} (skipped 이유용)
    jobs: list[DrawJob]
    drawn: Annotated[list, operator.add]   # [(index, DrawResult)] — draw 노드들이 더한다


# ── 노드 ─────────────────────────────────────────
def load_node(state: Module5State) -> dict:
    raw = resolve_inputs(state)
    plan, contents, calcs, displays, errors = parse_inputs(raw)
    return {"plan": plan, "contents": contents, "calcs": calcs, "display_map": displays, "load_errors": errors,
            "checks": raw.get("validation") or {}, "query_id": plan.get("query_id") or "noquery"}


def prepare_node(state: Module5State) -> dict:
    return {"jobs": build_jobs(state["plan"], state["contents"], state["display_map"], state["load_errors"],
                               state.get("checks"))}


def fan_out(state: Module5State):
    """차트마다 draw 노드 하나 (Send). 차트가 없으면 바로 save"""
    jobs = state.get("jobs") or []
    return [Send("draw", {"index": i, "job": j}) for i, j in enumerate(jobs)] or "save"


def draw_node(task: DrawTask) -> dict:
    return {"drawn": [(task["index"], draw_chart(task["job"]))]}


def save_node(state: Module5State) -> dict:
    results = [r for _, r in sorted(state.get("drawn") or [], key=lambda t: t[0])]
    html = None
    if state.get("save", True) and results:
        out_dir = Path(state.get("out_dir") or OUTPUT_ROOT / state["query_id"])
        html = str(fan_in(results, out_dir, state["query_id"]))
    return {"results": results, "html": html}


# ── 연결 ─────────────────────────────────────────
def build_module5_graph():
    b = StateGraph(Module5State, input_schema=Module5Input, output_schema=Module5Result)
    b.add_node("load", load_node)
    b.add_node("prepare", prepare_node)
    b.add_node("draw", draw_node)
    b.add_node("save", save_node)

    b.add_edge(START, "load")
    b.add_edge("load", "prepare")
    b.add_conditional_edges("prepare", fan_out, ["draw", "save"])    # fan-out
    b.add_edge("draw", "save")                                       # fan-in: 모든 draw가 끝나야 save
    b.add_edge("save", END)
    return b.compile()


graph = build_module5_graph()
