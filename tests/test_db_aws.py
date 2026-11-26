"""AWS DB 구성 (PostgreSQL 통계값 · pgvector 임베딩 · Redis 세션 · 대화 이력) — 실제 서버가 있을 때만

  T4_TEST_DATABASE_URL    빈 시험용 PostgreSQL (kosis · app 스키마를 지우고 다시 만듦)
  T4_TEST_VECTOR_DB_URL   빈 시험용 PostgreSQL + pgvector (vec 스키마를 지우고 다시 만듦)
  T4_TEST_REDIS_URL       시험용 Redis db (flushdb 함 — 예: redis://localhost:6379/15)

예) docker compose -f deploy/local/compose.yml 의 DB 들을 띄우고
    T4_TEST_DATABASE_URL=postgresql://... T4_TEST_VECTOR_DB_URL=postgresql://... T4_TEST_REDIS_URL=redis://.../15 \
    pytest tests/test_db_aws.py -q
"""
import os
import shutil

import pytest

from tests import fake_kosis
from tests.helpers import env, run

URLS = {k: os.getenv(f"T4_TEST_{k}") for k in ("DATABASE_URL", "VECTOR_DB_URL", "REDIS_URL")}
pytestmark = pytest.mark.skipif(not all(URLS.values()), reason="T4_TEST_DATABASE_URL · VECTOR_DB_URL · REDIS_URL 필요")


def test_parquet_to_postgres_same_answers(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    out = tmp_path / "expected.json"
    base = {"STORAGE_DIR": str(storage), "HCX_API_KEY": "test-key", "DATABASE_URL": URLS["DATABASE_URL"],
            "STAT_BACKEND": "parquet", "VECTOR_STORE": "file", "REDIS_URL": "", "CHAT_HISTORY": "off"}
    r = run(["-m", "tests.scenario_db", "phase1", str(out)], environ=env(**base))
    print(r.stdout[-3000:])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-5000:]
    assert '"PHASE1": "PASS"' in r.stdout

    # EC2 처럼: 원본 CSV · 정규화 parquet · 프로필 · dense pickle 없음 (catalog.csv · meta · 색인은 묶음으로 옴)
    sqlite = tmp_path / "embed_cache.sqlite"
    shutil.copy(storage / "indices" / "embed_cache.sqlite", sqlite)
    for d in (storage / "kosis_data" / "raw", storage / "parquet" / "processed", storage / "parquet" / "profiles",
              storage / "indices" / "search_cache" / "dense"):
        shutil.rmtree(d, ignore_errors=True)
    (storage / "indices" / "embed_cache.sqlite").unlink()
    pg = {**base, "STAT_BACKEND": "postgres", "VECTOR_STORE": "pgvector", "VECTOR_DB_URL": URLS["VECTOR_DB_URL"],
          "REDIS_URL": URLS["REDIS_URL"], "CHAT_HISTORY": "on", "SQLITE_CACHE": str(sqlite)}
    r = run(["-m", "tests.scenario_db", "phase2", str(out)], environ=env(**pg))
    print(r.stdout[-3000:])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-5000:]
    assert '"PHASE2": "PASS"' in r.stdout
