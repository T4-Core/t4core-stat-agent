"""
View 모듈 상세 결과·관리 응답 (구 view_model/schemas.py 중 1.1~1.3 에 들어가지 않는 것)
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import Filters, QueryBundle
from backend.schemas.record import Record
from backend.schemas.search import Candidate

# ─── 구 view_model/schemas.py 118~123 행 (내용 그대로) ───
class ViewItem(BaseModel):
    record: Record
    notes: list[str] = Field(default_factory=list, description="표에 없어 못 맞춘 조건 (확인용, 카드에는 안 들어감)")
    rank: int
    tbl_id: str


# ─── 구 view_model/schemas.py 138~154 행 (내용 그대로) ───
class UnitResult(BaseModel):
    """검색 단위 하나 (상위 질의 또는 서브쿼리)"""
    unit_id: str = Field(..., description="'main' 또는 서브쿼리 ID")
    query: str = Field(..., description="검색에 쓴 자연어")
    filters: Filters | None = Field(None, description="View 조건에 쓴 슬롯")
    candidates: list[Candidate]
    views: list[ViewItem]
    notes: list[str] = Field(default_factory=list)


class ViewResult(BaseModel):
    """판단 모듈로 넘기는 묶음: 원래 질의 + 단위별 View"""
    query_id: str
    original: str
    filters: Filters | None
    units: list[UnitResult]


# ─── 구 view_model/schemas.py 162~198 행 (내용 그대로) ───
class MetaBuildSummary(BaseModel):
    file: str
    n_tables: int
    failed: list[dict[str, str]]
    n_meta_empty: int
    n_raw_missing: int
    kinds: dict[str, int]
    n_with_regions: int
    n_with_sido: int
    periods: dict[str, int]
    n_no_unit: int


class NormalizeResult(BaseModel):
    table_key: str
    tbl_nm: str
    cached: bool = Field(..., description="true 면 기존 정규화 결과를 재사용")
    seconds: float
    row_check: dict[str, int]
    profile: dict[str, Any] = Field(..., description="정규화 프로필 (full=false 면 코드 목록 생략)")


class PipelineRequest(BaseModel):
    # Swagger 가 QueryBundle 예시로 queries 를 채워 1개만 돌리는 일이 없도록 예시를 명시 (queries 없음 = 예시 12개)
    model_config = ConfigDict(json_schema_extra={"examples": [{"top_k": 10, "n_views": 3}]})
    queries: list[QueryBundle] | None = Field(None, description="비우면 쿼리 모듈 예시 12개 질의 (결과: view_results.jsonl). "
                                                                 "넣으면 그 질의만 (결과: view_results_custom_<시각>.jsonl)")
    top_k: int = Field(10, description="검색 후보 수")
    n_views: int = Field(3, description="View 를 만들 후보 수 (상위부터)")


class PipelineResult(BaseModel):
    n_queries: int
    n_records: int
    file: str = Field(..., description="카드 목록 저장 경로 (JSON 배열 하나)")
    detail_file: str = Field(..., description="상세 결과 저장 경로 (jsonl, 한 줄 = ViewResult)")
    records: list[Record]
