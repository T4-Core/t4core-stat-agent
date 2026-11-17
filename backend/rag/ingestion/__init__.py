"""수집 → 검색 준비

  collector.py     KOSIS OpenAPI → catalog.csv / meta/*.json / raw/*.csv
  meta_profile.py  catalog + meta → meta_profiles.jsonl (표 구조 요약)
  table_text.py    표 설명문 + BM25 토큰 색인
  normalize.py     raw CSV → 정규화 parquet + 프로필 (검색에서 처음 뽑힌 표만, 지연 정규화)
  prepare.py       준비 한 번에: 메타 프로필 → 표 색인 → CSV 값 사전
"""
