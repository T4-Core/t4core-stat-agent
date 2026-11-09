"""[NEW v4] 검색 실험 구성 요소의 공통 모양 (Protocol) — 구현은 corpus·tokenizers·embedders·retrievers·rerankers

구성 요소를 갈아 끼울 때 지켜야 할 것만 적는다. 새 구현은 이 모양만 맞추고 factory.register 로 이름을 붙이면
YAML 구성(configs/retrieval/*.yaml)에서 바로 쓸 수 있다.

  Corpus     문서 목록 (표 하나 = 문서 하나). id = tbl_id
  Tokenizer  문장 → 토큰 (BM25 용)
  Embedder   문장들 → 정규화된 벡터 (질의·문서 앞머리(prefix) 를 따로 둘 수 있음)
  Retriever  질의 → 전체 문서에서 상위 k  [(문서 번호, 점수)]
  Reranker   질의 + 후보 목록 → 다시 줄 세운 후보 목록 (후보 수를 줄일 수 있음)

후보(Candidate) 는 dict 하나. 기존 table_search.search 결과와 같은 키(tbl_id·rank·score·bm25_rank·bm25·dense·
unmet·cover·cost)를 쓰고, 단계별 기록은 stages[단계 이름] = {rank, score} 에 쌓는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass
class Doc:
    id: str                        # tbl_id
    text: str                      # 검색에 쓰는 설명문
    meta: dict = field(default_factory=dict)   # tbl_nm · survey_nm · selected … (출력·화면용)


@runtime_checkable
class Corpus(Protocol):
    name: str

    def docs(self) -> list[Doc]: ...

    def signature(self) -> str:
        """내용이 바뀌면 달라지는 문자열 (토큰·임베딩 캐시 키)"""
        ...


@runtime_checkable
class Tokenizer(Protocol):
    id: str                        # 캐시 키 (설정이 다르면 달라야 함)

    def __call__(self, text: str) -> list[str]: ...


@runtime_checkable
class Embedder(Protocol):
    id: str

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...

    def embed_docs(self, texts: list[str]) -> np.ndarray: ...


@runtime_checkable
class Retriever(Protocol):
    name: str

    def fit(self, corpus: Corpus) -> None: ...

    def search(self, query: str, k: int) -> list[tuple[int, float]]: ...


@runtime_checkable
class Reranker(Protocol):
    name: str

    def rerank(self, query: str, cands: list[dict], ctx: "SearchContext") -> list[dict]: ...


@dataclass
class SearchContext:
    """재정렬 단계가 함께 보는 것: 슬롯 조건, 코퍼스, 단계 기록"""
    filters: dict | None
    corpus: Any
    docs_by_id: dict
    top_k: int = 10
    notes: list = field(default_factory=list)


def mark(cands: list[dict], stage: str, key: str = "score") -> list[dict]:
    """현재 순서를 rank 로 매기고 stages[stage] 에 남김"""
    for r, c in enumerate(cands, 1):
        c["rank"] = r
        c.setdefault("stages", {})[stage] = {"rank": r, "score": c.get(key)}
    return cands
