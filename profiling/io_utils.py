"""
공용 입출력: DuckDB 연결, raw CSV 읽기, 표별 결과 캐시, 결과 저장

raw 는 베이스라인(kosis_views.prepare_table)과 똑같은 옵션(all_varchar, header)으로 읽는다.
읽는 방식이 다르면 '베이스라인이 보는 데이터'와 '프로파일링이 본 데이터'가 달라지기 때문이다.
"""
import json
import logging

import duckdb
import pandas as pd

from profiling import config
from profiling.baseline import sql_str

log = logging.getLogger("profiling")


def setup_logging(verbose=False):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")


def connect():
    """대용량 CSV 스트리밍 집계용 DuckDB 연결 (메모리 상한을 넘으면 임시 폴더로 내려씀)"""
    config.DUCKDB_TMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads = {config.DUCKDB_THREADS}")
    con.execute(f"SET memory_limit = {sql_str(config.DUCKDB_MEMORY_LIMIT)}")
    con.execute(f"SET temp_directory = {sql_str(config.DUCKDB_TMP.as_posix())}")
    con.execute("SET preserve_insertion_order = false")      # 집계만 하므로 순서 보존 불필요 → 메모리 절약
    return con


def read_csv_sql(path):
    """raw CSV 를 읽는 SQL 조각 (베이스라인과 같은 옵션)"""
    return f"read_csv({sql_str(path.as_posix())}, all_varchar=true, header=true)"


def csv_columns(con, path):
    return [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {read_csv_sql(path)}").fetchall()]


def file_sig(path):
    """캐시 유효성 판단용 서명: 크기 + 수정시각이 같으면 내용도 같다고 본다"""
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def cached(check, key, sources, compute, force=False):
    """표 하나의 체크 결과를 JSON 으로 캐시. sources(입력 파일들)가 바뀌면 다시 계산한다.

    19GB 이동통계를 매번 다시 훑지 않기 위한 장치. 결과는 JSON 직렬화 가능한 dict 여야 한다."""
    sig = {p.name: file_sig(p) for p in sources if p.exists()}
    cp = config.CACHE_DIR / check / f"{key}.json"
    if cp.exists() and not force:
        try:
            c = json.loads(cp.read_text(encoding="utf-8"))
            if c.get("_sig") == sig:
                return c["result"]
        except (json.JSONDecodeError, KeyError):
            pass                                              # 깨진 캐시는 다시 계산
    result = compute()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"_sig": sig, "result": result}, ensure_ascii=False, default=str),
                  encoding="utf-8")
    return result


def write_csv(df, name):
    """output/<name>.csv 저장 (엑셀에서 한글이 깨지지 않게 utf-8-sig)"""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = config.OUTPUT_DIR / f"{name}.csv"
    pd.DataFrame(df).to_csv(p, index=False, encoding="utf-8-sig")
    return p
