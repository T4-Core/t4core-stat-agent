"""
카드용 재정렬 — 기존 재정렬기와 같은 계산, 읽는 데이터만 카드

  card_condition  기존 condition(= resolve.rerank) 과 같은 함수(unmet · period_cover · cost)로 비용을 매기고
                  (cost, 앞 단계 순서) 로 정렬. 프로필만 카드 문서(meta.profile)에서 읽음
  card_embed      기존 embed 재정렬과 같은 계산 (cos, respect_cost 면 (cost, -dense)). 임베딩할 글만 dense_text
"""
from __future__ import annotations

from backend.rag.retrieval.rerankers import EmbedReranker, _cost_key, _cut

MISSING = [{"slot": None, "dim": None, "type": "missing", "requested": None, "applied": None, "text": "카드 프로필 없음"}]


class CardConditionReranker:
    def __init__(self, top_n=None, name="card_condition"):
        self.top_n, self.name = top_n, name

    def rerank(self, query, cands, ctx):
        if ctx.filters is None:                   # [CHANGED 11-12] 슬롯이 없으면 top_k (table_search.search 의 filters 없는 경로와 같게)
            return _cut(cands, "top_k" if self.top_n is not None else None, ctx)
        from backend.rag.ingestion.resolve import cost, period_cover, unmet
        for c in cands:
            p = ctx.docs_by_id[c["tbl_id"]].meta.get("profile")
            c["unmet"] = unmet(p, ctx.filters) if p else list(MISSING)
            c["cover"] = round(period_cover(p, ctx.filters), 2) if p else 0.0
            c["cost"] = round(cost(c["unmet"], c["cover"]), 3)
        return _cut(sorted(cands, key=lambda c: c["cost"]), self.top_n, ctx)   # 안정 정렬 = resolve.rerank 와 같음


class CardEmbedReranker(EmbedReranker):
    def __init__(self, embedder=None, top_n=None, respect_cost=True, text_field="dense_text", name="card_embed"):
        if isinstance(embedder, dict) or embedder is None:
            from backend.rag.retrieval.factory import build_embedder
            embedder = build_embedder(embedder or {"type": "hcx_bge_m3"})
        super().__init__(embedder, top_n=top_n, respect_cost=respect_cost, name=name)
        self.text_field = text_field

    def rerank(self, query, cands, ctx):
        if not cands:
            return cands
        texts = [ctx.docs_by_id[c["tbl_id"]].meta.get(self.text_field) or ctx.docs_by_id[c["tbl_id"]].text
                 for c in cands]
        vecs = self.emb.embed_docs(texts)
        sims = vecs @ self.emb.embed_queries([query])[0]
        for c, s in zip(cands, sims):
            c["dense"] = round(float(s), 4)
            c["score"] = c["dense"]
        order = sorted(range(len(cands)), key=lambda j: ((_cost_key(cands[j]) if self.respect_cost else 0), -sims[j]))
        return _cut([cands[j] for j in order], self.top_n, ctx)
