"""table_card · table_card_expend 카드용 검색 — 기존 검색(backend.rag.retrieval)과 같은 단계, 읽는 데이터만 카드

import 하면 기존 검색 구성 공장(factory.REGISTRY)에 카드용 부품을 등록한다 (기존 파일 수정 없음)
  corpus    table_card · table_card_expend
  reranker  card_condition · card_embed
"""
from table_card_search.register import register_all

register_all()
