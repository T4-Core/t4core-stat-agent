"""표·View 메타데이터 모델.

- TableMetadata: 원본 통계표 1개 (기관ID_통계표ID)
- ViewMetadata : Golden Set 생성 전용 View 1개 (원본 표의 선택 조건 + 데이터 스냅샷)

C1 이 지역, C2 가 성별이라는 가정을 하지 않는다. 각 분류 레벨(C1~C8)의 의미는
OBJ_NM 과 메타 JSON 으로 추론한 dim_type 으로 기록한다.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DimensionType(str, Enum):
    REGION = "REGION"
    SEX = "SEX"
    AGE = "AGE"
    HOUSEHOLD = "HOUSEHOLD"
    NATIONALITY = "NATIONALITY"
    INDUSTRY = "INDUSTRY"
    SCENARIO = "SCENARIO"
    OTHER = "OTHER"


class ObservationType(str, Enum):
    OBSERVED = "OBSERVED"
    PROJECTED = "PROJECTED"
    UNKNOWN = "UNKNOWN"


class InputMode(str, Enum):
    STORED_VIEW = "STORED_VIEW"            # 방식 A: 저장된 View 를 직접 읽음
    GENERATED_FROM_RAW = "GENERATED_FROM_RAW"  # 방식 B: RAW + 메타로 생성


class ValueKind(str, Enum):
    COUNT = "COUNT"        # 명, 가구, 건, 호 … (합산 가능)
    AMOUNT = "AMOUNT"      # 원, 백만원 … (합산 가능)
    RATE = "RATE"          # %, ‰, 율 (합산 불가)
    MEAN = "MEAN"          # 세, 평균 … (합산 불가)
    INDEX = "INDEX"        # 지수 (합산 불가)
    UNKNOWN = "UNKNOWN"


class DimensionCode(BaseModel):
    code: str
    name: str
    parent_code: str | None = None
    depth: int = 0
    is_total: bool = False
    has_children: bool = False


class DimensionDefinition(BaseModel):
    level: str = Field(..., description="원본 CSV 컬럼 접두어 (C1~C8)")
    obj_id: str | None = None
    obj_nm: str
    dim_type: DimensionType = DimensionType.OTHER
    dim_type_basis: str = Field("", description="dim_type 을 정한 근거 (키워드 등)")
    n_codes: int = 0
    total_codes: list[str] = Field(default_factory=list)
    code_name_unique: bool = Field(True, description="코드 이름이 레벨 안에서 유일한가 (이름 기반 매핑 가능 여부)")


class IndicatorDefinition(BaseModel):
    itm_id: str
    itm_nm: str
    unit_nm: str | None = None
    unit_family: str | None = None
    unit_multiplier: float | None = None
    value_kind: ValueKind = ValueKind.UNKNOWN
    additive: bool = False


class MetadataCompleteness(BaseModel):
    score: float = Field(..., ge=0, le=1)
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ViewSelector(BaseModel):
    """원본 표에서 View 를 자른 실제 선택 조건 (= View 의 원본 좌표)."""
    itm_ids: list[str]
    prd_se: str
    prd_de: list[str]
    dim_filters: dict[str, list[str]] = Field(default_factory=dict, description="{C레벨: [코드]} (없으면 전체)")


class TableMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    parent_table_id: str = Field(..., description="기관ID_통계표ID (예: 101_DT_1B040A3)")
    org_id: str
    tbl_id: str
    survey_name: str = ""
    table_title: str = ""
    section: str = ""
    path: str = ""
    source_path: str = Field(..., description="읽은 원본 파일 (저장소 기준 상대 경로 또는 절대 경로)")
    source_file_hash: str
    source_url: str
    meta_path: str | None = None
    metadata_source: str = Field("raw_only", description="meta_json | raw_only | stored_view")
    dimension_definitions: list[DimensionDefinition] = Field(default_factory=list)
    dimension_codes: dict[str, list[DimensionCode]] = Field(default_factory=dict)
    indicator_definitions: list[IndicatorDefinition] = Field(default_factory=list)
    periods: dict[str, list[str]] = Field(default_factory=dict, description="{PRD_SE: [PRD_DE]} 실제 데이터 기준")
    meta_periods: dict[str, list[str]] = Field(default_factory=dict, description="메타 PRD 기준 (실제와 다를 수 있음)")
    comments: list[str] = Field(default_factory=list)
    symbol_meanings: dict[str, str] = Field(default_factory=dict)
    population_scope: str = "UNSPECIFIED"
    population_scope_basis: str = ""
    reference_time: str | None = None
    aggregation_basis: str | None = None
    observed_or_projected: ObservationType = ObservationType.UNKNOWN
    observation_basis: str = ""
    duplicate_coordinate_rows: int = Field(0, description="같은 원본 좌표가 여러 행인 경우의 수 (행 증폭 위험)")
    n_rows: int = 0


class ViewMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    view_id: str
    parent_table_id: str
    org_id: str
    tbl_id: str
    survey_name: str = ""
    table_title: str = ""
    source_path: str
    source_file_hash: str
    source_url: str
    view_file: str = Field(..., description="View 데이터 파일 (generated_views/ 또는 저장된 View 경로)")
    view_file_hash: str = ""
    input_mode: InputMode
    column_schema: list[str]
    dimension_definitions: list[DimensionDefinition]
    dimension_codes: dict[str, list[DimensionCode]] = Field(..., description="이 View 에 실제 존재하는 코드")
    available_periods: list[str]
    period_frequency: str = Field(..., description="표준 주기 Y/H/Q/M/D/F/IR")
    period_frequency_raw: str = ""
    indicator_definitions: list[IndicatorDefinition]
    units: list[str]
    unit_multiplier: dict[str, float | None] = Field(default_factory=dict)
    population_scope: str = "UNSPECIFIED"
    reference_time: str | None = None
    aggregation_basis: str | None = None
    observed_or_projected: ObservationType = ObservationType.UNKNOWN
    scenario: str | None = None
    hierarchy_information: dict[str, dict[str, str | None]] = Field(default_factory=dict,
                                                                    description="{C레벨: {코드: 상위코드}}")
    total_and_subtotal_codes: dict[str, list[str]] = Field(default_factory=dict)
    source_coordinates: ViewSelector
    metadata_completeness: MetadataCompleteness
    data_snapshot_hash: str = Field(..., description="View 에 담긴 원본 행들의 해시")
    n_rows: int = 0
    n_numeric: int = 0
    duplicate_coordinate_rows: int = 0
    symbol_meanings: dict[str, str] = Field(default_factory=dict)
    comments: list[str] = Field(default_factory=list)

    def dim(self, level: str) -> DimensionDefinition | None:
        return next((d for d in self.dimension_definitions if d.level == level), None)

    def dims_of_type(self, dim_type: DimensionType) -> list[DimensionDefinition]:
        return [d for d in self.dimension_definitions if d.dim_type == dim_type]

    def code_map(self, level: str) -> dict[str, DimensionCode]:
        return {c.code: c for c in self.dimension_codes.get(level, [])}

    def item(self, itm_id: str) -> IndicatorDefinition | None:
        return next((i for i in self.indicator_definitions if i.itm_id == itm_id), None)


class ViewCard(BaseModel):
    """LLM 에 전달하는 View 요약 (전체 RAW 대신 구조화된 정보만)."""
    view_id: str
    parent_table_id: str
    survey_name: str
    table_title: str
    items: list[dict[str, Any]]
    dimensions: list[dict[str, Any]]
    periods: list[str]
    period_frequency: str
    units: list[str]
    population_scope: str
    observed_or_projected: str
    scenario: str | None = None
    sample_rows: list[dict[str, Any]] = Field(default_factory=list, description="최대 3행")
