"""보완 평가 데이터셋 v2 스키마와 내부 Question 변환

데이터셋에 동봉된 dataset_schema.py 를 import 하지 않는다 (저장소 밖 코드 실행 회피). 같은 필드를 여기서 정의하고,
판정기가 쓰는 필드만 Question 으로 옮긴다. 원본 Case 는 Question.v2 에 그대로 붙여 보고서(묶음 · 짝 문항)에 쓴다.

변환 규칙
  - 기대 상태: 하위 질문의 expected_status 고정값 (격리 입력이라 조건 술어가 필요 없다)
  - 하위 질문 대응: 입력 query_bundle.sub_questions 순번 (match_index)
  - claim 값: display.scaled_value · display.unit 을 평가 정규형으로 (% → ratio, %p → pp, 백만원 → 원)
  - 요구 자릿수: display.digits. 요구 정밀도는 표시 단위 기준이라 정규화 배율(scale)을 함께 둔다
"""
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eval.generator.checks.normalize import normalize
from eval.generator.schema import Coord, M3Spec, Match, Question, Rule, SubQuestion, ValueSpec


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Binding(_Open):
    region: list[str] = Field(default_factory=list)
    period: list[str] = Field(default_factory=list)
    item: str | None = None
    frequency: list[str] = Field(default_factory=list)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list)


class Display(_Open):
    text: str | None = None
    unit: str | None = None
    scale: str = "1"
    digits: int | None = None
    rounding: str = "ROUND_HALF_UP"
    scaled_value: str | None = None


class Tolerance(_Open):
    atol: str = "0"
    rtol: str = "0"


class Calculation(_Open):
    op: str | None = None
    refs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    expression: str | None = None


class Claim(_Open):
    id: str
    value: str
    unit: str | None = None
    binding: Binding = Field(default_factory=Binding)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation: Calculation = Field(default_factory=Calculation)
    display: Display = Field(default_factory=Display)
    tolerance: Tolerance = Field(default_factory=Tolerance)
    rank: int | None = None


class SubQ(_Open):
    key: str
    question: str = ""
    expected_status: str
    required_evidence_ids: list[str] = Field(default_factory=list)
    expected_operations: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    hold_reason: str | None = None
    required_caveats: list[str] = Field(default_factory=list)


class RequiredChart(_Open):
    mode: str = "optional"
    acceptable_types: list[str | None] = Field(default_factory=list)
    excluded_types: list[str] = Field(default_factory=list)
    notice_required: bool = False
    expected_outcome: str | None = None
    expected_outcomes: list[str] = Field(default_factory=list)
    subquestions: dict[str, list[str | None]] = Field(default_factory=dict)
    null_allowed: bool | None = None
    reason: str | None = None
    requirements: list[str] = Field(default_factory=list)


class Case(_Open):
    id: str
    group: str
    question: str
    scope: str = "in"
    evidence_kind: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    sub_questions: list[SubQ] = Field(default_factory=list)
    reference_answer: str = ""
    required_chart: RequiredChart = Field(default_factory=RequiredChart)
    forbidden_claims: list[str] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)
    pair: dict[str, Any] | None = None
    notes: str = ""
    review: dict[str, Any] = Field(default_factory=dict)
    required_facts: list[str] = Field(default_factory=list)
    evidence_aliases: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Probe(_Open):
    id: str
    base_case_id: str
    candidate_answer: str
    expected_verdict: str          # pass · fail
    reason: str = ""


def _factor(unit: str | None) -> float:
    """정규화 배율: normalize(1, unit).value (% → 0.01, 백만원 → 1e6, 명 → 1)"""
    n = normalize(1.0, unit)
    return n.value if n.value is not None else 1.0


def value_spec(c: Claim) -> ValueSpec:
    """정답은 원값(c.value, 반올림 전)을 표시 단위로 옮긴 뒤 정규형으로. scaled_value 는 반올림된 표시값이라 쓰지 않는다.
    표시 단위로 옮기는 이유: ㎡ → ㎢ 처럼 정규형 환산표에 없는 배율도 display.scale 로 맞출 수 있다"""
    d = c.display
    unit = d.unit or c.unit
    n = normalize(float(Decimal(c.value) / Decimal(d.scale or "1")), unit)
    k = _factor(unit)
    tol_k = _factor(c.unit)
    b = c.binding
    key = {"시점": b.period[0]} if len(b.period) == 1 else None
    return ValueSpec(role="FINAL", value=n.value, unit=n.unit or "", display=d.text,
                     binding=Coord(region=b.region or None, period=b.period or None, item=b.item),
                     key=key, atol=float(Decimal(c.tolerance.atol)) * abs(tol_k), rtol=float(Decimal(c.tolerance.rtol)),
                     digits=d.digits, scale=abs(k))


def to_question(case: Case, *, version: str) -> Question:
    subs = []
    for i, s in enumerate(case.sub_questions, 1):
        ops = list(dict.fromkeys(s.expected_operations))
        subs.append(SubQuestion(
            key=s.key, match_index=i, match=Match(op_any=ops if len(ops) > 1 else []),
            answerable_when=[Rule(expect="hold" if s.expected_status == "hold" else "answer", hold_reason=s.hold_reason)],
            m3=M3Spec(op=ops[0] if len(ops) == 1 else None),
            values=[value_spec(c) for c in s.claims]))
    rc = case.required_chart
    return Question(
        id=case.id, group=case.group, question=case.question, scope="out" if case.scope == "out" else "in",
        sub_questions=subs, required_facts=list(case.required_facts), expect_text=case.reference_answer,
        verified=bool(case.review.get("human_verified")), notes=case.notes,
        dataset="v2", dataset_version=version, strict_final=True,
        citation_labels=sorted({a.get("label") for a in case.evidence_aliases.values() if a.get("label")}),
        chart_mode=rc.mode, chart_types=list(rc.acceptable_types), chart_notice=rc.notice_required,
        v2=case.model_dump(mode="json"))
