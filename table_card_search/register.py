"""기존 검색 구성 공장에 카드용 부품 등록 (factory.register 사용 — backend 파일은 그대로)"""
from __future__ import annotations

_done = False


def register_all():
    global _done
    if _done:
        return
    from backend.rag.retrieval.factory import register
    from table_card_search.cards import ExpendCardCorpus, TableCardCorpus
    from table_card_search.rerankers import CardConditionReranker, CardEmbedReranker
    register("corpus", "table_card")(TableCardCorpus)
    register("corpus", "table_card_expend")(ExpendCardCorpus)
    register("reranker", "card_condition")(CardConditionReranker)
    register("reranker", "card_embed")(CardEmbedReranker)
    _done = True
