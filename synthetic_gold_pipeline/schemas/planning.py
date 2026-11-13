"""샘플링 · 연산 계획 모델.

PlannerAgent(LLM)는 이 스키마의 구조화된 연산 명세만 반환한다.
수치 계산은 하지 않으며, SQL 은 Calculation Tool 이 명세에서 컴파일한다.

연산 그래프 평가 순서: operands → filters → operation.steps (참조 순서대로 위상 정렬)
참조(ref)는 operand_id / filter_id / step_id 중 하나.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from synthetic_gold_pipeline.schemas.metadata import ViewCard


_NULLISH = {"", "null", "none", "None", "NULL", "N/A", "없음"}


def _allows_none(annotation) -> bool:
    import types
    import typing
    args = typing.get_args(annotation)
    return annotation is type(None) or (typing.get_origin(annotation) in (typing.Union, types.UnionType)
                                        and type(None) in args)


class LLMModel(BaseModel):
    """LLM 이 채우는 모델의 공통 바탕: None 을 허용하는 칸에 빈 문자열·'null' 이 오면 None 으로 (HCX 는 안 쓰는
    선택 칸을 "" 로 채우는 경우가 많음 → 그대로 두면 group_by_level="" 가 벡터로 처리돼 KeyError '' 발생)"""

    @model_validator(mode="before")
    @classmethod
    def _empty_to_none(cls, data):
        if isinstance(data, dict):
            fields = cls.model_fields
            for k, v in list(data.items()):
                f = fields.get(k)
                if f is not None and isinstance(v, str) and v.strip() in _NULLISH and _allows_none(f.annotation):
                    data[k] = None
        return data


class ReasoningType(str, Enum):
    SIMPLE_LOOKUP = "SIMPLE_LOOKUP"                  # [NEW 11-12] View 1개에서 값 하나 그대로 (쉬운 평가셋)
    TIME_SERIES_COMPARISON = "TIME_SERIES_COMPARISON"
    CROSS_TABLE_RATIO = "CROSS_TABLE_RATIO"
    CONDITIONAL_AGGREGATION = "CONDITIONAL_AGGREGATION"
    UNANSWERABLE_ABSTENTION = "UNANSWERABLE_ABSTENTION"


class HopType(str, Enum):
    SINGLE_TABLE_MULTI_VIEW = "SINGLE_TABLE_MULTI_VIEW"
    MULTI_TABLE_MULTI_VIEW = "MULTI_TABLE_MULTI_VIEW"
    SINGLE_TABLE_SINGLE_VIEW = "SINGLE_TABLE_SINGLE_VIEW"


class AtomicOp(str, Enum):
    LOOKUP = "LOOKUP"
    DIFFERENCE = "DIFFERENCE"
    GROWTH_RATE = "GROWTH_RATE"
    SHARE_RATIO = "SHARE_RATIO"
    SUM = "SUM"
    MEAN = "MEAN"
    WEIGHTED_MEAN = "WEIGHTED_MEAN"
    MIN = "MIN"
    MAX = "MAX"
    TOP_K = "TOP_K"
    COUNT = "COUNT"
    PERCENTAGE_POINT_DIFFERENCE = "PERCENTAGE_POINT_DIFFERENCE"


AGGREGATE_OPS = {AtomicOp.SUM, AtomicOp.MEAN, AtomicOp.WEIGHTED_MEAN, AtomicOp.MIN, AtomicOp.MAX,
                 AtomicOp.TOP_K, AtomicOp.COUNT}
BINARY_OPS = {AtomicOp.DIFFERENCE, AtomicOp.GROWTH_RATE, AtomicOp.SHARE_RATIO,
              AtomicOp.PERCENTAGE_POINT_DIFFERENCE}


class AnswerabilityType(str, Enum):
    ANSWERABLE = "ANSWERABLE"
    CONTEXT_UNANSWERABLE = "CONTEXT_UNANSWERABLE"
    CORPUS_UNANSWERABLE = "CORPUS_UNANSWERABLE"
    AMBIGUOUS = "AMBIGUOUS"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    FUTURE_OBSERVATION = "FUTURE_OBSERVATION"


class PlanStatus(str, Enum):
    OK = "OK"
    REJECT_PLAN = "REJECT_PLAN"


Comparator = Literal[">", ">=", "<", "<=", "==", "!="]


class Operand(LLMModel):
    """View 에서 값을 꺼내는 좌표. group_by_level 이 있으면 벡터(코드별 값 목록), 없으면 스칼라(정확히 1행)."""
    model_config = ConfigDict(extra="forbid")
    operand_id: str
    view_id: str
    itm_id: str
    prd_de: str
    coordinates: dict[str, str] = Field(default_factory=dict, description="{C레벨: 코드} 고정 조건")
    group_by_level: str | None = Field(None, description="벡터 operand 의 키 레벨 (예: C1)")
    exclude_totals: bool = Field(True, description="벡터에서 총계·소계 코드 제외")
    depth: int | None = Field(None, description="벡터 코드의 계층 깊이 제한 (예: 시도=1)")
    include_codes: list[str] | None = Field(None, description="벡터에 포함할 코드 (없으면 조건에 맞는 전체)")
    role: str = ""
    label: str = ""


class FilterSpec(LLMModel):
    """target 벡터를 condition 벡터(같은 키)의 조건으로 필터링한다. 결과 ref = filter_id."""
    model_config = ConfigDict(extra="forbid")
    filter_id: str
    target_ref: str
    condition_ref: str
    comparator: Comparator
    threshold_mode: Literal["ABSOLUTE", "QUANTILE"] = "ABSOLUTE"
    threshold_value: str | None = Field(None, description="ABSOLUTE 일 때 기준값 (condition 단위)")
    quantile: float | None = Field(None, ge=0, le=1, description="QUANTILE 일 때 분위 (Tool 이 값으로 확정)")
    nice_round: bool = Field(True, description="QUANTILE 기준값을 유효숫자 2자리로 반올림해 질문에 쓰기 쉽게")


class OperationStep(LLMModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    op: AtomicOp
    inputs: list[str]
    params: dict[str, Any] = Field(default_factory=dict, description="scale(SHARE_RATIO), k·order(TOP_K) 등")


class OperationGraph(LLMModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[OperationStep]
    final_step_id: str

    @model_validator(mode="after")
    def _final_exists(self):
        if self.steps and self.final_step_id not in {s.step_id for s in self.steps}:
            raise ValueError(f"final_step_id={self.final_step_id} 가 steps 에 없음")
        return self


class JoinSpecification(LLMModel):
    model_config = ConfigDict(extra="forbid")
    dimension_type: str = Field(..., description="REGION 등 DimensionType")
    levels: dict[str, str] = Field(..., description="{view_id: C레벨}")
    key_basis: Literal["CODE"] = "CODE"
    expected: Literal["ONE_TO_ONE"] = "ONE_TO_ONE"


class AggregationSpec(LLMModel):
    model_config = ConfigDict(extra="forbid")
    function: AtomicOp
    over_level: str | None = None
    input_ref: str | None = None
    weight_ref: str | None = None
    exclude_totals: bool = True
    k: int | None = None
    order: Literal["DESC", "ASC"] | None = None


class UnitConversionSpec(LLMModel):
    model_config = ConfigDict(extra="forbid")
    operand_id: str
    from_unit: str
    to_unit: str


class ComparisonPolicy(LLMModel):
    model_config = ConfigDict(extra="forbid")
    rounding_digits: list[int] = Field(default_factory=lambda: [1, 2])
    abs_tolerance: float = 0.0
    rel_tolerance: float = 0.0
    sign_sensitive: bool = True
    unit_required: bool = True


class OperationPlan(LLMModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = ""
    plan_status: PlanStatus = PlanStatus.OK
    reject_reason: str | None = None
    reasoning_type: ReasoningType
    subtype: str = ""
    required_view_ids: list[str] = Field(default_factory=list)
    required_table_ids: list[str] = Field(default_factory=list)
    join_specification: JoinSpecification | None = None
    operands: list[Operand] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    aggregation_specification: AggregationSpec | None = None
    operation: OperationGraph | None = None
    unit_conversion: list[UnitConversionSpec] = Field(default_factory=list)
    result_unit: str | None = None
    comparison_policy: ComparisonPolicy = Field(default_factory=ComparisonPolicy)
    expected_cardinality: dict[str, str] = Field(default_factory=dict, description="{operand_id: ONE|MANY}")
    necessity_expectations: dict[str, str] = Field(default_factory=dict, description="{view_id: 왜 필요한가}")
    statistical_assumptions: list[str] = Field(default_factory=list)
    answerability_type: AnswerabilityType = AnswerabilityType.ANSWERABLE
    sql_plan: str | None = Field(None, description="선택: 읽기 전용 SQL (설정에서 허용한 경우만, 검증 후 실행)")

    def refs(self) -> set[str]:
        out = {o.operand_id for o in self.operands} | {f.filter_id for f in self.filters}
        if self.operation:
            out |= {s.step_id for s in self.operation.steps}
        return out


class SampledCluster(BaseModel):
    """ViewClusterSampler 출력: 함께 쓸 View 2~3개와 그 근거."""
    sample_id: str
    attempt_index: int
    random_seed: int
    reasoning_type: ReasoningType
    subtype: str
    hop_type: HopType
    view_ids: list[str]
    table_ids: list[str]
    join_dimension_type: str | None = None
    join_levels: dict[str, str] = Field(default_factory=dict)
    common_codes: list[str] = Field(default_factory=list)
    hard_negative_candidates: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlannerContext(BaseModel):
    """PlannerAgent 입력 (LLM 에 들어가는 구조화 정보)."""
    sample_id: str
    random_seed: int
    reasoning_type: ReasoningType
    subtype: str
    hop_type: HopType
    views: list[ViewCard]
    join_dimension_type: str | None = None
    join_levels: dict[str, str] = Field(default_factory=dict)
    common_join_codes: list[dict[str, Any]] = Field(default_factory=list, description="실제 공통 코드 [{code, name, is_total}]")
    allowed_operations: list[str] = Field(default_factory=list)
    previous_errors: list[str] = Field(default_factory=list, description="Self-correction 재시도용 오류 메시지")
