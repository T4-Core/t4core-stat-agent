"""[파트 3] 검색

  table_search.py (구 view_model/services/search.py)   표 메타데이터 검색: BM25 → bge-m3 재정렬   ← 통합 파이프라인이 씀
  dense.py        (구 view_model/services/embedding.py) CLOVA 임베딩 v2(bge-m3) 클라이언트 + 캐시
  lexical.py      (구 kosis_rag_qa.py tokenize)        Kiwi 형태소 토큰
  fusion.py       (구 kosis_rag_qa.py Index)           records.jsonl 하이브리드 BM25 + Dense → RRF (legacy)
                                                       [v4] fuse_rrf · fuse_weighted (실험 파이프라인용) 추가
  reranker.py     [NEW, 자리만]                        pass-through (실제 리랭커는 rerankers.py)

  [NEW v4] 검색 실험 (구성 YAML 로 갈아 끼우기 — docs/query_retrieval_v4/RETRIEVAL_LAB.md)
  interfaces.py   구성 요소 모양 (Corpus · Tokenizer · Embedder · Retriever · Reranker)
  corpus.py       table_text(현재) · csv_index(CSV 값 사전 설명문) · external(정제 데이터 파일)
  tokenizers.py   kiwi(table·hybrid·+사전) · okt/mecab · char_ngram · whitespace
  embedders.py    hcx_bge_m3(현재) · sentence_transformers(로컬 HF, CPU/GPU) · hash(구조 확인용)
  retrievers.py   bm25(okapi·plus·l) · dense(코퍼스 전체)
  rerankers.py    none · condition(resolve.rerank) · embed(후보만 dense) · cross_encoder · rrf_stages
  factory.py      configs/retrieval/<이름>.yaml → RetrievalPipeline (extends · overrides · register)
  pipeline.py     RetrievalPipeline.search → 후보 + 단계별 순위·점수 + trace. search_compat = table_search 모양
  lab.py          질의 묶음 × 구성들 → 나란히 비교 보고서(HTML·MD) + 사람 판정표(review.csv) → 점수
"""
