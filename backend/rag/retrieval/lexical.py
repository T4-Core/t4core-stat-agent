"""
Kiwi 형태소 기반 BM25 토큰화  (구 kosis_rag_qa.py tokenize 를 그대로 옮김)

  tokenize(text)        하이브리드 인덱스(records.jsonl)용: 기본 형태소 + 복합어 분해 + 지역명·비율 용어 축약형
  table_tokenize(text)  View 모듈 표 색인용 (backend/rag/ingestion/table_text.py 의 tokenize, 축약형 없음) — 다시 내보냄

BM25 검색 자체는 fusion.Index.search_bm25 / table_search.search 1단계에 있음 (추후 이 파일로 모을 대상)
"""
import re

from backend.rag.ingestion.table_text import tokenize as table_tokenize  # noqa: F401  [NEW] 한 곳에서 찾을 수 있게 다시 내보냄

TOKEN_TAGS = ("NN", "SL", "SN", "XR", "VV", "VA")     # kosis_views.py --kiwi 와 같은 기준

# ─── 아래는 구 kosis_rag_qa.py 246~272행 를 그대로 옮긴 코드 ───
# 토큰 -bm25 용
_kiwi = None


REGION_SUFFIX = re.compile(r"(특별자치시|특별자치도|특별자치|특별시|광역시|자치시|자치도|도)$")


def tokenize(text):
    """BM25 토큰: 기본 형태소 + 복합어 분해 + 지역명·비율 용어 축약형
    예) 서울특별시 → 서울특별시, 서울 / 경기도 → 경기도, 경기 / 합계출산율 → 합계출산율, 출산율
    문서와 질의에 똑같이 적용해야 하므로 인덱싱 때도 bm25_tokens 대신 이 함수로 다시 토큰화합니다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    text = str(text)
    toks = [t.form for t in _kiwi.tokenize(text) if t.tag.startswith(TOKEN_TAGS)]
    extra = [t.form for t in _kiwi.tokenize(text, split_complex=True) if t.tag.startswith(TOKEN_TAGS)]
    for t in toks:
        if len(t) >= 3 and REGION_SUFFIX.search(t):
            stem = REGION_SUFFIX.sub("", t)
            if len(stem) >= 2:
                extra.append(stem)
        if len(t) >= 4 and t[-1] in "율률":
            extra.append(t[-3:])
    return toks + [e for e in extra if e not in toks]

