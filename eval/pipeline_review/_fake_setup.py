"""[NEW v4] review_v4.ipynb 의 V4_NB_FAKE=1 용 — 가짜 KOSIS 데이터 + HCX 대역 + 질문 파일(재작성 80문항 원문)
실제 데이터로 돌릴 때는 쓰이지 않음. backend 를 import 하기 전에 setup() 을 불러야 경로 환경변수가 반영됨"""
import csv
import json
import os
import tempfile
from pathlib import Path


def setup(root):
    from tests import fake_kosis as fk
    from tests.v4.test_retrieval_lab import _extra_tables
    from tests.v4.test_view_v4 import build_conflict_data
    tmp = Path(tempfile.mkdtemp())
    fk.TABLES[:] = fk.TABLES + _extra_tables()
    build_conflict_data(tmp / "storage" / "kosis_data")
    for k in ("KOSIS_DATA_DIR", "KOSIS_DATA", "VIEW_OUT_DIR", "TABLE_INDEX_DIR", "VIEW_EMBED_CACHE", "CSV_INDEX_DIR",
              "RUNS_DIR", "EVAL_RUNS_DIR"):
        os.environ[k] = ""
    os.environ.update(STORAGE_DIR=str(tmp / "storage"), HCX_API_KEY="test", TEST_DATA_DIR=str(tmp / "test_data"))
    (tmp / "test_data").mkdir()
    qs = [b["original"] for b in json.loads((Path(root) / "eval/query_rewrite/outputs/query_bundles.json").read_text(encoding="utf-8"))]
    with (tmp / "test_data" / "kosis_rag_eval_80_queries.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "question"])
        w.writerows([[f"Q{i:03d}", q] for i, q in enumerate(qs, 1)])
    import backend.core.llm as llm
    import backend.rag.retrieval.dense as dense
    llm._post, dense._post = fk.fake_hcx_post, fk.fake_dense_post
    from backend.rag.csv_index import build_index
    from backend.rag.ingestion import meta_profile, table_text
    meta_profile.build_all()
    table_text.build_index(progress=lambda m: None)
    build_index(scope="all", log=lambda m: None)
    print("가짜 데이터:", tmp)
    return tmp
