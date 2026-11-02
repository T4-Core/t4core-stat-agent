"""[파트 2] 수집·정규화·View 생성·인덱싱

  collector.py     (구 kosis_rag_builder.py)          KOSIS OpenAPI → catalog / meta / raw CSV
  view_builder.py  (구 kosis_views.py)                raw → processed parquet + records.jsonl (legacy 하이브리드 검색용)
  meta_profile.py  (구 view_model/services)           catalog + meta → meta_profiles.jsonl (표 탐색 범위)
  normalize.py     (구 view_model/services)           고른 표만 지연 정규화 → parquet + 프로필
  table_text.py    (구 view_model/services)           표 설명문 + BM25 토큰 색인
  build_view.py    (구 view_model/services)           표 + 슬롯 → View 카드(Record)
  views.py         (구 view_model/services)           QueryBundle → 검색 단위별 View 카드 (검색 + build_view)
  indexer.py       (구 kosis_rag_qa.py index 단계)     records.jsonl → BM25 + Dense 인덱스
"""
