"""2번 모듈 출력 스키마 (고도화 5단계) — chart_plan 을 pydantic 으로 검증한다

  ChartPlanOut ─ query_id · charts: [ChartOut] · overlays: [OverlayOut]
  반환은 지금처럼 dict (model_dump). 필드가 빠지거나 타입이 틀리면 validate_plan 이 errors 에 남긴다.
  overlays 는 5번(차트 그리기)만 읽는다. 3번 어댑터(from_module2)는 charts 만 읽는다.
"""
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

ChartType = Literal["line", "bar", "stacked_bar", "pyramid", "area", "pie", "donut", "bubble",
                    "combo", "radar", "map", "heatmap", "treemap", "scatter", "dumbbell"]


class ChartOut(BaseModel):
    chart_id: str = Field(..., examples=["c1"])
    sub_question_ids: list[str] = Field(default_factory=list, description="'{query_id}-{순번}'")
    view_ids: list[str] = Field(default_factory=list, description="쓰는 View 의 record.id")
    chart_type: ChartType | None = Field(None, description="None = 차트 없음 (표만)")
    requirements: list[str] = Field(default_factory=list)
    fallback_charts: list[str] = Field(default_factory=list)
    measure: str | None = Field(None, description="raw · change · … · '범위 밖'. None = 정하지 못함")
    reason: str = ""
    warnings: list[str] = Field(default_factory=list, description="사용자용 경고")
    # [NEW 11-20 KOS-41] 질문에서 지정한 차트 요청 (preferred · excluded · scope · stage). 없으면 None.
    # 2번 모듈은 backend.schemas 에 의존하지 않으므로 dict 로 두고, 3번 어댑터(from_module2)가 ChartRequestInfo 로 검증한다
    request: dict | None = Field(None, description="차트 지정 요청 (ChartRequestInfo 모양)")


class OverlayOut(BaseModel):
    # [CHANGED 11-25 5단계] 차트 2개만 → 2개 이상 (lines · bars 는 N개, combo · scatter 는 2개, bubble 은 3개, radar 는 3~8개).
    #   mode 에 scatter · bubble · radar (사용자가 요청한 관계 차트), axes 값에 x · size 추가. 기존 2개짜리 표시는 그대로 맞다
    overlay_id: str = Field(..., examples=["c1+c2", "c1+c2+c3"])
    charts: list[str] = Field(..., min_length=2, description="합쳐 그릴 차트의 chart_id (하위질문 순서)")
    mode: Literal["combo", "lines", "bars", "scatter", "bubble", "radar"]
    axes: dict[str, Literal["y", "y2", "x", "size"]] = Field(
        default_factory=dict, description="combo: {chart_id: y | y2} · scatter: {c1: x, c2: y} · bubble: {c1: x, c2: y, c3: size}")
    reason: str = ""


class ChartPlanOut(BaseModel):
    query_id: str | None = None
    charts: list[ChartOut] = Field(default_factory=list)
    overlays: list[OverlayOut] = Field(default_factory=list, description="5번만 읽는 겹쳐 그리기 표시")


def validate_plan(plan):
    """chart_plan dict → (검증한 dict, errors). 틀리면 원래 dict 를 그대로 돌려주고 오류를 남긴다"""
    try:
        return ChartPlanOut.model_validate(plan).model_dump(), []
    except ValidationError as e:
        first = e.errors()[0]
        return plan, [{"node": "reason", "reason": f"chart_plan 스키마 오류 {e.error_count()}건: {first['loc']} {first['msg']}"}]
