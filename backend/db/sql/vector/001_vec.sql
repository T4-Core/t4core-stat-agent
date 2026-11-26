-- 벡터 PostgreSQL (db-server, pgvector) · 임베딩
--
--   embedding_cache  글 → 임베딩 (예전 storage/indices/embed_cache.sqlite). 키는 sqlite 와 같다: sha1("<모델>\n<글>")
--   doc_set          dense 문서 묶음 하나 (표 설명문 코퍼스 서명 × 임베더 × 문서 종류)
--   doc_embedding    묶음의 글 하나 = 행 하나 (예전 storage/indices/search_cache/dense/*.pkl). doc_idx = 코퍼스 안 표 순서
--
-- 검색은 질문 임베딩과 묶음 안 모든 행의 내적을 한 번에 계산한다 (표 1,100개 안팎 — 순차 계산이 색인보다 빠름).
-- HNSW 색인은 1024차원(HCX bge-m3) 행에만 두고, 상위 k 개만 필요한 조회(vectors nearest)에서 쓴다.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS vec;

CREATE TABLE IF NOT EXISTS vec.embedding_cache (
    k             text PRIMARY KEY,
    model         text NOT NULL,
    dim           int  NOT NULL,
    embedding     vector NOT NULL,
    text_preview  text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vec.doc_set (
    set_id      serial PRIMARY KEY,
    set_key     text NOT NULL UNIQUE,      -- sha1(코퍼스 서명 | 임베더 | 문서 종류 | 글 목록 해시)
    corpus_sig  text NOT NULL,
    embedder    text NOT NULL,
    view_name   text NOT NULL,
    n_docs      int  NOT NULL,
    n_rows      int  NOT NULL,
    dim         int  NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vec.doc_embedding (
    set_id     int NOT NULL REFERENCES vec.doc_set (set_id) ON DELETE CASCADE,
    row_no     int NOT NULL,
    doc_idx    int NOT NULL,
    tbl_id     text,
    dim        int NOT NULL,
    text_sha1  text,
    embedding  vector NOT NULL,
    PRIMARY KEY (set_id, row_no)
);

CREATE INDEX IF NOT EXISTS doc_embedding_hnsw_1024 ON vec.doc_embedding
    USING hnsw ((embedding::vector(1024)) vector_ip_ops) WHERE dim = 1024;
