"""
1.1 QueryBundle — 질의 분석(파트 1) → View 검색·생성(파트 2·3) 입력 계약

두 가지 QueryBundle 이 있다 (모양이 달라 그대로 연결하면 안 맞음 → adapter.py 로 변환):
  RewriterBundle : 재작성 모듈 출력 (구 Rewritten_fastapi QueryBundle dataclass)
                   filters 값이 모두 문자열 목록 ('2025년', '20~29세'), 의도는 intent 에만, 비교축은 목록
  QueryBundle    : View 모듈 입력 (구 view_model/schemas.py)
                   시점 = int 목록, 연령 = {from,to}, 비교축 = 문자열, 의도는 filters 안에도

[CHANGED v3] 재작성 모듈 v3 (backend/rag/query_analyzer, 노트북 user_question_rewrite_v3.ipynb)
  - 의도 9종 (Intent). 원 질문 의도는 여러 개일 수 있고 RewriterBundle.intent 에는 첫 번째 값 하나
  - 하위 질문마다 의도 하나 → RewriteResponse.sub_intents, View 입력 sub_filters[i].의도
  - '범위 밖' (통계 수치를 묻지 않는 질문) → RewriteResponse.out_of_scope
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 재작성 모듈 v3 의도 9종 (backend/rag/query_analyzer/slots.py INTENTS 와 같은 순서. tests/query_analyzer 에서 확인)
Intent = Literal["값 조회", "추이", "비교", "순위", "구성비", "증감", "증감률", "범위 밖", "합계"]

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


# [NEW v3] 재작성 모듈 v3 실제 출력 모양 (POST /api/v1/rag/query-rewrite). 하위 질문마다 의도가 다름 (값 조회 / 순위)
EX_REWRITE_V3 = {
    "original": "2023년 충남 인구랑 시군구별 고령인구비율 순위",
    "rewritten": "2023년 충청남도 인구수 고령인구비율 시군구별 순위",
    "sub_questions": ["2023년 충청남도 인구수", "2023년 충청남도 고령인구비율 시군구별 순위"],
    "intent": "값 조회",
    "filters": {"시점": ["2023년"], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수", "고령인구비율"], "비교축": ["시군구"]},
    "sub_filters": [{"시점": ["2023년"], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수"]},
                    {"시점": ["2023년"], "지역": ["충청남도"], "지표": ["고령인구비율"], "비교축": ["시군구"]}],
}
EX_VIEW_V3 = {   # EX_REWRITE_V3 → adapter.to_view_bundle (sub_intents = ['값 조회', '순위'])
    "query_id": "q1",
    "original": EX_REWRITE_V3["original"],
    "rewritten": EX_REWRITE_V3["rewritten"],
    "intent": "값 조회",
    "filters": {"시점": [2023], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수", "고령인구비율"], "비교축": "시군구",
                "의도": "값 조회"},
    "sub_questions": EX_REWRITE_V3["sub_questions"],
    "sub_filters": [{"시점": [2023], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수"], "의도": "값 조회"},
                    {"시점": [2023], "지역": ["충청남도"], "지표": ["고령인구비율"], "비교축": "시군구", "의도": "순위"}],
    "search_text": EX_REWRITE_V3["rewritten"],
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
    의도: str | None = Field(None, description="View 종류를 정하는 의도: 값 조회 / 추이 / 비교 / 순위 "
                                             "(재작성 모듈 v3 의도 9종은 adapter.VIEW_INTENT 로 이 4종으로 바뀜)")


class QueryBundle(BaseModel):
    """쿼리 모듈 → View 모듈 입력. 검색은 자연어(original, sub_questions)로, View 조건은 슬롯(filters, sub_filters)으로"""
    model_config = ConfigDict(json_schema_extra={"examples": [EX_VIEW_V3, EX_QUERY_1, EX_QUERY_6]})
    query_id: str | None = Field(None, description="질의 ID (Record id 에 쓰임). 없으면 자동 생성")
    original: str = Field(..., description="사용자 질문 자연어 — 검색에 사용")
    rewritten: str | None = Field(None, description="재작성 문장 (v3: '2025년 대구광역시 남자 20~29세 인구수') 또는 "
                                                  "슬롯 형식 문자열 ('[시점] 2025년 [지역] …'). filters 가 없으면 슬롯 형식일 때만 파싱")
    intent: str | None = Field(None, description="질문 분류 (재작성 모듈 v3 의도 9종 중 하나. View 종류는 filters.의도)")
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
        {"question": "2023년 충남 인구랑 시군구별 고령인구비율 순위", "today": "2026-11-02"},
        {"question": "2022년 대전 노인 인구랑 다문화가구 수", "today": "2026-11-02"}]})
    question: str = Field(..., description="사용자 질문 (구어체 그대로)")
    today: str | None = Field(None, description="상대 시점(작년·최근 5년) 기준일 YYYY-MM-DD. 비우면 오늘")
    query_id: str | None = Field(None, description="View 모듈 Record id 에 쓸 질의 ID (비우면 자동)")
    search_with: Literal["rewritten", "original"] = Field(
        "rewritten", description="view_bundle.search_text: rewritten(재작성 문장) | original(원 질문)")


class RewriterBundle(BaseModel):
    """재작성 모듈 출력 = backend.rag.query_analyzer.bundle.QueryBundle(dataclass) 와 같은 필드"""
    model_config = ConfigDict(json_schema_extra={"examples": [EX_REWRITE_V3]})
    original: str
    rewritten: str = Field(..., description="검색용 문장 (예: '2025년 전국 1인가구 가구수'). 슬롯이 모두 비면 original")
    sub_questions: list[str] = Field(default_factory=list)
    intent: Intent | None = Field(None, description="원 질문 의도 하나 (v3 의도 9종 중, 여러 개면 첫 번째). "
                                                    "목록이 오면 첫 번째 값으로 받음 (예전 저장 파일 호환)")
    filters: dict[str, list[str]] | None = Field(None, description="값 있는 슬롯만, 의도 제외 (키: 시점·지역·전출지·전입지·국적·"
                                                                 "대상·성별·연령·조건·이동·지표·비교축)")
    sub_filters: list[dict[str, list[str]]] | None = Field(None, description="하위 질문 슬롯 (sub_questions 와 같은 순서, 의도 제외)")

    @field_validator("intent", mode="before")
    @classmethod
    def _one_intent(cls, v):
        # v3 검증 슬롯의 의도는 목록 → 첫 번째 값 (bundle._intent_one 과 같은 규칙). 빈 값은 None
        if isinstance(v, (list, tuple)):
            v = next((x for x in v if x), None)
        return v or None


class RewriteResponse(BaseModel):
    """POST /api/v1/rag/query-rewrite 응답. view_bundle 을 그대로 POST /api/v1/rag/views 에 넣으면 다음 단계"""
    bundle: RewriterBundle = Field(..., description="재작성 모듈 원본 출력")
    view_bundle: QueryBundle = Field(..., description="View 모듈 입력으로 바꾼 것 (adapter.to_view_bundle)")
    intents: list[Intent] = Field(default_factory=list, description="[v3] 원 질문 의도 전체 (bundle.intent 는 그중 첫 번째)")
    sub_intents: list[Intent] = Field(default_factory=list, description="[v3] 하위 질문마다 의도 하나 (sub_questions 와 같은 순서). "
                                                                    "view_bundle.sub_filters[i].의도 는 이것을 View 종류로 바꾼 것")
    out_of_scope: bool = Field(False, description="[v3] 의도 '범위 밖' (통계 수치를 묻지 않는 질문). "
                                                 "POST /api/v1/chat 은 이때 표를 검색하지 않고 안내 답변을 돌려줌")
    notes: list[str] = Field(default_factory=list, description="변환 중 버리거나 바꾼 값 (예: 월 → 연도, 지원 안 하는 슬롯)")
    elapsed_s: float | None = None


class AdaptRequest(BaseModel):
    """재작성 결과(파일 outputs/query_bundles_*.json 의 한 항목 등)를 View 모듈 입력으로만 바꿀 때"""
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"bundle": EX_REWRITE_V3, "query_id": "q1", "search_with": "rewritten", "sub_intents": ["값 조회", "순위"]}]})
    bundle: RewriterBundle
    query_id: str | None = None
    search_with: Literal["rewritten", "original"] = Field("rewritten", description="상위 질의 검색 문장: rewritten(재작성 문장) | original(원 질문)")
    sub_intents: list[Intent] | None = Field(None, description="[v3] 하위 질문 의도 (저장 파일에는 없음). 비우면 하위 문장 끝 의도어 "
                                                              "('… 순위') → 원 질문 의도 순으로 정함")


class SlotSpec(BaseModel):
    """GET /api/v1/rag/query-slots — 재작성 모듈 v3 슬롯·의도와 View 입력 대응표"""
    slot_keys: list[str] = Field(..., description="슬롯 12개 (slots.SLOT_KEYS)")
    intents: list[Intent] = Field(..., description="의도 9종 (slots.INTENTS)")
    view_intents: list[str] = Field(..., description="View 모듈이 아는 의도 4종")
    view_intent_map: dict[str, str] = Field(..., description="v3 의도 → View 의도 (adapter.VIEW_INTENT)")
    age_targets: dict[str, str] = Field(..., description="연령을 뜻하는 대상 용어 → View 연령 (adapter.AGE_TARGETS)")


class RewriteTrace(BaseModel):
    """POST /api/v1/rag/query-rewrite/trace — rewrite_trace.json 의 items 한 개 (trace.build_trace)"""
    model_config = ConfigDict(extra="allow")
    no: int
    question: str = Field(..., description="1. 사용자 질문")
    term_hits: list[list[Any]] = Field(default_factory=list, description="2-1. 용어 사전 [[일상어, [대표 용어…]], …]")
    input_question: str = Field(..., description="2-2. 상대 시점·범위를 바꾼 질문")
    time_notes: list[str] = Field(default_factory=list)
    rule_found: dict[str, list[str]] = Field(default_factory=dict, description="2-2. 코드가 찾은 값")
    user_prompt: str = Field(..., description="2-3. HCX user 프롬프트")
    hcx_out: Any = Field(None, description="2-3. HCX 원 응답")
    hcx_slots: dict[str, Any] | None = None
    hcx_subs: list[dict[str, Any]] = Field(default_factory=list)
    parsed: bool | None = None
    error: str = ""
    elapsed_s: float | None = None
    valid_slots: dict[str, Any] = Field(..., description="2-4. 검증 슬롯 (의도는 목록)")
    valid_subs: list[dict[str, Any]] = Field(default_factory=list, description="2-4. 검증 하위 슬롯 (의도는 하나)")
    valid_log: list[str] = Field(default_factory=list)
    rewritten: str = Field(..., description="3. 슬롯 → 문장 (비면 '')")
    sub_questions: list[str] = Field(default_factory=list)
    bundle: RewriterBundle = Field(..., description="4. QueryBundle")


class HcxCheckResponse(BaseModel):
    """GET /api/v1/rag/hcx-check"""
    settings: dict[str, Any] = Field(..., description="현재 설정 (키 값은 넣지 않음)")
    check: dict[str, Any] = Field(..., description="{ok, elapsed_s, response 또는 error}")
