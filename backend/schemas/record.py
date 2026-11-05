"""
1.2 Record — View 모듈(파트 2) 출력 = 판단·Agent 모듈 입력 카드 (doc_type = view)
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─── 구 view_model/schemas.py 92~116 행 (내용 그대로) ───
# ── View 모듈 → 판단 모듈 ────────────────────────────────────────
class DocType(str, Enum):
    table = "table"
    view = "view"
    item = "item"


class ViewTable(BaseModel):
    columns: list[str] = Field(..., examples=[["시점", "행정구역(시군구)별", "항목", "값"]])
    rows: list[list[Any]] = Field(..., examples=[[["2025", "서울특별시", "총인구수", 9299548.0]]])


# [NEW 11-03] 못 맞춘 조건 하나 (build_view.note() 와 같은 모양)
class Note(BaseModel):
    slot: str | None = Field(..., description="시점 · 지역 · 성별 · 연령 · 지표 · 시나리오 · 행수")
    dim: str | None = Field(None, description="표의 어느 분류에서 생겼는지 (예: 시나리오별, 항목)")
    type: str = Field(..., description="missing · default · partial · latest_shift · truncated · empty")
    requested: Any = Field(None, description="요청한 값 (예: [2025], ['부산광역시'], {'from': 20, 'to': 29})")
    applied: Any = Field(None, description="실제로 쓴 값 (예: [2024], ['전국'])")
    text: str = Field(..., description="사람이 읽는 문장")


class Match(BaseModel):
    rank: int = Field(..., description="검색 순위 (1부터)")
    cover: float | None = Field(None, description="요청 연도 중 표 기간 안에 든 비율 (0~1, 연도를 안 물었으면 1)")
    unmet: list[Note] = Field(default_factory=list, description="표 메타데이터 기준으로 못 맞춘 조건")


class Record(BaseModel):
    """View 카드 하나 = 판단·RAG 모듈이 받는 단위 (2026-11-02 받은 예시 모양)"""
    id: str = Field(..., description="view::표key::주기::질문ID-순위::종류 (예: view::101_DT_1B040A3::Y::12-1::trend)")
    lexical_text: str = Field(..., description="BM25 입력 (표 이름·조사명·조건·항목·단위)")
    table: ViewTable = Field(..., description="자른 표 (전체 행)")
    doc_type: DocType = DocType.view
    parent_id: str = Field(..., description="View 를 만든 표 (table::표key)")
    metadata: dict[str, Any] = Field(default_factory=dict, description=(
        "survey_nm, category, survey_type, view_type, prd_se, prd_from, prd_to, is_latest, unit, geo_level, "
        "n_points, items, dims"))
    source: dict[str, Any] = Field(default_factory=dict, description=(
        "다시 조회하는 좌표: table_key, file, org_id, tbl_id, prd_se, itm_id, dims{c1:{codes}}, period, kosis_url"))
    # [NEW 11-03] 판단 모듈이 규칙으로 읽을 수 있게 구조화
    notes: list[Note] = Field(default_factory=list, description="View 를 만들 때 못 맞춘 조건 (빈 목록 = 다 맞춤)")
    match: Match | None = Field(None, description="표를 고를 때의 결과 (검색 순위, 요청 연도 중 담은 비율, 못 맞춘 조건)")

