"""[NEW v4] 재정렬 단계 — 후보 목록을 받아 다시 줄 세움 (구성의 rerank: 목록 순서대로 이어 붙임 = 체인)

  none           그대로 (top_n 만 자름)
  condition      resolve.rerank: 슬롯 조건(시점·지역·성별·연령·지표)을 못 맞춘 정도(cost)가 적은 표부터
                 filters 가 None 이면 순서를 바꾸지 않고 top_n 만 자름 (= table_search.search 의 filters 없는 경우)
  embed          후보 설명문만 임베딩해서 코사인 순으로 (= table_search 2단계 dense)
                 respect_cost: true 면 (cost, -dense) 순 — 앞 단계 condition 의 판단을 우선
  cross_encoder  (질의, 설명문) 쌍 점수 — sentence-transformers CrossEncoder (예: BAAI/bge-reranker-v2-m3,
                 dragonkue/bge-reranker-v2-m3-ko, Dongjin-kr/ko-reranker). CPU·GPU 자동
  rrf_stages     앞 단계들의 순위를 RRF 로 다시 합침 (예: bm25 순위 + embed 순위 + cross_encoder 순위 앙상블)

공통: top_n (남길 후보 수. 'top_k' = 검색 호출의 top_k), name (단계 이름 — 같은 type 을 두 번 쓸 때 구분)
"""
from __future__ import annotations

import numpy as np

from backend.rag.retrieval.embedders import resolve_device


def _cost_key(c):
    return c.get("cost", 0)


def _cut(cands, top_n, ctx=None):
    """top_n: 숫자 | 'top_k'(검색 호출의 top_k) | None(자르지 않음)"""
    if top_n == "top_k":
        top_n = getattr(ctx, "top_k", None)
    return cands[:int(top_n)] if top_n else cands


class NoneReranker:
    def __init__(self, top_n=None, name="none"):
        self.top_n, self.name = top_n, name

    def rerank(self, query, cands, ctx):
        return _cut(cands, self.top_n, ctx)


class ConditionReranker:
    def __init__(self, top_n=None, name="condition"):
        self.top_n, self.name = top_n, name

    def rerank(self, query, cands, ctx):
        if ctx.filters is None:
            return _cut(cands, self.top_n, ctx)
        from backend.rag.ingestion.resolve import rerank
        out = rerank(cands, ctx.filters)          # score 는 앞 단계 값 그대로 두고 cost·unmet·cover 를 붙임
        return _cut(out, self.top_n, ctx)


class EmbedReranker:
    def __init__(self, embedder, top_n=None, respect_cost=True, name="embed"):
        self.emb, self.top_n, self.respect_cost, self.name = embedder, top_n, respect_cost, name

    def rerank(self, query, cands, ctx):
        if not cands:
            return cands
        vecs = self.emb.embed_docs([ctx.docs_by_id[c["tbl_id"]].text for c in cands])
        sims = vecs @ self.emb.embed_queries([query])[0]
        for c, s in zip(cands, sims):
            c["dense"] = round(float(s), 4)
            c["score"] = c["dense"]
        order = sorted(range(len(cands)), key=lambda j: ((_cost_key(cands[j]) if self.respect_cost else 0), -sims[j]))
        return _cut([cands[j] for j in order], self.top_n, ctx)


class CrossEncoderReranker:
    def __init__(self, model="BAAI/bge-reranker-v2-m3", top_n=None, max_length=512, batch_size=16, device="auto",
                 respect_cost=False, activation="sigmoid", trust_remote_code=False, name="cross_encoder"):
        self.model_name, self.top_n, self.max_length, self.batch_size = model, top_n, max_length, batch_size
        self.device_req, self.respect_cost, self.activation = device, respect_cost, activation
        self.trust_remote_code, self.name = trust_remote_code, name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise ImportError("cross_encoder 리랭커는 sentence-transformers 가 필요합니다: "
                                  "pip install sentence-transformers (torch 는 CPU/GPU 에 맞게)") from e
            self.device = resolve_device(self.device_req)
            self._model = CrossEncoder(self.model_name, max_length=self.max_length, device=self.device,
                                       trust_remote_code=self.trust_remote_code)
        return self._model

    def rerank(self, query, cands, ctx):
        if not cands:
            return cands
        pairs = [(query, ctx.docs_by_id[c["tbl_id"]].text) for c in cands]
        s = np.asarray(self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False), dtype=float)
        if s.ndim > 1:
            s = s[:, -1]
        if self.activation == "sigmoid":
            s = 1 / (1 + np.exp(-s))
        for c, v in zip(cands, s):
            c["ce"] = round(float(v), 4)
            c["score"] = c["ce"]
        order = sorted(range(len(cands)), key=lambda j: ((_cost_key(cands[j]) if self.respect_cost else 0), -s[j]))
        return _cut([cands[j] for j in order], self.top_n, ctx)


class RrfStagesReranker:
    """앞 단계 순위(stages[이름].rank)를 RRF 로 합침. stages 를 비우면 기록된 모든 단계"""

    def __init__(self, stages=None, k=60, weights=None, top_n=None, name="rrf_stages"):
        self.stages, self.k, self.weights, self.top_n, self.name = stages, k, weights or {}, top_n, name

    def rerank(self, query, cands, ctx):
        names = self.stages or sorted({s for c in cands for s in c.get("stages", {})})
        worst = len(cands) + 1
        for c in cands:
            st = c.get("stages", {})
            c["score"] = round(sum(float(self.weights.get(n, 1.0)) / (self.k + (st.get(n) or {}).get("rank", worst))
                                   for n in names), 6)
        return _cut(sorted(cands, key=lambda c: -c["score"]), self.top_n, ctx)
