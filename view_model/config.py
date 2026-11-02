"""
View 모듈 공통 설정 — 모든 엔드포인트(.py)가 같은 경로·대상 표·공용 함수를 쓰도록 한 곳에 모음

  ROOT : 저장소 루트 (kosis_data 폴더가 있는 곳)
  DATA : 입력 (kosis_data, 읽기 전용)
  OUT  : 출력 (view_model/output, 이 폴더 밖에는 쓰지 않음)
"""
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "kosis_data"
OUT = Path(__file__).resolve().parent / "output"

# 표 탐색 범위는 카탈로그 전체(selected == True, 992개) — meta_profile.py 가 만든 meta_profiles.jsonl
# 표 목록을 코드에 두지 않는다. 정규화는 resolve 가 고른 표만 normalize.ensure_normalized() 가 그때 한다.


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


def safe(name):
    # 폴더/파일명에 쓸 수 없는 문자 치환 (kosis_rag_builder 가 raw 폴더를 만들 때 쓴 규칙과 같아야 경로가 맞음)
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


def sql_str(s):
    # SQL 문자열 리터럴 (작은따옴표 이스케이프)
    return "'" + str(s).replace("'", "''") + "'"


def norm_space(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()
