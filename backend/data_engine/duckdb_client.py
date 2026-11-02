"""
DuckDB 조회 — Record.source(좌표)로 parquet 수치를 다시 꺼낸다

  connect / one           : 구 view_model/config.py 에서 옮김 (내용 그대로)
  load_view               : 구 kosis_views.py 의 좌표 → DataFrame (backend/rag/ingestion/view_builder.py 에 그대로 있음, 여기서 다시 내보냄)
  load_record_data  [NEW] : 두 종류의 좌표를 모두 받는 진입점
      - View 모듈 Record.source   (file 기준 폴더 = VIEW_OUT_DIR,  period = {"in": ["2025", …]} ← 연도)
      - kosis_views 레코드 source  (file 기준 폴더 = RAG_VIEWS_DIR, period = {"in": [prd_de …]} | {"from","to"})

[입출력 보정] View 모듈 Record.source.period.in 은 '연도'(예: "2025") 인데 load_view 는 prd_de 와 비교한다.
            연간표는 prd_de == "2025" 라 맞지만 월·분기표(prd_de = "202501")는 0행이 된다.
            build_view 를 고치지 않고, 여기서 parquet 에 year 열이 있으면 연도로 거른다.
"""
import copy
import re
from pathlib import Path

import duckdb

from backend.core.config import RAG_VIEWS_DIR, VIEW_OUT_DIR
from backend.rag.ingestion.view_builder import load_view  # noqa: F401  (다시 내보냄)

_YEAR = re.compile(r"^\d{4}$")


def connect():
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
    except duckdb.Error:
        pass
    return con


def one(con, sql):
    # 결과 1행 조회. DuckDB 는 결과를 끝까지 읽지 않으면 같은 연결로 다음 작업을 못 하므로 fetchall 사용
    return con.execute(sql).fetchall()[0]


def base_dir_of(source):
    """source.file(상대 경로)이 실제로 있는 기준 폴더 (View 모듈 → kosis_views 순)"""
    f = source.get("file", "")
    for d in (VIEW_OUT_DIR, RAG_VIEWS_DIR):
        if (Path(d) / f).exists():
            return Path(d)
    raise FileNotFoundError(f"좌표 파일을 찾을 수 없음: {f} (VIEW_OUT_DIR={VIEW_OUT_DIR}, RAG_VIEWS_DIR={RAG_VIEWS_DIR})")


def load_record_data(record_or_source, con=None, limit=None):
    """Record(dict) 또는 source(dict) → 정렬된 DataFrame"""
    src = record_or_source.get("source", record_or_source)
    src = copy.deepcopy(src)
    base = base_dir_of(src)
    years = None
    per = src.get("period") or {}
    if per.get("in") and all(_YEAR.match(str(x)) for x in per["in"]):
        cols = {c[0] for c in (con or duckdb).execute(
            f"DESCRIBE SELECT * FROM read_parquet('{(base / src['file']).as_posix()}')").fetchall()}
        if "year" in cols and src.get("prd_se") not in ("Y", "F", "IR", None):
            years = {int(x) for x in per["in"]}
            src["period"] = {}                      # prd_de 비교 대신 아래에서 year 로 거름
    df = load_view(src, base, con)
    if years is not None:
        df = df[df["year"].isin(years)].reset_index(drop=True)
    return df.head(limit) if limit else df
