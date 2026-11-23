"""QA 그래프 State · QA 기록 요약

  QAInput   그래프 입력 (viewset · 옵션)
  QAResult  그래프 출력 (result = run_modules 와 같은 11개 키 + qa)
  QAState   노드 사이에 오가는 값 전부

  모듈 5 와 6 은 병렬로 돈다 → 두 갈래가 함께 쓰는 키는 합치기 규칙(reducer)을 둔다
    목록 (issues · retries · dropped · skipped · checked · notes)   이어 붙인다 (operator.add)
    dict (outs · excs · tries · pending · routes)                   키별로 덮어쓴다 (merge)
  그 밖의 키는 한 갈래만 쓴다 (모듈 5: drawn / 모듈 6: req6 · m6)

  HCX 함수(chat)와 시험용 모듈 바꿔 끼우기(mods)는 state 가 아니라 config["configurable"] 로 받는다 (모듈 3 · 6 과 같은 방식).
"""
import operator
from typing import Annotated, Any, TypedDict

from .qa_check import ERROR, INFO, WARNING, Issue
from .qa_policy import RULES, SEMANTIC_KINDS, skip_message, stop_message


def merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class QAInput(TypedDict, total=False):
    viewset: dict
    use_llm_chart: bool
    draw: bool
    max_rows: int
    decision: Any                       # 모듈 3 decision 고정 (주면 HCX 를 부르지 않고 재시도도 하지 않는다)
    analysis_notes: list                # 질의 분석 메모 (사전에 없는 지표 → A0 조기 종료)


class QAResult(TypedDict, total=False):
    result: dict


class QAState(QAInput, QAResult, total=False):
    # 모듈 2 입력 · 출력
    bundle: Any                         # QueryBundle
    view_input: dict
    role_views: list
    role_links: list                    # RoleLink[] — split_roles_linked (모듈 3 · 6 에 그대로 넘김)
    role_unit_ids: list                 # 질문에서 뺀 역할 단위의 id (role_links.unit_id 짝)
    out2: dict
    plan: dict
    # 어댑터 · 모듈 3
    charts: list                        # ChartRequest[]
    charts_dump: list
    records: list                       # Record[]
    chart_errors: list
    req3: Any                           # Module3Request
    m3: Any                             # Module3Output (검사 · 메모 재시도를 마친 것)
    m3_first: Any                       # 메모 재시도 전 결과
    note_mode: bool                     # True = 지금 모듈 3 실행은 메모 재시도
    note_hits: list
    note_why: str
    # 모듈 5 · 6 (병렬)
    drawn: list
    render_error: str | None            # 모듈 5 예외 요약 (KOS-41: failed/exception)
    render_rejected: bool               # M5-out 이 모듈 5 출력 전체를 버림 (KOS-41: failed/render_error)
    req6: Any
    m6: Any
    # 모듈 실행 · 재시도
    outs: Annotated[dict, merge]        # {지점: 모듈 출력}
    excs: Annotated[dict, merge]        # {지점: 예외 | None}
    tries: Annotated[dict, merge]       # {지점: 실행 횟수}
    pending: Annotated[dict, merge]     # {지점: 재시도 이유} — 결과가 나오면 None
    routes: Annotated[dict, merge]      # {지점: ok | partial | retry | fail} — 분기 함수가 읽는다
    # QA 기록
    notes: Annotated[list, operator.add]
    issues: Annotated[list, operator.add]
    retries: Annotated[list, operator.add]
    dropped: Annotated[list, operator.add]
    dropped_requests: Annotated[list, operator.add]  # QA 가 뺀 차트 중 사용자가 지정한 차트 {point, chart_id, name}
    skipped: Annotated[list, operator.add]
    checked: Annotated[list, operator.add]
    stopped_at: str | None
    stop_note: str | None               # 형식 오류가 아닌 중단의 안내 문구 (데이터 없음 · 지표 없음)


class AnswerInput(TypedDict, total=False):
    """모듈 6 갈래 서브그래프의 입력 — 부모 state 중 필요한 값만 받는다
    (부모의 기록 목록을 받으면 서브그래프가 끝날 때 그대로 돌려줘 같은 항목이 두 번 쌓인다)"""
    bundle: Any
    records: list
    m3: Any
    max_rows: int
    role_links: list                    # 모듈 6 이 보조 · 대체 결과를 가려내는 데 쓴다 (KOS-38)
    role_unit_ids: list                 # M6-in id 짝 검사용
    req3: Any                           # M6-in id 짝 검사용 (모듈 3 이 받은 차트 id)


class AnswerOutput(TypedDict, total=False):
    """모듈 6 갈래가 부모에 돌려주는 것 — 새로 생긴 기록만"""
    m6: Any
    issues: Annotated[list, operator.add]
    retries: Annotated[list, operator.add]
    skipped: Annotated[list, operator.add]
    checked: Annotated[list, operator.add]


class AnswerState(AnswerInput, AnswerOutput, total=False):
    req6: Any
    outs: Annotated[dict, merge]
    excs: Annotated[dict, merge]
    tries: Annotated[dict, merge]
    pending: Annotated[dict, merge]
    routes: Annotated[dict, merge]


def mark(issues: list[Issue], action: str | None = None) -> list[Issue]:
    """문제에 대응(action)을 붙인다. action 은 오류(error)에만 붙이고, 나머지는 보정·경고·기록으로"""
    for i in issues:
        if action and i.severity == ERROR:
            i.action = action
        elif i.action is None:
            i.action = "fixed" if i.fixed else ("warn" if i.severity == WARNING else "info")
    return issues


def summarize(issues, retries, dropped, skipped, checked, stopped_at, stop_note: str | None = None) -> dict:
    """QA 기록 → result['qa'] (상태 · 멈춘 단계 · 안내 문구 · 문제 목록)
    상태: stopped(중단) · partial(일부 뺌 · 건너뜀) · warned(오류 · 재시도 · 내용 경고) · ok (문제 없음 또는 형식 경고만)"""
    semantic = sum(1 for i in issues if i.severity == WARNING and i.kind in SEMANTIC_KINDS)
    if stopped_at:
        for i in issues:                    # 멈춘 지점의 오류는 '중단' 으로 표시
            if i.point == stopped_at and i.severity == ERROR and i.action in (None, "skip", "info"):
                i.action = "stop"
        status = "stopped"
    elif dropped or skipped:
        status = "partial"
    elif retries or semantic or any(i.severity == ERROR for i in issues):
        status = "warned"
    else:
        status = "ok"
    msgs = [stop_note or stop_message(stopped_at)] if stopped_at else [skip_message(p) for p in skipped]
    counts = {s: sum(1 for i in issues if i.severity == s) for s in (ERROR, WARNING, INFO)}
    counts.update(semantic=semantic, format=counts[WARNING] - semantic)
    return {"status": status, "stopped_at": stopped_at,
            "stopped_stage": RULES[stopped_at].stage if stopped_at else None,
            "message": " ".join(m for m in msgs if m) or None,
            "checked": list(checked), "skipped": list(skipped), "retries": list(retries), "dropped": list(dropped),
            "counts": counts, "issues": [i.as_dict() for i in issues]}


class QARecord:
    """그래프 밖에서 QA 기록을 모을 때 (노트북의 '검사만' 등). 그래프 안에서는 QAState 의 목록을 쓴다"""

    def __init__(self):
        self.issues: list[Issue] = []
        self.retries: list[dict] = []
        self.dropped: list[dict] = []
        self.skipped: list[str] = []
        self.stopped_at: str | None = None
        self.checked: list[str] = []

    def add(self, issues, action=None):
        self.issues += mark(issues, action)

    def summary(self) -> dict:
        return summarize(self.issues, self.retries, self.dropped, self.skipped, self.checked, self.stopped_at)
