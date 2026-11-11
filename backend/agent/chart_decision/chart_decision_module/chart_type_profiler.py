"""③ 데이터 모양 파악 (노트북 5번)

걸러진 View에서 재료(시점, 범주·계열, 수치, 구성비, 추가 수치, 지역코드)를 뽑는다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import re

from .chart_type_rules import TOTAL_WORDS


def profile_data(view, sub_filter, filters):
    """걸러진 View에서 차트 판단에 필요한 재료를 뽑는다. 반환: profile(dict)"""
    def as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def clean_label(s):                       # '혼인건수(건)' → '혼인건수'
        return re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", str(s)))

    def label_unit(s):                        # '혼인건수(건)' → '건'
        m = re.search(r"\((.*?)\)", str(s))
        return m.group(1).strip() if m else None

    def to_num(x):
        try:
            return float(str(x).replace(",", ""))
        except (TypeError, ValueError):
            return None

    meta = view["record"]["metadata"]
    source = view["record"]["source"]
    table = view["record"]["table"]
    columns, rows = table["columns"], table["rows"]
    finfo = view.get("filter_info") or {}
    slot_cols = finfo.get("slot_cols", {})
    col_slot = {c: s for s, c in slot_cols.items()}                    # 열 → 슬롯 이름

    def distinct(col):
        i = columns.index(col)
        return list(dict.fromkeys(str(r[i]) for r in rows))

    time_col = slot_cols.get("시점", "시점" if "시점" in columns else None)
    value_col = "값" if "값" in columns else columns[-1]
    ind_col = finfo.get("indicator_col")

    # ── 1. 시점 ─────────────────────────────
    periods = distinct(time_col) if time_col else []
    if not periods:                                                    # 표에 없으면 filters에서
        periods = [re.sub(r"\D", "", str(p)) for p in (as_list(sub_filter.get("시점")) or as_list(filters.get("시점")))]
    prd_se = meta.get("prd_se")
    time_continuous = None                                             # 연간만 연속 여부 판단
    if prd_se == "Y" and len(periods) >= 2 and all(p.isdigit() for p in periods):
        ys = sorted(int(p) for p in periods)
        time_continuous = all(b - a == 1 for a, b in zip(ys, ys[1:]))

    # ── 2. 범주·계열: 시점·값·지표 열을 뺀 열 중 값이 2개 이상인 열 = 나누는 기준 ──
    dims = []
    for col in columns:
        if col in (time_col, value_col, ind_col):
            continue
        vals = distinct(col)
        if len(vals) >= 2:
            dims.append({"name": col_slot.get(col, col), "col": col, "values": vals, "n": len(vals)})

    # ── 3. 수치 ─────────────────────────────
    ind_labels = distinct(ind_col) if ind_col else []
    indicators = [clean_label(x) for x in ind_labels] or as_list(sub_filter.get("지표"))
    units = {clean_label(x): label_unit(x) for x in ind_labels}
    nums = [to_num(r[columns.index(value_col)]) for r in rows]

    # ── 4. 구성비: 바로 들어 있는 경우는 드물어 '계산할 수 있는가'를 본다 ──
    non_negative = bool(nums) and all(v is not None and v >= 0 for v in nums)
    total_rows = [f"{d['col']}={v}" for d in dims for v in d["values"] if clean_label(v) in TOTAL_WORDS]
    has_total = bool(total_rows)

    # ── 5. 추가 수치: 지표가 2개 이상이고 단위가 다른가 ──
    unit_set = {u for u in units.values() if u}
    units_differ = len(unit_set) >= 2

    # ── 6. 지역코드: 지역 열이 있고 2곳 이상일 때, source.dims의 분류 코드(열 순서대로 c1, c2…로 추정) ──
    region_col = slot_cols.get("지역")
    regions = distinct(region_col) if region_col else (as_list(sub_filter.get("지역")) or as_list(filters.get("지역")))
    class_cols = [c for c in columns if c not in (time_col, value_col, "항목")]
    region_codes = []
    if region_col in class_cols:
        key = f"c{class_cols.index(region_col) + 1}"
        region_codes = (source.get("dims", {}).get(key) or {}).get("codes", [])
    has_region_code = len(regions) >= 2 and len(region_codes) >= 2

    # ── 6번 CHART_CONDITIONS용 기본값 (역할 배정은 6번에서 바꿀 수 있음) ──
    #   범주 = 값이 가장 많은 나누는 기준, 없으면 시점 / 계열 = 두 번째 기준 또는 지표 여러 개
    dims_sorted = sorted(dims, key=lambda d: -d["n"])
    n_categories = dims_sorted[0]["n"] if dims_sorted else len(periods)
    n_series = dims_sorted[1]["n"] if len(dims_sorted) >= 2 else (len(indicators) if len(indicators) >= 2 else 1)

    return {
        # 1. 시점
        "has_time": len(periods) >= 2,
        "prd_se": prd_se,
        "n_points": len(periods),
        "periods": periods,
        "time_continuous": time_continuous,
        # 2. 범주·계열
        "dims": dims,
        "n_dims": len(dims) + (1 if len(periods) >= 2 else 0),         # 시점도 차원 하나로 셈
        "n_categories": n_categories,
        "n_series": n_series,
        "has_region": len(regions) >= 2,
        "n_regions": len(regions),
        "geo_level": meta.get("geo_level"),
        # 3. 수치
        "indicators": indicators,
        "n_indicators": len(indicators),
        "units": units,
        "n_values": len(nums),
        # 4. 구성비
        "non_negative": non_negative,
        "has_total": has_total,
        "total_rows": total_rows,
        "share_possible": non_negative and has_total,
        # 5. 추가 수치
        "n_measures": len(indicators),
        "units_differ": units_differ,
        # 6. 지역코드
        "has_region_code": has_region_code,
        "region_codes": region_codes,
        # 덤벨용: 비교 대상이 정확히 2개
        "two_points_per_category": len(periods) == 2 or any(d["n"] == 2 for d in dims),
    }
