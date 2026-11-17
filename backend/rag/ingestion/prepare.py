"""준비 한 번에 — 메타 프로필 → 표 설명문 색인 → CSV 값 사전 (catalog·meta·raw 가 바뀌었을 때 다시)

  python -m backend.rag.ingestion.prepare [--workers 4] [--force]
  POST /api/v1/ingest/prepare
"""
import argparse
import sys


def prepare(log=print, workers=4, force=False):
    from backend.rag.csv_index import build_index as build_csv_index
    from backend.rag.ingestion.meta_profile import build_all
    from backend.rag.ingestion.table_text import build_index as build_table_index
    log("① 메타 프로필 (catalog.csv selected + meta/*.json)")
    meta = build_all()
    log(f"   → 표 {meta['n_tables']}개, 원본 없음 {meta['n_raw_missing']}개")
    log("② 표 설명문 + BM25 토큰 색인")
    index = build_table_index(progress=log)
    log("③ CSV 값 사전 (raw 폴더 전체, 바뀐 표만 다시 스캔)")
    csv = build_csv_index(scope="all", workers=workers, force=force, log=log)
    log("완료")
    return {"meta": meta, "index": index, "csv_index": {k: csv[k] for k in ("n_tables", "n_values", "n_errors") if k in csv}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingestion.prepare")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="CSV 값 사전을 원본이 같아도 다시 스캔")
    a = ap.parse_args()
    prepare(workers=a.workers, force=a.force)


if __name__ == "__main__":
    main()
