"""검사 지점별 기준 스키마 (qa 설계.md 4장)

  팀·모듈 스키마는 import 만 한다. QA 가 새로 정의하는 것은 스키마가 없는 곳뿐이다.
    Module2Error   모듈 2 errors[] 원소            (chart_decision_module/chart_type_nodes.py 의 실제 모양)
    DrawResultQA   모듈 5 DrawResult (dataclass) 를 pydantic 으로 옮긴 것 — 필드는 DrawResult 에서 그대로 가져온다
    DrawnChart     run_modules 반환 drawn[] 원소  (backend/agent/modules.py _draw 의 모양)
  지점 하나에 값이 여럿이면 묶음 모델(AgentInput · Module2Input · Module2Result · Module5Result · ModulesResult)로 검사한다.
"""
import dataclasses
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.agent.chart_decision.chart_decision_module.chart_type_schema import ChartPlanOut
from backend.agent.draw_chart.draw_chart_module.draw_chart_schema import (CHART_TYPES, DRAWN, FAILED,
                                                                          NOT_IMPLEMENTED, SKIPPED, DrawResult)
from backend.schemas.answer import Module6Output, Module6Request
from backend.schemas.chart import ChartRequest, Module3Output, Module3Request
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record
from backend.schemas.view import ViewItem, ViewResult, ViewSet

DrawStatus = Literal[DRAWN, SKIPPED, FAILED, NOT_IMPLEMENTED]
DrawChartType = Literal[tuple(CHART_TYPES)]
OVERLAY = "overlay"                     # 겹친 차트(c1+c2)의 planned_type (draw_chart_overlay.py)
PlannedType = Literal[tuple(CHART_TYPES) + (OVERLAY,)]


# ── A0 에이전트 입력 ─────────────────────────────────────────────
class AgentInput(BaseModel):
    viewset: ViewSet
    view_bundle: QueryBundle = Field(..., description="ViewSet.view_bundle 은 dict 로만 선언되어 있어 QueryBundle 로 따로 검사")


# ── 모듈 2 ──────────────────────────────────────────────────────
class Module2Input(BaseModel):
    query_bundle: QueryBundle
    view_input: ViewResult


class Module2Error(BaseModel):
    """모듈 2 errors[] 하나. level 이 없으면 오류, warning · info 는 알림"""
    reason: str
    node: str | None = None
    level: Literal["warning", "info"] | None = None
    chart_id: str | None = None
    unit_id: str | None = None
    sub_question: str | None = None


class Module2Result(BaseModel):
    chart_plan: ChartPlanOut
    filtered_views: list[ViewItem] | None = Field(None, description="짝이 없어 바로 끝나면 None")
    errors: list[Module2Error] = Field(default_factory=list)


# ── 모듈 5 ──────────────────────────────────────────────────────
_OVERRIDE = {"status": DrawStatus, "chart_type": DrawChartType | None, "planned_type": PlannedType | None}


def _draw_result_model():
    """DrawResult(dataclass) 의 필드를 그대로 옮긴 pydantic 모델. status · chart_type 만 허용값을 좁힌다"""
    fields = {}
    for f in dataclasses.fields(DrawResult):
        typ = _OVERRIDE.get(f.name, f.type)
        if f.default is not dataclasses.MISSING:
            fields[f.name] = (typ, f.default)
        elif f.default_factory is not dataclasses.MISSING:
            fields[f.name] = (typ, Field(default_factory=f.default_factory))
        else:
            fields[f.name] = (typ, ...)
    return create_model("DrawResultQA", __config__=ConfigDict(arbitrary_types_allowed=True), **fields)


DrawResultQA = _draw_result_model()


class Module5Result(BaseModel):
    """run_module5 반환값 중 에이전트가 쓰는 부분"""
    results: list[DrawResultQA] = Field(default_factory=list)
    html: str | None = None
    load_errors: dict[str, Any] = Field(default_factory=dict)


def draw_result_raw(r) -> dict:
    """DrawResult → 검사용 dict (얕은 복사: figure 객체는 그대로)"""
    return {f.name: getattr(r, f.name) for f in dataclasses.fields(r)}


# ── A9 에이전트 출력 ─────────────────────────────────────────────
class DrawnChart(BaseModel):
    chart_id: str
    chart_type: DrawChartType | None = None
    status: DrawStatus
    title: str | None = None
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    merged_from: list[str] = Field(default_factory=list)
    figure: dict[str, Any] | None = None


class ModulesResult(BaseModel):
    """run_modules 반환 8개 키. QA 가 중단하면 module3 · answer 가 None 일 수 있다"""
    charts: list[ChartRequest] = Field(default_factory=list)
    chart_errors: list[dict[str, Any]] = Field(default_factory=list)
    chart_plan: ChartPlanOut | None = None
    records: list[Record] = Field(default_factory=list)
    module3: Module3Output | None = None
    drawn: list[DrawnChart] = Field(default_factory=list)
    answer: Module6Output | None = None
    notes: list[str] = Field(default_factory=list)


# ── 지점 → 기준 스키마 ───────────────────────────────────────────
SCHEMAS: dict[str, type[BaseModel]] = {
    "A0": AgentInput,
    "M2-in": Module2Input,
    "M2-out": Module2Result,
    "M3-in": Module3Request,
    "M3-out": Module3Output,
    "M5-out": Module5Result,
    "M6-in": Module6Request,
    "M6-out": Module6Output,
    "A9": ModulesResult,
}
