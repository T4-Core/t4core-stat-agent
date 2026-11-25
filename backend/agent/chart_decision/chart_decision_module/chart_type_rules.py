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

# ── ①-2 View 적합도 (고도화 1단계: chart_type_view_check.py) ──
TREND_INTENT = "추이"
TREND_MIN_POINTS = 2                              # 추이를 물었는데 표의 시점이 이보다 적으면 차트 없음 (표만)
SPLIT_SLOTS = ["성별", "연령", "지역"]             # 요청한 나눔으로 보는 슬롯 (View notes 의 slot)
SPLIT_CHARTS = {"성별": ["pyramid"],               # 그 나눔이 표에 없으면 후보에서 빼는 차트
                "연령": ["pyramid"],
                "지역": ["map"]}
# [CHANGED 11-24] '값 1개 → 표만' 차단(SCALAR_MEASURES · SCALAR_MAX_POINTS · MIN_CHART_VALUES)은 없앴다.
#   차이 계산의 결과가 1개면 비교한 값들을 그리고, 값이 정말 1개인 표는 빈 좌표 판정에서 탈락한다 (chart_type_frames.py)

# ── 사용자용 경고 (고도화 4단계): errors 중 이 노드에서 나온 warning 만 chart_plan.charts[].warnings 로 넘긴다
#    profile 노드의 메모('요청하지 않은 나눔 … 제외' 등)는 개발자용이라 errors 에만 둔다
USER_WARNING_NODES = ("view_check", "chart_select")

# ── ⑥-1 겹쳐 그리기 (고도화 5단계: chart_type_overlay.py) ──
# 하위질문 2개의 차트를 모듈 5 가 그림 하나로 겹쳐 그리도록 chart_plan.overlays 에 표시한다 (모듈 3 은 읽지 않음)
OVERLAY_INTENTS = ["추이", "비교"]                 # 이 의도일 때만 (순위 · 구성비 · 값 조회는 겹치지 않음)
OVERLAY_MODES = {"line": "lines", "bar": "bars"}   # 두 차트가 모두 이 유형이고 크기가 비슷하면 → 선 여러 개 / 묶음 막대
OVERLAY_SCALE_RATIO = 10                           # 두 값의 최댓값 비율이 이 이상이면 → combo (큰 값 막대 · 작은 값 선)

# ── ③-1 요청한 나눔 (고도화 2단계: chart_type_axes.py) ──
# 비교축 말 → 축 이름. 여기 없는 말(예: '가구원수')은 그 말 자체를 축으로 보고, 열 이름에 그 말이 든 열과 맞춘다
AXIS_WORDS = {"연도": "시점", "시점": "시점", "년": "시점", "월": "시점", "분기": "시점",
              "시도": "지역", "시군구": "지역", "지역": "지역", "행정구역": "지역",
              "연령": "연령", "연령대": "연령", "나이": "연령",
              "성": "성별", "성별": "성별", "남녀": "성별"}
AXIS_COLUMN_HINTS = {"지역": ["행정구역", "시도", "시군구", "지역"],     # 열 이름에 이 말이 있으면 그 축
                     "연령": ["연령", "세별", "나이"],
                     "성별": ["성별"]}
SEX_WORDS = ["남자", "여자", "남성", "여성"]                             # 값에 이 말이 있으면 성별 열 ('남자인구수' 등)
REGION_SUFFIXES = ["특별시", "광역시", "특별자치시", "특별자치도", "도"]   # 값이 지역 이름인지
AGE_TARGET_WORDS = ["고령자", "노인", "고령인구", "영유아", "유소년인구", "생산연령인구"]   # 대상이 연령 범위를 뜻하는 말
CATEGORY_INTENTS = ["비교", "순위", "구성비"]   # 요청한 나눔이 표에 없을 때 다른 나눔을 범주로 남겨 두는 의도 (안전장치)

# ── ④-1 차트 요청 · 데이터 모양 점수 (고도화 3단계: chart_type_preference.py) ──
# 질문 속 말 → 차트. 긴 말부터 찾고 찾은 부분은 지운다 ('누적 막대' 안의 '막대'를 다시 잡지 않음)
CHART_WORDS = {
    "누적 막대": "stacked_bar", "누적막대": "stacked_bar",
    "꺾은선": "line", "선그래프": "line", "선 그래프": "line", "라인 차트": "line",
    "막대": "bar", "바 차트": "bar",
    "원그래프": "pie", "원 그래프": "pie", "파이 차트": "pie", "파이차트": "pie",
    "도넛": "donut",
    "피라미드": "pyramid",
    "지도": "map",
    "히트맵": "heatmap", "열지도": "heatmap",
    "산점도": "scatter",
    "버블": "bubble", "거품": "bubble",
    "트리맵": "treemap",
    "레이더": "radar", "방사형": "radar",
    "면적 그래프": "area", "면적그래프": "area", "영역 그래프": "area",
    "덤벨": "dumbbell",
    "콤보": "combo", "복합 그래프": "combo",
}
REQUEST_ONLY_CHARTS = ["map"]          # 사용자가 이름으로 요청할 때만 고르는 차트 (자동 선택하지 않음)

# [NEW 11-20 KOS-41] 지원하지 않는 차트 이름 → 가장 가까운 지원 차트 (None = 대체할 차트 없음, 규칙으로 고른다)
# 히스토그램은 수치 변수의 구간 분포를 보는 차트인데 현재 데이터는 범주별 값이다. 값을 구간으로 묶으면 의미가 달라져 지원하지 않고 막대로 대체한다
UNSUPPORTED_CHART_WORDS = {
    "히스토그램": "bar", "상자그림": None, "박스플롯": None, "박스 플롯": None, "상자 그림": None,
    "워드클라우드": None, "워드 클라우드": None, "폭포 차트": "bar", "워터폴": "bar",
    "간트": "bar", "깔때기": "bar", "퍼널": "bar", "생키": None, "산키": None,
}
# 이름이 일반 단어와 겹쳐 차트 용법(뒤에 차트·그래프, '로 보여줘' 등)이 확인될 때만 요청으로 본다 ('운동지도자', '막대기', '도넛 가게')
AMBIGUOUS_CHART_WORDS = {"지도", "막대", "버블", "거품", "덤벨", "콤보", "도넛"}
NEGATION_MARKS = ("말고", "말구", "빼고", "제외", "아니라", "아닌", "대신")      # '막대 말고 원그래프로' 의 막대 = 요청이 아니라 제외
ALTERNATIVE_CONNECTORS = ("나", "이나", "또는", "혹은", "거나", "와", "과", "랑", "이랑", "하고", "및", ",", "/")   # '막대나 원그래프'
USAGE_SUFFIXES = ("그래프", "차트", "도표", "형태", "형식", "형", "플롯")
USAGE_PREDICATES = ("보여", "그려", "나타", "표시", "바꿔", "만들", "출력", "시각화", "변환", "그리")
# 이름 바로 뒤에 한글이 이어질 때 이름의 일부가 아닌 말(조사·표지)이어야 한다 ('지도자', '막대기' 는 다른 단어)
NAME_TRAILERS = ("으로", "로", "를", "을", "은", "는", "이", "가", "도", "만", "나", "이나", "와", "과", "랑", "이랑", "에", "의",
                 "보다", "처럼", "말고", "말구", "빼고", "제외", "대신", "아니라", "아닌", "하고", "및", "또는", "혹은", "거나")
# 데이터 모양 점수 규칙 (chart_type_preference.shape_score). 생존 후보 중 점수가 가장 높은 차트, 같으면 기존 순서
SHAPE_SCORES = {
    "pyramid_age_sex": 3,              # 범주 = 연령 + 계열 = 성별 2개 → pyramid
    "line_time": 3,                    # 범주 = 시점 3개 이상 → line
    "heatmap_two_axes": 2,             # 시점이 아닌 요청 나눔 2개, 각각 3개 이상 → heatmap
    "donut_small_share": 2,            # 비중 + 범주 5개 이하 → donut
    "bar_rank": 2,                     # 순위 → bar
    "bar_base": 1,                     # 기본 → bar
}

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
    "share":       ["donut", "pie", "stacked_bar", "treemap", "pyramid", "area", "map",
                    "bar"],                              # [NEW 11-24] 항목이 많아 원형이 탈락할 때 막대로 (임시 — 뺄 때는 이 줄만 지운다)
    "diff":        ["dumbbell", "bar"],
    "ratio":       ["bar"],
    "rank":        ["bar"],
    "extreme":     [],                                   # 차트 없음 → 표만
    "aggregate":   ["bar", "area"],
}

# 차트별 requirements (데이터가 지켜야 할 조건 이름) — 모듈 3 에 넘겨 계산 뒤에 판정한다
# [CHANGED 11-24] 모듈 2 는 이 조건으로 후보를 거르지 않는다 (빈 좌표 판정은 chart_type_frames.py). 이전 profile 추정 판정(REQ_CHECKS)은 없앴다
CHART_REQUIREMENTS = {
    "line":        ["time_axis_required", "min_points_3"],
    "area":        ["time_axis_required", "min_points_3"],
    # min_categories_2: 값 1개짜리 막대를 만들지 않는 안전망. 모듈 3 이 계산한 차트 내용으로 판정한다
    #   (대체 차트는 모듈 3 이 자기 기본 조건으로 검증하므로 dumbbell 에는 붙이지 않는다 — 붙여도 효과 없음)
    "bar":         ["max_categories_20", "min_categories_2"],
    "stacked_bar": ["non_negative", "parts_sum_to_total", "min_categories_2"],
    "pyramid":     ["two_series_required", "non_negative", "category_axis_required"],
    "pie":         ["non_negative", "parts_sum_to_total", "max_categories_5", "min_categories_2"],
    "donut":       ["non_negative", "parts_sum_to_total", "max_categories_5", "min_categories_2"],
    "bubble":      ["three_measures_required"],
    "combo":       ["time_axis_required", "two_series_required", "min_points_3"],
    "radar":       ["min_categories_3", "max_categories_8"],
    "map":         ["region_dimension_required"],
    "heatmap":     ["two_dimensions_required"],
    "treemap":     ["non_negative", "parts_sum_to_total", "min_categories_2"],
    "scatter":     ["two_measures_required", "min_points_5"],
    "dumbbell":    ["two_points_per_category"],
}

# ── ⑥ reason (노트북 8번) ──
REASON_TEMPLATE = "{지표} {비교축}별 {의도}"
