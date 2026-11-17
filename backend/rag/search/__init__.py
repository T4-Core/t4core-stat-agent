"""표 검색 — 다채널 점수 + 표 구조 계수 (engine.py)

  from backend.rag.search import get_search, search_fn
  s = get_search()
  s.search("혼인건수 증감", filters, 10, question="인천에서 1973년에 비해 1979년에 결혼한 커플 수가 얼마나 증가했나요?")
  run_query(view_bundle, search_fn=search_fn(dense="hash"))      # View 단계에 다른 설정으로 끼우기

  engine.py     TableSearch · get_search · search_fn
  index.py      코퍼스 · 토크나이저 · BM25 · dense · 임베더
  channels.py   채널 점수 (dense · value · title · lex · ngram)
  facets.py     표 구조 (실제 수록 연도 · 분류 값 · 시군구 이름 …)
  query.py      질문 원문에서 조건 읽기 · 일상어 → 통계어 (configs/colloquial.yaml)
  resolve.py    검색 문장 다듬기 · 표 메타 기준 못 맞춘 조건(unmet)
  siblings.py   형제 표 해소 ((계)/(남)/(여) · 전국/시도/시군구판 · 연도판)
  concepts.py   개념 카탈로그 (같은 값을 주는 표 묶음)
  llm_rerank.py (선택) LLM 재정렬
  tuning/       골든셋 비교 · 가중치 맞추기 · 일상어 사전 캐내기
"""
from backend.rag.search.engine import TableSearch, get_search, search_fn

__all__ = ["TableSearch", "get_search", "search_fn"]
