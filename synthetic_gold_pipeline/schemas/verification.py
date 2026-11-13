"""검증 결과 모델 (결정론적 통계 검증 · Ablation · View 판정 · LLM 의미 검수)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CheckState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_RUN = "NOT_RUN"      # 검증하지 않음 — PASS 로 취급하지 않는다


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationIssue(BaseModel):
    code: str
    severity: Severity = Severity.ERROR
    stage: str
    message: str
    retryable: bool = False
    refs: list[str] = Field(default_factory=list)


class StatisticalValidationReport(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    checks: dict[str, CheckState] = Field(default_factory=dict)
    statistical_assumptions: list[str] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def retryable(self) -> bool:
        errs = self.errors
        return bool(errs) and all(i.retryable for i in errs)


class AblationOutcome(str, Enum):
    NECESSARY = "NECESSARY"              # 제거하면 필수 근거를 다른 View 에서 얻을 수 없음
    REPLACEABLE = "REPLACEABLE"          # 남은 View 가 같은 Fact 를 제공 → 필수 아님
    NOT_CONTRIBUTING = "NOT_CONTRIBUTING"  # 연산 계획에서 이 View 의 값을 쓰지 않음


class AblationResult(BaseModel):
    view_id: str
    outcome: AblationOutcome
    required_fact_ids: list[str] = Field(default_factory=list)
    replacement_view_ids: list[str] = Field(default_factory=list)
    rerun_success: bool | None = Field(None, description="View 제거 후 같은 계획 재실행 성공 여부")
    rerun_error_code: str | None = None
    detail: str = ""


class ViewLabel(str, Enum):
    POSITIVE = "POSITIVE"
    ALTERNATIVE_POSITIVE = "ALTERNATIVE_POSITIVE"
    HARD_NEGATIVE = "HARD_NEGATIVE"
    UNJUDGED = "UNJUDGED"


class ViewJudgement(BaseModel):
    view_id: str
    parent_table_id: str
    label: ViewLabel
    evidence_group: str | None = None
    reason: str


class NumericCheck(BaseModel):
    passed: bool
    final_value_ok: bool | None = None
    unit_ok: bool | None = None
    sign_ok: bool | None = None
    intermediates_ok: bool | None = None
    swap_detected: bool = False
    binding_errors: list[str] = Field(default_factory=list)
    unsupported_numbers: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class QualityReview(BaseModel):
    """QualityVerifierAgent(LLM) 의 구조화 출력."""
    semantic_valid: bool
    question_answer_alignment: bool
    ambiguity_detected: bool
    missing_conditions: list[str] = Field(default_factory=list)
    multi_hop_necessity: bool
    paraphrase_equivalence: bool
    statistical_validity: bool
    natural_question: bool = Field(True, description="실제 사용자가 물을 법한가 (억지로 엮은 지표·과도한 조건이면 false)")
    rejection_reasons: list[str] = Field(default_factory=list)
    suggested_revision: str | None = None


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_WARNINGS = "VERIFIED_WITH_WARNINGS"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    REJECTED = "REJECTED"
