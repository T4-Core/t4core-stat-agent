"""③ 데이터 모양 파악 (노트북 5번)

걸러진 View에서 재료(시점, 범주·계열, 수치, 구성비, 추가 수치, 지역코드)를 뽑는다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import re

from .chart_type_axes import TIME, classify_dims
from .chart_type_rules import TOTAL_WORDS


def profile_data(view, sub_filter, filters, intents=None):
    """걸러진 View에서 차트 판단에 필요한 재료를 뽑는다. 반환: profile(dict)
    intents: 질문 의도 목록 (고도화 2단계 — 추이면 시점을 범주로, 비교·순위·구성비면 안전장치에 씀)"""
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

    # ── 2. 범주·계열: 시점·값·지표 열을 뺀 열 중 값이 2개 이상인 열 = 나누는 기준 후보 ──
    all_dims = []
    for col in columns:
        if col in (time_col, value_col, ind_col):
            continue
        vals = distinct(col)
        if len(vals) >= 2:
            all_dims.append({"name": col_slot.get(col, col), "col": col, "values": vals, "n": len(vals)})
    # [고도화 2단계] 질문이 요청한 나눔만 범주·계열로 (연령 범위 구성 요소 · 요청하지 않은 열은 뺀다)
    dims, excluded, axis_notes, req_axes = classify_dims(all_dims, sub_filter, filters, intents)

    # ── 3. 수치 ─────────────────────────────
    ind_labels = distinct(ind_col) if ind_col else []
    indicators = [clean_label(x) for x in ind_labels] or as_list(sub_filter.get("지표"))
    units = {clean_label(x): label_unit(x) for x in ind_labels}
    nums = [to_num(r[columns.index(value_col)]) for r in rows]

    # ── 4. 구성비: 바로 들어 있는 경우는 드물어 '계산할 수 있는가'를 본다 ──
    non_negative = bool(nums) and all(v is not None and v >= 0 for v in nums)
    total_rows = [f"{d['col']}={v}" for d in all_dims for v in d["values"] if clean_label(v) in TOTAL_WORDS]
    has_total = bool(total_rows)

    # ── 5. 추가 수치: 지표가 2개 이상이고 단위가 다른가 ──
    unit_set = {u for u in units.values() if u}
    units_differ = len(unit_set) >= 2

    # ── 6. 지역코드: 지역 열이 있고 2곳 이상일 때, source.dims의 분류 코드(열 순서대로 c1, c2…로 추정) ──
    region_col = slot_cols.get("지역")
    regions = distinct(region_col) if region_col else (as_list(sub_filter.get("지역")) or as_list(filters.get("지역")))
    # [고도화 3단계] 지역 슬롯('전국')이 표의 열과 맞지 않아도, 요청한 나눔 중 지역 축 열(예: 시도 17곳)이 있으면 그 열로 센다
    region_dim = next((d for d in dims if d.get("axis") == "지역"), None)
    if region_dim and region_dim["n"] > len(regions):
        region_col, regions = region_dim["col"], list(region_dim["values"])
    class_cols = [c for c in columns if c not in (time_col, value_col, "항목")]
    region_codes = []
    if region_col in class_cols:
        key = f"c{class_cols.index(region_col) + 1}"
        region_codes = (source.get("dims", {}).get(key) or {}).get("codes", [])
    has_region_code = len(regions) >= 2 and len(region_codes) >= 2

    # ── 6번 CHART_CONDITIONS용 범주·계열 [고도화 2단계: 요청한 나눔 기준] ──
    #   시점을 요청했거나(비교축 연도 · 의도 추이) 다른 나눔이 없으면 → 범주 = 시점, 계열 = 첫 번째 나눔
    #   아니면 → 범주 = 첫 번째 나눔, 계열 = 두 번째 나눔 / 계열이 없으면 지표가 여럿일 때 지표 수, 아니면 1
    time_axis = len(periods) >= 2 and (TIME in req_axes or "추이" in (intents or []) or not dims)
    if time_axis:
        category = {"axis": TIME, "col": time_col, "n": len(periods)}
        series_dim = dims[0] if dims else None
    else:
        category = {"axis": dims[0]["axis"], "col": dims[0]["col"], "n": dims[0]["n"]} if dims else             {"axis": TIME, "col": time_col, "n": len(periods)}
        series_dim = dims[1] if len(dims) >= 2 else None
    n_categories = category["n"]
    n_series = series_dim["n"] if series_dim else (len(indicators) if len(indicators) >= 2 else 1)

    return {
        # 1. 시점
        "has_time": len(periods) >= 2,
        "prd_se": prd_se,
        "n_points": len(periods),
        "periods": periods,
        "time_continuous": time_continuous,
        # 2. 범주·계열
        "dims": dims,                                                    # 요청한 나눔만 (고도화 2단계)
        "n_dims": len(dims) + (1 if len(periods) >= 2 else 0),         # 시점도 차원 하나로 셈
        "requested_axes": req_axes,                                    # 질문이 요청한 나눔
        "category_axis": category,                                     # {"axis", "col", "n"}
        "series_axis": ({"axis": series_dim["axis"], "col": series_dim["col"], "n": series_dim["n"]}
                        if series_dim else None),
        "excluded_dims": [{"col": d["col"], "n": d["n"], "kind": d["kind"]} for d in excluded],
        "axis_notes": axis_notes,                                      # 범주에서 뺀 열 · 안전장치 메모
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
