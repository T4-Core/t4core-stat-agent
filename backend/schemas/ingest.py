"""수집 결과 준비 (메타 프로필·정규화·CSV 값 사전) 입출력"""
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class CsvIndexBuildRequest(BaseModel):
    scope: Literal["all", "selected"] = Field("all", description="all = raw 폴더 전체 (조회 때 설정 csv_scope 로 거름) / selected")
    limit: int | None = Field(None, description="앞에서부터 n개 표만 (빠른 확인)")
    force: bool = Field(False, description="원본이 같아도 다시 스캔")
    workers: int = Field(4, ge=1, le=16)


class CsvValue(BaseModel):
    value: str
    n_tables: int
    example_tables: list[str] = []
