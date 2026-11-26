"""
임베딩 저장소 — db-server 의 PostgreSQL + pgvector (VECTOR_STORE=pgvector, VECTOR_DB_URL)

  PgEmbedCache   글 → 임베딩 캐시 (core/llm.embed_cache 가 sqlite 대신 씀). 키는 sqlite 와 같음
  PgDocStore     dense 문서 묶음 (search/index.DenseRetriever 가 pickle 대신 씀)
                 load_or_create: 같은 묶음이 있으면 벡터를 읽고, 없으면 임베딩해서 올림
                 scores: 질문 벡터 · 묶음 안 모든 행의 내적을 DB 에서 계산 (실패하면 호출한 쪽이 메모리로 계산)

  python -m backend.db vectors import-sqlite [경로]   예전 embed_cache.sqlite → vec.embedding_cache (HCX 다시 안 부름)
  python -m backend.db vectors sync                   검색기를 한 번 만들어 dense 문서 묶음을 올림
  python -m backend.db vectors status | prune | nearest "질문"
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading

import numpy as np

from backend.db import conn

log = logging.getLogger("t4core.vectors")


def to_literal(v):
    """numpy → pgvector 글 표기 '[0.1,0.2,…]' (float32 값이 그대로 돌아오는 자릿수)"""
    return "[" + ",".join(repr(float(x)) for x in np.asarray(v, dtype=np.float32).ravel()) + "]"


def from_literal(s):
    s = str(s).strip()
    return np.array(s[1:-1].split(","), dtype=np.float32) if len(s) > 2 else np.zeros(0, np.float32)


# ── 글 → 임베딩 캐시 ──────────────────────────────────────────
class PgEmbedCache:
    """core/llm._EmbedCache 와 같은 get · put (+ get_many). DB 오류는 '캐시 없음'으로 보고 계속"""

    def __init__(self, model):
        self.model = model

    def key(self, text):
        return hashlib.sha1(f"{self.model}\n{text}".encode()).hexdigest()

    def get(self, text):
        return self.get_many([text])[0]

    def get_many(self, texts):
        keys = [self.key(t) for t in texts]
        found = {}
        try:
            with conn.vector_pool().connection() as c:
                for i in range(0, len(keys), 500):
                    part = list(dict.fromkeys(keys[i:i + 500]))
                    for k, v in c.execute("SELECT k, embedding::text FROM vec.embedding_cache WHERE k = ANY(%s)",
                                          (part,)).fetchall():
                        found[k] = from_literal(v)
        except Exception as e:  # noqa: BLE001
            log.warning("임베딩 캐시 읽기 실패 (HCX 로 다시 계산): %s", e)
        return [found.get(k) for k in keys]

    def put(self, text, vec):
        v = np.asarray(vec, dtype=np.float32)
        try:
            with conn.vector_pool().connection() as c:
                c.execute("INSERT INTO vec.embedding_cache (k, model, dim, embedding, text_preview) "
                          "VALUES (%s, %s, %s, %s::vector, %s) ON CONFLICT (k) DO UPDATE SET embedding = EXCLUDED.embedding",
                          (self.key(text), self.model, int(v.size), to_literal(v), str(text)[:200]))
        except Exception as e:  # noqa: BLE001
            log.warning("임베딩 캐시 저장 실패 (계속): %s", e)


# ── dense 문서 묶음 ───────────────────────────────────────────
class VectorDbUnavailable(RuntimeError):
    pass


def set_key(keys, n):
    return hashlib.sha1(("|".join(map(str, keys)) + f"|n={n}").encode()).hexdigest()


class PgDocStore:
    def load(self, key):
        with conn.vector_pool().connection() as c:
            row = c.execute("SELECT set_id, n_rows FROM vec.doc_set WHERE set_key = %s", (key,)).fetchone()
            if not row:
                return None, None
            sid, n = row
            vecs = c.execute("SELECT embedding::text FROM vec.doc_embedding WHERE set_id = %s ORDER BY row_no",
                             (sid,)).fetchall()
        if len(vecs) != n:
            return None, None
        return np.vstack([from_literal(v) for (v,) in vecs]).astype(np.float32), sid

    def save(self, key, corpus_sig, embedder, view_name, M, owners, tbl_ids):
        M = np.asarray(M, dtype=np.float32)
        n_docs = len(set(owners)) if owners is not None else M.shape[0]
        with conn.vector_pool().connection() as c:
            with c.transaction():
                c.execute("DELETE FROM vec.doc_set WHERE set_key = %s", (key,))
                sid = c.execute("INSERT INTO vec.doc_set (set_key, corpus_sig, embedder, view_name, n_docs, n_rows, dim) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING set_id",
                                (key, corpus_sig, embedder, view_name, n_docs, M.shape[0], M.shape[1])).fetchone()[0]
                buf = io.StringIO()
                for r in range(M.shape[0]):
                    d = int(owners[r]) if owners is not None else r
                    tid = tbl_ids[d] if d < len(tbl_ids) else ""
                    buf.write(f"{sid}\t{r}\t{d}\t{tid}\t{M.shape[1]}\t{to_literal(M[r])}\n")
                with c.cursor() as cur:
                    with cur.copy("COPY vec.doc_embedding (set_id, row_no, doc_idx, tbl_id, dim, embedding) FROM STDIN") as cp:
                        cp.write(buf.getvalue())
        return sid

    def load_or_create(self, keys, corpus_sig, embedder, view_name, texts, owners, tbl_ids, embed_fn):
        """→ (행렬, set_id). 묶음이 없으면 embed_fn 으로 만들어 올림.
        db-server 에 닿지 않으면 VectorDbUnavailable — 표 전체를 HCX 로 다시 임베딩하지 않게 (호출한 쪽이 파일 캐시로)"""
        key = set_key(keys, len(texts))
        try:
            M, sid = self.load(key)
        except Exception as e:  # noqa: BLE001
            raise VectorDbUnavailable(f"벡터 DB(VECTOR_DB_URL)에 연결하지 못함 — db-server 를 먼저 켜세요: "
                                      f"{e.__class__.__name__}: {str(e)[:200]}") from e
        if M is not None and M.shape[0] == len(texts):
            return M, sid
        M = embed_fn()
        try:
            sid = self.save(key, corpus_sig, embedder, view_name, M, owners, tbl_ids)
        except Exception as e:  # noqa: BLE001
            log.warning("dense 묶음 저장 실패 (메모리로 계속): %s", e)
            sid = None
        return M, sid

    def scores(self, set_id, q):
        """묶음의 모든 행 · 질문 벡터 내적 (row_no 순서)"""
        with conn.vector_pool().connection() as c:
            rows = c.execute("SELECT (embedding <#> %s::vector) * -1 FROM vec.doc_embedding WHERE set_id = %s "
                             "ORDER BY row_no", (to_literal(q), set_id)).fetchall()
        return np.asarray([r[0] for r in rows], dtype=np.float32)


_doc_store, _lock = None, threading.Lock()


def doc_store():
    global _doc_store
    with _lock:
        if _doc_store is None:
            _doc_store = PgDocStore()
        return _doc_store


def score_in_db():
    """VECTOR_SCORE=db(기본) — 내적을 db-server 에서 / memory — 읽어 온 행렬로 backend 에서"""
    return conn.env("VECTOR_SCORE", "db").lower() != "memory"


# ── CLI 작업 ──────────────────────────────────────────────────
def import_sqlite(path=None, log=print):
    import sqlite3
    from pathlib import Path

    from backend.core.config import EMBED_CACHE
    from backend.core.llm import EMBED_MODEL
    from backend.db.migrate import migrate
    migrate("vector", log)
    p = Path(path or EMBED_CACHE)
    if not p.exists():
        raise SystemExit(f"sqlite 임베딩 캐시가 없습니다: {p}")
    src = sqlite3.connect(str(p))
    rows = src.execute("SELECT k, v FROM emb").fetchall()
    src.close()
    n = 0
    with conn.vector_pool().connection() as c:
        with c.transaction():
            c.execute("CREATE TEMP TABLE _imp (k text, model text, dim int, embedding vector) ON COMMIT DROP")
            buf = io.StringIO()
            for k, v in rows:
                vec = np.frombuffer(v, dtype=np.float32)
                buf.write(f"{k}\t{EMBED_MODEL}\t{vec.size}\t{to_literal(vec)}\n")
                n += 1
            with c.cursor() as cur:
                with cur.copy("COPY _imp FROM STDIN") as cp:
                    cp.write(buf.getvalue())
            added = c.execute("INSERT INTO vec.embedding_cache (k, model, dim, embedding) "
                              "SELECT k, model, dim, embedding FROM _imp ON CONFLICT (k) DO NOTHING").rowcount
    log(f"[vectors] sqlite {n}건 읽음 → 새로 {added}건 (이미 있던 것은 그대로)")
    return {"read": n, "added": added}


def sync(log=print):
    """검색기를 만들어 dense 문서 묶음을 올림 (없는 임베딩만 HCX 호출)"""
    import os
    os.environ.setdefault("VECTOR_STORE", "pgvector")
    from backend.db.migrate import migrate
    from backend.rag.search.engine import get_search
    migrate("vector", log)
    s = get_search(log=log)
    log(f"[vectors] 검색기 {s.name} · 표 {len(s.docs)} · dense {s.info()['dense']}")
    return status(log)


def status(log=print):
    with conn.vector_pool().connection() as c:
        n_cache = c.execute("SELECT count(*) FROM vec.embedding_cache").fetchone()[0]
        sets = c.execute("SELECT set_id, embedder, view_name, n_docs, n_rows, dim, created_at, corpus_sig "
                         "FROM vec.doc_set ORDER BY created_at DESC").fetchall()
        size = c.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    log(f"[vectors] 임베딩 캐시 {n_cache}건 · 문서 묶음 {len(sets)}개 · DB {size / 2**20:.1f} MiB")
    for s in sets[:10]:
        log(f"  #{s[0]} {s[1]} {s[2]} 표 {s[3]} 행 {s[4]} × {s[5]}차원 · {s[6]:%Y-%m-%d %H:%M} · {s[7]}")
    return {"embedding_cache": n_cache, "doc_sets": len(sets), "bytes": int(size)}


def prune(keep=1, log=print):
    """(임베더, 문서 종류)마다 최근 keep 개 묶음만 남김 (표 색인을 다시 만들면 옛 묶음이 쌓임)"""
    with conn.vector_pool().connection() as c:
        n = c.execute("""DELETE FROM vec.doc_set WHERE set_id IN (
            SELECT set_id FROM (SELECT set_id, row_number() OVER (PARTITION BY embedder, view_name
                                ORDER BY created_at DESC) AS rn FROM vec.doc_set) s WHERE rn > %s)""", (keep,)).rowcount
    log(f"[vectors] 옛 묶음 {n}개 지움")
    return n


def nearest(question, k=10, log=print):
    """질문 → 가장 가까운 표 (HCX 임베딩 1024차원 묶음, HNSW 색인). 검색 엔진과 별개인 확인용"""
    from backend.rag.search.index import HcxEmbedder
    q = HcxEmbedder().embed_queries([question])[0]
    with conn.vector_pool().connection() as c:
        row = c.execute("SELECT set_id FROM vec.doc_set WHERE embedder = 'hcx:bge-m3' AND view_name = 'rule' "
                        "ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit("hcx 문서 묶음이 없습니다 → python -m backend.db vectors sync")
        lit = to_literal(q)
        rows = c.execute("SELECT tbl_id, (embedding::vector(1024) <#> %s::vector(1024)) * -1 AS score "
                         "FROM vec.doc_embedding WHERE dim = 1024 AND set_id = %s "
                         "ORDER BY embedding::vector(1024) <#> %s::vector(1024) LIMIT %s",
                         (lit, row[0], lit, int(k))).fetchall()
    for t, s in rows:
        log(f"  {s:.4f}  {t}")
    return rows
