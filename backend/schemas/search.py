"""
1.3 검색 계약
  SearchRequest / Candidate / SearchResult : View 모듈 표 검색 (BM25 → bge-m3 재정렬)  — 구 view_model
  HybridSearchRequest / HybridHit          : records.jsonl 하이브리드 검색 (BM25 + Dense → RRF) — 구 kosis_rag_qa Index.search  [NEW 스키마]
"""
from pydantic import BaseModel, Field

from backend.schemas.record import Note

# ─── 구 view_model/schemas.py 125~136 행 (내용 그대로) ───
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
    # [NEW 11-03] 슬롯을 넘겨 검색했을 때만 (resolve.py)
    unmet: list[Note] | None = Field(None, description="표 메타데이터 기준으로 못 맞춘 조건")
    cover: float | None = Field(None, description="요청 연도 중 표 기간 안에 든 비율 (0~1)")
    cost: float | None = Field(None, description="정렬 점수 = 시점 외 못 맞춘 조건 수 + (1 - cover). 작을수록 앞")



# ─── 구 view_model/schemas.py 157~160 행 (내용 그대로) ───
class SearchResult(BaseModel):
    query: str
    candidates: list[Candidate]



class SearchRequest(BaseModel):
    """(구 view_model/routers/search.py 안에 있던 요청 모델)"""
    query: str = Field(..., examples=["최근 5년간 대전의 인구 변화 추이"])
    top_k: int = Field(10, ge=1, le=100)


class HybridSearchRequest(BaseModel):
    query: str = Field(..., examples=["서울 인구 추이"])
    k: int = Field(10, ge=1, le=50)
    variant: str = Field("base", description="인덱스 이름 (base | enriched …) = RAG_INDEX_DIR/<variant>")
    doc_type: str | None = Field(None, description="table | view (비우면 둘 다)")


class HybridHit(BaseModel):
    id: str
    score: float
    title: str
    doc_type: str | None = None
    bm25_rank: int | None = None
    dense_rank: int | None = None
    dense_sim: float | None = None
