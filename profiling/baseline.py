"""
베이스라인(kosis_views.py) 어댑터

프로파일링은 베이스라인이 데이터를 '어떻게 해석하는지'를 그대로 따라야 진단이 의미가 있다.
그래서 메타 해석·합계 판정·파일명 규칙을 다시 만들지 않고 kosis_views 의 함수를 가져다 쓴다.
베이스라인 파일은 수정하지 않는다. (버그를 찾으면 summary.md 에 기록하고 수정은 제안만)

kosis_rag_builder.py / kosis_rag_qa.py 는 import 시 .env 를 읽으므로 여기서는 가져오지 않는다.
"""
import json
import sys

import pandas as pd

from profiling import config

if str(config.REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(config.REPO_ROOT))

import kosis_views as kv  # noqa: E402

# 베이스라인과 같은 규칙을 쓰기 위해 그대로 노출
meta_levels = kv.meta_levels          # ITM 메타 → (분류 레벨, 항목)
dims_frame = kv.dims_frame            # 레벨별 코드 사전 (순서·깊이·합계 여부)
level_kind = kv.level_kind            # 분류 종류: geo / sex / age / other
is_ordinal = kv.is_ordinal            # 순서형 분류(연령 등) 판정
prepare_table = kv.prepare_table      # raw → processed parquet + profile json
safe = kv.safe                        # raw 폴더명 규칙
sql_str = kv.sql_str                  # SQL 문자열 이스케이프
TOTAL_RE = kv.TOTAL_RE
GEO_RE = kv.GEO_RE
SE_NORM = kv.SE_NORM                  # 주기 표기 정규화 SQL (A/년 → Y 등)
MAX_ITEMS = kv.MAX_ITEMS              # 표당 뷰를 만드는 대표 항목 수 (L4 커버리지 진단 기준)
MAX_BREAKDOWN_ITEMS = kv.MAX_BREAKDOWN_ITEMS
MAX_VIEWS = kv.MAX_VIEWS

SCHEMA_COLS = ["org_id", "tbl_id", "dimensions", "items", "n_items", "prd_se", "prd_range",
               "est_cells_per_period", "est_cells_total"]


def load_tables(categories=None, tables=None, max_tables=None):
    """catalog.csv(selected=True) + table_schema.csv → 담당 범위의 표 목록 (표 1개 = 1행)

    kv.load_catalog 와 같은 필터 규칙이고, 스키마 요약 컬럼을 붙인다. 코드가 '01' → 1 로
    바뀌지 않도록 모두 문자열로 읽는다."""
    cat = pd.read_csv(config.DATA_DIR / "catalog.csv", dtype=str)
    cat = cat[cat["selected"] == "True"]
    cat = cat[cat["category"].isin(categories or config.CATEGORIES)]
    if tables:
        cat = cat[cat["tbl_id"].isin(tables)]
    if max_tables:
        cat = cat.head(max_tables)
    sch_p = config.DATA_DIR / "table_schema.csv"
    if sch_p.exists():
        sch = pd.read_csv(sch_p, dtype=str)[SCHEMA_COLS]
        cat = cat.merge(sch, on=["org_id", "tbl_id"], how="left")
    return cat.reset_index(drop=True)


def table_key(row):
    return f"{row.org_id}_{row.tbl_id}"


def raw_path(row):
    return config.DATA_DIR / "raw" / safe(row.category) / f"{table_key(row)}.csv"


def meta_path(row):
    return config.DATA_DIR / "meta" / f"{table_key(row)}.json"


def processed_path(row, views_dir=None):
    return (views_dir or config.VIEWS_DIR) / "processed" / f"{table_key(row)}.parquet"


def profile_path(row, views_dir=None):
    return (views_dir or config.VIEWS_DIR) / "profiles" / f"{table_key(row)}.json"


def load_meta(row):
    """meta json → dict (없거나 깨졌으면 빈 dict, 베이스라인과 같은 동작)"""
    p = meta_path(row)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
