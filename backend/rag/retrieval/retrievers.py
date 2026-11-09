"""[NEW v4] 1단계 검색기 — 코퍼스 전체에서 상위 k  →  [(문서 번호, 점수)]

  bm25   rank_bm25 (okapi 기본 | plus | l). tokenizer 는 tokenizers.py 의 아무것이나
         문서 토큰 캐시: 코퍼스가 주는 색인 토큰(table_text + kiwi:table) → 디스크 캐시 → 새로 계산
  dense  임베더로 코퍼스 전체를 벡터화(디스크 캐시) 후 코사인 상위 k
         (baseline 처럼 'BM25 후보만 dense 로 다시 줄 세우기' 는 rerankers.embed 가 맡음)
"""
from __future__ import annotations

import hashlib
import pickle
import time

import numpy as np

from backend.rag.retrieval.embedders import LAB_DIR


def _cache_file(kind, *keys):
    h = hashlib.sha1("|".join(map(str, keys)).encode()).hexdigest()[:16]
    return LAB_DIR / kind / f"{h}.pkl"


class BM25Retriever:
    def __init__(self, tokenizer, name="bm25", variant="okapi", k1=1.5, b=0.75, epsilon=0.25, delta=None,
                 cache=True):
        self.name, self.tok, self.variant = name, tokenizer, variant
        self.k1, self.b, self.epsilon, self.delta, self.cache = k1, b, epsilon, delta, cache
        self.fit_info = {}

    def _doc_tokens(self, corpus):
        docs = corpus.docs()
        toks = corpus.cached_tokens(self.tok.id) if hasattr(corpus, "cached_tokens") else None
        if toks is not None and len(toks) == len(docs):
            self.fit_info["tokens"] = "corpus index"
            return toks
        f = _cache_file("tokens", corpus.signature(), self.tok.id)
        if self.cache and f.exists():
            self.fit_info["tokens"] = "disk cache"
            return pickle.loads(f.read_bytes())
        t0 = time.time()
        toks = [self.tok(d.text) for d in docs]
        self.fit_info.update(tokens="computed", tokenize_seconds=round(time.time() - t0, 2))
        if self.cache:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(toks))
        return toks

    def fit(self, corpus):
        import rank_bm25
        toks = self._doc_tokens(corpus)
        if self.variant == "okapi":
            self.bm25 = rank_bm25.BM25Okapi(toks, k1=self.k1, b=self.b, epsilon=self.epsilon)
        elif self.variant == "plus":
            self.bm25 = rank_bm25.BM25Plus(toks, k1=self.k1, b=self.b, delta=self.delta or 1.0)
        elif self.variant == "l":
            self.bm25 = rank_bm25.BM25L(toks, k1=self.k1, b=self.b, delta=self.delta or 0.5)
        else:
            raise ValueError(f"bm25 variant 는 okapi | plus | l: {self.variant}")
        self.n = len(toks)
        self.fit_info["n_docs"] = self.n
        return self

    def search(self, query, k):
        toks = self.tok(query)
        self.last_query_tokens = toks
        scores = self.bm25.get_scores(toks) if toks else np.zeros(self.n)
        return [(int(i), float(scores[i])) for i in np.argsort(-scores)[:k]]   # table_search 와 같은 정렬


class DenseRetriever:
    def __init__(self, embedder, name="dense", cache=True):
        self.name, self.emb, self.cache = name, embedder, cache
        self.fit_info = {}

    def fit(self, corpus):
        docs = corpus.docs()
        f = _cache_file("dense", corpus.signature(), self.emb.id, getattr(self.emb, "doc_prefix", ""))
        if self.cache and f.exists():
            self.M = pickle.loads(f.read_bytes())
            self.fit_info["vectors"] = "disk cache"
        else:
            t0 = time.time()
            self.M = self.emb.embed_docs([d.text for d in docs])
            self.fit_info.update(vectors="computed", embed_seconds=round(time.time() - t0, 2))
            if self.cache:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(pickle.dumps(self.M))
        self.fit_info["n_docs"] = len(docs)
        return self

    def search(self, query, k):
        q = self.emb.embed_queries([query])[0]
        sims = self.M @ q
        return [(int(i), float(sims[i])) for i in np.argsort(-sims)[:k]]
