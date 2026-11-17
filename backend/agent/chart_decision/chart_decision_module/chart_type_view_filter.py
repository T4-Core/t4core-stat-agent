"""①-1 View 필터링 (노트북 3번)

SLOT_KEYS 슬롯마다 값이 든 열을 찾아 글자가 같은 행만 남긴다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import copy
import re

from .chart_type_rules import SLOT_KEYS


def filter_view(view, sub_filter, filters, slot_keys=SLOT_KEYS):
    """SLOT_KEYS의 슬롯마다 값이 든 열을 찾아, 그 값과 글자가 같은 행만 남긴 View 복사본을 반환한다.

    - 슬롯 값은 sub_filter에서 먼저 찾고, 없으면 filters(전체 질문)에서 찾는다. (예: 지역)
    - 시점은 숫자만 남겨 비교한다: '2021년' → '2021'
    - 나머지 슬롯은 단위 괄호·공백을 지우고 비교한다: '혼인건수(건)' → '혼인건수'
    - 값이 든 열이 없는 슬롯은 거르지 않고 건너뛴다. (예: 대상 '혼인', 비교축 '연도')
    - 원본 View는 바꾸지 않는다. 결과 View에 filter_info를 붙인다.
    """
    def as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def clean_label(s):                       # '혼인건수(건)' → '혼인건수'
        return re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", str(s)))

    def clean_period(p):                      # '2021년' → '2021'
        return re.sub(r"\D", "", str(p))

    def label_unit(s):                        # '혼인건수(건)' → '건'
        m = re.search(r"\((.*?)\)", str(s))
        return m.group(1) if m else None

    def find_col(columns, rows, targets, clean, skip):
        """정리한 값 중 targets가 하나라도 있는 첫 번째 열의 (이름, 위치)"""
        for i, col in enumerate(columns):
            if col in skip:
                continue
            if any(clean(r[i]) in targets for r in rows):
                return col, i
        return None, None

    view = copy.deepcopy(view)
    table = view["record"]["table"]
    columns, rows = table["columns"], table["rows"]

    used_cols = {"값"}            # 값 열은 비교하지 않음, 한 열은 한 슬롯만
    slot_cols, unmatched = {}, []

    for key in slot_keys:
        values = as_list(sub_filter.get(key)) or as_list(filters.get(key))
        if not values:
            continue
        clean = clean_period if key == "시점" else clean_label
        targets = {clean(v) for v in values} - {""}
        col, ci = find_col(columns, rows, targets, clean, skip=used_cols)
        if col is None:
            unmatched.append(key)
            continue
        rows = [r for r in rows if clean(r[ci]) in targets]
        slot_cols[key] = col
        used_cols.add(col)

    # 단위: 지표 열의 괄호에서
    ind_col = slot_cols.get("지표")
    units = []
    if ind_col is not None:
        ii = columns.index(ind_col)
        units = sorted({label_unit(r[ii]) for r in rows if label_unit(r[ii])})

    table["rows"] = rows
    view["filter_info"] = {
        "indicator_col": ind_col,
        "indicators": as_list(sub_filter.get("지표")),
        "unit": units[0] if len(units) == 1 else (units or None),
        "slot_cols": slot_cols,          # 슬롯 → 값이 든 열
        "unmatched_slots": unmatched,    # 값은 있지만 맞는 열이 없어 거르지 않은 슬롯
    }
    return view
