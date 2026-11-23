"""
[NEW] 모듈 6 그래프 (LangGraph) — Module6Request → Module6Output

  START → build_tables ─┬(계산 없음)────────────────────────────────────────┐
                        ├(계산 전부 실패)→ template ─────────────────────────┤
                        └→ write → fill → check ─(통과)──────────────────────┤→ assemble → END
                                     ▲            ├(실패, 1회째)→ write 로 돌아감
                                     └────────────┘(실패, 2회째 · HCX 호출 오류)→ template ┘

  build_tables  계산 요약표 · 계산 목록표 · 원본 View 표 · caveats      (규칙)
  write         HCX 가 자리표시자가 든 답변 초안을 쓴다 (2회째는 무엇이 틀렸는지 알려 준다)
  fill          자리표시자 → 값
  check         풀 수 없는 자리표시자 · 자리표시자 밖 숫자 · 인용 누락 검사
  template      규칙 문장 (HCX 를 부르지 않는다)
  assemble      Module6Output + 단계별 중간 결과(Module6Trace)

  - HCX 호출 함수(chat)는 state 가 아니라 config["configurable"]["chat"] 로 받는다 (모듈 3 과 같은 방식).
  - 노드는 state 를 읽고 바뀐 키만 돌려주는 함수다. 그래프 밖에서도 그대로 부를 수 있다.
"""
from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from backend.agent.answer_compose import placeholder, template
from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.tables import build_tables
from backend.agent.answer_compose.write import ask, initial_messages, retry_messages, shown_tokens
from backend.schemas.answer import AnswerTable, Caveat, Method, Module6Output, Module6Request

MAX_ATTEMPTS = 2            # HCX 는 처음 한 번 + 재시도 한 번
NO_CALC_ANSWER = "계산된 결과가 없어 수치 답변을 만들 수 없습니다."


def no_calc_answer(request: Module6Request) -> str:
    """[NEW 11-20] 계산 결과가 없을 때의 첫 문장 (M6-3). 이전: 고정 문구('계산된 결과가 없어 수치 답변을 만들 수 없습니다') — 시스템 사정처럼 들리고 사유가 없다.
    지표 대응 때문에 보류했으면 '받은 자료에서 ○○을 확인하지 못했습니다' (통계가 없다고 단정하지 않는다: 확인한 범위는 받은 자료뿐이다).
    다른 보류 사유면 그 사유 문장을, 사유가 없으면 예전 문구를 쓴다"""
    from backend.core.korean import josa
    held = [w.text for w in request.withheld]       # 범위를 모르는 예전 입력(plan_warnings 만)은 기존 문구를 유지한다
    if not held:
        return NO_CALC_ANSWER
    indicators = [str(x) for x in (request.query_bundle.filters.지표 if request.query_bundle.filters and request.query_bundle.filters.지표 else [])]
    if indicators and held[0].startswith("요청한 지표("):
        return f"받은 자료에서 {josa(', '.join(indicators), '을')} 확인하지 못했습니다."
    return held[0]


# ── 중간 결과 (테스트 화면용. 모듈 간 계약이 아니라 schemas/ 에 두지 않는다) ──
class AnswerAttempt(BaseModel):
    messages: list[dict[str, str]] = Field(default_factory=list, description="HCX 에 보낸 메시지")
    raw: Any = Field(None, description="HCX 원 응답")
    draft: str | None = Field(None, description="자리표시자가 든 초안")
    filled: str | None = Field(None, description="자리표시자를 채운 문장")
    problems: list[str] = Field(default_factory=list, description="검사에서 걸린 문제 (비어 있으면 통과)")

Attempt = AnswerAttempt   # 예전 이름 (Swagger 스키마 이름이 모듈 3·6 에서 겹치지 않게 클래스 이름을 나눔)


class Module6Trace(BaseModel):
    attempts: list[AnswerAttempt] = Field(default_factory=list)
    output: Module6Output


# ── State ────────────────────────────────────────────────────────
class Module6Input(TypedDict, total=False):
    request: Module6Request | dict      # dict 로 와도 된다 (Studio · 다른 모듈의 JSON)


class Module6Result(TypedDict, total=False):
    output: Module6Output
    trace: Module6Trace


class Module6State(Module6Input, Module6Result, total=False):
    facts: Facts
    tables: list[AnswerTable]
    caveats: list[Caveat]
    attempt: int
    messages: list[dict[str, str]]
    raw: Any
    draft: str | None
    hcx_error: str | None
    allowed: set[str]
    filled: placeholder.Filled | None
    problems: list[str]
    attempts: list[AnswerAttempt]
    answer: str
    method: Method
    used: list[str]


# ── 노드 ─────────────────────────────────────────────────────────
def build_tables_node(state: Module6State) -> dict:
    request = Module6Request.model_validate(state["request"])
    facts = Facts(request)
    return {"request": request, "facts": facts, "tables": build_tables(facts), "caveats": build_caveats(facts),
            "attempt": 0, "attempts": [], "problems": []}


def write_node(state: Module6State, config: RunnableConfig) -> dict:
    attempt = state.get("attempt", 0) + 1
    if attempt == 1:
        messages = initial_messages(state["facts"], state["caveats"])
    else:
        messages = retry_messages(state["messages"], state.get("draft") or "", state["problems"])
    chat = (config.get("configurable") or {}).get("chat")
    raw, draft, error = ask(messages, chat)
    out = {"attempt": attempt, "messages": messages, "raw": raw, "draft": draft, "hcx_error": error}
    if attempt == 1:                      # 모델에게 보여 준 자리표시자만 허용한다 (재시도에도 같은 목록)
        out["allowed"] = shown_tokens(state["facts"])
    return out


def fill_node(state: Module6State) -> dict:
    if state.get("hcx_error"):
        return {"filled": None}
    return {"filled": placeholder.fill(state["draft"] or "", state["facts"], state.get("allowed"))}


def check_node(state: Module6State) -> dict:
    filled, error = state.get("filled"), state.get("hcx_error")
    problems = [error] if error else placeholder.check(state["draft"] or "", filled, state["facts"], state["caveats"])
    log = AnswerAttempt(messages=state["messages"], raw=state.get("raw"), draft=state.get("draft"),
                  filled=filled.text if filled else None, problems=problems)
    out: dict = {"problems": problems, "attempts": [*state["attempts"], log]}
    if not problems:
        out.update(answer=filled.text, used=filled.used, method="hcx" if state["attempt"] == 1 else "hcx_retry")
    return out


def template_node(state: Module6State) -> dict:
    facts = state["facts"]
    return {"answer": template.compose(facts, state["caveats"]), "method": "template",
            "used": [r.step_id for r in facts.ok_results]}


def assemble_node(state: Module6State) -> dict:
    request, facts, caveats = state["request"], state["facts"], state["caveats"]
    if "answer" in state:
        answer, method, used = state["answer"], state["method"], state.get("used", [])
    else:                                         # 계산 결과가 없어 답변할 것이 없다
        head = no_calc_answer(request)
        answer = "\n".join([head, *(f"※ {c.text}" for c in caveats if c.text != head)])
        method, used = "none", []
    attempts = state.get("attempts", [])
    notes = [f"{n}차 시도 실패: {'; '.join(a.problems)}" for n, a in enumerate(attempts, 1) if a.problems]
    output = Module6Output(query_id=request.query_bundle.query_id, answer=answer, insufficient=not facts.ok_results,
                           method=method, tables=state["tables"], caveats=caveats, used_step_ids=used, notes=notes)
    return {"output": output, "trace": Module6Trace(attempts=attempts, output=output)}


# ── 분기 ─────────────────────────────────────────────────────────
def route_start(state: Module6State) -> Literal["write", "template", "assemble"]:
    facts = state["facts"]
    if not facts.req.calc_results:
        return "assemble"
    return "write" if facts.ok_results else "template"      # 전부 계산 실패면 HCX 에게 쓸 숫자가 없다


def route_check(state: Module6State) -> Literal["assemble", "write", "template"]:
    if not state["problems"]:
        return "assemble"
    if state.get("hcx_error") or state["attempt"] >= MAX_ATTEMPTS:      # 호출 오류는 다시 불러도 같다고 본다
        return "template"
    return "write"


# ── 연결 ─────────────────────────────────────────────────────────
def build_module6_graph():
    b = StateGraph(Module6State, input_schema=Module6Input, output_schema=Module6Result)
    b.add_node("build_tables", build_tables_node)
    b.add_node("write", write_node)
    b.add_node("fill", fill_node)
    b.add_node("check", check_node)
    b.add_node("template", template_node)
    b.add_node("assemble", assemble_node)

    b.add_edge(START, "build_tables")
    b.add_conditional_edges("build_tables", route_start, ["write", "template", "assemble"])
    b.add_edge("write", "fill")
    b.add_edge("fill", "check")
    b.add_conditional_edges("check", route_check, ["assemble", "write", "template"])
    b.add_edge("template", "assemble")
    b.add_edge("assemble", END)
    return b.compile()


graph = build_module6_graph()          # LangGraph Studio 에서 쓰는 이름
