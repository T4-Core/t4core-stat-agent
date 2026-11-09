"""[NEW v4] 2-2·2-3 View 묶음 · Point 충돌 · 선택 입출력 — backend/api/v1_view_v4.py"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

EX_VB = {"query_id": "v4demo", "original": "2025년 대전 인구 수", "search_text": "2025년 대전광역시 인구수",
         "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["인구수"], "의도": "값 조회"}}


class ViewsV4Request(BaseModel):
    """셋 중 하나: question(분석부터) · analysis(POST /rag/v4/analyze 응답) · view_bundle"""
    model_config = ConfigDict(json_schema_extra={"examples": [{"view_bundle": EX_VB}, {"question": "작년 대전 인구 수"}]})
    question: str | None = Field(None, description="질문 — v4 분석(HCX 1회)부터. 되묻기가 필요하면 status=needs_clarification")
    today: str | None = None
    analysis: dict | None = Field(None, description="POST /api/v1/rag/v4/analyze (또는 /clarify) 응답 그대로")
    view_bundle: QueryBundle | None = Field(None, description="기존 View 입력 (POST /rag/views 와 같은 모양)")
    retrieval_config: str | None = Field(None, description="Step 3 검색 구성 이름. 비우면 설정값(view_retrieval_config) → 기존 검색")
    top_k: int | None = Field(None, ge=1, le=50)
    n_views: int | None = Field(None, ge=1, le=10, description="단위마다 View 를 만들어 비교할 표 수 (기본 3)")
    overrides: dict = Field(default_factory=dict, description="configs/query_v4.yaml 값 일부만 바꾸기 (예: conflict_rel_tol)")
    auto_select: Literal["first"] | None = Field(None, description="first = 충돌이 있으면 검색 순위가 가장 높은 선택지를 자동으로 고름")


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
    description: str = Field("", description="표 설명 (CSV 값 사전 설명문: 분류·항목·단위·기간·경로)")
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
    selection_token: str | None = Field(None, description="POST /api/v1/rag/v4/views/select 에 option_id 와 함께")
    selected_option: str | None = None
    notes: list[str] = []


class ViewUnit(BaseModel):
    model_config = ConfigDict(extra="allow")
    unit_id: str
    query: str
    search_query: str
    filters: dict | None
    candidates: list[dict] = []
    views: list[dict] = Field(default_factory=list, description="run_query 의 views (record · notes · rank · tbl_id)")
    notes: list[str] = []
    conflict: PointConflict
    selected: dict | None = None


class PendingSelection(BaseModel):
    unit_id: str
    selection_token: str
    options: list[ConflictOption]


class ViewSetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["ok", "needs_selection", "needs_clarification", "out_of_scope"]
    query_id: str | None = None
    original: str | None = None
    units: list[ViewUnit] = []
    records: list[Record] = Field(default_factory=list, description="답변 모듈로 넘길 카드 (POST /api/v1/agent/answer 의 records)")
    pending: list[PendingSelection] = []
    analysis_status: str | None = None
    clarifications: list[dict] = []
    retrieval_config: str | None = None
    notes: list[str] = []
    seconds: float | None = None
    view_bundle: dict | None = None


class SelectionItem(BaseModel):
    selection_token: str
    option_id: str = Field(..., examples=["opt-1"])


class SelectRequest(BaseModel):
    selections: list[SelectionItem]
    previous: dict | None = Field(None, description="POST /rag/v4/views 응답 전체. 있으면 그 Record 를 그대로 쓰고 records 를 다시 묶음. "
                                                    "없으면 토큰의 좌표로 View 를 다시 만들어 선택한 것만 돌려줌")


class SelectResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    viewset: ViewSetResponse | None = None
    records: list[Record] = Field(default_factory=list, description="previous 가 있으면 전체 records, 없으면 선택한 Record 만")
    applied: list[dict] = []


class PointsRequest(BaseModel):
    records: list[Record] = Field(..., description="비교할 View 카드 (POST /rag/views 응답 등)")
    filters: dict | None = Field(None, description="질문 슬롯 (view_bundle.filters)")
    overrides: dict = Field(default_factory=dict)


class PointsResponse(BaseModel):
    points: dict[str, list[dict]] = Field(..., description="record_id → Point 목록 {key, key_str, value, raw_value, unit, labels}")
    point_notes: dict[str, list[str]] = {}
    conflict: PointConflict
