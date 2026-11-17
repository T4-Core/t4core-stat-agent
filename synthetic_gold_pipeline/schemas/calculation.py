"""계산 결과 · 원본 좌표 · Intermediate Fact 모델.

행 번호 규약 (ROW_NUMBER_CONVENTION):
  row_number      = 원본 CSV 의 데이터 행 번호, 1부터, 헤더 행 제외
  csv_line_number = 원본 CSV 의 물리적 줄 번호, 1부터, 헤더(1행) 포함 → row_number + 1
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

ROW_NUMBER_CONVENTION = "row_number: 1-based data row, header excluded; csv_line_number = row_number + 1 (header is line 1)"


class CalcErrorCode(str, Enum):
    # ── 구조 오류: PlannerAgent 에 오류를 전달해 재시도 가능 ──
    PLAN_STRUCTURE_ERROR = "PLAN_STRUCTURE_ERROR"
    UNKNOWN_VIEW = "UNKNOWN_VIEW"
    UNKNOWN_ITEM = "UNKNOWN_ITEM"
    UNKNOWN_CODE = "UNKNOWN_CODE"
    UNKNOWN_LEVEL = "UNKNOWN_LEVEL"
    CARDINALITY_ERROR = "CARDINALITY_ERROR"
    UNUSED_VIEW = "UNUSED_VIEW"
    SQL_SAFETY_VIOLATION = "SQL_SAFETY_VIOLATION"
    # ── 데이터 / 통계 오류: 즉시 폐기 (LLM 재호출 없음) ──
    MISSING_VALUE = "MISSING_VALUE"
    MISSING_PERIOD = "MISSING_PERIOD"
    EMPTY_RESULT = "EMPTY_RESULT"
    EMPTY_JOIN = "EMPTY_JOIN"
    DENOMINATOR_ZERO = "DENOMINATOR_ZERO"
    NON_FINITE = "NON_FINITE"
    JOIN_AMPLIFICATION = "JOIN_AMPLIFICATION"
    JOIN_CODE_SYSTEM_MISMATCH = "JOIN_CODE_SYSTEM_MISMATCH"
    UNIT_INCOMPATIBLE = "UNIT_INCOMPATIBLE"
    STATISTICALLY_INCOMPATIBLE = "STATISTICALLY_INCOMPATIBLE"
    AMBIGUOUS_RESULT = "AMBIGUOUS_RESULT"
    TIMEOUT = "TIMEOUT"
    ROW_LIMIT_EXCEEDED = "ROW_LIMIT_EXCEEDED"
    PLAN_REJECTED = "PLAN_REJECTED"


RETRYABLE_CODES = {
    CalcErrorCode.PLAN_STRUCTURE_ERROR, CalcErrorCode.UNKNOWN_VIEW, CalcErrorCode.UNKNOWN_ITEM,
    CalcErrorCode.UNKNOWN_CODE, CalcErrorCode.UNKNOWN_LEVEL, CalcErrorCode.CARDINALITY_ERROR,
    CalcErrorCode.UNUSED_VIEW, CalcErrorCode.SQL_SAFETY_VIOLATION,
}


class NumericResult(BaseModel):
    raw: float
    exact_decimal: str
    round_0: int | None = None
    round_1: float
    round_2: float
    unit: str
    display_digits: int = 1
    display: str
    formatted_candidates: list[str]


class SourceCoordinate(BaseModel):
    view_id: str
    parent_table_id: str
    source_path: str
    source_file_hash: str
    row_number: int
    csv_line_number: int
    row_number_convention: str = ROW_NUMBER_CONVENTION
    column_name: str = "DT"
    ORG_ID: str
    TBL_ID: str
    PRD_SE: str
    PRD_DE: str
    ITM_ID: str
    ITM_NM: str | None = None
    dims: dict[str, str] = Field(default_factory=dict, description="{C1: 코드, ...}")
    dim_names: dict[str, str] = Field(default_factory=dict, description="{C1: 코드 이름, ...}")
    UNIT_NM: str | None = None
    raw_value: str | None = None
    value_status: str = "NUMERIC"
    normalized_value: str | None = None
    applied_multiplier: str = "1"
    normalized_unit: str | None = None


class IntermediateFact(BaseModel):
    fact_id: str
    operand_id: str
    view_id: str
    parent_table_id: str
    kind: str = Field(..., description="SCALAR | VECTOR_ELEMENT")
    key_code: str | None = None
    key_name: str | None = None
    period: str
    item_id: str
    item_name: str
    coordinate_labels: dict[str, str] = Field(default_factory=dict, description="{분류명: 코드 이름}")
    unit: str
    value: NumericResult
    coordinate: SourceCoordinate


class VectorEntry(BaseModel):
    key_code: str
    key_name: str
    value: NumericResult
    fact_ids: list[str] = Field(default_factory=list)


class RankedEntry(BaseModel):
    rank: int
    key_code: str
    key_name: str
    value: NumericResult


class StepResult(BaseModel):
    step_id: str
    op: str
    formula: str
    input_refs: list[str]
    output_kind: str = Field(..., description="SCALAR | VECTOR | ENTITY | RANKING")
    scalar: NumericResult | None = None
    vector: list[VectorEntry] = Field(default_factory=list)
    ranking: list[RankedEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvidenceFileRef(BaseModel):
    path: str
    sha256: str
    n_rows: int
    query_spec: dict[str, Any]


class JoinDiagnostics(BaseModel):
    refs: list[str]
    n_left: int
    n_right: int
    n_joined: int
    n_left_only: int
    n_right_only: int
    duplicate_keys_left: int
    duplicate_keys_right: int
    name_mismatches: list[dict[str, str]] = Field(default_factory=list)
    amplified: bool = False
    sql: str = ""


class UnitConversionTrace(BaseModel):
    ref: str
    from_unit: str
    to_unit: str
    factor: str
    reason: str


class FinalAnswer(BaseModel):
    kind: str = Field(..., description="SCALAR | ENTITY | RANKING | COUNT")
    value: NumericResult | None = None
    entity: RankedEntry | None = None
    ranking: list[RankedEntry] = Field(default_factory=list)
    unit: str | None = None


class CalculationResult(BaseModel):
    plan_id: str
    success: bool
    error_code: CalcErrorCode | None = None
    error_message: str | None = None
    retryable: bool = False
    executed_sql: list[str] = Field(default_factory=list)
    executed_formula: str = ""
    intermediate_facts: list[IntermediateFact] = Field(default_factory=list)
    step_results: list[StepResult] = Field(default_factory=list)
    final: FinalAnswer | None = None
    unit_conversion_trace: list[UnitConversionTrace] = Field(default_factory=list)
    join_diagnostics: list[JoinDiagnostics] = Field(default_factory=list)
    evidence_files: list[EvidenceFileRef] = Field(default_factory=list)
    resolved_thresholds: dict[str, NumericResult] = Field(default_factory=dict)
    row_counts: dict[str, int] = Field(default_factory=dict)
    views_used: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0
