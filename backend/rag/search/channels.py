"""검색 채널 — 표 전체(약 1,100개)에 점수를 매긴다. 후보를 50개로 먼저 자르지 않는다

  lex     Kiwi 형태소 BM25 (기존 표 설명문 그대로 — baseline 1단계와 같은 색인)
  ngram   글자 2·3-gram BM25 (표 이름·항목·분류 값) — 형태소 분석이 쪼개는 복합어('보증부월세'·'시도간전출')에 강함
  title   질문 안에 표 이름이 (거의) 그대로 들어 있는가 — 표 이름 글자쌍 중 질문에 있는 비율 (IDF 가중)
  value   값 연결: 질문 속 표현이 어느 표의 '항목·분류 값·분류 이름' 인가 (드문 값일수록 큰 점수)
          '유학생'·'국제결혼 이주자'·'슬레이트'·'옥탑' 처럼 표를 사실상 지정하는 단어를 놓치지 않기 위함
  dense   (선택) 문서 임베딩 전체 코사인
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from backend.rag.search.facets import facet_text
from backend.rag.search.text import TOTALS, bigrams, idf, norm, variants

KIND_W = {"item": 1.0, "dim": 0.8, "obj": 0.5}
MAX_LEN = 24


class _MiniCorpus:
    """BM25Retriever.fit 이 받는 모양 (docs · signature)"""

    def __init__(self, docs, sig):
        self._docs, self._sig = docs, sig

    def docs(self):
        return self._docs

    def signature(self):
        return self._sig


class TitleChannel:
    def __init__(self, facets):
        self.n = len(facets)
        self.grams = [bigrams(norm(f.tbl_nm)) for f in facets]
        df = defaultdict(int)
        for g in self.grams:
            for b in g:
                df[b] += 1
        self.idf = {b: idf(d, self.n) for b, d in df.items()}
        self.total = np.array([sum(self.idf[b] for b in g) or 1.0 for g in self.grams])
        self.post = defaultdict(list)
        for i, g in enumerate(self.grams):
            for b in g:
                self.post[b].append(i)

    def scores(self, link: str, min_cover=0.5):
        """표 이름 글자쌍의 IDF 가중 포함 비율 × log(1 + 맞은 IDF 합). 절반 미만으로 겹치면 0"""
        hit = np.zeros(self.n)
        for b in bigrams(link):
            w = self.idf.get(b)
            if w and "|" not in b:
                for i in self.post[b]:
                    hit[i] += w
        cover = hit / self.total
        return np.where(cover >= min_cover, cover * np.log1p(hit), 0.0)


class ValueChannel:
    def __init__(self, facets):
        self.n = len(facets)
        table = defaultdict(dict)                         # 표현(norm) → {표 번호: 가중치}
        self._cohort = []                                 # 출생연도(코호트) 분류가 있는 표
        for i, f in enumerate(facets):
            def add(name, w):
                for v in variants(name):
                    if 2 <= len(v) <= MAX_LEN and table[v].get(i, 0) < w:
                        table[v][i] = w
            for n in f.items:
                add(n, KIND_W["item"])
            for obj, kind, names in f.dims:
                add(obj, KIND_W["obj"])
                for n in names:
                    if norm(n) not in TOTALS:
                        add(n, KIND_W["dim"])
            if any(re.search(r"생년|출생\s*연도|코호트", obj) for obj, _, _ in f.dims):
                self._cohort.append(i)
        self.table = dict(table)
        self.idf = {k: idf(len(v), self.n) for k, v in self.table.items()}

    def link(self, link: str):
        """질문에서 사전 표현 찾기 (긴 것 먼저, 겹치지 않게) → [표현]"""
        out, i = [], 0
        while i < len(link):
            for L in range(min(MAX_LEN, len(link) - i), 1, -1):
                key = link[i:i + L]
                if key in self.table:
                    out.append(key)
                    i += L
                    break
            else:
                i += 1
        return list(dict.fromkeys(out))

    def scores(self, link: str, cohort=False):
        s = np.zeros(self.n)
        found = self.link(link)
        for key in found:
            w = self.idf[key] * (0.6 if len(key) == 2 else 1.0)   # 두 글자 표현은 우연히 겹치기 쉬움
            for i, kw in self.table[key].items():
                s[i] += w * kw
        if cohort and self._cohort:                        # '1983년생' → 출생연도 분류가 있는 표
            s[self._cohort] += idf(len(self._cohort), self.n)
        return s, found


class Channels:
    def __init__(self, corpus, facets, embedder=None, log=None):
        from backend.rag.retrieval.interfaces import Doc
        from backend.rag.retrieval.retrievers import BM25Retriever, DenseRetriever
        from backend.rag.retrieval.tokenizers import CharNgramTokenizer, KiwiTokenizer
        self.docs = corpus.docs()
        self.facets = [facets[d.id] for d in self.docs]
        self.n = len(self.docs)
        self.lex = BM25Retriever(KiwiTokenizer(), name="lex").fit(corpus)
        mini = _MiniCorpus([Doc(d.id, facet_text(f)) for d, f in zip(self.docs, self.facets)], corpus.signature() + ":facet")
        self.ngram = BM25Retriever(CharNgramTokenizer((2, 3), keep_words=False), name="ngram", cache=False).fit(mini)
        self.title = TitleChannel(self.facets)
        self.value = ValueChannel(self.facets)
        self.dense = DenseRetriever(embedder, name="dense").fit(corpus) if embedder is not None else None
        # 분류마다 '그 분류를 쓴다'고 볼 표현 집합 (분류 이름·값의 표기 변형) — 질문이 건드리지 않은 분류 수를 세는 데 씀
        self.dim_keys = [[(k, {x for n in [obj, *names[:300]] for x in variants(n)}) for obj, k, names in f.dims]
                         for f in self.facets]
        self.region_dict = {r for f in self.facets if f.regions_full for r in f.regions} or None
        if log:
            log(f"[v5] 채널 준비: 표 {self.n} · 값 사전 {len(self.value.table)}개 표현 · "
                f"지역 사전 {len(self.region_dict or [])} · dense {'있음' if self.dense else '없음'}")

    def _bm25(self, r, text):
        toks = r.tok(text)
        return np.asarray(r.bm25.get_scores(toks), dtype=float) if toks else np.zeros(self.n)

    def score(self, lex_text, link, cohort=False, dense_text=None):
        """문장 하나 → {채널: 점수 배열}, 찾은 값 표현"""
        val, found = self.value.scores(link, cohort)
        out = {"lex": self._bm25(self.lex, lex_text), "ngram": self._bm25(self.ngram, lex_text),
               "title": self.title.scores(link), "value": val}
        if self.dense is not None and dense_text:
            out["dense"] = np.asarray(self.dense.M @ self.dense.emb.embed_queries([dense_text])[0], dtype=float)
        return out, found


def ranks(scores, depth=200, floor=0.0):
    """점수 → 순위 (같은 점수는 같은 순위 — 이름이 같은 연도판 표들을 임의로 줄 세우지 않게). 0 이하·depth 밖은 0"""
    order = np.argsort(-scores, kind="stable")[:depth]
    r = np.zeros(len(scores))
    rank, prev = 0, None
    for pos, i in enumerate(order, 1):
        if scores[i] <= floor:
            break
        if prev is None or scores[i] < prev - 1e-12:
            rank, prev = pos, scores[i]
        r[i] = rank
    return r
