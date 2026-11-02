"""
[NEW] Agent 입출력 — 통합 파이프라인(POST /api/v1/chat)과 단계별 답변(POST /api/v1/agent/answer)

  ChatRequest  ─▶ ① 질의 재작성 ─▶ ② View 검색·생성 ─▶ ③ Record 기반 답변 ─▶ ChatResponse
  AnswerRequest(question + Record 목록) ─▶ ③ 만 실행 ─▶ AnswerResult   (Swagger 에서 단계별로 이어 붙여 테스트할 때)
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.query import QueryBundle, RewriterBundle
from backend.schemas.record import Record
from backend.schemas.view import ViewResult


class ChartData(BaseModel):
    """프론트엔드 차트용 (data_engine/chart_generator.chart_from_record)"""
    record_id: str
    type: str = Field(..., description="line | bar | table")
    title: str
    x: str | None = None
    y: str = "값"
    series: str | None = None
    unit: str | None = None
    columns: list[str]
    rows: list[list[Any]]


class AnswerResult(BaseModel):
    answer: str
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    insufficient: bool = False
    unverified_numbers: list[str] = Field(default_factory=list, description="자료에서 확인되지 않은 숫자 (계산값일 수 있음)")
    used_ids: list[str] = Field(default_factory=list)
    chart_id: str | None = None
    chart: ChartData | None = None
    sources: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list, description="View 생성 때 못 맞춘 조건 (notes)")


class AnswerRequest(BaseModel):
    """③ 답변만: POST /api/v1/rag/views 결과(Record 목록)를 그대로 붙여 넣음"""
    question: str
    records: list[Record]
    notes: dict[str, list[str]] = Field(default_factory=dict, description="record id → 못 맞춘 조건 (views/detail 의 notes)")
    titles: dict[str, str] = Field(default_factory=dict, description="record id → 표 이름 (없으면 lexical_text 앞부분)")
    max_rows: int = Field(40, ge=1, le=500, description="Record 하나당 LLM 에 넣을 최대 행 수")


class ChatRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"question": "작년 대구의 남자 20대 인구 수", "today": "2026-11-02"},
        {"question": "최근 5년간 대전의 인구 변화 추이", "top_k": 10, "n_views": 3}]})
    question: str
    today: str | None = Field(None, description="상대 시점 기준일 YYYY-MM-DD (비우면 오늘)")
    top_k: int = Field(10, ge=1, le=50, description="BM25 1단계 후보 수")
    n_views: int = Field(3, ge=0, le=10, description="bge-m3 재정렬 후 View 를 만들 표 수")
    search_with: str = Field("rewritten", description="상위 질의 검색 문장: rewritten | original")
    use_rewrite: bool = Field(True, description="false 면 재작성(HCX) 없이 원 질문으로 바로 검색")
    max_rows: int = Field(40, ge=1, le=500)
    save: bool = Field(False, description="true 면 ANSWERS_DIR 에 결과 JSON 저장")


class ChatResponse(BaseModel):
    question: str
    rewrite: RewriterBundle | None = Field(None, description="① 재작성 모듈 출력")
    view_bundle: QueryBundle = Field(..., description="① → ② 변환된 입력")
    views: ViewResult = Field(..., description="② 검색 후보 + View 카드 상세")
    records: list[Record] = Field(..., description="② 카드 목록 (판단 모듈 입력)")
    result: AnswerResult = Field(..., description="③ 답변")
    notes: list[str] = Field(default_factory=list, description="단계 사이 변환 메모")
    timings: dict[str, float] = Field(default_factory=dict, description="단계별 소요 시간(초)")
    saved: str | None = None


class LegacyChatRequest(BaseModel):
    """구 kosis_rag_qa.py ask (records.jsonl 하이브리드 인덱스 기반)"""
    question: str = Field(..., examples=["최근 10년 서울 인구 어떻게 변했어?"])
    variant: str = "base"
    k: int = Field(5, ge=1, le=20)
    use_rewrite: bool = True
    max_rows: int = 40
    save: bool = False
