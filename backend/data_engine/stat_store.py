"""
통계값 저장소 — 정규화 parquet 와 PostgreSQL(kosis 스키마) 중 어디서 읽을지 한 곳에서 정한다

  relation(con, prof, where)   DuckDB 에서 FROM 뒤에 쓸 관계 이름
      parquet   read_parquet('<VIEW_OUT_DIR>/<prof.file>')   where 는 무시 (호출한 쪽 WHERE 가 그대로 거름)
      postgres  kosis.stat_value 에서 where 를 먼저 걸어 가져온 행을 DuckDB 에 등록한 이름
                열 이름·종류는 parquet 와 같다 (c1_code · c1_label … · itm_nm · period_label …)
  pg_profile(tbl_id)           STAT_BACKEND=postgres 일 때 PostgreSQL 에 올린 표의 정규화 프로필 (없으면 None)
  profile_by_key(table_key)    프로필 파일 → (없으면) PostgreSQL

where 는 호출한 쪽이 sql_str 로 만든 표준 SQL 조건 목록이다 (prd_se = 'Y', c1_code IN (...), year IN (...),
NOT c1_total, value IS NOT NULL …). PostgreSQL 과 DuckDB 가 같은 문법이라 그대로 넘겨 먼저 거른 뒤,
DuckDB 쪽에서 같은 조건으로 한 번 더 거르므로 결과는 parquet 와 같다.

STAT_BACKEND=postgres 여도 PostgreSQL 에 없는 표는 parquet(있으면) → 지연 정규화(원본이 있으면)로 읽는다.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
import time
from pathlib import Path

from backend.core.utils import sql_str
from backend.db import conn

log = logging.getLogger("t4core.stat_store")

STORE_KEY = "store"          # 프로필에 붙이는 표시: "postgres" 면 PostgreSQL 에서 읽음
LEVELS = range(1, 9)

# parquet 열 이름 → arrow 종류 (normalize.normalize_table 의 SELECT 와 같은 순서)
HEAD_COLS = [("table_key", "string"), ("org_id", "string"), ("tbl_id", "string"), ("prd_se", "string"),
             ("prd_de", "string"), ("year", "int32"), ("period_label", "string"), ("period_date", "date32")]
LEVEL_COLS = [("code", "string"), ("name", "string"), ("label", "string"), ("std", "string"), ("ord", "int64"),
              ("depth", "int64"), ("total", "bool"), ("geo_type", "string"), ("parent", "string")]
TAIL_COLS = [("itm_id", "string"), ("itm_nm", "string"), ("itm_ord", "int64"), ("itm_kind", "string"),
             ("itm_total", "bool"), ("unit", "string"), ("unit_inferred", "bool"), ("value", "float64"),
             ("value_raw", "string"), ("symbol", "string")]
# 분류 열 → stat_code 의 열
_CODE_SRC = {"code": None, "name": "name", "label": "label", "std": "std", "ord": "ord", "depth": "depth",
             "total": "is_total", "geo_type": "geo_type", "parent": "parent"}


class StatStoreError(RuntimeError):
    pass


def use_postgres():
    return conn.stat_backend() == "postgres"


def columns(levels):
    """표의 분류 수준 → parquet 와 같은 열 목록 [(이름, arrow 종류)]"""
    out = list(HEAD_COLS)
    for i in levels:
        out += [(f"c{i}_{k}", t) for k, t in LEVEL_COLS]
    return out + list(TAIL_COLS)


def select_sql(table_id, levels):
    """kosis 정규 표들 → parquet 모양의 행 (table_id 는 int 로만 받는다)"""
    tid = int(table_id)
    sel = ["t.table_key", "t.org_id", "t.tbl_id", "v.prd_se", "v.prd_de", "v.year::int AS year",
           "p.period_label", "p.period_date"]
    joins = ["JOIN kosis.stat_table t ON t.table_id = v.table_id",
             "LEFT JOIN kosis.stat_period p ON p.table_id = v.table_id AND p.prd_se = v.prd_se AND p.prd_de = v.prd_de"]
    for i in levels:
        i = int(i)
        for k, _ in LEVEL_COLS:
            src = _CODE_SRC[k]
            sel.append(f"v.c{i} AS c{i}_code" if src is None else f"d{i}.{src} AS c{i}_{k}")
        joins.append(f"LEFT JOIN kosis.stat_code d{i} ON d{i}.table_id = v.table_id AND d{i}.level = {i} "
                     f"AND d{i}.code = v.c{i}")
    sel += ["v.itm_id", "i.itm_nm", "i.itm_ord", "i.itm_kind", "i.itm_total", "v.unit", "v.unit_inferred",
            "v.value", "v.value_raw", "v.symbol"]
    joins.append("LEFT JOIN kosis.stat_item i ON i.table_id = v.table_id AND i.itm_id = v.itm_id")
    return (f"SELECT {', '.join(sel)} FROM kosis.stat_value v {' '.join(joins)} "
            f"WHERE v.table_id = {tid}")


def _arrow_types(levels):
    import pyarrow as pa
    kinds = {"string": pa.string(), "int32": pa.int32(), "int64": pa.int64(), "bool": pa.bool_(),
             "float64": pa.float64(), "date32": pa.date32()}
    return {n: kinds[t] for n, t in columns(levels)}


def fetch_arrow(table_id, levels, where=()):
    """PostgreSQL → pyarrow.Table (COPY … TO STDOUT CSV 로 한 번에)"""
    import pyarrow.csv as pacsv
    sql = f"SELECT * FROM ({select_sql(table_id, levels)}) s"
    if where:
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    buf = io.BytesIO()
    t0 = time.time()
    try:
        with conn.main_pool().connection() as c:
            with c.cursor() as cur:
                with cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
                    for block in cp:
                        buf.write(block)
    except conn.DbNotConfigured:
        raise
    except Exception as e:  # noqa: BLE001
        raise StatStoreError(f"통계 DB(DATABASE_URL) 조회 실패: {e.__class__.__name__}: {str(e)[:200]}") from e
    buf.seek(0)
    tbl = pacsv.read_csv(
        buf, parse_options=pacsv.ParseOptions(newlines_in_values=True),
        convert_options=pacsv.ConvertOptions(column_types=_arrow_types(levels), strings_can_be_null=True,
                                             quoted_strings_can_be_null=False, true_values=["t"],
                                             false_values=["f"]))
    log.debug("stat_store fetch table_id=%s rows=%s %.3fs", table_id, tbl.num_rows, time.time() - t0)
    return tbl


def relation(con, prof, where=(), base=None):
    """DuckDB 의 FROM 자리에 넣을 관계 (위 설명). base = parquet 뿌리 (비우면 config.VIEW_OUT_DIR —
    View 생성처럼 모듈 변수로 뿌리를 바꿔 쓰는 곳은 자기 값을 넘긴다)"""
    if (prof or {}).get(STORE_KEY) != "postgres":
        if base is None:
            from backend.core.config import VIEW_OUT_DIR as base
        return f"read_parquet({sql_str((Path(base) / prof['file']).as_posix())})"
    meta = prof.get("_pg") or {}
    tbl = fetch_arrow(meta["table_id"], meta.get("levels") or [lv["level"] for lv in prof.get("levels") or []],
                      list(where or ()))
    name = "pg_" + hashlib.sha1(f"{meta['table_id']}|{'|'.join(where or ())}".encode()).hexdigest()[:16]
    try:
        con.register(name, tbl)
    except Exception as e:  # noqa: BLE001
        # duckdb 2.x: 같은 연결에 끝까지 읽지 않은 결과(fetchone 등)가 남아 있으면 등록을 거부 → 남은 결과를 버리고 다시
        if "unfinished result" not in str(e) or not hasattr(con, "abort"):
            raise
        con.abort()
        con.register(name, tbl)
    return name


# ── 프로필 ─────────────────────────────────────────────────────
_prof_cache: dict = {}
_prof_lock = threading.Lock()


def _attach(prof, table_id, levels, loaded_at):
    out = dict(prof)
    out[STORE_KEY] = "postgres"
    out["_pg"] = {"table_id": int(table_id), "levels": [int(x) for x in (levels or [])], "loaded_at": str(loaded_at)}
    return out


def _lookup(where_sql, arg):
    try:
        with conn.main_pool().connection() as c:
            row = c.execute(f"SELECT table_id, table_key, levels, loaded_at FROM kosis.stat_table WHERE {where_sql} "
                            "ORDER BY selected DESC, table_key LIMIT 1", (arg,)).fetchone()
            if row is None:
                return None
            tid, key, levels, loaded = row
            with _prof_lock:
                hit = _prof_cache.get(tid)
            if hit and hit[0] == loaded:
                return hit[1]
            prof = c.execute("SELECT profile FROM kosis.stat_table WHERE table_id = %s", (tid,)).fetchone()[0]
    except conn.DbNotConfigured:
        raise
    except Exception as e:  # noqa: BLE001
        raise StatStoreError(f"통계 DB(DATABASE_URL) 연결 실패: {e.__class__.__name__}: {str(e)[:200]}") from e
    out = _attach(prof, tid, levels, loaded)
    stale = _stale(out)
    if stale:
        # parquet 모드라면 여기서 다시 정규화하지만, 서버에는 원본이 없다 → 경고만 (팀 PC 에서 normalize → load)
        out["_pg"]["stale_kinds"] = stale
        log.warning("분류 판정 규칙이 바뀐 뒤 올리지 않은 표 %s: %s → 팀 PC 에서 stats normalize --all 후 stats load",
                    key, stale)
    with _prof_lock:
        _prof_cache[tid] = (loaded, out)
    return out


def _stale(prof):
    from backend.rag.ingestion.normalize import KIND_RULES_VERSION, stale_kinds
    if prof.get("kind_rules") == KIND_RULES_VERSION:
        return []
    try:
        return stale_kinds(prof)
    except Exception:  # noqa: BLE001
        return []


def pg_profile(tbl_id):
    """PostgreSQL 에 올린 표의 프로필 (STAT_BACKEND=postgres 가 아니거나 없으면 None)"""
    if not use_postgres() or not tbl_id:
        return None
    return _lookup("tbl_id = %s", str(tbl_id))


def pg_profile_by_key(table_key):
    if not use_postgres() or not table_key:
        return None
    return _lookup("table_key = %s", str(table_key))


def profile_by_key(table_key):
    """프로필 파일(VIEW_OUT_DIR/profiles) → PostgreSQL. 둘 다 없으면 None"""
    import json
    from backend.core.config import VIEW_OUT_DIR
    p = Path(VIEW_OUT_DIR) / "profiles" / f"{table_key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        return pg_profile_by_key(table_key)
    except (StatStoreError, conn.DbNotConfigured) as e:
        log.warning("프로필 조회 실패 %s: %s", table_key, e)
        return None


def n_tables():
    """PostgreSQL 에 올린 표 수 (postgres 모드가 아니거나 연결 실패면 None)"""
    if not use_postgres():
        return None
    try:
        with conn.main_pool().connection() as c:
            return c.execute("SELECT count(*) FROM kosis.stat_table").fetchone()[0]
    except Exception:  # noqa: BLE001
        return None


def clear_cache():
    with _prof_lock:
        _prof_cache.clear()
