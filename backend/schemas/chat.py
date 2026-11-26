"""
답변·통합 파이프라인 입출력

  ChatRequest  ─▶ 질의 분석 ─▶ 검색·View(충돌 판정) ─▶ 답변 ─▶ ChatResponse      (POST /api/v1/chat)
  AnswerRequest(question + Record 목록) ─▶ 답변만 ─▶ AnswerResult                  (POST /api/v1/agent/answer)
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import QueryAnalysis
from backend.schemas.record import Record
from backend.schemas.view import SelectionItem, ViewSet

Status = Literal["ok", "needs_clarification", "needs_selection", "out_of_scope"]


class ChartData(BaseModel):
    record_id: str
    type: str = Field(..., description="line | bar | table")
    title: str
    x: str | None = None
    y: str = "값"
    series: str | None = None
    unit: str | None = None
    columns: list[str]
    rows: list[list[Any]]


class AnswerResult(BaseModel):
    answer: str
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    insufficient: bool = False
    unverified_numbers: list[str] = Field(default_factory=list, description="자료에서 확인되지 않은 숫자 (계산값일 수 있음)")
    used_ids: list[str] = Field(default_factory=list)
    chart_id: str | None = None
    chart: ChartData | None = None
    sources: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list, description="View 생성 때 못 맞춘 조건")
    calculations: list[dict] = Field(default_factory=list, description="코드 계산 결과 (플러그인 파이프라인이 채움)")


class AnswerRequest(BaseModel):
    question: str
    records: list[Record]
    notes: dict[str, list[str]] = Field(default_factory=dict, description="record id → 못 맞춘 조건")
    titles: dict[str, str] = Field(default_factory=dict, description="record id → 표 이름 (없으면 lexical_text 앞부분)")
    max_rows: int = Field(40, ge=1, le=500, description="Record 하나당 LLM 에 넣을 최대 행 수")


class ChatRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"question": "작년 대구의 남자 20대 인구 수", "today": "2026-11-02"},
        {"question": "2023년 충남 인구랑 시군구별 고령인구비율 순위", "today": "2026-11-02"}]})
    question: str
    today: str | None = Field(None, description="상대 시점 기준일 YYYY-MM-DD (비우면 오늘)")
    top_k: int | None = Field(None, ge=1, le=50, description="검색 단위마다 후보 표 수 (비우면 설정값)")
    n_views: int | None = Field(None, ge=1, le=10, description="검색 단위마다 View 를 만들 표 수 (비우면 설정값)")
    max_rows: int = Field(40, ge=1, le=500)
    auto_select: bool = Field(True, description="표마다 값이 다르면 검색 순위가 가장 높은 선택지로 바로 답변. "
                                                "false 면 status=needs_selection 으로 멈추고 views.pending 을 돌려줌")
    overrides: dict = Field(default_factory=dict, description="configs/pipeline.yaml 값 일부만 바꾸기")
    previous: dict | None = Field(None, description="이어서 할 때 직전 /chat 응답 그대로 (needs_clarification · needs_selection)")
    selections: dict[str, list[str]] | None = Field(None, description="되묻기 응답 (슬롯 → 값). previous 와 함께")
    view_selections: list[SelectionItem] | None = Field(None, description="충돌 선택 (selection_token + option_id). previous 와 함께")
    save: bool = Field(False, description="true 면 ANSWERS_DIR 에 결과 JSON 저장")
    session_id: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]{8,100}$", description=(
        "멀티턴 세션 id (REDIS_URL 이 있을 때). 주면 응답을 서버에 두어 GET /api/v1/sessions/{id} 로 다시 받을 수 있고, "
        "이어서 할 때 previous 없이 selections · view_selections 만 보내도 된다 (previous 가 있으면 그것이 먼저)"))
    pipeline: str = Field("default", description="default | 개인 폴더 파이프라인 이름 (GET /api/v1/system/pipelines)")
    answer_mode: Literal["default", "modules"] = Field("default", description=(
        "default = 답변 HCX 1회 (agent/answer.py) · modules = 모듈 2→3→5→6 (차트 계획·계산·그림·답변 문장). "
        "modules 의 결과 전체는 응답 modules 에, 답변은 result 에도 같은 모양으로 넣는다"))
    draw: bool = Field(True, description="answer_mode=modules 일 때 모듈 5 로 차트 그림(plotly JSON)도 만들지")


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    question: str
    status: Status
    analysis: QueryAnalysis | None = Field(None, description="질의 분석 결과")
    views: ViewSet | None = Field(None, description="검색 단위별 View + 충돌 판정")
    records: list[Record] = Field(default_factory=list, description="답변에 넘긴 카드")
    result: AnswerResult | None = Field(None, description="답변 (status=ok · out_of_scope 일 때)")
    notes: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict, description="단계별 소요 시간(초)")
    modules: dict[str, Any] | None = Field(None, description=(
        "answer_mode=modules 결과: charts · chart_errors · chart_plan(모듈 2) · module3 · drawn(모듈 5) · answer(모듈 6) · notes"))
    saved: str | None = None
    session_id: str | None = Field(None, description="요청의 session_id (세션 저장을 켰을 때)")
    trace: list[dict] | None = Field(None, description="플러그인 파이프라인 단계 기록 (있으면)")


class ModulesRequest(BaseModel):
    """POST /api/v1/rag/views 응답(ViewSet) → 모듈 2→3→5→6 한 번에"""
    views: ViewSet = Field(..., description="POST /api/v1/rag/views 응답 그대로 (status=ok)")
    use_llm_chart: bool = Field(True, description="False 면 모듈 2 가 HCX 를 부르지 않는다 (규칙으로 못 정한 measure 는 raw)")
    draw: bool = Field(True, description="모듈 5 로 차트 그림(plotly JSON)도 만들지")
    max_rows: int = Field(50, ge=1, le=500, description="근거 표에 넣을 원본 View 최대 행 수")
