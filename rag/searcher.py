"""
rag/searcher.py - 검색 모듈

이 파일이 하는 일 (한 줄 요약)
    오케스트레이터가 넘긴 (views, QueryBundle) 을 받아서, views 를 BM25 + Dense 로 검색하고,
    RRF 로 순위를 합쳐서, 점수와 함께 SearchResult(hits, debug) 로 돌려준다.

"""
from __future__ import annotations

import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

import numpy as np

class DocType(str, Enum):
    """청킹 단위. 자바의 enum 과 같다. B 모듈이 어느 단위로 자르든 이 중 하나로 표시한다."""
    TABLE = "table"
    VIEW = "view"
    ITEM = "item"


@dataclass
class QueryBundle:
    """A(재작성) 모듈 -> 검색 모듈."""
    original: str                                              # 사용자 원 질문
    rewritten: str                                             # 재작성된 질문
    sub_questions: list[str] = field(default_factory=list)     # 복합 질문을 나눈 것 (없으면 [])
    intent: Optional[str] = None                               # 질문 분류 (값 목록은 협의 중, 아직 검색에 안 씀)
    filters: Optional[dict] = None                             # 질문에서 뽑은 연도/지역 등. 검색에는 쓰지 않는다 (필터링은 하지 않기로 함)
    sub_filters: Optional[list[Optional[dict]]] = None         # 서브 질문별 조건. sub_questions 와 같은 순서·같은 길이. 검색에는 쓰지 않는다

@dataclass
class Record:
    """B(View) 모듈 -> 검색 모듈."""
    id: str                                                    # 문서 고유 ID
    lexical_text: str                                          # 검색용 텍스트. BM25 는 이 글자를 쪼개 쓰고, Dense 는 이 글자를 임베딩(숫자 벡터로 변환)해서 쓴다
    #   벡터는 이 모듈(DenseRetriever)이 직접 계산한다. Record 에는 벡터를 담지 않는다.
    table: dict = field(default_factory=dict)                  # view 의 통계표 데이터. {"columns": [컬럼명...], "rows": [[값...], ...]}
    #   2차원 배열(행 x 열) 모양이다. 검색에는 쓰지 않고 Hit 에 그대로 전달한다. 어떤 값이 고정 조건인지는 metadata 가 알려 준다.
    doc_type: DocType = DocType.VIEW
    parent_id: Optional[str] = None                            # 소속 표 ID (parent-child 관계)
    metadata: dict = field(default_factory=dict)               # view 속성(기간, 분류, 지역 등). 검색에는 쓰지 않고 Hit 에 그대로 전달한다
    source: dict = field(default_factory=dict)                 # 수치 재조회 좌표. 검색은 "어떤 문서인가"만 찾고 숫자는 여기로 다시 조회


@dataclass
class Candidate:
    """Retriever 하나가 돌려주는 후보."""
    id: str
    score: float                                               # 그 검색기가 매긴 원점수 (BM25 점수, 코사인 유사도 등)
    rank: int                                                  # 순위. 1부터 시작한다 (1등 = 1)


@dataclass
class Hit:
    """검색 결과 한 건."""
    id: str
    rank: int                                                  # 최종 순위 (1부터)
    final_score: float                                         # RRF 로 합친 최종 점수
    scores: dict                                               # {"bm25": {"score":..,"rank":..}, "dense": {...}}  후보에 없으면 값이 None
    doc_type: DocType
    parent_id: Optional[str]
    metadata: dict
    source: dict
    table: dict = field(default_factory=dict)                  # Record.table 을 그대로 전달 (검색에는 쓰지 않았다)


@dataclass
class SearchResult:
    """검색 모듈 -> 오케스트레이터. 최종 출력."""
    hits: list[Hit]                                            # 상위 k개. 결과가 없으면 []
    debug: dict                                                # 사용한 구성, 단계별 소요시간

@dataclass
class SearchConfig:
    top_k: int = 5                                             # 최종 반환 개수
    pool_size: int = 50                                        # 검색기마다 뽑아 두는 후보 수.
    rrf_k: int = 60                                            # RRF 상수. 클수록 상위권과 하위권의 점수 차이가 줄어든다
    weight_rewritten: float = 1.0                              # 질의 종류별 가중치
    weight_sub_question: float = 1.0
    weight_original: float = 0.5                               # 구어체 원 질문은 문서 용어와 다를 수 있어 보조 신호로만 쓴다
    retrievers: tuple = ("bm25", "dense")                      # 사용할 검색 모델.


_kiwi = None

# NN=명사, SL=외국어, SN=숫자, XR=어근, VV=동사, VA=형용사
_KIWI_TAGS = ("NN", "SL", "SN", "XR", "VV", "VA")


def kiwi_tokenize(text: str) -> list[str]:
    """한국어 형태소 분석(Kiwi)으로 쪼갠다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi            
        _kiwi = Kiwi()
    return [t.form for t in _kiwi.tokenize(str(text)) if t.tag.startswith(_KIWI_TAGS)]


def simple_tokenize(text: str) -> list[str]:
    """공백/기호 기준으로 쪼개는 간단한 버전. 테스트용(tests/test_searcher.py). 형태소 분석은 안 한다."""
    return re.findall(r"[0-9A-Za-z가-힣]+", str(text).lower())



class Retriever(ABC):
    name: str = "base"     # 결과의 scores 딕셔너리에서 키로 쓰인다 ("bm25", "dense")

    @abstractmethod
    def build(self, records: list[Record]) -> Any:
        """이번 질문의 Record[] 로 검색용 인덱스를 만들어 돌려준다."""

    @abstractmethod
    def search(self, index: Any, query: str, k: int) -> list[Candidate]:
        """build 가 돌려준 index 에서 질의 하나로 상위 k개 후보를 돌려준다."""

    @property
    @abstractmethod
    def signature(self) -> str:
        """이 검색기가 어떤 설정(토크나이저, 임베딩 모델)인지 나타내는 문자열. debug 에 남겨 실험 결과를 구분한다."""

@dataclass
class _BM25Index:
    ids: list[str]
    bm25: Any                      # BM25Plus 객체. 모든 문서에 토큰이 하나도 없으면 None
    token_sets: list[set]          # 문서별 토큰 집합. '단어가 겹치는가' 판정용


class BM25Retriever(Retriever):
    name = "bm25"

    def __init__(self, tokenizer: Callable[[str], list[str]] = kiwi_tokenize, tokenizer_name: str = "kiwi"):
        self._tokenizer = tokenizer           
        self._tokenizer_name = tokenizer_name

    @property
    def signature(self) -> str:
        return f"bm25:{self._tokenizer_name}"

    def build(self, records: list[Record]) -> _BM25Index:
        from rank_bm25 import BM25Plus         
        ids = [r.id for r in records]
        corpus = [self._tokenizer(r.lexical_text) for r in records]   
        if not any(corpus):                   
            return _BM25Index(ids, None, [set() for _ in corpus])    
        return _BM25Index(ids, BM25Plus(corpus), [set(tokens) for tokens in corpus])

    def search(self, index: _BM25Index, query: str, k: int) -> list[Candidate]:
        query_tokens = self._tokenizer(query)
        if index.bm25 is None or not query_tokens:                   
            return []
        scores = index.bm25.get_scores(query_tokens)                  
        query_set = set(query_tokens)
        out: list[Candidate] = []
        for i in np.argsort(-scores, kind="stable"):                 
            i = int(i)
            if not (query_set & index.token_sets[i]):                 
                continue
            out.append(Candidate(index.ids[i], float(scores[i]), rank=len(out) + 1))
            if len(out) >= k:
                break
        return out


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """벡터(행)마다 길이를 1로 맞춘다."""
    norm = np.linalg.norm(mat, axis=-1, keepdims=True)
    return mat / np.maximum(norm, 1e-12)       # 0 으로 나누는 것을 막으려고 아주 작은 값을 하한으로 둔다


@dataclass
class _DenseIndex:
    ids: list[str]
    matrix: np.ndarray       # (view 수, 차원). 정규화된 view 벡터가 쌓여 있다. i번째 행이 ids[i] 의 벡터다 (view 하나당 벡터 하나)


class DenseRetriever(Retriever):
    name = "dense"
    _CACHE_LIMIT = 1000          # 질문 임베딩 캐시가 무한히 커지지 않게 하는 상한
    _VIEW_CACHE_LIMIT = 20000    # view 임베딩 캐시 상한. view 는 질문마다 후보가 달라도 같은 view 가 반복해서 나오므로 질문 캐시보다 크게 잡는다

    def __init__(self, embed_fn: Callable[[str], Sequence[float]], model_name: str):
        self._embed = embed_fn
        self._model_name = model_name
        self._query_cache: dict[str, np.ndarray] = {}   # 같은 문장을 또 임베딩하지 않으려는 캐시
        self._view_cache: dict[tuple[str, int], np.ndarray] = {}   # (view id, 텍스트 해시) -> 정규화된 벡터. 임베딩은 API 비용이 들어서 view 마다 한 번만 한다
        self._cache_lock = threading.Lock()             # 캐시는 여러 요청이 같이 쓰는 공유 상태라서 잠금이 필요하다 (두 캐시가 같은 잠금을 쓴다)

    @property
    def signature(self) -> str:
        return f"dense:{self._model_name}"

    def _embed_query(self, query: str) -> np.ndarray:
        with self._cache_lock:                          # 캐시를 읽는 동안 다른 스레드가 clear() 하지 못하게 막는다
            cached = self._query_cache.get(query)
        if cached is not None:
            return cached
        vec = _l2_normalize(np.asarray(self._embed(query), dtype=np.float32))   # API 호출은 잠금 밖에서 한다 (오래 걸려서 다른 요청을 막지 않게)
        with self._cache_lock:
            if len(self._query_cache) >= self._CACHE_LIMIT:
                self._query_cache.clear()               # 단순하게 가득 차면 비운다 (필요해지면 LRU 로 교체)
            self._query_cache[query] = vec
        return vec                                      # 캐시에서 다시 꺼내지 않고 지역 변수를 돌려준다 (그 사이 clear() 되어도 안전)

    def _embed_view(self, record: Record) -> np.ndarray:
        """view 하나의 lexical_text 를 임베딩해서 길이 1짜리 벡터로 돌려준다. 이미 했으면 캐시에서 꺼낸다."""
        key = (record.id, hash(record.lexical_text))    # 텍스트가 바뀌면 해시도 바뀌어서, 옛 벡터를 잘못 쓰는 일을 막는다
        with self._cache_lock:                          # 캐시를 읽는 동안만 잠근다
            cached = self._view_cache.get(key)
        if cached is not None:
            return cached
        vec = _l2_normalize(np.asarray(self._embed(record.lexical_text), dtype=np.float32))   # API 호출은 잠금 밖에서 한다
        with self._cache_lock:
            if len(self._view_cache) >= self._VIEW_CACHE_LIMIT:
                self._view_cache.clear()                # 단순하게 가득 차면 비운다
            self._view_cache[key] = vec
        return vec

    def build(self, records: list[Record]) -> _DenseIndex:
        """view 들의 lexical_text 를 임베딩해서 (view 수, 차원) 행렬로 쌓는다. 질문마다 호출되지만 캐시 덕분에 처음 보는 view 만 API 를 부른다."""
        if not records:
            return _DenseIndex([], np.zeros((0, 0), dtype=np.float32))
        matrix = np.vstack([self._embed_view(r) for r in records])    # 벡터 여러 개를 위아래로 쌓아 2차원 행렬로 만든다
        return _DenseIndex([r.id for r in records], matrix)

    def search(self, index: _DenseIndex, query: str, k: int) -> list[Candidate]:
        if not index.ids:
            return []
        qv = self._embed_query(query)
        sims = index.matrix @ qv                        # 행렬 x 벡터 = view 마다 질문과의 코사인 유사도 (둘 다 길이 1로 정규화돼 있어서 내적이 곧 코사인)
        out: list[Candidate] = []
        for i in np.argsort(-sims):                     # 유사도가 높은 순서로 view 번호를 훑는다
            i = int(i)
            out.append(Candidate(index.ids[i], float(sims[i]), rank=len(out) + 1))
            if len(out) >= k:
                break
        return out


def rrf_fuse(ranked_lists: list[tuple[float, list[str]]], rrf_k: int = 60) -> dict[str, float]:
    """ranked_lists: [(가중치, [1등 id, 2등 id, ...]), ...]  ->  {id: 융합 점수}"""
    scores: dict[str, float] = {}
    for weight, ids in ranked_lists:
        for rank, doc_id in enumerate(ids, start=1):           
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (rrf_k + rank)
    return scores


class Searcher:

    def __init__(self, retrievers: list[Retriever], config: Optional[SearchConfig] = None):
        self.retrievers = retrievers
        self.config = config or SearchConfig()

    def _build_queries(self, bundle: QueryBundle) -> list[tuple[str, float]]:
        cfg = self.config
        pairs = [(bundle.rewritten, cfg.weight_rewritten)]
        pairs += [(s, cfg.weight_sub_question) for s in bundle.sub_questions]
        pairs.append((bundle.original, cfg.weight_original))
        merged: dict[str, float] = {}
        for text, w in pairs:
            text = (text or "").strip()
            if text:                                              
                merged[text] = max(merged.get(text, 0.0), w)
        return list(merged.items())

    def search(self, views: Optional[list[Record]], bundle: QueryBundle, top_k: Optional[int] = None) -> SearchResult:
        """views: view 모듈이 넘긴 후보. None 이거나 비어 있으면 검색하지 않고 빈 결과를 돌려준다.
        top_k: None 이면 설정값을 쓴다. 0 이하는 호출 실수로 보고 ValueError."""
        cfg = self.config
        top_k = cfg.top_k if top_k is None else top_k
        if top_k <= 0:
            raise ValueError(f"top_k 는 1 이상이어야 한다: {top_k}")
        active = [r for r in self.retrievers if r.name in cfg.retrievers]
        timing: dict[str, float] = {}
        t_total = time.perf_counter()
        queries = self._build_queries(bundle)

        if not views:
            return SearchResult(hits=[], debug={
                "retrievers": [r.signature for r in active], "n_views": 0, "empty_views": True,
                "queries": [{"text": q, "weight": w} for q, w in queries],
            })
        by_id = {v.id: v for v in views}

        t = time.perf_counter()
        indexes = {r.name: r.build(views) for r in active}
        timing["index_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        ranked_lists: list[tuple[float, list[str]]] = []
        per_retriever: dict[str, dict] = {}
        for text, weight in queries:
            for r in active:
                cands = r.search(indexes[r.name], text, cfg.pool_size)
                ranked_lists.append((weight, [c.id for c in cands]))
                for c in cands:
                    slot = per_retriever.setdefault(c.id, {})
                    if r.name not in slot or c.rank < slot[r.name]["rank"]:
                        slot[r.name] = {"score": c.score, "rank": c.rank}
        timing["retrieve_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        fused = rrf_fuse(ranked_lists, cfg.rrf_k)
        ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
        timing["fuse_ms"] = (time.perf_counter() - t) * 1000

        hits = []
        for rank, (doc_id, score) in enumerate(ordered[:top_k], start=1):
            rec = by_id[doc_id]
            hits.append(Hit(
                id=doc_id, rank=rank, final_score=round(score, 6),
                scores={r.name: per_retriever.get(doc_id, {}).get(r.name) for r in active},   # 후보에 없으면 None
                doc_type=rec.doc_type, parent_id=rec.parent_id, metadata=rec.metadata, source=rec.source,
                table=rec.table,
            ))

        timing["total_ms"] = (time.perf_counter() - t_total) * 1000
        debug = {
            "retrievers": [r.signature for r in active],
            "n_views": len(views),
            "config": {"top_k": top_k, "pool_size": cfg.pool_size, "rrf_k": cfg.rrf_k},
            "queries": [{"text": q, "weight": w} for q, w in queries],
            "latency_ms": {k: round(v, 2) for k, v in timing.items()},
        }
        return SearchResult(hits=hits, debug=debug)
