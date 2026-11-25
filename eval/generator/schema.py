"""질문 세트의 기대 결과 스키마 (criteria.md 2장). 실행 전에 작성하고, 실행 결과를 보고 바꾸지 않는다"""
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Expect = Literal["answer", "hold"]


class Coord(BaseModel):
    """원본 행 좌표. region · period · item 외의 차원은 열 이름을 키로 그대로 둔다 (예: 성별: 남자)"""
    model_config = ConfigDict(extra="allow")
    # [CHANGED] 이전: region · period 는 str 하나. v2 claim binding 은 허용 지역 · 기간 목록이다 (S04 기간 2023 · 2024)
    region: str | list[str] | None = None
    period: str | list[str] | None = None
    item: str | None = None

    def regions(self) -> list[str]:
        return [self.region] if isinstance(self.region, str) else list(self.region or [])

    def dims(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Rule(BaseModel):
    """answerable_when 규칙 하나. when 이 없으면 default"""
    when: dict[str, Any] | None = None
    expect: Expect
    hold_reason: str | None = Field(None, description="평가기 사유 코드. from_predicate = 실패한 검사의 사유")


class Match(BaseModel):
    item_any: list[str] = Field(default_factory=list)
    region_any: list[str] = Field(default_factory=list)
    op_any: list[str] = Field(default_factory=list)


class M2Spec(BaseModel):
    acceptable_charts: list[str | None] = Field(default_factory=list, description="None = 차트 없음 허용")
    measure: str | None = None


class M3Spec(BaseModel):
    op: str | None = None
    operands: list[Coord] = Field(default_factory=list)
    denominator: Coord | None = None
    min_periods: int | None = None
    result_unit: str | None = Field(None, description="ratio 처럼 결과 단위가 피연산자로 정해지는 연산의 기대 결과 단위")


class ValueSpec(BaseModel):
    role: Literal["FINAL", "INTERMEDIATE"] = "FINAL"
    value: float
    unit: str = Field(..., description="평가 정규형 단위 (ratio · pp · times · 원단위)")
    display: str | None = Field(None, description="기대 표시 문자열 (있으면 (c)층 비교)")
    binding: Coord | None = None
    key: dict[str, Any] | None = Field(None, description="목록 결과에서 이 값의 점 key (예: {시점: 2022})")
    atol: float | None = None
    rtol: float | None = None
    digits: int | None = Field(None, description="[NEW] 요구 소수 자릿수 (v2 display.digits · 질문의 '소수 셋째 자리')")
    scale: float = Field(1.0, description="[NEW] 표시 배율 (v2 display.scale). 요구 정밀도 = 0.5 × 10^-digits × scale")


class SubQuestion(BaseModel):
    key: str
    match: Match = Field(default_factory=Match)
    answerable_when: list[Rule] = Field(default_factory=lambda: [Rule(expect="answer")])
    m2: M2Spec = Field(default_factory=M2Spec)
    m3: M3Spec = Field(default_factory=M3Spec)
    values: list[ValueSpec] = Field(default_factory=list)
    direction: Literal["up", "down"] | None = None
    match_index: int | None = Field(None, description="[NEW] v2: 입력 query_bundle.sub_questions 의 순번(1부터). 있으면 내용 대신 순번으로 대응")


class RequestedName(BaseModel):
    text: str
    supported: bool = True
    code: str | None = None


class ExpectedOutcome(BaseModel):
    outcome: Literal["honored", "substituted", "table_only"]
    reason: str | None = None
    final_chart: str | None = None


class ChartRequestSpec(BaseModel):
    preferred: list[RequestedName] = Field(default_factory=list)
    excluded: list[RequestedName] = Field(default_factory=list)
    expected_outcome: ExpectedOutcome
    notice_required: bool = False


class Question(BaseModel):
    id: str
    group: str = ""
    question: str
    scope: Literal["in", "out"] = "in"
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    required_caveats: list[str] = Field(default_factory=list, description="projection · missing_period:2026 · substituted_period")
    required_facts: list[str] = Field(default_factory=list)
    chart_request: ChartRequestSpec | None = Field(None, description="생략 = 요청 없음이 정답 (오인식 검사 대상)")
    expect_text: str = Field("", description="기존 questions.py 의 expect 문장 (원문 보존)")
    verified: bool = Field(False, description="원본 View 와 대조해 제3자가 확인했는가")
    notes: str = ""
    # [NEW] v2 데이터셋 문항 (schema_v2.to_question 이 채운다). core34 · ext-chart-request 는 기본값
    dataset: str = "core34"
    dataset_version: str = "1.0"
    strict_final: bool = Field(False, description="FINAL 값이 답변에 없으면 보류 (v2: 기대 claim 은 모두 답변에 있어야 한다)")
    citation_labels: list[str] | None = Field(None, description="답변이 인용할 수 있는 근거 라벨 (v2 evidence_aliases). None = 검사 안 함")
    chart_mode: str | None = Field(None, description="v2 required_chart.mode (required · forbidden · fallback · per_subquestion · optional)")
    chart_types: list[str | None] = Field(default_factory=list, description="v2 required_chart.acceptable_types")
    chart_notice: bool = False
    v2: dict[str, Any] | None = Field(None, description="v2 원본 Case (보고서 묶음 · 짝 문항 · 커버리지용)")


class QuestionSet(BaseModel):
    name: str
    version: str
    frozen: bool = True
    questions: list[Question]

    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions}


def load_set(path: str | Path) -> QuestionSet:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return QuestionSet.model_validate(data)
