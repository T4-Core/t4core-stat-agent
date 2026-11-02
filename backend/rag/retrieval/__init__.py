"""[파트 3] 검색

  table_search.py (구 view_model/services/search.py)   표 메타데이터 검색: BM25 → bge-m3 재정렬   ← 통합 파이프라인이 씀
  dense.py        (구 view_model/services/embedding.py) CLOVA 임베딩 v2(bge-m3) 클라이언트 + 캐시
  lexical.py      (구 kosis_rag_qa.py tokenize)        Kiwi 형태소 토큰
  fusion.py       (구 kosis_rag_qa.py Index)           records.jsonl 하이브리드 BM25 + Dense → RRF (legacy)
  reranker.py     [NEW, 자리만]                        Cross-encoder 리랭커 (아직 없음)
"""
