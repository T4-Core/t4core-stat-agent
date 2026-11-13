"""최종 Golden Set 레코드 스키마 (JSONL 한 줄 = Fact 레코드 1개, 질문은 original/paraphrased 2개)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from synthetic_gold_pipeline.schemas.calculation import (FinalAnswer, IntermediateFact, NumericResult,
                                                          SourceCoordinate, UnitConversionTrace)
from synthetic_gold_pipeline.schemas.planning import (AnswerabilityType, ComparisonPolicy, HopType,
                                                       ReasoningType)
from synthetic_gold_pipeline.schemas.verification import AblationResult, QualityReview, VerificationStatus

DATASET_VERSION = "synthetic-gold-v0.1"


class EvidenceGroup(BaseModel):
    description: str
    acceptable_view_ids: list[str]
    acceptable_table_ids: list[str] = Field(default_factory=list)
    required_fact_ids: list[str] = Field(default_factory=list)


class ExpectedClaim(BaseModel):
    claim_id: str
    role: str = Field(..., description="FINAL | INTERMEDIATE | ENTITY | THRESHOLD")
    value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    period: str | None = None
    region: str | None = None
    item: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    accepted_forms: list[str] = Field(default_factory=list)


class RetrievalEval(BaseModel):
    golden_view_ids: list[str]
    golden_table_ids: list[str]
    golden_org_table_ids: list[str]
    alternative_positive_view_ids: list[str] = Field(default_factory=list)
    hard_negative_view_ids: list[str] = Field(default_factory=list)
    unjudged_view_ids: list[str] = Field(default_factory=list)
    required_evidence_groups: dict[str, EvidenceGroup] = Field(default_factory=dict)
    join_keys: list[dict[str, Any]] = Field(default_factory=list)
    source_coordinate_references: list[SourceCoordinate] = Field(default_factory=list)
    retrieval_eligible: bool = True
    view_mapping_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context_view_ids: list[str] | None = Field(None, description="CONTEXT_UNANSWERABLE: 생성기에 제공할 (불완전한) 문맥")


class GenerationEval(BaseModel):
    exact_numeric_ground_truth: NumericResult | None = None
    final_answer: FinalAnswer | None = None
    intermediate_facts: list[IntermediateFact] = Field(default_factory=list)
    executed_sql: list[str] = Field(default_factory=list)
    executed_formula: str = ""
    reference_answer: str
    reference_answer_text: str = Field("", description="자연어 정답 문장만 (근거·계산 블록 제외)")
    expected_claims: list[ExpectedClaim] = Field(default_factory=list)
    expected_abstention: bool = False
    abstention_reason: str | None = None
    unit_conversion_trace: list[UnitConversionTrace] = Field(default_factory=list)
    comparison_policy: ComparisonPolicy = Field(default_factory=ComparisonPolicy)
    evidence_trace: list[dict[str, Any]] = Field(default_factory=list)


class M1Eval(BaseModel):
    expected_intent: str
    expected_filters: dict[str, Any] = Field(default_factory=dict)
    expected_sub_questions: list[str] = Field(default_factory=list)
    ambiguity_handling: str = "NONE"
    pass_criteria: list[str] = Field(default_factory=list)


class M2Eval(BaseModel):
    expected_source_coordinates: list[SourceCoordinate] = Field(default_factory=list)
    expected_dimensions: dict[str, list[str]] = Field(default_factory=dict)
    expected_items: list[str] = Field(default_factory=list)
    expected_periods: list[str] = Field(default_factory=list)
    expected_units: list[str] = Field(default_factory=list)
    expected_values: list[dict[str, Any]] = Field(default_factory=list)
    aggregation_constraints: list[str] = Field(default_factory=list)
    pass_criteria: list[str] = Field(default_factory=list)


class M3Eval(BaseModel):
    expected_table_ids: list[str] = Field(default_factory=list)
    expected_view_ids: list[str] = Field(default_factory=list)
    required_evidence_groups: dict[str, EvidenceGroup] = Field(default_factory=dict)
    expected_final_context: list[str] = Field(default_factory=list)
    pass_criteria: list[str] = Field(default_factory=list)


class ModuleEval(BaseModel):
    M1: M1Eval
    M2: M2Eval
    M3: M3Eval


class VerificationMetrics(BaseModel):
    """None = 검증하지 않음 (자동 PASS 아님)."""
    deterministic_passed: bool | None = None
    numeric_validation_passed: bool | None = None
    unit_validation_passed: bool | None = None
    statistical_validation_passed: bool | None = None
    ablation_passed: bool | None = None
    per_view_ablation_results: list[AblationResult] = Field(default_factory=list)
    semantic_validation_passed: bool | None = None
    paraphrase_equivalence_passed: bool | None = None
    max_jaccard_similarity: float | None = None
    max_cosine_similarity: float | None = None
    max_similarity_score: float | None = None
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.NEEDS_HUMAN_REVIEW
    human_review_required: bool = True
    quality_review: QualityReview | None = None
    check_states: dict[str, str] = Field(default_factory=dict)


class Provenance(BaseModel):
    sample_id: str
    attempt_index: int
    plan_id: str | None = None
    planner_attempts: int = 0
    plan_repairs: list[str] = Field(default_factory=list, description="계획 자동 보정 기록 (tools/plan_repair.py)")
    llm_provider: str = ""
    llm_model: str = ""
    created_at: str
    pipeline_version: str
    source_record_id: str | None = Field(None, description="답변 불가 레코드가 파생된 원 레코드")


class GoldenRecord(BaseModel):
    dataset_id: str
    dataset_version: str = DATASET_VERSION
    data_snapshot_id: str
    reasoning_type: ReasoningType
    subtype: str = ""
    hop_type: HopType | None = None
    survey_names: list[str] = Field(default_factory=list)
    answerability_type: AnswerabilityType
    difficulty: str
    question_original: str
    question_paraphrased: str
    question_ids: dict[str, str] = Field(default_factory=dict, description="{original: id, paraphrased: id}")
    random_seed: int
    retrieval_eval: RetrievalEval
    generation_eval: GenerationEval
    module_eval: ModuleEval
    verification_metrics: VerificationMetrics
    provenance: Provenance
    fact_signature: str = ""


class QueryCsvRow(BaseModel):
    id: str
    survey: str
    test_type: str
    target_module: str
    question: str


QUERY_CSV_COLUMNS = ["id", "survey", "test_type", "target_module", "question"]
ANSWER_REF_COLUMNS = ["id", "dataset_id", "gold_table_ids", "gold_table_ids_json", "answerability", "question_variant",
                      "gold_org_table_id", "gold_view_ids",
                      "required_evidence_groups", "gold_answer_text", "gold_answer", "numeric_ground_truth", "source_url",
                      "source_csv_paths", "source_coordinates", "executed_sql", "executed_formula",
                      "gold_status", "strict_hit_eligible", "module_eval"]
