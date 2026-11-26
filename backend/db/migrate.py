"""
스키마 적용 — backend/db/sql/<대상>/*.sql 을 이름 순서대로 한 번씩

  main    DATABASE_URL   kosis(통계값) · app(대화 이력)
  vector  VECTOR_DB_URL  vec(임베딩, pgvector 확장)

SQL 파일은 모두 IF NOT EXISTS 라 다시 실행해도 안전하다. 적용 기록: public.t4_schema_migrations
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from backend.db import conn

SQL_DIR = Path(__file__).resolve().parent / "sql"
TARGETS = {"main": conn.main_pool, "vector": conn.vector_pool}

_LOG_DDL = """CREATE TABLE IF NOT EXISTS public.t4_schema_migrations (
    target text NOT NULL, name text NOT NULL, sha1 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (target, name))"""


def files(target):
    return sorted((SQL_DIR / target).glob("*.sql"))


def migrate(target, log=print):
    pool = TARGETS[target]()
    applied = []
    with pool.connection() as c:
        c.execute(_LOG_DDL)
        done = {n: s for n, s in c.execute("SELECT name, sha1 FROM public.t4_schema_migrations WHERE target = %s",
                                           (target,)).fetchall()}
        for f in files(target):
            sql = f.read_text(encoding="utf-8")
            sha = hashlib.sha1(sql.encode()).hexdigest()
            if done.get(f.name) == sha:
                continue
            with c.transaction():
                c.execute(sql)
                c.execute("INSERT INTO public.t4_schema_migrations (target, name, sha1) VALUES (%s, %s, %s) "
                          "ON CONFLICT (target, name) DO UPDATE SET sha1 = EXCLUDED.sha1, applied_at = now()",
                          (target, f.name, sha))
            applied.append(f.name)
            log(f"[migrate:{target}] {f.name} 적용")
    if not applied:
        log(f"[migrate:{target}] 바뀐 것 없음")
    return applied


def migrate_configured(log=print):
    """설정된 DB 만 (DATABASE_URL · VECTOR_DB_URL 중 있는 것)"""
    out = {}
    if conn.database_url():
        out["main"] = migrate("main", log)
    if conn.vector_db_url():
        out["vector"] = migrate("vector", log)
    if not out:
        log("[migrate] DATABASE_URL · VECTOR_DB_URL 이 모두 비어 있음")
    return out
