"""
[NEW] 모듈 6 (답변 · 통계 표 생성) 입출력 계약

  구현: backend/agent/answer_compose/*.py. 이 파일은 스키마 정의만 한다.

  Module6Request (모듈 3 출력 중 필요한 것 + records + query_bundle)
      └▶ 표 만들기(계산 요약 · 계산 목록 · 원본 View) ─▶ 답변 작성(HCX, 자리표시자) ─▶ 치환 · 검사 ─▶ Module6Output

  답변 속 숫자는 HCX 가 쓰지 않는다. HCX 는 '{a1}' 같은 자리표시자만 쓰고, 코드가 CalcResult 값을 displays 로 바꿔 채운다.
  자리표시자 문법은 agent/answer_compose/placeholder.py 머리말에 있다.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.schemas.chart import CalcResult, Display, Step
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

TableKind = Literal["calc_summary", "calc_list", "view"]
Method = Literal["hcx", "hcx_retry", "template", "none"]


# ── 입력 ─────────────────────────────────────────────────────────
class Module6Request(BaseModel):
    query_bundle: QueryBundle
    records: list[Record] = Field(..., description="모듈 3 에 넘겼던 View 들. 원본 View 표의 근거")
    calc_results: list[CalcResult] = Field(default_factory=list, description="모듈 3 Module3Output.calc_results")
    displays: dict[str, Display] = Field(default_factory=dict, description="모듈 3 Module3Output.displays")
    answer_steps: list[Step] = Field(default_factory=list, description=(
        "모듈 3 Module3Output.chart_plan.answer_steps. 없어도 된다 — 있으면 극값 방향(kind)·집계 방식(agg)을 문장에 쓴다"))
    plan_warnings: list[str] = Field(default_factory=list, description=(
        "모듈 3 Module3Output.chart_plan.warnings. 계산을 보류한 사유(질문의 지역 자료 없음, 분모 자료가 세트 밖 등)를 주의사항으로 전달한다"))
    max_rows: int = Field(50, ge=1, le=500, description="원본 View 표 하나의 최대 행 수. 계산에 쓴 행은 이 수와 관계없이 넣는다")


# ── 출력 ─────────────────────────────────────────────────────────
class AnswerTable(BaseModel):
    """근거 표 하나. 화면은 rows(표시 문자열)를 그대로 그리고, QA(모듈 7)는 raw_rows 로 다시 계산해 본다"""
    table_id: str = Field(..., examples=["t_calc", "t_a3", "t_view_1"])
    kind: TableKind
    title: str
    columns: list[str]
    rows: list[list[str | None]] = Field(..., description="displays 를 적용한 표시 문자열")
    raw_rows: list[list[Any]] = Field(..., description="rows 와 같은 모양의 원래 값 (원래 정밀도)")
    record_ids: list[str] = Field(default_factory=list)
    step_ids: list[str] = Field(default_factory=list, description="이 표를 만든 CalcResult.step_id")
    highlight_rows: list[int] = Field(default_factory=list, description="rows 안의 행 번호 (0부터). view 표에서 계산에 쓴 행")
    truncated: bool = False
    total_rows: int = Field(..., description="행 제한 전의 행 수")


class Caveat(BaseModel):
    source: Literal["view_note", "calc_note", "view_missing", "plan_warning"]
    ref: str = Field(..., description="Record.id 또는 CalcResult.step_id")
    text: str


class Module6Output(BaseModel):
    query_id: str | None = None
    answer: str
    insufficient: bool = Field(False, description="계산 결과가 없거나 모두 계산하지 못해 수치 답변을 하지 못했다")
    method: Method = Field(..., description="hcx = 첫 시도 통과 / hcx_retry = 재시도 후 통과 / template = 규칙 문장 / none = 답변할 계산 없음")
    tables: list[AnswerTable] = Field(default_factory=list, description="계산 요약 → 계산 목록 → 원본 View 순서")
    caveats: list[Caveat] = Field(default_factory=list)
    used_step_ids: list[str] = Field(default_factory=list, description="답변 문장이 실제로 인용한 CalcResult.step_id")
    notes: list[str] = Field(default_factory=list, description="HCX 실패·재시도 사유 등 (QA 가 본다)")
