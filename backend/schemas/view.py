"""
검색·View 입출력

  Candidate · SearchResult       표 검색 결과 (POST /api/v1/rag/search)
  ViewResult                     검색 단위별 View (판단 모듈 입력)
  ViewSet                        ViewResult + 단위별 Point 충돌 판정 · 선택 (POST /api/v1/rag/views)
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import Filters, QueryBundle
from backend.schemas.record import Note, Record

EX_VB = {"query_id": "demo", "original": "2025년 대전 인구 수", "search_text": "대전광역시 인구수",
         "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["인구수"], "의도": "값 조회"}}


# ── 검색 ────────────────────────────────────────────────────────
class Candidate(BaseModel):
    model_config = ConfigDict(extra="allow")
    rank: int = Field(..., description="최종 순위 (1부터)")
    tbl_id: str
    tbl_nm: str
    survey_nm: str
    score: float = Field(..., description="채널 점수 합 × 표 구조 계수")
    dense: float | None = Field(None, description="질문 ↔ 표 설명문 코사인 유사도")
    bm25_rank: int | None = None
    bm25: float | None = None
    has_view: bool = Field(False, description="View 카드를 만들었는지 (상위 n_views 개만)")
    unmet: list[Note] | None = Field(None, description="표 메타데이터 기준으로 못 맞춘 조건")
    cover: float | None = Field(None, description="요청 연도 중 표 기간 안에 든 비율 (0~1)")
    cost: float | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., examples=["최근 5년간 대전의 인구 변화 추이"])
    top_k: int = Field(10, ge=1, le=100)
    filters: Filters | None = Field(None, description="슬롯 (있으면 표 구조 계수에 반영)")


class SearchResult(BaseModel):
    query: str
    candidates: list[Candidate]


# ── View ────────────────────────────────────────────────────────
class ViewItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    record: Record
    notes: list[str] = Field(default_factory=list, description="표에 없어 못 맞춘 조건")
    rank: int
    tbl_id: str


class UnitResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    unit_id: str = Field(..., description="'main' 또는 서브쿼리 ID")
    query: str = Field(..., description="검색 단위 문장")
    filters: Filters | None = None
    candidates: list[Candidate] = []
    views: list[ViewItem] = []
    notes: list[str] = []


class ViewResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    query_id: str
    original: str
    filters: Filters | None = None
    units: list[UnitResult]


# ── 충돌·선택 ───────────────────────────────────────────────────
class ViewCheck(BaseModel):
    model_config = ConfigDict(extra="allow")
    record_id: str
    tbl_id: str
    rank: int | None = None
    usable: bool = Field(..., description="필수 메타를 모두 썼는가 (False 면 비교에서 빠짐)")
    used: dict[str, bool] = {}
    checks: dict[str, dict] = {}
    notes: list[str] = []
    n_points: int = 0


class DifferingPoint(BaseModel):
    key: dict[str, Any]
    key_str: str
    values: list[dict] = Field(..., description="표마다 {record_id, tbl_id, value, unit, base_value, labels}")


class ConflictOption(BaseModel):
    option_id: str = Field(..., examples=["opt-1"])
    record_ids: list[str] = Field(..., description="이 선택지의 View (값이 서로 같은 표들, 첫 번째가 대표)")
    tbl_ids: list[str]
    tbl_nm: str = ""
    survey_nm: str | None = None
    value_preview: list[dict] = Field(default_factory=list, description="다른 값이 나온 교차점: 이 선택지 값 + 다른 표 값")
    footnotes: list[dict] = Field(default_factory=list, description="메타 주석 (통계표·항목·분류) {type, target, text}")
    description: str = Field("", description="표 설명 (분류·항목·단위·기간·경로)")
    basis: dict = Field(default_factory=dict, description="산출 기준: 조사·주기·기간·단위·항목·검색 순위·View 메모")
    kosis_url: str | None = None
    same_value_tables: list[str] = []


class PointConflict(BaseModel):
    model_config = ConfigDict(extra="allow")
    unit_id: str
    status: Literal["ok", "ambiguous", "partial", "empty"]
    views: list[ViewCheck] = []
    n_compared_keys: int = Field(0, description="두 표 이상에 있는 교차점 수")
    n_agree: int = 0
    differing_points: list[DifferingPoint] = []
    clusters: list[list[str]] = []
    options: list[ConflictOption] = []
    selection_token: str | None = Field(None, description="선택할 때 option_id 와 함께 보냄")
    selected_option: str | None = None
    notes: list[str] = []


class ViewUnit(UnitResult):
    search_query: str = ""
    conflict: PointConflict
    selected: dict | None = None
    survey_options: list[dict] = Field(default_factory=list,
                                       description="조사를 지정하지 않았고 상위 후보가 여러 조사로 갈리면 조사별 대표 표 — 고르면 filters['조사'] 로 다시")


class PendingSelection(BaseModel):
    unit_id: str
    selection_token: str
    options: list[ConflictOption]


class ViewSet(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["ok", "needs_selection", "needs_clarification", "out_of_scope"]
    query_id: str | None = None
    original: str | None = None
    units: list[ViewUnit] = []
    records: list[Record] = Field(default_factory=list, description="답변으로 넘길 카드")
    pending: list[PendingSelection] = []
    analysis_status: str | None = None
    clarifications: list[dict] = []
    notes: list[str] = []
    seconds: float | None = None
    view_bundle: dict | None = None


class ViewsRequest(BaseModel):
    """셋 중 하나: question(분석부터) · analysis(/rag/analyze 응답) · view_bundle"""
    model_config = ConfigDict(json_schema_extra={"examples": [{"view_bundle": EX_VB}, {"question": "작년 대전 인구 수"}]})
    question: str | None = Field(None, description="질문 — 분석(HCX 1회)부터")
    today: str | None = None
    analysis: dict | None = Field(None, description="POST /api/v1/rag/analyze (또는 /clarify) 응답 그대로")
    view_bundle: QueryBundle | None = None
    top_k: int | None = Field(None, ge=1, le=50)
    n_views: int | None = Field(None, ge=1, le=10, description="단위마다 View 를 만들어 비교할 표 수")
    overrides: dict = Field(default_factory=dict, description="configs/pipeline.yaml 값 일부만 바꾸기")
    auto_select: Literal["first"] | None = Field(None, description="first = 충돌이 있으면 검색 순위가 가장 높은 선택지를 자동으로")


class SelectionItem(BaseModel):
    selection_token: str
    option_id: str = Field(..., examples=["opt-1"])


class SelectRequest(BaseModel):
    selections: list[SelectionItem]
    previous: dict | None = Field(None, description="POST /rag/views 응답 전체. 있으면 그 Record 를 그대로 쓰고 records 를 다시 묶음. "
                                                    "없으면 토큰의 좌표로 View 를 다시 만들어 선택한 것만 돌려줌")


class SelectResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    viewset: ViewSet | None = None
    records: list[Record] = Field(default_factory=list)
    applied: list[dict] = []


class PointsRequest(BaseModel):
    records: list[Record] = Field(..., description="비교할 View 카드")
    filters: dict | None = Field(None, description="질문 슬롯 (view_bundle.filters)")
    overrides: dict = Field(default_factory=dict)


class PointsResponse(BaseModel):
    points: dict[str, list[dict]] = Field(..., description="record_id → Point 목록 {key, key_str, value, raw_value, unit, labels}")
    point_notes: dict[str, list[str]] = {}
    conflict: PointConflict
