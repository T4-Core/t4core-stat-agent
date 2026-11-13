"""[NEW] select.py — 행 선택과 검증 ① (데이터 존재)"""
import pytest

from backend.agent.chart_calculate.select import find_item_column, select_rows, to_number
from tests.chart_calculate._views import COLS, ROWS, TRUNCATED, view


@pytest.mark.parametrize("raw, want", [
    (192507.0, 192507.0), (5, 5), ("1,234", 1234.0), (None, None), ("-", None), ("…", None), ("", None),
    (float("nan"), None), ("비공개", None), (True, None)])
def test_to_number(raw, want):
    assert to_number(raw) == want


def test_select_by_dims_and_item():
    sel = select_rows(view(), {"행정구역별": ["전국"], "시점": ["2021", "2025"]}, item="혼인건수(건)")
    assert sel.ok and [(r[0], r[3]) for r in sel.rows] == [("2021", 192507.0), ("2025", 240326.0)]


def test_select_compares_as_text():
    """LLM 이 시점을 숫자로 줘도 같은 행을 고른다"""
    assert len(select_rows(view(), {"시점": [2021]}, item="혼인건수(건)").rows) == 1


def test_item_overrides_same_column_condition():
    """combo: 상위 select 는 항목 둘, 피연산자 item 은 그중 하나"""
    sel = select_rows(view(), {"항목": ["혼인건수(건)", "조혼인율(천명당)"], "시점": ["2025"], "행정구역별": ["전국"]},
                      item="조혼인율(천명당)")
    assert [r[3] for r in sel.rows] == [4.7]


def test_item_matches_without_unit_suffix():
    assert find_item_column(COLS, ROWS, "혼인건수") == ("항목", "혼인건수(건)")
    assert select_rows(view(), {"시점": ["2021"]}, item="혼인건수").ok


def test_item_found_in_dimension_column():
    """명세 예시처럼 항목 값이 분류 열에 들어 있는 View"""
    rows = [["2025", "혼인건수(건)", 240326.0], ["2025", "출생아수(명)", 254341.0]]
    sel = select_rows(view(rows, ["시점", "종류별", "값"]), item="출생아수(명)")
    assert sel.ok and sel.rows == [["2025", "출생아수(명)", 254341.0]]


def test_missing_value_rows_are_dropped_not_errors():
    sel = select_rows(view(), {"시점": ["2025"]}, item="혼인건수(건)")
    assert sel.ok and len(sel.rows) == 1
    assert sel.dropped == [{"시점": "2025", "행정구역별": "서울특별시", "항목": "혼인건수(건)"}]


def test_only_missing_values_is_error():
    sel = select_rows(view(), {"행정구역별": ["서울특별시"]}, item="혼인건수(건)")
    assert not sel.ok and sel.errors == ["조건에 맞는 값이 없음"]


@pytest.mark.parametrize("select, item, part", [
    ({"시점": ["2021", "2030"]}, None, "시점에 없는 값: ['2030']"),
    ({"성별": ["남자"]}, None, "열 없음: 성별"),
    (None, "사망자수(명)", "항목 없음: 사망자수(명)"),
])
def test_reports_what_is_absent(select, item, part):
    sel = select_rows(view(), select, item)
    assert not sel.ok and part in sel.errors


def test_truncated_view_is_not_ok():
    sel = select_rows(view(notes=[TRUNCATED]), {"시점": ["2021"]}, item="혼인건수(건)")
    assert not sel.ok and sel.errors[0].startswith("truncated") and sel.rows   # 행은 주되 계산에는 쓰지 않는다
