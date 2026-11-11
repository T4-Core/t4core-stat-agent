"""규칙·사전 (노트북 3·4·5·6·8번의 상수)

차트 종류나 키워드를 늘릴 때는 판단 코드가 아니라 이 파일만 고친다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
# ── ①-1 View 필터링 (노트북 3번) ──
SLOT_KEYS = ["시점", "지역", "전출지", "전입지", "국적", "대상", "성별", "연령", "조건", "이동", "지표", "비교축"]

# ── ② measure (노트북 4번) ──
MEASURES = ["raw", "change", "growth_rate", "cagr", "index", "share",
            "diff", "ratio", "rank", "extreme", "aggregate"] # 11개

OUT_OF_SCOPE = "범위 밖"                         # 데이터로 답할 수 없는 질문

MEASURE_CHOICES = MEASURES + [OUT_OF_SCOPE]       # LLM이 고를 수 있는 값 (11개 + 범위 밖)

# INTENTS 키워드 → measure (재작성 질문 끝에 붙는 키워드)
# None이면 규칙이 정하지 않고 LLM이 원 질문·재작성 질문을 보고 채운다
INTENT_TO_MEASURE = {
    "값 조회": "raw", "추이": "raw", "비교": "raw",
    "증감": "change", "증감률": "growth_rate",
    "구성비": "share", "순위": "rank", "합계": "aggregate",
    "범위 밖": None, #LLM 호출
}

# 일반 키워드 → measure (끝 키워드로 못 정할 때 문장 전체에서 찾음)
MEASURE_KEYWORDS = {
    "change":      ["증감", "늘었", "줄었", "몇 명 차이"],
    "growth_rate": ["증감률", "증가율", "감소율", "몇 %"],
    "cagr":        ["연평균 증가율"],
    "index":       ["기준 대비", "지수"],
    "share":       ["구성비", "비중", "차지"],
    "diff":        ["차이"],
    "ratio":       ["몇 배"],
    "rank":        ["순위", "상위", "하위"],
    "extreme":     ["가장 많은", "가장 적은", "최대", "최소"],
    "aggregate":   ["합계", "총", "평균"],
}

# 지금 가진 데이터 범위: KOSIS '인구' 분야 통계 12개
DATA_SCOPE = [
    "주민등록인구현황", "인구총조사", "인구동향조사(출생·사망·혼인·이혼)", "장래인구추계",
    "국내인구이동통계", "출입국자및체류외국인통계", "지방자치단체외국인주민현황", "장래가구추계",
    "국제인구이동통계", "고령친화용품제조업실태조사", "인구동태패널통계", "영주귀국사할린동포실태조사",
]

# ── ③ 데이터 모양 (노트북 5번) ──
TOTAL_WORDS = ["계", "합계", "총계", "전체", "소계", "전국"]   # 구성비 계산에 쓸 합계 행 이름

# ── ④⑤ chart_type · requirements (노트북 6번) ──
# measure별 후보 목록: 4번 표 "맞는 차트" 순서 = 우선순위. rank는 세로 막대 bar만
MEASURE_TO_CHARTS = {
    "raw":         ["line", "bar", "map", "bubble", "scatter", "combo", "pyramid", "heatmap"],
    "change":      ["bar", "dumbbell", "map", "heatmap"],
    "growth_rate": ["bar", "line", "combo", "map", "heatmap", "scatter"],
    "cagr":        [],                                   # 차트 없음 → 표만
    "index":       ["line", "radar"],
    "share":       ["donut", "pie", "stacked_bar", "treemap", "pyramid", "area", "map"],
    "diff":        ["dumbbell", "bar"],
    "ratio":       ["bar"],
    "rank":        ["bar"],
    "extreme":     [],                                   # 차트 없음 → 표만
    "aggregate":   ["bar", "area"],
}

# 차트별 requirements (데이터가 지켜야 할 조건 이름)
CHART_REQUIREMENTS = {
    "line":        ["time_axis_required", "min_points_3"],
    "area":        ["time_axis_required", "min_points_3"],
    "bar":         ["max_categories_20"],
    "stacked_bar": ["non_negative", "parts_sum_to_total"],
    "pyramid":     ["two_series_required", "non_negative", "category_axis_required"],
    "pie":         ["non_negative", "parts_sum_to_total", "max_categories_5"],
    "donut":       ["non_negative", "parts_sum_to_total", "max_categories_5"],
    "bubble":      ["three_measures_required"],
    "combo":       ["time_axis_required", "two_series_required", "min_points_3"],
    "radar":       ["min_categories_3", "max_categories_8"],
    "map":         ["region_dimension_required"],
    "heatmap":     ["two_dimensions_required"],
    "treemap":     ["non_negative", "parts_sum_to_total"],
    "scatter":     ["two_measures_required", "min_points_5"],
    "dumbbell":    ["two_points_per_category"],
}

# requirement → profile 검사. 반환: (통과 여부, 확인한 값 설명)
REQ_CHECKS = {
    "time_axis_required":        lambda p: (p["has_time"],                f'시점 {p["n_points"]}개 (2개 이상 필요)'),
    "min_points_3":              lambda p: (p["n_points"] >= 3,           f'점 {p["n_points"]}개 (3개 이상 필요)'),
    "min_points_5":              lambda p: (p["n_categories"] >= 5,       f'범주 {p["n_categories"]}개 (5개 이상 필요)'),   # scatter의 점 = 범주
    "max_categories_20":         lambda p: (p["n_categories"] <= 20,      f'범주 {p["n_categories"]}개 (20개 이하 필요)'),
    "max_categories_5":          lambda p: (p["n_categories"] <= 5,       f'범주 {p["n_categories"]}개 (5개 이하 필요)'),
    "min_categories_3":          lambda p: (p["n_categories"] >= 3,       f'범주 {p["n_categories"]}개 (3개 이상 필요)'),
    "max_categories_8":          lambda p: (p["n_categories"] <= 8,       f'범주 {p["n_categories"]}개 (8개 이하 필요)'),
    "category_axis_required":    lambda p: (len(p["dims"]) >= 1,          f'나누는 기준 {len(p["dims"])}개 (1개 이상 필요)'),
    "two_series_required":       lambda p: (p["n_series"] == 2,           f'계열 {p["n_series"]}개 (정확히 2개 필요)'),
    "non_negative":              lambda p: (p["non_negative"],            "값 0 이상" if p["non_negative"] else "음수 값 있음"),
    "parts_sum_to_total":        lambda p: (p["has_total"],               "합계 행 있음" if p["has_total"] else "합계 행 없음"),
    "two_measures_required":     lambda p: (p["n_measures"] >= 2,         f'지표 {p["n_measures"]}개 (2개 이상 필요)'),
    "three_measures_required":   lambda p: (p["n_measures"] >= 3,         f'지표 {p["n_measures"]}개 (3개 이상 필요)'),
    "region_dimension_required": lambda p: (p["has_region"],              f'지역 {p["n_regions"]}곳 (2곳 이상 필요)'),
    "two_dimensions_required":   lambda p: (p["n_dims"] >= 2,             f'차원 {p["n_dims"]}개 (2개 이상 필요)'),
    "two_points_per_category":   lambda p: (p["two_points_per_category"], "비교 대상 2개" if p["two_points_per_category"] else "비교 대상이 2개가 아님"),
}

# ── ⑥ reason (노트북 8번) ──
REASON_TEMPLATE = "{지표} {비교축}별 {의도}"
