"""
[NEW] 모듈 3 (질문 계산 + 차트용 계산·내용 구성·검증) 입출력 계약

  명세: docs/discussions/2026-11-09-차트-계산-명세.md (상태: 제안 — 팀 합의 전)
  구현: backend/agent/chart_calculate/*.py. 이 파일은 스키마 정의만 한다.

  Module3Request(records + query_bundle + charts)
      └▶ ChartPlan ─▶ 계산 ─▶ ChartContent[] · CalcResult[] · displays · validation = Module3Output

  직렬화 주의: Step 의 from 은 파이썬 예약어라 from_ 으로 두고 alias 로 받는다.
              dict 로 바꿀 때는 model_dump(by_alias=True) 를 써야 명세와 같은 키("from")가 나온다.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

# ── 코드값 ───────────────────────────────────────────────────────
ChartType = Literal["line", "bar", "stacked_bar", "pyramid", "area", "pie", "donut", "bubble",
                    "combo", "radar", "map", "heatmap", "treemap", "scatter", "dumbbell"]

# measure 와 Step.op 는 같은 값 집합을 쓴다 (명세 4장)
Measure = Literal["raw", "change", "growth_rate", "cagr", "index", "share",
                  "diff", "ratio", "rank", "extreme", "aggregate", "combine"]
# [CHANGED 11-11] combine 추가 (명세 외): 부호 붙은 피연산자 여럿을 시점끼리 더하고 뺀다 (출생 − 사망 + 순이동)

# 축 역할 코드 (명세 3장)
Role = Literal["x", "y", "y2", "series", "value", "label", "size", "region", "parent", "group", "start", "end"]


# ── 입력 ─────────────────────────────────────────────────────────
class ChartRequest(BaseModel):
    """모듈 2 의 차트 계획 하나 (charts[] 의 원소)

    TODO(임시): 모듈 2 출력 스키마가 저장소에 없어 명세 2장의 필드 목록으로 임시 정의했다.
                모듈 2 담당자 확인 후 필드 이름·타입을 맞춘다.
    """
    chart_id: str = Field(..., examples=["c1"])
    sub_question_ids: list[str] = Field(default_factory=list)
    chart_type: ChartType | None = Field(None, description="None = 모듈 2 가 차트 없음으로 판단 (plans 를 만들지 않는다)")
    measure: Measure = "raw"
    requirements: list[str] = Field(default_factory=list, description="검증 코드 (예: time_axis_required, min_points_3)")
    fallback_chart: ChartType | None = None
    reason: str | None = None


class Module3Request(BaseModel):
    records: list[Record] = Field(..., description="모듈 1 이 고른 View 들. 계산 근거는 Record.table.rows")
    query_bundle: QueryBundle
    charts: list[ChartRequest] = Field(default_factory=list)


# ── ChartPlan (계산 계획) ────────────────────────────────────────
Select = dict[str, list[Any]]   # {열 이름: [값, ...]} — Record.table.rows 에서 쓸 행을 고르는 조건


class Operand(BaseModel):
    role: str | None = Field(None, description="연산별 역할 이름 (diff·ratio: a, b / growth_rate: value / share: part / "
                                               "combine: term). denominator.operand 에서는 생략한다")
    sign: Literal["+", "-"] | None = Field(None, description="[NEW] combine 전용: 더할지(+) 뺄지(-). 생략하면 +")
    # [NEW 11-11] 단위의 출처. hcx 는 표시에만 쓰고 단위 호환 검사에는 쓰지 않는다 (그 항목의 단위인지 확인할 수 없어서)
    unit_source: Literal["item", "table", "hcx"] | None = Field(
        None, description="item: 항목 이름의 괄호 / table: View 의 단일 단위 / hcx: HCX 가 고름 (확인 안 됨)")
    record_id: str
    # 명세가 모호한 부분: View 열은 '항목' 인데 명세 예시의 select 는 분류 열('종류별')에 항목 값을 넣는다.
    # 구현(select.py)은 '항목' 열을 먼저 보고, 없으면 이 값을 가진 분류 열을 찾는다.
    item: str | None = Field(None, description="대상 항목 (예: 인구수(명))")
    select: Select = Field(default_factory=dict)
    unit: str | None = Field(None, description="원 단위 (항목 이름의 괄호 부분)")


class Denominator(BaseModel):
    """share 의 분모 범위"""
    scope: Literal["question", "selected"]
    basis: str | None = Field(None, description="범위를 정한 근거 (예: 질문의 '전국 대비')")
    operand: Operand | None = Field(None, description="scope=question 일 때 총계를 가져올 곳")
    label: str | None = Field(None, description="표시 문구. scope=selected 면 '선택 항목 내 비중'")


class Step(BaseModel):
    """Calculate 호출 하나. plans[].steps(차트용) 와 answer_steps(질문용) 가 같은 모양을 쓴다"""
    # 연산별 인자는 후속 명세에서 확정된다 → 아직 정의되지 않은 인자도 버리지 않고 받는다
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    step_id: str = Field(..., examples=["s1", "a1"])
    op: Measure
    operands: list[Operand] | None = Field(None, description="plans[].steps 에서 생략하면 상위 record_id·select 를 피연산자 하나로 쓴다. "
                                                             "answer_steps 에서는 항상 적는다")
    join_on: list[str] | None = Field(None, description="여러 피연산자를 짝지을 열 (예: ['시점']). 피연산자가 둘 이상이면 필수")
    input: str | None = Field(None, description="앞 단계의 step_id (그 결과를 입력으로 쓴다)")
    denominator: Denominator | None = Field(None, description="share 전용")
    display_ref: str | None = Field(None, description="displays 의 키")
    from_: str | None = Field(None, alias="from", description="기간 시작 시점")
    to: str | None = Field(None, description="기간 끝 시점")
    base: str | None = Field(None, description="기준 시점. 'prev' = 직전 시점")
    agg: Literal["sum", "mean"] | None = None
    top_n: int | None = Field(None, ge=1)


class PlanOutput(BaseModel):
    step_id: str
    role: Role


class Plan(BaseModel):
    """차트 하나의 계획"""
    chart_id: str
    sub_question_ids: list[str] = Field(default_factory=list)
    record_id: str = Field(..., description="기본 계산 대상 View. 단계에 operands 가 있으면 그쪽이 우선")
    chart_type: ChartType = Field(..., description="모듈 2 의 원래 차트")
    fallback_chart: ChartType | None = None
    measure: Measure
    select: Select = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    output: list[PlanOutput] | None = Field(None, description="갈래가 하나면 생략 → 마지막 단계를 쓴다")
    # [NEW 명세 외] 질문의 말로 쓴 차트 제목 (HCX). 비어 있으면 content.py 가 규칙으로 만든다
    title: str | None = Field(None, description="차트 제목 (HCX 작성, planner 가 검사). 없으면 규칙 제목")


class ChartPlan(BaseModel):
    plans: list[Plan] = Field(default_factory=list)
    answer_steps: list[Step] = Field(default_factory=list, description="질문용 계산. 차트가 없어도 만든다")
    # [NEW 명세 외] 질문용 연산(HCX 가 정함)과 모듈 2 measure 가 다를 때의 기록 등. QA(모듈 7)가 본다
    notes: list[str] = Field(default_factory=list)


# ── 표시 설정 ────────────────────────────────────────────────────
class Display(BaseModel):
    """표시 방법: 원값 ÷ unit_scale → digits 자리로 한 번 반올림 → display_unit"""
    source_unit: str
    display_unit: str
    unit_scale: float = Field(1, gt=0)
    digits: int | None = Field(None, ge=0, description="생략하면 단위별 기본값 (agent/chart_calculate/display.py)")


# ── ChartContent (차트에 들어갈 내용) ────────────────────────────
class AxisSpec(BaseModel):
    label: str | None = None
    type: Literal["time", "category", "numeric", "region"] | None = None
    scale: Literal["linear", "log", "percent", "index"] | None = None
    min: float | None = None
    max: float | None = None
    display_ref: str | None = None


class ChartContent(BaseModel):
    """최종 차트 하나. 대체되었으면 대체 차트의 내용이고, 대체도 실패한 차트는 만들지 않는다"""
    chart_id: str
    chart_type: ChartType = Field(..., description="최종 차트 유형")
    measure: Measure
    title: str
    encoding: dict[Role, str] = Field(..., description="{역할 코드: 열 이름}")
    axis: dict[Literal["x", "y", "y2"], AxisSpec] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict, description="marks · orientation · center_text · scope_label …")
    columns: list[str]
    rows: list[list[Any]] = Field(..., description="값은 원래 정밀도. 표시 변환은 받는 쪽이 displays 로 한다")
    record_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── CalcResult (질문용 계산 결과) ────────────────────────────────
class CalcInput(BaseModel):
    """계산에 쓴 원래 값 하나 (QA 가 다시 계산할 때 쓴다)"""
    role: str
    record_id: str
    item: str | None = None
    key: dict[str, Any] = Field(default_factory=dict, description="이 값을 특정하는 열 값 (예: {'시점': '2021'})")
    value: int | float | None = None     # [CHANGED 11-11] 이전: float — 정수가 실수로 바뀌어 큰 정수의 정밀도를 잃었다
    unit: str | None = None


class CalcResult(BaseModel):
    step_id: str
    op: Measure
    # [CHANGED 11-11] 이전: float | list | None — 정수 결과가 실수로 바뀌었다 (int 를 float 보다 앞에 두어야 int 가 유지된다)
    value: int | float | list[Any] | None = Field(None, description="원래 정밀도. 여러 값이면 list, 계산할 수 없으면 None")
    unit: str | None = None
    display_ref: str | None = None
    inputs: list[CalcInput] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)
    scope_label: str | None = None
    note: str | None = Field(None, description="계산하지 못한 이유 (기준값 0, 키 중복, truncated …)")


# ── validation ───────────────────────────────────────────────────
class CheckResult(BaseModel):
    chart_type: ChartType
    passed: bool
    checked: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ChartValidation(BaseModel):
    original: CheckResult
    fallback: CheckResult | None = Field(None, description="대체 차트를 시도하지 않았으면 None")
    final_chart_type: ChartType | None = None
    content_built: bool = False


# ── 전체 출력 ────────────────────────────────────────────────────
class Module3Output(BaseModel):
    query_id: str | None = None
    chart_plan: ChartPlan
    chart_contents: list[ChartContent] = Field(default_factory=list)
    calc_results: list[CalcResult] = Field(default_factory=list)
    displays: dict[str, Display] = Field(default_factory=dict, description="{display_ref: 설정}")
    validation: dict[str, ChartValidation] = Field(default_factory=dict, description="{chart_id: 검증 결과}")
