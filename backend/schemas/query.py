"""
질의 분석 입출력

  QueryAnalysis  질문 → 분석 결과 (POST /api/v1/rag/analyze). status=ok 이면 view_bundle 이 검색·View 입력
  QueryBundle    검색·View 입력 (view_bundle). 검색은 자연어(search_text·sub_questions), View 조건은 슬롯(filters·sub_filters)
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["값 조회", "추이", "비교", "순위", "구성비", "증감", "증감률", "범위 밖", "합계"]

EX_Q = "2025년 대전 출생아 수와 사망자 수 차이"
EX_VIEW_BUNDLE = {
    "query_id": "q1",
    "original": "2023년 충남 인구랑 시군구별 고령인구비율 순위",
    "rewritten": "2023년 충청남도 인구수 고령인구비율 시군구별 순위",
    "intent": "값 조회",
    "filters": {"시점": [2023], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수", "고령인구비율"], "비교축": "시군구",
                "의도": "값 조회"},
    "sub_questions": ["2023년 충청남도 인구수", "2023년 충청남도 고령인구비율 시군구별 순위"],
    "sub_filters": [{"시점": [2023], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수"], "의도": "값 조회"},
                    {"시점": [2023], "지역": ["충청남도"], "지표": ["고령인구비율"], "비교축": "시군구", "의도": "순위"}],
    "search_text": "충청남도 인구수 고령인구비율",
}


# ── 검색·View 입력 ───────────────────────────────────────────────
class AgeRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: int | None = Field(None, alias="from", description="시작 나이 (포함)")
    to: int | None = Field(None, description="끝 나이 (포함). 없으면 상한 없음 (예: 65세 이상)")


# [NEW 11-20] 조건의 열·연산자·값 보존 (KOS-26). 조건(list[str])은 검색 보조어라 어댑터가 값만 남기고 연산자와 열 이름을 버렸다
#   ('가구원수>=5' → '5'). 모듈 3 이 '이 조건을 실제로 적용했는가' 를 검사하려면 이 구조가 필요하다
class Condition(BaseModel):
    field: str | None = Field(None, description="분류 축 이름 (혼인상태, 가구원수). 원문에 없으면 None")
    op: Literal["=", "!=", ">", ">=", "<", "<="] = "="
    value: str = Field(..., description="미혼, 5, 99000 (숫자는 쉼표 없이)")
    unit: str | None = Field(None, description="명, 가구 (숫자 기준일 때)")
    text: str = Field(..., description="원문 표기 ('가구원수 99,000명 이상')")
    source: Literal["slot", "threshold"] = "slot"


class Filters(BaseModel):
    """슬롯 dict. 빈 슬롯은 None (View 생성 때 기본값 적용)"""
    model_config = ConfigDict(populate_by_name=True)
    시점: list[int] | None = Field(None, description="연도 목록. None 이면 값 조회=최신 연도, 추이=전체 기간")
    지역: list[str] | None = Field(None, description="지역 표준명. None 이면 전국")
    대상: list[str] | None = Field(None, description="무엇에 대한 통계인가 (인구, 출생아, 가구 …)")
    성별: list[str] | None = Field(None, description="남자 / 여자")
    연령: AgeRange | None = Field(None, description="나이 범위 {from, to}")
    지표: list[str] | None = Field(None, description="무엇을 셌는가 (인구수, 출생아수, 고령인구비율 …)")
    비교축: str | None = Field(None, description="비교·순위의 기준 축 (시도, 시군구, 행정구역, 지역 …)")
    보조축: list[str] | None = Field(None, description="비교축과 함께 나눠 볼 축 (연령 · 성별 …). '자치구별 연령대 구성' → "
                                                   "비교축 시군구 + 보조축 [연령] — View 가 연령 구간도 펼침")
    조건: list[str] | None = Field(None, description="분류 값으로 찾을 말 (보증부월세, 재판이혼 …)")
    국적: list[str] | None = Field(None, description="국적 분류 값 (베트남, 중국 …)")
    출생연도: list[int] | None = Field(None, description="출생연도(코호트) 분류 값 — 시점과 다름 (1983년생 → [1983])")
    원문표현: list[str] | None = Field(None, description="질문 원문에 있던 CSV 표현 중 다른 슬롯에 없는 것 "
                                                    "(대상·지표로 못 고른 분류·항목을 고를 때만 씀)")
    조건식: list[Condition] | None = Field(None, description="[NEW 11-20] 이 단위의 결과를 **제한하는** 조건 (열·연산자·값·단위). "
                                                           "역할 단위(분모·조건)에는 넣지 않고 역할이 없는 본 질문에만 넣는다")
    역할: str | None = Field(None, description="검색 단위의 역할: 분모 / 조건 (query_analyzer/roles.py). "
                                             "분모 단위는 같은 조사·수준의 단순한 인구·가구 표를 찾음")
    의도: str | None = Field(None, description="View 종류를 정하는 의도: 값 조회 / 추이 / 비교 / 순위")


class RoleLink(BaseModel):
    """[NEW 11-20] 역할 단위(분모·조건)가 어느 본 질문을 지원하는가. split_roles 가 역할 단위를 질문에서 빼기 전에 남긴다
    (뺀 뒤에는 모듈 6 이 어느 결과가 보조 결과인지 알 방법이 없다)"""
    unit_id: str = Field(..., description="뺀 하위 질문 ID ('{query_id}-{순번}')")
    role: Literal["분모", "조건"]
    term: str = Field("", description="역할 단위의 말 (가구원수)")
    supports: list[str] = Field(default_factory=list, description="이 단위가 지원하는 본 하위 질문 ID. add_role_units 가 대상을 기록하지 않아 남은 본 질문 전부")
    record_ids: list[str] = Field(default_factory=list, description="이 단위에서 세트에 붙인 View 의 Record.id")


class QueryBundle(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [EX_VIEW_BUNDLE]})
    query_id: str | None = Field(None, description="질의 ID (Record id 에 쓰임). 없으면 자동 생성")
    original: str = Field(..., description="사용자 질문")
    rewritten: str | None = Field(None, description="재작성 문장 ('2025년 대구광역시 남자 20~29세 인구수')")
    intent: str | None = Field(None, description="질문 의도 (Intent 9종 중 하나. View 종류는 filters.의도)")
    filters: Filters | None = Field(None, description="슬롯 dict — View 를 자를 조건")
    sub_questions: list[str] = Field(default_factory=list, description="서브쿼리 자연어")
    sub_filters: list[Filters] | None = Field(None, description="서브쿼리 슬롯 dict (sub_questions 와 같은 순서)")
    search_text: str | None = Field(None, description="본 질의 검색 문장. 비우면 original")


# ── 분석 결과 ───────────────────────────────────────────────────
class CsvRow(BaseModel):
    tbl_id: str
    kind: str = Field(..., description="dim(분류 값) / item(항목) / obj(열 머리) / table(표 이름)")
    slot: str = Field(..., description="지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표")
    obj_nm: str = ""
    name: str
    code: str = ""


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
    thresholds: list[dict] = Field(default_factory=list, description="숫자 기준 조건 [{말, 값, 단위, 비교, op, 표기, 지역_고르기}] "
                                                                     "('가구원수가 99,000명 이상' — query_analyzer/roles.find_thresholds)")
    vocab_choices: dict[str, dict] = Field(default_factory=dict, description="벡터 후보 중 HCX 가 고른 결과 {낱말: {choice, why, by}} "
                                                                           "(되묻기 응답 때 HCX 를 다시 부르지 않게 — vocab_suggest.py)")


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
    bundle: dict = Field(..., description="재작성 결과 {original, rewritten, intent, filters, sub_questions, sub_filters}")
    view_bundle: QueryBundle | None = Field(None, description="status=ok 일 때 검색·View 입력")
    search_text: str = ""
    slots: dict[str, list[SlotValue]] = {}
    clarifications: list[Clarification] = []
    sub_queries: list[SubQuery] = []
    decompose_reason: str = ""
    applied_rules: list[str] = []
    notes: list[str] = []
    vocab_suggestions: list[dict] = Field(default_factory=list, description="사전에 없는 질문 낱말의 벡터 후보 "
                                          "[{term, candidates[{name, slot, dim, score}], choice, by, applied, why}] — "
                                          "사람이 고르면 /lexicon/learn (approve) 로 학습 사전에")
    state: AnalysisState
    trace: list[StepTraceModel] = []


# ── API 요청 ────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    question: str = Field(..., examples=[EX_Q])
    today: str | None = Field(None, description="YYYY-MM-DD ('작년'·'최근 N년' 기준). 비우면 오늘")
    query_id: str | None = None
    overrides: dict[str, Any] | None = Field(None, description="configs/pipeline.yaml 값 일부 바꾸기 "
                                                               "(예: {\"base_year\": 2025, \"search_text_mode\": \"llm\"})")


class ClarifyRequest(BaseModel):
    question: str = Field(..., examples=["출생아 수 알려줘"])
    selections: dict[str, list[str]] = Field(..., examples=[{"지역": ["대전광역시"], "시점": ["2025년"]}],
                                             description="되묻기 options[].value 중 고른 값 (슬롯 → 값 목록)")
    previous: QueryAnalysis | None = Field(None, description="직전 /analyze 응답 (있으면 HCX 다시 안 부름)")
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


class HcxCheckResponse(BaseModel):
    settings: dict[str, Any] = Field(..., description="현재 설정 (키 값은 넣지 않음)")
    check: dict[str, Any] = Field(..., description="{ok, elapsed_s, response 또는 error}")
