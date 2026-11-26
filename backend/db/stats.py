"""
KOSIS 통계값 → PostgreSQL (kosis 스키마) 적재

  normalize   원본 CSV → 정규화 parquet + 프로필 (원본이 있는 PC 에서. 바뀐 표만)
  load        정규화 parquet + 프로필 → kosis.stat_table · stat_code · stat_item · stat_period · stat_value
              표마다: 새 파티션에 COPY → 인덱스 → 한 트랜잭션에서 옛 파티션과 바꿔 끼움 (읽는 쪽은 끊기지 않음)
              바뀐 표만 (parquet·프로필의 크기·수정 시각이 같으면 건너뜀, --force 면 모두)
  verify      표마다 행 수 · 값 합계 · 부호 수 · 표본 행을 parquet 와 비교
  status      올라간 표 수 · 행 수 · 디스크 크기
  estimate    PostgreSQL 크기 미리 보기 (프로필의 행 수, 아직 정규화하지 않은 표는 원본 CSV 크기로 추정)
  drop        표 지우기

  python -m backend.db stats normalize --all
  python -m backend.db stats load --all
  python -m backend.db stats verify --all --sample 200
"""
from __future__ import annotations

import io
import json
import secrets
import time
from pathlib import Path

from backend.db import conn

BIG_TABLE_ROWS = 200_000          # 이보다 큰 표는 분류 열(c1·c2) 인덱스도 만든다
BATCH_ROWS = 200_000
ROW_BYTES_GUESS = 110             # PostgreSQL 한 행 크기 추정 (인덱스 포함 전, 실제 적재 뒤 status 로 확인)
RAW_BYTES_PER_ROW_GUESS = 130     # 원본 CSV 한 행 크기 추정 (정규화 전 표의 행 수를 어림할 때)
FACT_COLS = ["table_id", "prd_se", "prd_de", "year", "itm_id", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
             "unit", "unit_inferred", "value", "value_raw", "symbol"]
LOCK_KEY = 4_401_050              # 적재 프로세스 하나만 (pg_advisory_lock)


def _paths():
    from backend.core.config import VIEW_OUT_DIR
    return Path(VIEW_OUT_DIR) / "processed", Path(VIEW_OUT_DIR) / "profiles"


def local_profiles(tables=None):
    """VIEW_OUT_DIR/profiles/*.json 중 parquet 가 함께 있는 것 → [(프로필, parquet 경로, 프로필 경로)]"""
    from backend.core.config import VIEW_OUT_DIR
    _, pdir = _paths()
    want = set(tables or [])
    out = []
    for p in sorted(pdir.glob("*.json")) if pdir.exists() else []:
        try:
            prof = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if want and prof.get("tbl_id") not in want and prof.get("table_key") not in want:
            continue
        pq = Path(VIEW_OUT_DIR) / prof.get("file", f"processed/{p.stem}.parquet")
        if pq.exists():
            out.append((prof, pq, p))
    return out


def source_sig(pq, prof_p):
    a, b = pq.stat(), prof_p.stat()
    return f"{a.st_size}:{a.st_mtime_ns}|{b.st_size}:{b.st_mtime_ns}"


def _selected_ids():
    """catalog.csv 의 selected 표 (없으면 None → 모두 selected 로 표시)"""
    from backend.core.config import KOSIS_DATA_DIR
    f = Path(KOSIS_DATA_DIR) / "catalog.csv"
    if not f.exists():
        return None
    import pandas as pd
    cat = pd.read_csv(f, dtype=str)
    return set(cat.loc[cat["selected"] == "True", "tbl_id"])


# ── 정규화 (원본이 있는 곳에서) ────────────────────────────────
def normalize(tables=None, all_selected=False, force=False, catalog_all=False, log=print):
    """catalog_all: selected 가 아닌 표까지 (검색 대상은 아니지만 DB 에 모두 두고 싶을 때)"""
    from backend.data_engine.duckdb_client import connect
    from backend.rag.ingestion.normalize import load_targets, normalize_table
    from backend.core.config import KOSIS_DATA_DIR
    if all_selected or catalog_all:
        import pandas as pd
        cat = pd.read_csv(Path(KOSIS_DATA_DIR) / "catalog.csv", dtype=str)
        tables = list(dict.fromkeys(cat["tbl_id"] if catalog_all else cat.loc[cat["selected"] == "True", "tbl_id"]))
    if not tables:
        raise SystemExit("--tables 또는 --all 이 필요합니다")
    con = connect()
    done, failed, missing, t0 = 0, [], [], time.time()
    for k, t in enumerate(tables, 1):
        try:
            row = next(load_targets([t]).itertuples())
            prof = normalize_table(con, row, force=force)
            if prof is None:
                missing.append(t)
            else:
                done += 1
        except Exception as e:  # noqa: BLE001  (표 하나 실패해도 계속)
            failed.append((t, f"{e.__class__.__name__}: {str(e)[:150]}"))
        if k % 20 == 0 or k == len(tables):
            log(f"[normalize] {k}/{len(tables)}  완료 {done} · 원본 없음 {len(missing)} · 실패 {len(failed)} "
                f"· {time.time() - t0:.0f}초")
    con.close()
    for t, e in failed[:20]:
        log(f"  실패 {t}: {e}")
    return {"normalized": done, "missing_raw": missing, "failed": failed}


# ── 적재 ──────────────────────────────────────────────────────
def _existing(c):
    return {k: (tid, sig) for k, tid, sig in
            c.execute("SELECT table_key, table_id, source_sig FROM kosis.stat_table").fetchall()}


def _dim_rows(con, rel, i):
    """분류 수준 i 의 코드 사전 + 이름 변형 수 (같은 코드에 다른 이름 → 가장 많은 행이 쓴 이름)"""
    return con.execute(f'''
        WITH g AS (
          SELECT c{i}_code AS code, c{i}_name AS name, c{i}_label AS label, c{i}_std AS std, c{i}_ord AS ord,
                 c{i}_depth AS depth, c{i}_total AS is_total, c{i}_geo_type AS geo_type, c{i}_parent AS parent,
                 count(*) AS n
          FROM {rel} WHERE c{i}_code IS NOT NULL GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9)
        SELECT code, name, label, std, ord, depth, is_total, geo_type, parent,
               count(*) OVER (PARTITION BY code) AS variants
        FROM g QUALIFY row_number() OVER (PARTITION BY code ORDER BY n DESC, name, label) = 1
        ORDER BY code''').fetchall()


def _item_rows(con, rel):
    return con.execute(f'''
        WITH g AS (SELECT itm_id, itm_nm, itm_ord, itm_kind, itm_total, count(*) AS n
                   FROM {rel} WHERE itm_id IS NOT NULL GROUP BY 1, 2, 3, 4, 5)
        SELECT itm_id, itm_nm, itm_ord, itm_kind, itm_total, count(*) OVER (PARTITION BY itm_id) AS variants
        FROM g QUALIFY row_number() OVER (PARTITION BY itm_id ORDER BY n DESC, itm_nm) = 1''').fetchall()


def _period_rows(con, rel):
    return con.execute(f'''
        SELECT prd_se, prd_de, year, period_label, period_date FROM (
          SELECT DISTINCT prd_se, prd_de, year, period_label, period_date FROM {rel}) g
        QUALIFY row_number() OVER (PARTITION BY prd_se, prd_de ORDER BY period_date) = 1''').fetchall()


def _arrow_reader(rel, n):
    """DuckDB 관계 → arrow 배치 읽개 (판마다 이름이 다름: 2.x to_arrow_reader · 1.x fetch_arrow_reader · record_batch)"""
    for name in ("to_arrow_reader", "fetch_arrow_reader", "fetch_record_batch", "record_batch"):
        f = getattr(rel, name, None)
        if f is not None:
            return f(n)
    raise RuntimeError("이 duckdb 판에서 arrow 배치 읽기를 찾지 못함")


def _copy_facts(dcon, rel, levels, pg, target, tid):
    import pyarrow as pa
    import pyarrow.csv as pacsv
    lv = set(levels)
    cols = [f"{int(tid)} AS table_id", "prd_se", "prd_de", "year", "itm_id"] + \
        [f"c{i}_code AS c{i}" if i in lv else f"NULL::VARCHAR AS c{i}" for i in range(1, 9)] + \
        ["unit", "unit_inferred", "value", "value_raw", "symbol"]
    reader = _arrow_reader(dcon.sql(f"SELECT {', '.join(cols)} FROM {rel}"), BATCH_ROWS)
    n = 0
    opts = pacsv.WriteOptions(include_header=False, quoting_style="needed")
    with pg.cursor() as cur:
        with cur.copy(f"COPY {target} ({', '.join(FACT_COLS)}) FROM STDIN WITH (FORMAT csv)") as cp:
            for batch in reader:
                buf = io.BytesIO()
                pacsv.write_csv(pa.Table.from_batches([batch]), buf, write_options=opts)
                cp.write(buf.getvalue())
                n += batch.num_rows
    return n


def load_table(pg, dcon, prof, pq, prof_p, existing, selected_ids=None, log=print):
    from backend.core.utils import sql_str
    key = prof["table_key"]
    levels = [int(lv["level"]) for lv in prof.get("levels") or []]
    rel = f"read_parquet({sql_str(pq.as_posix())})"
    t0 = time.time()
    tid = existing[key][0] if key in existing else pg.execute(
        "SELECT nextval(pg_get_serial_sequence('kosis.stat_table', 'table_id'))").fetchone()[0]
    tok = secrets.token_hex(3)
    new = f"kosis.stat_value_{tid}_{tok}"
    part = f"stat_value_{tid}"
    # 1) 새 파티션 후보 (아직 부모에 붙이지 않음) ← COPY
    pg.execute(f"CREATE TABLE {new} (LIKE kosis.stat_value INCLUDING DEFAULTS)")
    try:
        n = _copy_facts(dcon, rel, levels, pg, new, tid)
        pg.execute(f"ALTER TABLE {new} ADD CONSTRAINT sv_{tid}_{tok}_ck CHECK (table_id = {int(tid)})")
        pg.execute(f"CREATE INDEX sv_{tid}_{tok}_a ON {new} (prd_se, year, itm_id)")
        if n > BIG_TABLE_ROWS and levels:
            pg.execute(f"CREATE INDEX sv_{tid}_{tok}_b ON {new} (prd_se, year, c{levels[0]})")
            if len(levels) > 1:
                pg.execute(f"CREATE INDEX sv_{tid}_{tok}_c ON {new} (prd_se, year, c{levels[1]})")
        pg.execute(f"ANALYZE {new}")
        dims = {i: _dim_rows(dcon, rel, i) for i in levels}
        items, periods = _item_rows(dcon, rel), _period_rows(dcon, rel)
        report = {"rows": n, "code_variants": {f"c{i}": sum(1 for r in rows if r[-1] > 1) for i, rows in dims.items()},
                  "item_variants": sum(1 for r in items if r[-1] > 1),
                  "row_check": prof.get("row_check"), "seconds_copy": round(time.time() - t0, 1)}
        sel = True if selected_ids is None else prof.get("tbl_id") in selected_ids
        # 2) 바꿔 끼우기 (한 트랜잭션)
        with pg.transaction():
            pg.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY + int(tid),))
            pg.execute("""
                INSERT INTO kosis.stat_table (table_id, table_key, org_id, tbl_id, tbl_nm, survey_nm, category, path,
                                              selected, levels, profile, n_rows, source_sig, load_report, loaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, now())
                ON CONFLICT (table_key) DO UPDATE SET
                  tbl_nm = EXCLUDED.tbl_nm, survey_nm = EXCLUDED.survey_nm, category = EXCLUDED.category,
                  path = EXCLUDED.path, selected = EXCLUDED.selected, levels = EXCLUDED.levels,
                  profile = EXCLUDED.profile, n_rows = EXCLUDED.n_rows, source_sig = EXCLUDED.source_sig,
                  load_report = EXCLUDED.load_report, loaded_at = now()""",
                       (tid, key, prof.get("org_id"), prof.get("tbl_id"), prof.get("tbl_nm"), prof.get("survey_nm"),
                        prof.get("category"), prof.get("path"), sel, levels,
                        json.dumps(prof, ensure_ascii=False, default=str), n, source_sig(pq, prof_p),
                        json.dumps(report, ensure_ascii=False, default=str)))
            for t in ("stat_code", "stat_item", "stat_period"):
                pg.execute(f"DELETE FROM kosis.{t} WHERE table_id = %s", (tid,))
            with pg.cursor() as cur:
                rows = [(tid, i, *r[:9]) for i, rs in dims.items() for r in rs]
                if rows:
                    cur.executemany("INSERT INTO kosis.stat_code (table_id, level, code, name, label, std, ord, depth, "
                                    "is_total, geo_type, parent) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
                if items:
                    cur.executemany("INSERT INTO kosis.stat_item (table_id, itm_id, itm_nm, itm_ord, itm_kind, itm_total)"
                                    " VALUES (%s,%s,%s,%s,%s,%s)", [(tid, *r[:5]) for r in items])
                if periods:
                    cur.executemany("INSERT INTO kosis.stat_period (table_id, prd_se, prd_de, year, period_label, "
                                    "period_date) VALUES (%s,%s,%s,%s,%s,%s)", [(tid, *r) for r in periods])
            if pg.execute("SELECT to_regclass(%s)", (f"kosis.{part}",)).fetchone()[0]:
                pg.execute(f"ALTER TABLE kosis.stat_value DETACH PARTITION kosis.{part}")
                pg.execute(f"DROP TABLE kosis.{part}")
            pg.execute(f"ALTER TABLE {new} RENAME TO {part}")
            pg.execute(f"ALTER TABLE kosis.stat_value ATTACH PARTITION kosis.{part} FOR VALUES IN ({int(tid)})")
    except BaseException:
        pg.execute(f"DROP TABLE IF EXISTS {new}")
        raise
    log(f"[load] {key:28s} 행 {n:>11,} · {time.time() - t0:5.1f}초"
        + (f" · 이름 변형 {report['code_variants']}" if any(report["code_variants"].values()) else ""))
    return n


def load(tables=None, force=False, max_rows=None, log=print):
    """정규화 parquet → PostgreSQL. 반환: {loaded, skipped, failed, too_big}
    max_rows: 이보다 행이 많은 표는 올리지 않음 (그 표는 서버의 parquet 로 읽힘 — stat_store 의 대체 경로)"""
    import psycopg
    from backend.data_engine.duckdb_client import connect
    from backend.db.migrate import migrate
    migrate("main", log)
    todo = local_profiles(tables)
    if not todo:
        from backend.core.config import VIEW_OUT_DIR
        raise SystemExit(f"올릴 정규화 표가 없습니다: {VIEW_OUT_DIR}/profiles/*.json + processed/*.parquet "
                         f"(원본이 있는 PC 에서 python -m backend.db stats normalize --all)")
    selected = _selected_ids()
    out = {"loaded": [], "skipped": [], "failed": [], "too_big": [], "rows": 0}
    t0 = time.time()
    with psycopg.connect(conn.database_url(), autocommit=True, application_name="t4core-stats-load") as pg:
        if not pg.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
            raise SystemExit("다른 적재가 실행 중입니다 (pg_advisory_lock)")
        pg.execute("SET maintenance_work_mem = '256MB'")
        existing = _existing(pg)
        dcon = connect()
        for k, (prof, pq, prof_p) in enumerate(todo, 1):
            key = prof["table_key"]
            if not force and key in existing and existing[key][1] == source_sig(pq, prof_p):
                out["skipped"].append(key)
                continue
            n_rows = int((prof.get("row_check") or {}).get("processed") or 0)
            if max_rows and n_rows > max_rows:
                out["too_big"].append((key, n_rows))
                log(f"[load] 건너뜀 (행 {n_rows:,} > --max-rows) {key} → 이 표는 parquet 로 읽힘")
                continue
            try:
                out["rows"] += load_table(pg, dcon, prof, pq, prof_p, existing, selected, log)
                out["loaded"].append(key)
            except Exception as e:  # noqa: BLE001  (표 하나 실패해도 계속)
                out["failed"].append((key, f"{e.__class__.__name__}: {str(e)[:200]}"))
                log(f"[load] 실패 {key}: {out['failed'][-1][1]}")
            if k % 50 == 0:
                log(f"[load] 진행 {k}/{len(todo)} · {time.time() - t0:.0f}초")
        dcon.close()
        pg.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    log(f"[load] 올림 {len(out['loaded'])} · 그대로 {len(out['skipped'])} · 실패 {len(out['failed'])} "
        + (f"· 큰 표 건너뜀 {len(out['too_big'])} " if out["too_big"] else "")
        + f"· 행 {out['rows']:,} · {time.time() - t0:.0f}초")
    return out


def drop(tables, log=print):
    import psycopg
    with psycopg.connect(conn.database_url(), autocommit=True) as pg:
        for t in tables:
            row = pg.execute("SELECT table_id, table_key FROM kosis.stat_table WHERE tbl_id = %s OR table_key = %s",
                             (t, t)).fetchone()
            if not row:
                log(f"[drop] 없음 {t}")
                continue
            tid, key = row
            with pg.transaction():
                if pg.execute("SELECT to_regclass(%s)", (f"kosis.stat_value_{tid}",)).fetchone()[0]:
                    pg.execute(f"ALTER TABLE kosis.stat_value DETACH PARTITION kosis.stat_value_{int(tid)}")
                    pg.execute(f"DROP TABLE kosis.stat_value_{int(tid)}")
                pg.execute("DELETE FROM kosis.stat_table WHERE table_id = %s", (tid,))
            log(f"[drop] {key}")


# ── 확인 ──────────────────────────────────────────────────────
def status(log=print):
    import psycopg
    with psycopg.connect(conn.database_url(), autocommit=True) as pg:
        n, rows, sel = pg.execute("SELECT count(*), coalesce(sum(n_rows), 0), count(*) FILTER (WHERE selected) "
                                  "FROM kosis.stat_table").fetchone()
        size = pg.execute("SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_inherits i "
                          "JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'kosis.stat_value'::regclass"
                          ).fetchone()[0]
        db = pg.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        top = pg.execute("SELECT table_key, n_rows, loaded_at FROM kosis.stat_table ORDER BY n_rows DESC LIMIT 5"
                         ).fetchall()
        from backend.rag.ingestion.normalize import KIND_RULES_VERSION
        old_rules = pg.execute("SELECT count(*) FROM kosis.stat_table WHERE coalesce((profile->>'kind_rules')::int, 0) < %s",
                               (KIND_RULES_VERSION,)).fetchone()[0]
    out = {"tables": n, "selected": sel, "rows": int(rows), "stat_value_bytes": int(size), "database_bytes": int(db),
           "old_kind_rules": int(old_rules),
           "bytes_per_row": round(size / rows, 1) if rows else None, "largest": [(k, int(r), str(t)) for k, r, t in top]}
    log(f"[status] 표 {n} (selected {sel}) · 행 {int(rows):,} · 값 {size / 2**30:.2f} GiB · DB 전체 {db / 2**30:.2f} GiB"
        + (f" · 행당 {out['bytes_per_row']} B" if rows else ""))
    for k, r, t in out["largest"]:
        log(f"  {k:28s} {r:>12,}  {t}")
    if old_rules:
        log(f"[status] 분류 판정 규칙(KIND_RULES_VERSION={KIND_RULES_VERSION})보다 옛 규칙으로 올린 표 {old_rules}개 "
            f"→ 팀 PC 에서 stats normalize --all → bundle → stats load --all")
    return out


def estimate(log=print):
    """PostgreSQL 에 올릴 크기 어림 (적재 전에 디스크가 충분한지)"""
    from backend.rag.ingestion.meta_profile import load_meta_profiles
    norm = {p["table_key"]: p for p, _, _ in local_profiles()}
    rows_known = sum(int((p.get("row_check") or {}).get("processed") or 0) for p in norm.values())
    rows_guess, raw_mb_missing, n_missing = 0, 0.0, 0
    try:
        metas = load_meta_profiles()
    except FileNotFoundError:
        metas = []
    for m in metas:
        if m["table_key"] in norm:
            continue
        mb = (m.get("raw") or {}).get("mb") or 0
        raw_mb_missing += mb
        n_missing += 1
        rows_guess += int(mb * 2**20 / RAW_BYTES_PER_ROW_GUESS)
    from backend.core.config import KOSIS_DATA_DIR
    raw_dir = Path(KOSIS_DATA_DIR) / "raw"
    raw_all = sum(f.stat().st_size for f in raw_dir.rglob("*.csv")) if raw_dir.exists() else 0
    raw_sel = sum(((m.get("raw") or {}).get("mb") or 0) for m in metas) * 2**20
    log(f"[estimate] 원본 CSV 전체 {raw_all / 2**30:.1f} GiB 중 검색 대상(selected) {len(metas)}개 표 "
        f"{raw_sel / 2**30:.1f} GiB — 서비스가 쓰는 것은 selected 표의 값")
    total = rows_known + rows_guess
    gib = total * ROW_BYTES_GUESS * 1.35 / 2**30      # 인덱스·여유 35%
    out = {"raw_all_gib": round(raw_all / 2**30, 1), "raw_selected_gib": round(raw_sel / 2**30, 1),
           "normalized_tables": len(norm), "normalized_rows": rows_known, "not_normalized_tables": n_missing,
           "not_normalized_raw_mb": round(raw_mb_missing), "rows_guess": rows_guess, "estimated_gib": round(gib, 1)}
    log(f"[estimate] 정규화된 표 {len(norm)} · 행 {rows_known:,}")
    log(f"[estimate] 아직 정규화 안 된 selected 표 {n_missing} · 원본 {raw_mb_missing / 1024:.1f} GiB → 행 약 {rows_guess:,}")
    log(f"[estimate] PostgreSQL 예상 약 {gib:.1f} GiB (행당 {ROW_BYTES_GUESS} B + 인덱스 35%, 적재 뒤 status 로 실제 확인)")
    return out


def verify(tables=None, sample=200, log=print):
    """parquet ↔ PostgreSQL: 행 수 · 값 합계 · 부호 수 · 표본 행(모든 열)"""
    import os
    from backend.core.utils import sql_str
    from backend.data_engine import stat_store
    from backend.data_engine.duckdb_client import connect
    os.environ["STAT_BACKEND"] = "postgres"
    bad, ok = [], 0
    dcon = connect()
    for prof, pq, _ in local_profiles(tables):
        pgp = stat_store.pg_profile(prof["tbl_id"])
        if pgp is None or pgp.get("table_key") != prof["table_key"]:
            continue
        rel_pq = f"read_parquet({sql_str(pq.as_posix())})"
        rel_pg = stat_store.relation(dcon, pgp, ())
        q = "SELECT count(*), round(coalesce(sum(value), 0), 3), count(symbol) FROM {}"
        a, b = dcon.execute(q.format(rel_pq)).fetchone(), dcon.execute(q.format(rel_pg)).fetchone()
        diff = []
        if tuple(a) != tuple(b):
            diff.append(f"요약 parquet={tuple(a)} pg={tuple(b)}")
        cols = [c[0] for c in dcon.execute(f"DESCRIBE SELECT * FROM {rel_pq}").fetchall()]
        sel = ", ".join(f'"{c}"' for c in cols)
        n_mis = dcon.execute(f"SELECT count(*) FROM (SELECT {sel} FROM {rel_pq} USING SAMPLE {int(sample)} ROWS "
                             f"EXCEPT SELECT {sel} FROM {rel_pg})").fetchone()[0] if sample else 0
        if n_mis:
            diff.append(f"표본 {sample}행 중 {n_mis}행이 다름 (이름 변형 코드일 수 있음 — load_report 확인)")
        if diff:
            bad.append((prof["table_key"], diff))
            log(f"[verify] 다름 {prof['table_key']}: {' / '.join(diff)}")
        else:
            ok += 1
    dcon.close()
    log(f"[verify] 같음 {ok} · 다름 {len(bad)}")
    return {"ok": ok, "different": bad}
