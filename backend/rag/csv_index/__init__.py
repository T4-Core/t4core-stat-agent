"""[NEW v4] 원본 CSV 값 사전 — 표마다 열 머리·분류 값·항목·단위·기간·주석을 스캔해 '값 → 표' 역색인으로

  source.py   DataSource 인터페이스 (KOSIS raw CSV / 추후 정제 데이터)
  scanner.py  원본 CSV 1개 → TableScan
  store.py    build_index · load_index · CsvIndex(find·contains·scan_text·values·years·table)

  python -m backend.rag.csv_index build [--scope all|selected] [--limit N] [--force] [--workers 4]
  python -m backend.rag.csv_index find 출생아 수
  python -m backend.rag.csv_index values 지역
"""
from backend.rag.csv_index.source import DataSource, KosisRawCsvSource, TableRef, get_source
from backend.rag.csv_index.store import CsvIndex, build_index, load_index, norm, variants

__all__ = ["DataSource", "KosisRawCsvSource", "TableRef", "get_source", "CsvIndex", "build_index", "load_index",
           "norm", "variants"]
