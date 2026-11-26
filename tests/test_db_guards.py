"""AWS 배포(PostgreSQL 모드)가 깨지지 않게 지키는 시험 — DB 없이 돈다 (보통 pytest · CI 에서 항상)

팀원이 RAG · 에이전트 코드를 고칠 때 아래 중 하나를 어기면 여기서 바로 실패하고, 메시지가 고칠 곳을 알려 준다.

  1. 정규화 parquet 의 열(이름·종류)이 바뀌면 → PostgreSQL 스키마(backend/db/sql/main)와 stat_store 열 목록도 같이
  2. 통계값 parquet 를 read_parquet 로 바로 읽지 말 것 → backend.data_engine.stat_store.relation(con, prof, where)
  3. prepare 가 storage/ 에 새 산출물을 만들면 → 배포 묶음에 자동으로 들어가는지 (제외 목록에 걸리지 않는지)
"""
import re
from pathlib import Path

import pytest

from tests import fake_kosis

ROOT = Path(__file__).resolve().parent.parent

# 통계값 parquet 를 직접 읽어도 되는 곳 (쓰는 쪽 · 저장소 계층 · 비교 도구)
PARQUET_OK = {
    "backend/rag/ingestion/normalize.py",      # parquet 를 만들고 프로필을 집계하는 쪽
    "backend/data_engine/stat_store.py",       # parquet ↔ PostgreSQL 을 고르는 곳
    "backend/data_engine/duckdb_client.py",    # stat_store 의 parquet 분기
    "backend/db/stats.py",                     # parquet → PostgreSQL 적재 · 비교
    "backend/rag/csv_index/store.py",          # CSV 값 사전(values.parquet) — 통계값 아님
}
DIRECT = re.compile(r"read_parquet\(|VIEW_OUT_DIR\s*/\s*prof(?:ile)?\[\s*[\"']file[\"']\s*\]")


def test_no_direct_stat_parquet_reads():
    bad = []
    for f in sorted((ROOT / "backend").rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if rel in PARQUET_OK or "/tuning/" in rel:          # tuning = 로컬 평가 도구 (서버에서 돌지 않음)
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if DIRECT.search(line.split("#")[0]):
                bad.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert not bad, ("통계값 parquet 를 바로 읽는 코드가 있습니다. 서버(STAT_BACKEND=postgres)에는 parquet 가 없을 수 있으니 "
                     "backend.data_engine.stat_store.relation(con, prof, where, base=VIEW_OUT_DIR) 로 읽어 주세요:\n"
                     + "\n".join(bad))


@pytest.fixture(scope="module")
def normalized(tmp_path_factory):
    """가짜 KOSIS 표 3개를 정규화 → [(프로필, parquet 경로)]"""
    import json
    import os
    import subprocess
    import sys
    storage = tmp_path_factory.mktemp("guard") / "storage"
    fake_kosis.build(storage / "kosis_data")
    env = {**os.environ, "STORAGE_DIR": str(storage), "KOSIS_DATA_DIR": "", "VIEW_OUT_DIR": "", "PYTHONPATH": str(ROOT),
           "STAT_BACKEND": "parquet", "PYTHONIOENCODING": "utf-8"}
    code = "from backend.db.stats import normalize; r = normalize(all_selected=True); assert r['normalized'] >= 3, r"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    out = []
    for p in sorted((storage / "parquet" / "profiles").glob("*.json")):
        prof = json.loads(p.read_text(encoding="utf-8"))
        out.append((prof, storage / "parquet" / prof["file"]))
    return out


def test_parquet_columns_match_postgres_shape(normalized):
    """normalize 의 SELECT 를 바꾸면 PostgreSQL 쪽(kosis 스키마 · stat_store.columns · stats._copy_facts)도 같이 바꿔야 함"""
    import pyarrow.parquet as pq

    from backend.data_engine import stat_store
    arrow_name = {"string": ("string", "large_string"), "int32": ("int32",), "int64": ("int64",), "bool": ("bool",),
                  "float64": ("double",), "date32": ("date32[day]",)}
    for prof, path in normalized:
        levels = [lv["level"] for lv in prof["levels"]]
        got = [(f.name, str(f.type)) for f in pq.read_schema(path)]
        want = stat_store.columns(levels)
        assert [n for n, _ in got] == [n for n, _ in want], (
            f"{prof['table_key']}: 정규화 parquet 열이 PostgreSQL 모양과 다릅니다.\n  parquet : {[n for n, _ in got]}\n"
            f"  postgres: {[n for n, _ in want]}\n→ backend/db/sql/main/001_kosis.sql · data_engine/stat_store.py "
            f"(HEAD_COLS · LEVEL_COLS · TAIL_COLS · select_sql) · db/stats.py(_copy_facts · _dim_rows) 를 함께 고치세요")
        for (n, t), (_, w) in zip(got, want):
            assert t in arrow_name[w], f"{prof['table_key']}.{n}: parquet 종류 {t} ≠ PostgreSQL 쪽 {w} (stat_store.py)"


def test_bundle_takes_new_storage_artifacts(tmp_path, monkeypatch):
    """prepare 가 storage/ 에 새 폴더를 만들어도 묶음에 들어감 · 원본/parquet/실행 기록은 빠짐"""
    from backend.core import config
    from backend.db import bundle
    s = tmp_path / "storage"
    files = ["indices/table_index/tokens.json", "csv_index/values.parquet", "parquet/meta_profiles.jsonl",
             "brand_new_index/vocab.json",                                    # 팀원이 새로 만든 산출물
             "parquet/processed/101_T.parquet", "parquet/profiles/101_T.json", "parquet/views/v.csv",
             "kosis_data/raw/x/101_T.csv", "kosis_data/catalog.csv", "kosis_data/meta/101_T.json",
             "indices/search_cache/dense/a.pkl", "indices/embed_cache.sqlite", "runs/r/x.json", ".view_selection_secret"]
    for f in files:
        (s / f).parent.mkdir(parents=True, exist_ok=True)
        (s / f).write_text("x", encoding="utf-8")
    for k, v in {"STORAGE_DIR": s, "VIEW_OUT_DIR": s / "parquet", "TABLE_INDEX_DIR": s / "indices/table_index",
                 "CSV_INDEX_DIR": s / "csv_index", "KOSIS_DATA_DIR": s / "kosis_data", "EMBED_CACHE": s / "indices/embed_cache.sqlite",
                 "OKF_DIR": s / "okf", "OKF_BUILD_DIR": s / "okf_build"}.items():
        monkeypatch.setattr(config, k, v)
    names = set(bundle.create(tmp_path / "b.tar.gz", log=lambda m: None)["names"])
    assert {"storage/brand_new_index/vocab.json", "storage/indices/table_index/tokens.json", "storage/csv_index/values.parquet",
            "storage/parquet/meta_profiles.jsonl", "storage/parquet/processed/101_T.parquet",
            "storage/parquet/profiles/101_T.json", "kosis_data/catalog.csv", "kosis_data/meta/101_T.json",
            "storage/indices/embed_cache.sqlite"} <= names, names
    assert not any(n.startswith(("kosis_data/raw", "storage/kosis_data", "storage/runs", "storage/parquet/views",
                                 "storage/indices/search_cache")) or n.endswith(".view_selection_secret") for n in names), names
    small = set(bundle.create(tmp_path / "c.tar.gz", parts=["indices"], log=lambda m: None)["names"])
    assert "storage/brand_new_index/vocab.json" in small and not any("processed" in n or "raw" in n for n in small)
