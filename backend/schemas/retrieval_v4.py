"""[NEW v4] 검색 실험실 (retrieval-lab) 입출력 — backend/api/v1_retrieval_lab.py"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ComponentSpec(BaseModel):
    """구성 요소 하나 (type + 그 type 의 인자). 인자는 type 마다 달라 자유 dict"""
    model_config = ConfigDict(extra="allow")
    type: str


class RetrievalConfig(BaseModel):
    """configs/retrieval/*.yaml 과 같은 모양 (extends 로 다른 구성을 물려받을 수 있음)"""
    model_config = ConfigDict(extra="allow")
    name: str = "inline"
    description: str = ""
    extends: str | None = None
    requires: list[str] = []
    corpus: dict = Field(default_factory=lambda: {"type": "table_text"},
                         examples=[{"type": "table_text"}, {"type": "csv_index", "scope": "selected"}])
    query: dict = Field(default_factory=lambda: {"prep": "none"})
    retrievers: list[dict] = Field(default_factory=list, examples=[[
        {"name": "bm25", "type": "bm25", "k": 50, "tokenizer": {"type": "kiwi", "variant": "table"}}]])
    fusion: dict | None = None
    rerank: list[dict] = Field(default_factory=list, examples=[[
        {"type": "condition", "top_n": "top_k"}, {"type": "embed", "embedder": {"type": "hcx_bge_m3"}, "respect_cost": True}]])
    top_k: int = 10


class ConfigSummary(BaseModel):
    name: str
    description: str = ""
    extends: str | None = None
    requires: list[str] = []
    missing: list[str] = []          # 설치 안 된 패키지 (있으면 이 구성은 실행 못 함)
    corpus: str | None = None
    retrievers: list[str] = []
    rerank: list[str] = []
    error: str | None = None


class LabSearchRequest(BaseModel):
    query: str = Field(..., description="검색 문장. prep=resolve 면 지역·시점 단어를 빼고 지표를 더해서 검색",
                       examples=["1인가구 가구수"])
    filters: dict | None = Field(None, description="View 슬롯 (기존 view_bundle.filters 모양). None 이면 조건 확인 생략",
                                 examples=[{"시점": [2025], "지역": ["전국"], "대상": ["1인가구"], "지표": ["가구수"]}])
    config: str | None = Field("baseline", description="configs/retrieval/<이름>.yaml")
    config_inline: RetrievalConfig | None = Field(None, description="이름 대신 구성 전체 (config 보다 우선)")
    overrides: dict = Field(default_factory=dict, description="점 경로로 일부만 바꾸기",
                            examples=[{"top_k": 5, "rerank.0.top_n": 20}])
    top_k: int | None = None
    prep: Literal["none", "resolve"] | None = Field(None, description="이 요청만 query.prep 를 바꿈 (resolve = views.run_query 와 같은 다듬기)")
    trace: bool = True


class LabHit(BaseModel):
    model_config = ConfigDict(extra="allow")
    rank: int
    tbl_id: str
    tbl_nm: str = ""
    survey_nm: str = ""
    score: float | None = None
    dense: float | None = None
    bm25_rank: int | None = None
    bm25: float | None = None
    unmet: list[dict] | None = None
    cover: float | None = None
    cost: float | None = None
    stages: dict[str, dict] = {}      # 단계 이름 → {rank, score}


class LabSearchResponse(BaseModel):
    config: str
    query: str
    search_query: str
    filters: dict | None
    top_k: int
    hits: list[LabHit]
    seconds: float
    trace: list[dict] = []
    pipeline: dict = {}               # 코퍼스 서명·문서 수·검색기 fit 정보


class LabQuery(BaseModel):
    id: str | None = None
    question: str | None = None
    search_text: str | None = None
    filters: dict | None = None
    gold: list[str] = []
    prep: bool = True                 # filters 가 있으면 resolve.search_query 로 다듬기


class CompareRequest(BaseModel):
    source: str | None = Field("bundles", description="bundles | golden | examples | <파일 경로>. queries 를 주면 무시",
                               examples=["bundles"])
    queries: list[LabQuery] = Field(default_factory=list, description="직접 넣는 질의 (source 대신)")
    limit: int | None = Field(10, description="질의 수 상한 (bundles 는 원 질문 기준, 하위 질의는 함께)")
    analyze: Literal["none", "v4"] = Field("none", description="v4 = 슬롯 없는 질문을 v4 쿼리 모듈로 분석 (HCX 호출)")
    today: str | None = None
    configs: list[str | RetrievalConfig] = Field(default_factory=lambda: ["baseline", "bm25_only"],
                                                 examples=[["baseline", "hybrid_rrf_hcx", "kiwi_lexicon"]])
    reference: str | None = Field(None, description="일치도 기준 구성 (기본 첫 구성)")
    top_k: int = 10
    blind: bool = Field(False, description="보고서·review.csv 에서 구성 이름을 A·B·C 로 가림 (key.json 에 대응표)")
    trace: bool = False
    save: bool = True


class CompareResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: str
    created: str
    top_k: int
    reference: str | None
    blind: bool
    labels: dict[str, str]
    configs: list[dict]
    summary: dict[str, Any]
    n_queries: int
    queries: list[dict]
    files: dict[str, str] = {}
    report_url: str | None = None
    review_url: str | None = None


class Judgment(BaseModel):
    query_id: str
    tbl_id: str
    label: str | int = Field(..., description="2|1|0 또는 O|△|X")


class ScoreRequest(BaseModel):
    judgments: list[Judgment] = Field(default_factory=list, description="비우면 실행 폴더의 review.csv label 칸을 읽음")
    k: int | None = None
