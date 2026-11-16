"""backend.rag.search — 다채널 표 라우팅 검색 (README.md)

  from backend.rag.search import get_search, search_fn
  s = get_search("v5")                                   # 표 설명문(table_text) 기반
  s.search("혼인건수 증감", filters, 10, question="인천에서 1973년에 비해 1979년에 결혼한 커플 수가 얼마나 증가했나요?")
  views.run_query(bundle, search_fn=search_fn("v5"))     # 기존 View 단계에 끼우기
"""
from backend.rag.search.router import METHODS, V5Search, get_search, search_fn  # noqa: F401
