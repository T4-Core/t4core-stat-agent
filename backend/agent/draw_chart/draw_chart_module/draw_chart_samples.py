"""
모듈 5 유형별 예시 데이터 — 15종(+가로 막대) ChartContent 16개를 그려 렌더러를 확인한다

  모듈 3(content.py)이 만드는 모양을 따른다: long 행 [분류…, 항목, 값] / joined 행 [키…, 지표1, 지표2 …]
  값은 그리기 확인용 예시 (실제 통계 아님). 출처 링크는 만들지 않는다 (record_ids 비움)

  from backend.agent.draw_chart import run_samples          # 짧게 (상위 패키지)
  # from backend.agent.draw_chart.draw_chart_module.draw_chart_samples import run_samples
  out = run_samples()          # → backend/agent/draw_chart/output/samples/samples.html
"""
from backend.schemas.chart import Display

from .draw_chart_schema import OUTPUT_ROOT

SAMPLE_DISPLAYS = {
    "d_cnt": Display(source_unit="건", display_unit="건", unit_scale=1),
    "d_man": Display(source_unit="명", display_unit="만 명", unit_scale=10000, digits=1),
    "d_pct": Display(source_unit="%", display_unit="%", unit_scale=1, digits=1),
    "d_tfr": Display(source_unit="명", display_unit="명", unit_scale=1, digits=2),
    "d_gae": Display(source_unit="개", display_unit="개", unit_scale=1),
}
YEARS10 = [str(y) for y in range(2015, 2025)]
YEARS5 = [str(y) for y in range(2020, 2025)]


def sample(chart_id, chart_type, title, columns, rows, encoding, axis=None, options=None, measure="raw"):
    return {"chart_id": chart_id, "chart_type": chart_type, "measure": measure, "title": f"[예시] {title}",
            "encoding": encoding, "axis": axis or {}, "options": options or {}, "columns": columns, "rows": rows,
            "record_ids": [], "warnings": []}


def long_rows(dim_values, item, values):
    """[분류값…] × 값 → long 행 [분류…, 항목, 값]"""
    return [[*(d if isinstance(d, (list, tuple)) else [d]), item, v] for d, v in zip(dim_values, values)]


AX_TIME = {"label": "시점", "type": "time"}
SIDO = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도",
        "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"]
AGES = ["0~9세", "10~19세", "20~29세", "30~39세", "40~49세", "50~59세", "60~69세", "70~79세", "80세 이상"]

SAMPLE_CONTENTS = [
    # line: 시점 × 계열 2개
    sample("s01", "line", "2015~2024년 혼인·이혼 건수 추이", ["시점", "항목", "값"],
           long_rows(YEARS10, "혼인건수", [302828, 281635, 264455, 257622, 239159, 213502, 192507, 191690, 193657, 222412])
           + long_rows(YEARS10, "이혼건수", [109153, 107328, 106032, 108684, 110831, 106500, 101673, 93232, 92394, 91151]),
           {"x": "시점", "y": "값", "series": "항목"},
           {"x": AX_TIME, "y": {"label": "값", "type": "numeric", "scale": "linear", "display_ref": "d_cnt"}}),
    # bar: 범주(시도) 세로 막대, y 범위에 0 포함
    sample("s02", "bar", "2024년 시도별 출생아수", ["행정구역별", "항목", "값"],
           long_rows(SIDO[:5], "출생아수", [38300, 12900, 9700, 15200, 6900]),
           {"x": "행정구역별", "y": "값"},
           {"x": {"label": "행정구역별", "type": "category"},
            "y": {"label": "출생아수", "type": "numeric", "scale": "linear", "min": 0, "display_ref": "d_man"}},
           {"orientation": "vertical"}),
    # bar (rank): 가로 막대, 1위가 위
    sample("s03", "bar", "2024년 고령인구비율 상위 8개 시도", ["행정구역별", "항목", "값"],
           long_rows(["전라남도", "경상북도", "강원특별자치도", "전북특별자치도", "부산광역시", "충청남도", "충청북도", "경상남도"],
                     "고령인구비율", [27.2, 25.4, 24.6, 24.6, 23.9, 21.6, 21.2, 21.1]),
           {"x": "행정구역별", "y": "값"},
           {"x": {"label": "행정구역별", "type": "category"},
            "y": {"label": "고령인구비율", "type": "numeric", "scale": "percent", "min": 0, "display_ref": "d_pct"}},
           {"orientation": "horizontal"}, measure="rank"),
    # stacked_bar: 시점 × 성별 쌓기
    sample("s04", "stacked_bar", "2020~2024년 성별 사망자수", ["시점", "성별", "항목", "값"],
           long_rows([(y, "남자") for y in YEARS5], "사망자수", [165300, 170100, 199700, 189900, 192000])
           + long_rows([(y, "여자") for y in YEARS5], "사망자수", [139600, 147600, 173100, 162600, 166400]),
           {"x": "시점", "y": "값", "series": "성별"},
           {"x": AX_TIME, "y": {"label": "사망자수", "type": "numeric", "scale": "linear", "min": 0, "display_ref": "d_man"}}),
    # pyramid: 연령 × 성별 (모듈 3은 피라미드에 display_ref를 넣지 않는다 → 원값 그대로)
    sample("s05", "pyramid", "2024년 연령별·성별 인구", ["연령별", "성별", "항목", "값"],
           long_rows([(a, "남자") for a in AGES], "인구",
                     [1790000, 2430000, 3320000, 3410000, 4090000, 4330000, 3780000, 1880000, 860000])
           + long_rows([(a, "여자") for a in AGES], "인구",
                       [1700000, 2270000, 3010000, 3160000, 3960000, 4260000, 3950000, 2210000, 1620000]),
           {"y": "연령별", "group": "성별", "value": "값"},
           {"y": {"label": "연령별", "type": "category"}}),
    # area: 시점, y.min = 0
    sample("s06", "area", "2015~2024년 고령인구비율 추이", ["시점", "항목", "값"],
           long_rows(YEARS10, "고령인구비율", [12.8, 13.2, 13.8, 14.3, 14.9, 15.7, 16.6, 17.5, 18.4, 19.2]),
           {"x": "시점", "y": "값", "series": "항목"},
           {"x": AX_TIME, "y": {"label": "고령인구비율", "type": "numeric", "scale": "percent", "min": 0, "display_ref": "d_pct"}}),
    # pie: 비중(share), 축 없음 → options.display_ref, scope_label
    sample("s07", "pie", "2024년 가구원수별 가구 비중", ["가구원수별", "항목", "값"],
           long_rows(["1인", "2인", "3인", "4인", "5인 이상"], "가구 비중", [35.5, 28.8, 19.2, 13.8, 2.7]),
           {"label": "가구원수별", "value": "값"}, None,
           {"display_ref": "d_pct", "scope_label": "선택 항목 내 비중"}, measure="share"),
    # donut: 원값 + center_text
    sample("s08", "donut", "2024년 산업별 사업체수", ["산업별", "항목", "값"],
           long_rows(["도소매업", "숙박음식점업", "제조업", "운수업", "기타"], "사업체수", [1050000, 790000, 600000, 590000, 1200000]),
           {"label": "산업별", "value": "값"}, None,
           {"display_ref": "d_gae", "center_text": "합계 4,230,000개"}),
    # bubble (joined): x, y, size, label
    sample("s09", "bubble", "2024년 시도별 혼인건수·합계출산율·출생아수", ["행정구역별", "혼인건수", "합계출산율", "출생아수"],
           [["서울특별시", 44000, 0.58, 38300], ["부산광역시", 12100, 0.68, 12900], ["인천광역시", 13200, 0.76, 15200],
            ["경기도", 61500, 0.79, 74000], ["세종특별자치시", 2300, 1.03, 3000], ["전라남도", 6300, 0.97, 7800]],
           {"x": "혼인건수", "y": "합계출산율", "size": "출생아수", "label": "행정구역별"},
           {"x": {"label": "혼인건수", "type": "numeric", "scale": "linear", "display_ref": "d_cnt"},
            "y": {"label": "합계출산율", "type": "numeric", "scale": "linear", "display_ref": "d_tfr"}}),
    # combo: 막대(y, 왼쪽) + 선(y2, 오른쪽), 단위가 다름
    sample("s10", "combo", "2015~2024년 출생아수와 합계출산율", ["시점", "항목", "값"],
           long_rows(YEARS10, "출생아수", [438420, 406243, 357771, 326822, 302676, 272337, 260562, 249186, 230028, 238317])
           + long_rows(YEARS10, "합계출산율", [1.24, 1.17, 1.05, 0.98, 0.92, 0.84, 0.81, 0.78, 0.72, 0.75]),
           {"x": "시점", "y": "값", "y2": "값", "series": "항목"},
           {"x": AX_TIME,
            "y": {"label": "출생아수", "type": "numeric", "scale": "linear", "display_ref": "d_man"},
            "y2": {"label": "합계출산율", "type": "numeric", "scale": "linear", "display_ref": "d_tfr"}},
           {"marks": {"y": "bar", "y2": "line"}, "series_axis": {"출생아수": "y", "합계출산율": "y2"}}),
    # radar: 지표 축 × 계열(지역), 같은 단위(%)
    sample("s11", "radar", "2024년 지역별 주요 지표 (%)", ["행정구역별", "항목", "값"],
           [[r, k, v] for r, vals in [("서울특별시", [62.9, 64.8, 70.1, 18.5, 39.3]), ("부산광역시", [57.4, 59.6, 71.8, 23.9, 35.1]),
                                       ("전국", [62.6, 64.5, 72.9, 19.2, 36.1])]
            for k, v in zip(["고용률", "경제활동참가율", "대학진학률", "고령인구비율", "1인가구비율"], vals)],
           {"label": "항목", "series": "행정구역별", "value": "값"}, None, {"display_ref": "d_pct"}),
    # map: 시도 17곳 + 전국(지도에 없음 → 경고)
    sample("s12", "map", "2024년 시도별 고령인구비율", ["행정구역별", "항목", "값"],
           long_rows(["전국"] + SIDO, "고령인구비율",
                     [19.2, 18.5, 23.9, 20.4, 17.3, 16.9, 17.1, 16.0, 11.6, 16.1, 24.6, 21.2, 21.6, 24.6, 27.2, 25.4, 21.1, 18.8]),
           {"region": "행정구역별", "value": "값"}, None,
           {"display_ref": "d_pct", "geo_level": "시도", "region_key": "name", "color_bins": None}),
    # heatmap: x(시점) × y(지역) (모듈 3은 히트맵에 display_ref를 넣지 않는다 → 원값 그대로)
    sample("s13", "heatmap", "2020~2024년 시도별 실업률 (%)", ["시점", "행정구역별", "항목", "값"],
           [[y, r, "실업률", v] for r, vals in [("서울특별시", [4.5, 4.8, 3.6, 3.4, 3.6]), ("부산광역시", [4.0, 3.9, 2.9, 2.8, 3.0]),
                                                 ("대구광역시", [4.2, 3.7, 2.8, 2.6, 2.9]), ("인천광역시", [4.6, 4.5, 3.3, 3.1, 3.2]),
                                                 ("경기도", [4.1, 4.0, 3.2, 3.0, 3.1])]
            for y, v in zip(YEARS5, vals)],
           {"x": "시점", "y": "행정구역별", "value": "값"},
           {"x": AX_TIME, "y": {"label": "행정구역별", "type": "category"}}),
    # treemap: parent(대분류) > label(중분류)
    sample("s14", "treemap", "2024년 산업별 사업체수", ["산업대분류", "산업중분류", "항목", "값"],
           [["제조업", "식료품", "사업체수", 60000], ["제조업", "금속가공", "사업체수", 75000], ["제조업", "전자부품", "사업체수", 20000],
            ["서비스업", "도소매", "사업체수", 1050000], ["서비스업", "숙박음식", "사업체수", 790000], ["서비스업", "운수", "사업체수", 590000],
            ["건설업", "종합건설", "사업체수", 15000], ["건설업", "전문공사", "사업체수", 120000]],
           {"parent": "산업대분류", "label": "산업중분류", "value": "값"}, None, {"display_ref": "d_gae"}),
    # scatter (joined): x, y, label
    sample("s15", "scatter", "2024년 시도별 고령인구비율과 1인가구비율", ["행정구역별", "고령인구비율", "1인가구비율"],
           [[r, x, y] for r, x, y in zip(SIDO[:10], [18.5, 23.9, 20.4, 17.3, 16.9, 17.1, 16.0, 11.6, 16.1, 24.6],
                                         [39.3, 35.1, 34.2, 32.0, 35.6, 38.2, 31.5, 33.8, 31.0, 38.9])],
           {"x": "고령인구비율", "y": "1인가구비율", "label": "행정구역별"},
           {"x": {"label": "고령인구비율", "type": "numeric", "scale": "percent", "display_ref": "d_pct"},
            "y": {"label": "1인가구비율", "type": "numeric", "scale": "percent", "display_ref": "d_pct"}}),
    # dumbbell (joined, 시점 펼침): label, start(첫 시점), end(마지막 시점)
    sample("s16", "dumbbell", "2015년 대비 2024년 시도별 합계출산율", ["행정구역별", "2015", "2024"],
           [["서울특별시", 1.00, 0.58], ["부산광역시", 1.14, 0.68], ["경기도", 1.27, 0.79], ["전라남도", 1.55, 0.97],
            ["세종특별자치시", 1.89, 1.03], ["전국", 1.24, 0.75]],
           {"label": "행정구역별", "start": "2015", "end": "2024"},
           {"x": {"label": "합계출산율", "type": "numeric", "scale": "linear", "display_ref": "d_tfr"}}),
]


def sample_plan():
    """예시용 ChartPlan (모듈 2 모양): 차트마다 계획 유형 = 최종 유형"""
    return {"query_id": "samples",
            "charts": [{"chart_id": c["chart_id"], "chart_type": c["chart_type"], "sub_question_ids": []} for c in SAMPLE_CONTENTS]}


def run_samples(out_dir=None, save=True):
    """예시 16개를 모듈 5 그래프로 그린다 → {query_id, results, html, load_errors}"""
    from .draw_chart_run import run_module5
    return run_module5(chart_plan=sample_plan(), chart_contents=SAMPLE_CONTENTS, calc_results=[],
                       displays=SAMPLE_DISPLAYS, out_dir=out_dir or OUTPUT_ROOT / "samples", save=save)
