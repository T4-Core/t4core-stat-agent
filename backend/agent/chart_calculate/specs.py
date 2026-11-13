"""
[NEW] 차트 15종 표 (명세 8장) — 필수 역할, 행 구조, 축 규칙, 기본 requirements

  차트마다 다른 점을 if 문으로 흩지 않고 이 표 한 곳에 둔다. content.py(구성)와 validate.py(검증)가 같은 표를 읽는다.

  axis_rules: ChartContent.axis 의 키(x · y · y2) → 축 범위 규칙 (axis.RULES). 계산은 axis.axis_range 가 한다.
    free          데이터 범위 + 여백 → 보기 좋은 값으로 반올림 (0 을 포함할 필요가 없는 축)
    include_zero  min = min(0, 최솟값)                          (명세 8장 bar: "y 범위에 0 포함")
    zero          min = 0                                       (명세 8장 stacked_bar · area: "y.min = 0")
    symmetric     −M … +M                                       (명세 8장 pyramid: "좌우 대칭")
    키가 없는 축 · 축이 없는 차트(pie · donut · treemap · map · radar · heatmap)는 범위를 채우지 않는다.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChartSpec:
    name: str
    required: tuple[str, ...]                 # 필수 역할 (encoding 에 반드시 연결)
    optional: tuple[str, ...] = ()
    rows: str = "long"                        # long = 행 하나가 값 하나 / joined = 행 하나가 점(범주) 하나
    requirements: tuple[str, ...] = ()        # 차트별 기본 조건 (명세 8장 + 음수 불가 표)
    non_negative: tuple[str, ...] = ()        # 음수가 오면 안 되는 역할
    category: str | None = None               # 범주 수(max/min_categories_N)를 세는 역할
    # [CHANGED] 이전: y_floor: str | None  ("zero" / "include_zero") — y 축밖에 쓸 수 없었다. 같은 이름의 규칙은 그대로 쓴다
    axis_rules: dict[str, str] = field(default_factory=dict)   # 축(ChartContent.axis 의 키) → 범위 규칙


SPECS: dict[str, ChartSpec] = {
    # [CHANGED] 이전: ("series",)   — y2 는 단위가 다른 지표 2개일 때만 (content._dual_axis). 필수가 아니라 y 하나만으로도 그려진다
    "line": ChartSpec("꺾은선", ("x", "y"), ("series", "y2"), requirements=("time_axis_required", "min_points_3"),
                      axis_rules={"y": "free", "y2": "free"}),
    "bar": ChartSpec("막대", ("x", "y"), ("series",), requirements=("max_categories_20",), category="x",
                     axis_rules={"y": "include_zero"}),
    "stacked_bar": ChartSpec("누적 막대", ("x", "y", "series"), requirements=("non_negative", "parts_sum_to_total"),
                             non_negative=("y",), axis_rules={"y": "zero"}),
    # 피라미드의 값 축은 가로다 → axis["x"] (범주 축 y = 연령). 한쪽을 음수로 그리므로 대칭 범위
    "pyramid": ChartSpec("피라미드", ("y", "group", "value"),
                         requirements=("two_series_required", "non_negative", "category_axis_required"),
                         non_negative=("value",), category="y", axis_rules={"x": "symmetric"}),
    # 명세 8장 표에는 area·bubble 에 non_negative 가 없지만 "음수 값" 표가 음수 불가로 분류한다 → 기본 조건에 넣었다
    # 여러 시리즈는 쌓지 않고 겹친다 (구성 합계 조건이 없다) → max 는 개별 최댓값. 화면도 stack:false 로 그린다
    "area": ChartSpec("면적", ("x", "y"), ("series",),
                      requirements=("time_axis_required", "min_points_3", "non_negative"), non_negative=("y",),
                      axis_rules={"y": "zero"}),
    "pie": ChartSpec("원형", ("label", "value"),
                     requirements=("non_negative", "parts_sum_to_total", "max_categories_5"),
                     non_negative=("value",), category="label"),
    "donut": ChartSpec("도넛", ("label", "value"),
                       requirements=("non_negative", "parts_sum_to_total", "max_categories_5"),
                       non_negative=("value",), category="label"),
    "bubble": ChartSpec("버블", ("x", "y", "size"), ("label", "series"), rows="joined",
                        requirements=("three_measures_required", "non_negative"), non_negative=("size",),
                        axis_rules={"x": "free", "y": "free"}),
    "combo": ChartSpec("복합", ("x", "y", "y2"), ("series",),
                       requirements=("time_axis_required", "two_series_required", "min_points_3"),
                       # 왼쪽 y 는 막대(options.marks) → 0 을 기준선으로. 오른쪽 y2 는 선 → 데이터 범위
                       axis_rules={"y": "include_zero", "y2": "free"}),
    "radar": ChartSpec("레이더", ("label", "series", "value"), requirements=("min_categories_3", "max_categories_8"),
                       category="label"),
    "map": ChartSpec("맵", ("region", "value"), requirements=("region_dimension_required",), category="region"),
    "heatmap": ChartSpec("히트맵", ("x", "y", "value"), requirements=("two_dimensions_required",)),
    "treemap": ChartSpec("트리맵", ("parent", "label", "value"), requirements=("non_negative", "parts_sum_to_total"),
                         non_negative=("value",), category="label"),
    "scatter": ChartSpec("산점도", ("x", "y"), ("label", "series"), rows="joined",
                         requirements=("two_measures_required", "min_points_5"), axis_rules={"x": "free", "y": "free"}),
    # 덤벨은 start·end 가 한 가로 값 축을 나눠 쓴다 → axis["x"]
    "dumbbell": ChartSpec("덤벨", ("label", "start", "end"), rows="joined",
                          requirements=("two_points_per_category",), category="label", axis_rules={"x": "free"}),
}


def requirements_for(chart_type: str, given: list[str] | None = None) -> list[str]:
    """검증할 조건 = 모듈 2 가 넘긴 것 + 이 차트의 기본 조건 (중복 제거, 넘긴 순서 유지)

    대체 차트는 모듈 2 가 조건을 넘기지 않으므로 given 없이 불러 기본 조건만 쓴다.
    """
    return list(dict.fromkeys([*(given or []), *SPECS[chart_type].requirements]))
