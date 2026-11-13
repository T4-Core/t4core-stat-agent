"""[NEW] chart 테스트들이 함께 쓰는 가짜 View (파일 이름이 test_ 로 시작하지 않아 pytest 가 실행하지 않는다)"""
from backend.schemas.record import Record

VID = "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
COLS = ["시점", "행정구역별", "항목", "값"]

# 명세 시나리오의 수치 (혼인건수·출생아수). 조혼인율과 서울 행은 설명용
ROWS = [
    ["2021", "전국", "혼인건수(건)", 192507.0], ["2021", "전국", "출생아수(명)", 260562.0],
    ["2022", "전국", "혼인건수(건)", 191690.0], ["2022", "전국", "출생아수(명)", 249186.0],
    ["2023", "전국", "혼인건수(건)", 193657.0], ["2023", "전국", "출생아수(명)", 230028.0],
    ["2024", "전국", "혼인건수(건)", 222412.0], ["2024", "전국", "출생아수(명)", 238317.0],
    ["2025", "전국", "혼인건수(건)", 240326.0], ["2025", "전국", "출생아수(명)", 254341.0],
    ["2025", "전국", "조혼인율(천명당)", 4.7],
    ["2025", "서울특별시", "혼인건수(건)", None],
]


def view(rows=None, columns=None, rid=VID, notes=None, **meta) -> Record:
    return Record.model_validate({
        "id": rid, "lexical_text": "인구동태건수 및 동태율", "parent_id": "table::101_DT_1B8000G",
        "table": {"columns": columns or COLS, "rows": ROWS if rows is None else rows},
        "metadata": {"prd_se": "Y", "view_type": "trend", **meta}, "notes": notes or []})


TRUNCATED = {"slot": "행수", "type": "truncated", "applied": 2000, "text": "행이 2000개를 넘어 앞부분만 사용"}
