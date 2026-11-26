"""
연결 — 환경변수 → psycopg 연결 풀 (프로세스마다 URL 하나에 풀 하나)

  main_pool()     DATABASE_URL   (backend-server PostgreSQL: kosis · app 스키마)
  vector_pool()   VECTOR_DB_URL  (db-server PostgreSQL + pgvector: vec 스키마)
  redis_client()  REDIS_URL

psycopg · redis 는 이 기능을 켤 때만 import 한다 (로컬 parquet 모드·테스트는 설치하지 않아도 됨).
"""
from __future__ import annotations

import atexit
import logging
import os
import threading

log = logging.getLogger("t4core.db")

_pools: dict = {}
_lock = threading.Lock()


def env(name, default=""):
    return (os.getenv(name) or default).strip()


def database_url():
    return env("DATABASE_URL")


def vector_db_url():
    return env("VECTOR_DB_URL")


def stat_backend():
    """parquet (기본) | postgres"""
    v = env("STAT_BACKEND", "parquet").lower()
    return "postgres" if v in ("postgres", "postgresql", "pg") else "parquet"


def vector_store():
    """file (기본: sqlite 임베딩 캐시 + pickle 문서 벡터) | pgvector"""
    v = env("VECTOR_STORE", "file").lower()
    return "pgvector" if v in ("pgvector", "postgres", "pg") else "file"


def chat_history_on():
    return env("CHAT_HISTORY", "off").lower() in ("1", "true", "on", "yes", "postgres")


class DbNotConfigured(RuntimeError):
    pass


def _pool(url, name, max_size):
    if not url:
        raise DbNotConfigured(f"{name} 가 비어 있습니다 (.env)")
    with _lock:
        p = _pools.get(url)
        if p is None:
            from psycopg_pool import ConnectionPool
            p = ConnectionPool(url, min_size=1, max_size=max_size, timeout=float(env("DB_POOL_TIMEOUT", "15")),
                               max_idle=300, name=name, open=False,
                               kwargs={"autocommit": True, "application_name": "t4core-backend"})
            p.open(wait=False)
            _pools[url] = p
        return p


def main_pool():
    return _pool(database_url(), "DATABASE_URL", int(env("DB_POOL_MAX", "10")))


def vector_pool():
    return _pool(vector_db_url(), "VECTOR_DB_URL", int(env("VECTOR_POOL_MAX", "6")))


def close_pools():
    with _lock:
        for p in _pools.values():
            try:
                p.close()
            except Exception:  # noqa: BLE001
                pass
        _pools.clear()


atexit.register(close_pools)

_redis = {"client": None, "url": None}


def redis_client():
    """REDIS_URL 이 없으면 None"""
    url = env("REDIS_URL")
    if not url:
        return None
    with _lock:
        if _redis["client"] is None or _redis["url"] != url:
            import redis
            _redis["client"] = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3,
                                                    health_check_interval=30)
            _redis["url"] = url
        return _redis["client"]


def ping_all():
    """GET /api/v1/system/db · python -m backend.db check — 켠 기능마다 연결 확인"""
    out = {"stat_backend": stat_backend(), "vector_store": vector_store(), "chat_history": chat_history_on(),
           "session_store": "redis" if env("REDIS_URL") else "off"}
    if database_url():
        try:
            with main_pool().connection() as c:
                n = c.execute("SELECT count(*) FROM kosis.stat_table").fetchone()[0] \
                    if c.execute("SELECT to_regclass('kosis.stat_table')").fetchone()[0] else None
            out["database"] = {"ok": True, "stat_tables": n}
        except Exception as e:  # noqa: BLE001
            out["database"] = {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:200]}"}
    if vector_db_url():
        try:
            with vector_pool().connection() as c:
                ver = c.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
                n = c.execute("SELECT count(*) FROM vec.embedding_cache").fetchone()[0] \
                    if c.execute("SELECT to_regclass('vec.embedding_cache')").fetchone()[0] else None
            out["vector_db"] = {"ok": True, "pgvector": ver[0] if ver else None, "cached_embeddings": n}
        except Exception as e:  # noqa: BLE001
            out["vector_db"] = {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:200]}"}
    r = redis_client()
    if r is not None:
        try:
            out["redis"] = {"ok": bool(r.ping())}
        except Exception as e:  # noqa: BLE001
            out["redis"] = {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:200]}"}
    return out
