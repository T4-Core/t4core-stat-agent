"""
1.1 QueryBundle — 질의 분석(파트 1) → View 검색·생성(파트 2·3) 입력 계약

두 가지 QueryBundle 이 있다 (모양이 달라 그대로 연결하면 안 맞음 → adapter.py 로 변환):
  RewriterBundle : 재작성 모듈 출력 (구 Rewritten_fastapi QueryBundle dataclass)
                   filters 값이 모두 문자열 목록 ('2025년', '20~29세'), 의도는 intent 에만, 비교축은 목록
  QueryBundle    : View 모듈 입력 (구 view_model/schemas.py)
                   시점 = int 목록, 연령 = {from,to}, 비교축 = 문자열, 의도는 filters 안에도
"""

from pydantic import BaseModel, ConfigDict, Field

# ─── 구 view_model/schemas.py 15~90 행 (내용 그대로) ───
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
    search_text: str | None = Field(None, description="[NEW] 상위 질의 검색 문장. 비우면 original 로 검색 (예전과 같음). "
                                                    "통합 파이프라인은 재작성 문장(rewritten)을 넣음")


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



# ── [NEW] 재작성 모듈(파트 1) API 입출력 ───────────────────────────
class RewriteRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"question": "작년 대구의 남자 20대 인구 수", "today": "2026-11-02"},
        {"question": "2022년 대전 노인 인구랑 다문화가구 수", "today": "2026-11-02"}]})
    question: str = Field(..., description="사용자 질문 (구어체 그대로)")
    today: str | None = Field(None, description="상대 시점(작년·최근 5년) 기준일 YYYY-MM-DD. 비우면 오늘")
    query_id: str | None = Field(None, description="View 모듈 Record id 에 쓸 질의 ID (비우면 자동)")


class RewriterBundle(BaseModel):
    """재작성 모듈 출력 = backend.rag.query_analyzer.bundle.QueryBundle(dataclass) 와 같은 필드"""
    original: str
    rewritten: str = Field(..., description="검색용 문장 (예: '2025년 전국 1인가구 가구수'). 슬롯이 모두 비면 original")
    sub_questions: list[str] = Field(default_factory=list)
    intent: str | None = Field(None, description="값 조회 / 추이 / 비교 / 순위 / 구성비 / 증감")
    filters: dict[str, list[str]] | None = Field(None, description="값 있는 슬롯만 (키: 시점·지역·전출지·전입지·국적·대상·성별·연령·조건·이동·지표·비교축)")
    sub_filters: list[dict] | None = None


class RewriteResponse(BaseModel):
    """POST /api/v1/rag/query-rewrite 응답. view_bundle 을 그대로 POST /api/v1/rag/views 에 넣으면 다음 단계"""
    bundle: RewriterBundle = Field(..., description="재작성 모듈 원본 출력")
    view_bundle: QueryBundle = Field(..., description="View 모듈 입력으로 바꾼 것 (adapter.to_view_bundle)")
    notes: list[str] = Field(default_factory=list, description="변환 중 버리거나 바꾼 값 (예: 월 → 연도, 지원 안 하는 슬롯)")
    elapsed_s: float | None = None


class AdaptRequest(BaseModel):
    """재작성 결과(파일 outputs/query_bundles.json 의 한 항목 등)를 View 모듈 입력으로만 바꿀 때"""
    bundle: RewriterBundle
    query_id: str | None = None
    search_with: str = Field("rewritten", description="상위 질의 검색 문장: rewritten(재작성 문장) | original(원 질문)")
