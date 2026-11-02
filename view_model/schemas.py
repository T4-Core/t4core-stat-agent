"""
View 모듈 입출력 스키마 (Pydantic) — Swagger(/docs) 에 그대로 문서화됨

  QueryBundle : 쿼리 모듈 → View 모듈 입력. 자연어(original) + 슬롯 dict(filters), 서브쿼리도 같은 쌍
  Record      : View 카드 하나 (doc_type = "view") — 판단·RAG 모듈로 넘기는 것은 Record 목록
  ViewResult  : 확인용 상세 = 질의(자연어·슬롯) + 검색 단위별 후보 + 카드·notes

나중에 팀 공용 스키마(common/schemas.py)가 생기면 QueryBundle·Record 는 그쪽 것을 import 해서 쓴다
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Swagger 예시: 쿼리 모듈 담당자가 준 질의 (1번 단일, 6번 서브쿼리 있음). original = 자연어, filters = 슬롯 dict
EX_QUERY_1 = {
    "query_id": "1",
    "original": "작년 대구의 남자 20대 인구 수",
    "rewritten": "[시점] 2025년 [지역] 대구광역시 [대상] 인구 [성별] 남자 [연령] 20~29세 [지표] 인구수 [의도] 값 조회",
    "intent": "값 조회",
    "filters": {"시점": [2025], "지역": ["대구광역시"], "대상": ["인구"], "성별": ["남자"],
                "연령": {"from": 20, "to": 29}, "지표": ["인구수"], "의도": "값 조회"},
    "sub_questions": [],
    "sub_filters": None,
}
EX_QUERY_6 = {
    "query_id": "6",
    "original": "부산 출생아 수 및 대구 사망자 수",
    "rewritten": "[지역] 부산광역시, 대구광역시 [대상] 출생아, 사망자 [지표] 출생아수, 사망자수 [의도] 값 조회",
    "intent": "값 조회",
    "filters": {"지역": ["부산광역시", "대구광역시"], "대상": ["출생아", "사망자"], "지표": ["출생아수", "사망자수"],
                "의도": "값 조회"},
    "sub_questions": ["부산의 연도별 출생아 수", "대구의 연도별 사망자 수"],
    "sub_filters": [{"지역": ["부산광역시"], "대상": ["출생아"], "지표": ["출생아수"], "의도": "값 조회"},
                    {"지역": ["대구광역시"], "대상": ["사망자"], "지표": ["사망자수"], "의도": "값 조회"}],
}


# ── 쿼리 모듈 → View 모듈 ────────────────────────────────────────
class AgeRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: int | None = Field(None, alias="from", description="시작 나이 (포함)")
    to: int | None = Field(None, description="끝 나이 (포함). 없으면 상한 없음 (예: 65세 이상)")


class Filters(BaseModel):
    """슬롯 dict. 키 이름 = 쿼리 모듈 슬롯 이름. 빈 슬롯은 None (View 생성 때 기본값 적용)"""
    model_config = ConfigDict(populate_by_name=True)
    시점: list[int] | None = Field(None, description="연도 목록. None 이면 값 조회=최신 연도, 추이=전체 기간")
    지역: list[str] | None = Field(None, description="지역 표준명 (region_dict.json). None 이면 전국")
    대상: list[str] | None = Field(None, description="무엇에 대한 통계인가 (인구, 출생아, 가구 …)")
    성별: list[str] | None = Field(None, description="남자 / 여자")
    연령: AgeRange | None = Field(None, description="나이 범위 {from, to}")
    지표: list[str] | None = Field(None, description="무엇을 셌는가 (인구수, 출생아수, 고령인구비율 …)")
    비교축: str | None = Field(None, description="비교·순위의 기준 축 (시도, 지역 …)")
    의도: str | None = Field(None, description="값 조회 / 추이 / 비교 / 순위")


class QueryBundle(BaseModel):
    """쿼리 모듈 → View 모듈 입력. 검색은 자연어(original, sub_questions)로, View 조건은 슬롯(filters, sub_filters)으로"""
    model_config = ConfigDict(json_schema_extra={"examples": [EX_QUERY_1, EX_QUERY_6]})
    query_id: str | None = Field(None, description="질의 ID (Record id 에 쓰임). 없으면 자동 생성")
    original: str = Field(..., description="사용자 질문 자연어 — 검색에 사용")
    rewritten: str | None = Field(None, description="슬롯 형식 문자열 (참고용). filters 가 없으면 이것을 파싱")
    intent: str | None = Field(None, description="질문 분류")
    filters: Filters | None = Field(None, description="슬롯 dict — View 를 자를 조건")
    sub_questions: list[str] = Field(default_factory=list, description="서브쿼리 자연어 (없으면 [])")
    sub_filters: list[Filters] | None = Field(None, description="서브쿼리 슬롯 dict (sub_questions 와 같은 순서)")


class SlotQuery(BaseModel):
    """② /query/bundle 입력: 슬롯이 문자열로만 올 때 dict 로 바꾸는 보조 기능"""
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"original": EX_QUERY_1["original"], "rewritten": EX_QUERY_1["rewritten"], "sub_questions": []}]})
    original: str
    rewritten: str
    sub_questions: list[str] = Field(default_factory=list)


class QueryBundleResult(BaseModel):
    """② /query/bundle 응답: QueryBundle + 해석하지 못한 부분"""
    bundle: QueryBundle
    notes: list[str] = Field(default_factory=list, description="모르는 슬롯, 해석 못 한 값, 지역명 표준화 내역")


class ExampleBundle(QueryBundleResult):
    """② /query/examples 항목: 쿼리 모듈 예시 질의 하나"""
    query_id: str
    sub_ids: list[str] = Field(default_factory=list, description="서브쿼리 ID (sub_questions 와 같은 순서)")


# ── View 모듈 → 판단 모듈 ────────────────────────────────────────
class DocType(str, Enum):
    table = "table"
    view = "view"
    item = "item"


class ViewTable(BaseModel):
    columns: list[str] = Field(..., examples=[["시점", "행정구역(시군구)별", "항목", "값"]])
    rows: list[list[Any]] = Field(..., examples=[[["2025", "서울특별시", "총인구수", 9299548.0]]])


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


class ViewItem(BaseModel):
    record: Record
    notes: list[str] = Field(default_factory=list, description="표에 없어 못 맞춘 조건 (확인용, 카드에는 안 들어감)")
    rank: int
    tbl_id: str


class Candidate(BaseModel):
    """검색 후보 (메타데이터 하나 = 표 하나). BM25 로 10개 → bge-m3 로 다시 줄 세운 순서"""
    rank: int = Field(..., description="bge-m3 재정렬 순위 (1부터)")
    tbl_id: str
    tbl_nm: str
    survey_nm: str
    score: float = Field(..., description="재정렬 점수 = 자연어 ↔ 표 설명문 코사인 유사도")
    dense: float = Field(..., description="자연어 ↔ 표 설명문 코사인 유사도")
    bm25_rank: int | None = Field(None, description="1단계 BM25 순위 (1부터)")
    bm25: float | None = Field(None, description="1단계 BM25 점수")
    has_view: bool = Field(..., description="View 카드를 만들었는지 (재정렬 상위 N개만)")


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


# ── 중간 단계 응답 ──────────────────────────────────────────────
class SearchResult(BaseModel):
    query: str
    candidates: list[Candidate]


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
