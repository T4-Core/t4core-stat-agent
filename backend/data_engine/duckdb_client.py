"""
DuckDB 조회 — Record.source(좌표)로 정규화 parquet 의 수치를 다시 꺼낸다

  source = {"file", "prd_se", "itm_id": [...], "dims": {"c1": {"codes": [...]} | {"depth": d, "exclude_total": true}},
            "period": {"in": [...]} | {"from": .., "to": ..}}

source.period.in 은 연도("2025")로 기록된다. 연간표는 prd_de 와 그대로 비교하고,
월·분기·반기표는 parquet 의 year 열로 거른다 (prd_de = "202501" 이라 그대로 비교하면 0행).
"""
import re
from pathlib import Path

import duckdb

from backend.core.config import VIEW_OUT_DIR
from backend.core.utils import sql_str

_YEAR = re.compile(r"^\d{4}$")
ANNUAL = ("Y", "F", "IR", None)


def connect():
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
    except duckdb.Error:
        pass
    return con


def one(con, sql):
    # 결과를 끝까지 읽지 않으면 같은 연결로 다음 작업을 못 하므로 fetchall
    return con.execute(sql).fetchall()[0]


def load_record_data(record_or_source, con=None, limit=None):
    """Record(dict) 또는 source(dict) → 정렬된 DataFrame"""
    src = record_or_source.get("source", record_or_source)
    path = Path(VIEW_OUT_DIR) / src.get("file", "")
    if not path.exists():
        raise FileNotFoundError(f"좌표 파일을 찾을 수 없음: {path}")
    con = con or connect()
    rel = f"read_parquet({sql_str(path.as_posix())})"
    cols = {c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}

    w = [f"prd_se = {sql_str(src['prd_se'])}"]
    if src.get("itm_id"):
        w.append(f"itm_id IN ({', '.join(map(sql_str, src['itm_id']))})")
    for c, s in (src.get("dims") or {}).items():
        if "codes" in s:
            w.append(f"{c}_code IN ({', '.join(map(sql_str, s['codes']))})")
        if "depth" in s:
            w.append(f"{c}_depth = {int(s['depth'])}")
        if s.get("exclude_total"):
            w.append(f"NOT {c}_total")
    p = src.get("period") or {}
    if p.get("in"):
        years = all(_YEAR.match(str(x)) for x in p["in"])
        if years and "year" in cols and src.get("prd_se") not in ANNUAL:
            w.append(f"year IN ({', '.join(str(int(x)) for x in p['in'])})")
        else:
            w.append(f"prd_de IN ({', '.join(map(sql_str, p['in']))})")
    if "from" in p:
        w.append(f"prd_de >= {sql_str(p['from'])}")
    if "to" in p:
        w.append(f"prd_de <= {sql_str(p['to'])}")

    df = con.execute(f"SELECT * FROM {rel} WHERE {' AND '.join(w)}").df()
    sort = [c for c in ["period_date", *sorted(c for c in df.columns if re.fullmatch(r"c\d_ord", c)), "itm_ord"]
            if c in df.columns]
    df = df.sort_values(sort, kind="stable").reset_index(drop=True) if sort else df
    return df.head(limit) if limit else df
