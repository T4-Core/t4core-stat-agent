"""
[NEW v4] 쿼리 모듈 v4 · CSV 값 사전 API 스키마 (Swagger 에서 단계별 확인)

기존 계약은 그대로 담음: bundle = 재작성 v3 RewriterBundle(dict), view_bundle = View 모듈 입력 QueryBundle (POST /api/v1/rag/views)
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.schemas.query import QueryBundle

EX_Q = "2025년 대전 출생아 수와 사망자 수 차이"


# ── CSV 값 사전 ──────────────────────────────────────────────────
class CsvIndexBuildRequest(BaseModel):
    scope: Literal["all", "selected"] = Field("all", description="all = raw 폴더 전체 (조회 때 설정 csv_scope 로 거름) / selected")
    limit: int | None = Field(None, description="앞에서부터 n개 표만 (빠른 확인)")
    force: bool = Field(False, description="원본이 같아도 다시 스캔")
    workers: int = Field(4, ge=1, le=16)


class CsvRow(BaseModel):
    tbl_id: str
    kind: str = Field(..., description="dim(분류 값) / item(항목) / obj(열 머리) / table(표 이름)")
    slot: str = Field(..., description="지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표")
    obj_nm: str = ""
    name: str
    code: str = ""


class CsvValue(BaseModel):
    value: str
    n_tables: int
    example_tables: list[str] = []


# ── 동의어 ──────────────────────────────────────────────────────
class LexiconLookupRequest(BaseModel):
    text: str = Field(..., examples=["신생아 수"])
    slot: str | None = Field("지표", description="슬롯 이름 (지역·성별·연령·대상·지표·국적·조건·이동·비교축). 비우면 전체")
    overrides: dict[str, Any] | None = Field(None, description="설정 일부 바꾸기 (예: {\"csv_scope\": \"all\"})")


class LexiconHit(BaseModel):
    surface: str
    value: str
    slot: str | None
    source: str = Field(..., description="learned / rule / csv / term>csv / contains / term")
    score: float
    match: str = ""
    grounded: bool
    n_tables: int
    tables: list[str] = []
    csv: list[CsvRow] = []


class LexiconLookupResponse(BaseModel):
    hits: list[LexiconHit]
    suggestions: list[str] = Field(default_factory=list, description="비슷한 CSV 이름 (접지 실패 시 되묻기 후보)")


class LearnRequest(BaseModel):
    surface: str = Field(..., examples=["아기 수"])
    value: str = Field(..., examples=["출생아수"])
    slot: str | None = "지표"
    approve: bool = Field(False, description="true 면 바로 사용(active), false 면 승인 대기(pending)")


# ── 분석 ────────────────────────────────────────────────────────
class SlotValue(BaseModel):
    raw: str
    value: Any = Field(..., description="표준 값 (연도 int · 지역 표준명 · 연령 {from,to} · CSV 이름)")
    source: str
    match: str = Field("", description="CSV 일치 방식: exact(띄어쓰기만 다름) / variant(괄호·'수' 등 표기 변형) / contains")
    grounded: bool = Field(..., description="CSV 값 사전에 근거가 있는가")
    n_tables: int
    tables: list[str] = []
    csv: list[CsvRow] = []
    candidates: list[dict] = []
    note: str = ""


class ChoiceOption(BaseModel):
    option_id: str
    value: str = Field(..., description="selections 에 그대로 넣을 값")
    label: str
    n_tables: int = 0
    example_tables: list[str] = []


class Clarification(BaseModel):
    slot: Literal["시점", "지역", "대상"]
    reason: str
    options: list[ChoiceOption]
    multi: bool = True
    answer_hint: str = ""


class SubQuery(BaseModel):
    id: str
    text: str
    slots: dict[str, list[str]]
    intent: str | None = None
    reason: str
    candidate_tables: list[str] = []


class AnalysisState(BaseModel):
    """되묻기 응답 때 previous.state 로 돌려보내면 HCX 를 다시 부르지 않음"""
    bundle: dict
    raw_slots: dict[str, list[str]]
    sub_slots: list[dict[str, list[str]]] = []
    intents: list[str] = []
    sub_intents: list[str | None] = []
    hcx_ok: bool = True
    hcx_error: str = ""


class StepTraceModel(BaseModel):
    step: str
    params: dict = {}
    output: Any = None
    notes: list[str] = []
    seconds: float = 0.0
    error: str | None = None


class QueryAnalysis(BaseModel):
    status: Literal["ok", "needs_clarification", "out_of_scope"]
    question: str
    query_id: str | None = None
    bundle: dict = Field(..., description="재작성 모듈 v3 출력 (RewriterBundle) 그대로")
    view_bundle: QueryBundle | None = Field(None, description="status=ok 일 때 → POST /api/v1/rag/views 에 그대로")
    search_text: str = ""
    slots: dict[str, list[SlotValue]] = {}
    clarifications: list[Clarification] = []
    sub_queries: list[SubQuery] = []
    decompose_reason: str = ""
    applied_rules: list[str] = []
    notes: list[str] = []
    state: AnalysisState
    trace: list[StepTraceModel] = []


class AnalyzeRequest(BaseModel):
    question: str = Field(..., examples=[EX_Q])
    today: str | None = Field(None, description="YYYY-MM-DD ('작년'·'최근 N년' 기준). 비우면 오늘")
    query_id: str | None = None
    overrides: dict[str, Any] | None = Field(None, description="configs/query_v4.yaml 값 일부 바꾸기 "
                                                               "(예: {\"base_year\": 2025, \"search_text_mode\": \"llm\"})")


class ClarifyRequest(BaseModel):
    question: str = Field(..., examples=["출생아 수 알려줘"])
    selections: dict[str, list[str]] = Field(..., examples=[{"지역": ["대전광역시"], "시점": ["2025년"]}],
                                             description="되묻기 options[].value 중 고른 값 (슬롯 → 값 목록)")
    previous: QueryAnalysis | None = Field(None, description="직전 /v4/analyze 응답 (있으면 HCX 다시 안 부름)")
    today: str | None = None
    query_id: str | None = None
    overrides: dict[str, Any] | None = None


class DecomposeRequest(BaseModel):
    question: str = Field(..., examples=[EX_Q])
    slots: dict[str, list[str]] = Field(..., examples=[{"시점": ["2025년"], "지역": ["대전광역시"], "지표": ["출생아수", "사망자수"]}])
    intents: list[str] = Field(default_factory=lambda: ["비교"])
    overrides: dict[str, Any] | None = None


class DecomposeResponse(BaseModel):
    reason: str
    sub_queries: list[SubQuery]
    slots: dict[str, list[SlotValue]]
