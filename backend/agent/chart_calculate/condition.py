"""
[NEW 11-20] 질문의 조건(Filters.조건식)을 View 의 열에 연결한다 (KOS-26 A-2)

  '혼인상태=미혼' · '점유형태=보증부월세' 같은 분류 조건이 **어느 열**에 적용되는지 정하고, 고른 행이 모두 그 값인지 확인한다.
  값이 같다는 이유만으로 다른 열을 대신 쓰지 않는다:
    '가구주연령=30~39세' 인데 View 에 '배우자연령' 열만 있고 거기 '30~39세' 가 있어도 적용한 것이 아니다 (다른 모집단).

  축을 찾는 규칙
    field 있음   열 이름이 field 와 같거나(공백 · '의' · '별' 정규화), 아래 AXIS_SYNONYMS 에 적힌 동의어인 열만.
                 예외: 이름 없는 '항목' 열 — 항목 값이 조건 값과 정확히 같고 그 항목이 지표 대응 검사를 별칭으로 통과했을 때만
                 ('점유형태=보증부월세' ↔ 항목 '보증부월세')
    field 없음   고유값에 조건 값이 **정확히** 있는 열이 하나일 때만. 둘 이상이면 모호하다고 본다. 부분 문자열 일치는 쓰지 않는다
"""
import re
from dataclasses import dataclass

from backend.agent.chart_calculate.select import ITEM_COL, VALUE_COL, find_item_column, select_rows
from backend.core.korean import strip_unit
from backend.schemas.record import Record

# 정규화한 열 이름 → 같은 축으로 보는 정규화 이름. 처음에는 골든셋 · 리포트에 나온 쌍만 둔다.
# 표에 없는 쌍은 보류로 나온다 (보류 사유에 field 와 View 의 열 목록이 남으므로 거기서 보강한다)
AXIS_SYNONYMS: dict[str, set[str]] = {
    "혼인상태": {"혼인상태", "혼인"},
    "점유형태": {"점유형태", "점유"},
    "세대구성": {"세대구성", "가구구성"},
    "가구구성": {"세대구성", "가구구성"},
    "거처종류": {"거처종류", "주택종류"},
}
_NORM = re.compile(r"\([^()]*\)|[\s의]")


def norm_axis(name: str) -> str:
    """'거처의 종류' → '거처종류', '행정구역(시군구)별' → '행정구역'. 끝의 '별' 은 뗀다"""
    t = _NORM.sub("", str(name))
    return t[:-1] if t.endswith("별") and len(t) > 2 else t


@dataclass
class Axis:
    column: str | None
    why: str = ""          # column 이 None 일 때 사유 (note 용)


def find_axis(rec: Record, cond: dict, alias_items: set[str]) -> Axis:
    """조건 하나가 적용될 열. alias_items = 이 View 에서 지표 대응 검사를 별칭 경로로 통과한 항목들"""
    cols = [c for c in rec.table.columns if c != VALUE_COL]
    field, value = cond.get("field"), str(cond["value"])
    if field:
        want = {norm_axis(field), *(norm_axis(x) for x in AXIS_SYNONYMS.get(norm_axis(field), ()))}
        hit = [c for c in cols if c != ITEM_COL and norm_axis(c) in want]
        if len(hit) == 1:
            return Axis(hit[0]) if _has_value(rec, hit[0], value) else Axis(None, f"열 '{hit[0]}' 에 값 '{value}' 없음")
        if len(hit) > 1:
            return Axis(None, f"조건 '{field}' 에 해당하는 열이 여럿: {hit}")
        if ITEM_COL in cols and any(strip_unit(i) == strip_unit(value) for i in alias_items):
            return Axis(ITEM_COL)
        return Axis(None, f"조건 '{field}' 에 해당하는 열이 없음 (표의 열: {cols})")
    hit = [c for c in cols if _has_value(rec, c, value)]
    if len(hit) == 1:
        return Axis(hit[0])
    return Axis(None, f"값 '{value}' 을 가진 열이 {'없음' if not hit else f'여럿: {hit}'}")


def _has_value(rec: Record, col: str, value: str) -> bool:
    i = rec.table.columns.index(col)
    return any(str(r[i]) == value or (col == ITEM_COL and strip_unit(str(r[i])) == strip_unit(value)) for r in rec.table.rows)


def selected_values(rec: Record, select: dict, item: str | None, col: str) -> set[str] | None:
    """고른 행들이 col 에서 가진 값 집합. 행을 고를 수 없으면 None (다른 검증이 사유를 낸다)"""
    sel = select_rows(rec, select, item)
    if not sel.rows or col not in sel.columns:
        return None
    i = sel.col(col)
    return {str(r[i]) for r in sel.rows}


def item_column_value(rec: Record, item: str | None) -> str | None:
    hit = find_item_column(list(rec.table.columns), rec.table.rows, item) if item else None
    return str(hit[1]) if hit else None
