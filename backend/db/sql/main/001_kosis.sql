-- 백엔드 PostgreSQL (backend-server) · KOSIS 통계값
--
-- 정규화 parquet(storage/parquet/processed/<기관_표>.parquet) 한 행 = kosis.stat_value 한 행.
-- 이름·순서·합계 여부처럼 코드마다 같은 값은 사전 표(stat_code · stat_item · stat_period)로 빼고,
-- 값 행에는 코드만 둔다. 읽을 때는 backend/data_engine/stat_store.py 가 원래 parquet 열 이름으로 다시 붙인다.
--
-- stat_value 는 표마다 파티션 하나 (LIST, table_id). 표를 다시 올릴 때는 새 파티션에 COPY → 인덱스 → 바꿔 끼우기
-- 라서 읽는 쪽은 옛 값 또는 새 값 중 하나만 본다.

CREATE SCHEMA IF NOT EXISTS kosis;

CREATE TABLE IF NOT EXISTS kosis.stat_table (
    table_id      serial PRIMARY KEY,
    table_key     text NOT NULL UNIQUE,              -- '<기관>_<표>' (parquet 파일 이름과 같음)
    org_id        text NOT NULL,
    tbl_id        text NOT NULL,
    tbl_nm        text,
    survey_nm     text,
    category      text,
    path          text,
    selected      boolean NOT NULL DEFAULT true,     -- catalog.csv selected (검색 대상)
    levels        smallint[] NOT NULL DEFAULT '{}',  -- 분류 수준 번호 (c1..c8 중 있는 것)
    profile       jsonb NOT NULL,                    -- 정규화 프로필 (profiles/<기관_표>.json 그대로)
    n_rows        bigint NOT NULL DEFAULT 0,
    source_sig    text,                              -- 올린 parquet·프로필의 크기·수정 시각 (바뀐 표만 다시 올리기)
    load_report   jsonb,                             -- 이름 변형 코드 수 등 적재 기록
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, tbl_id)
);
CREATE INDEX IF NOT EXISTS stat_table_tbl_id ON kosis.stat_table (tbl_id);

-- 분류 코드 사전 (c1..c8). 같은 코드에 이름이 여러 개면 가장 많은 행이 쓴 이름 (load_report.code_variants 에 개수)
CREATE TABLE IF NOT EXISTS kosis.stat_code (
    table_id   int      NOT NULL REFERENCES kosis.stat_table (table_id) ON DELETE CASCADE,
    level      smallint NOT NULL,
    code       text     NOT NULL,
    name       text,
    label      text,
    std        text,
    ord        int,
    depth      smallint,
    is_total   boolean,
    geo_type   text,
    parent     text,
    PRIMARY KEY (table_id, level, code)
);

CREATE TABLE IF NOT EXISTS kosis.stat_item (
    table_id   int  NOT NULL REFERENCES kosis.stat_table (table_id) ON DELETE CASCADE,
    itm_id     text NOT NULL,
    itm_nm     text,
    itm_ord    int,
    itm_kind   text,
    itm_total  boolean,
    PRIMARY KEY (table_id, itm_id)
);

CREATE TABLE IF NOT EXISTS kosis.stat_period (
    table_id      int  NOT NULL REFERENCES kosis.stat_table (table_id) ON DELETE CASCADE,
    prd_se        text NOT NULL,
    prd_de        text NOT NULL,
    year          smallint,
    period_label  text,
    period_date   date,
    PRIMARY KEY (table_id, prd_se, prd_de)
);

-- 값. 파티션은 backend/db/stats.py 가 표마다 만든다 (kosis.stat_value_<table_id>)
CREATE TABLE IF NOT EXISTS kosis.stat_value (
    table_id       int      NOT NULL,
    prd_se         text     NOT NULL,
    prd_de         text     NOT NULL,
    year           smallint NOT NULL,
    itm_id         text,
    c1 text, c2 text, c3 text, c4 text, c5 text, c6 text, c7 text, c8 text,
    unit           text,
    unit_inferred  boolean,
    value          double precision,
    value_raw      text,
    symbol         text
) PARTITION BY LIST (table_id);
