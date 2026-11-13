"""[NEW] axis.py — 축 범위 계산 (min · max). 값은 원값 기준, HCX 없이 도는 단위 시험"""
import math
import random

import pytest

from backend.agent.chart_calculate.axis import RULES, axis_range, group_sums, nice_step, numbers

MARRIAGE = [192507, 191690, 193657, 222412, 240326]        # 명세 시나리오 혼인건수


# ── nice_step ────────────────────────────────────────────────────
def test_nice_step_is_1_2_5_times_power_of_ten_not_exceeding_target_ticks():
    assert nice_step(47819) == 10000                        # 47819 / 5 = 9564 → 10000
    assert nice_step(100) == 20 and nice_step(10) == 2 and nice_step(2.5) == 0.5
    for span in (0.003, 0.7, 3, 47, 999, 123456, 8e9):
        step = nice_step(span)
        assert span / step <= 5 + 1e-9                      # 눈금이 목표 개수를 넘지 않는다
        assert f"{step / 10 ** math.floor(math.log10(step)):.6g}" in ("1", "2", "5")


def test_nice_step_integer_never_below_one():
    assert nice_step(2, integer=True) == 1 and nice_step(2) == 0.5


# ── free ─────────────────────────────────────────────────────────
def test_free_matches_scenario_example():
    """실제 최솟값은 2022년의 191,690 (첫 해 192,507 이 아니다). span 48,636 · 여백 2,432 → 아래 한계 189,258 →
    step 10,000 배수로 내리면 180,000. 데이터는 축 가장자리에 닿지 않는다"""
    lo, hi = axis_range(MARRIAGE, "free")
    assert (lo, hi) == (180000, 250000)
    assert lo < min(MARRIAGE) and hi > max(MARRIAGE)


def test_free_padding_keeps_points_off_the_edges_and_pad_is_overridable():
    assert axis_range([1000, 2000], "free") == (800, 2200)          # 5% 여백 후 step(200) 배수로
    assert axis_range([1000, 2000], "free", pad=0) == (1000, 2000)  # 인자로 덮어쓰면 여백 없음


def test_free_constant_values_are_widened_around_the_value():
    lo, hi = axis_range([5, 5, 5], "free")
    assert lo < 5 < hi
    assert axis_range([0, 0], "free") == (0, 1)                     # 0 이상 데이터는 0 아래로 안 내려간다


def test_free_nonnegative_data_never_goes_below_zero_and_nonpositive_never_above():
    lo, _ = axis_range([1, 2, 3], "free")
    assert lo >= 0
    _, hi = axis_range([-5, -3, -1], "free")
    assert hi <= 0


def test_free_includes_negative_values():
    lo, hi = axis_range([-8.2, 3.1, 4.4], "free")
    assert lo <= -8.2 and hi >= 4.4 and lo < 0


def test_free_integer_data_gets_integer_ticks_but_float_data_may_use_half_steps():
    assert axis_range([3, 4, 5], "free") == (2, 6)                  # step 1 (0.5 가 아니라)
    assert axis_range([3.2, 4.1], "free") == (3.0, 4.2)             # 실수 데이터는 step 0.2 처럼 1 보다 작아도 된다


def test_free_has_no_float_noise():
    assert axis_range([0.1, 0.3], "free") == (0.05, 0.35)           # 0.30000000000000004 같은 값이 남지 않는다


# ── 규칙별 ───────────────────────────────────────────────────────
def test_include_zero_keeps_spec_min_exactly():
    """명세 8장: bar 는 y.min = min(0, 최솟값). 반올림하지 않는다"""
    assert axis_range([3, 5, 9], "include_zero")[0] == 0
    lo, hi = axis_range([-3.7, 5], "include_zero")
    assert lo == -3.7 and hi >= 5
    assert axis_range([0, 0], "include_zero") == (0, 1)


def test_zero_rule_min_is_zero_and_max_covers_data():
    assert axis_range([10, 20], "zero") == (0, 25)                  # span 20 → step 5, 여백 포함 21 → 25


def test_symmetric_is_mirrored_and_covers_both_sides():
    lo, hi = axis_range([-120, 80], "symmetric")
    assert lo == -hi and hi >= 120


# ── 값이 없을 때 · 잘못된 입력 ────────────────────────────────────
@pytest.mark.parametrize("rule", RULES)
def test_no_numbers_means_no_range(rule):
    assert axis_range([], rule) == (None, None)
    assert axis_range([None, "가", True, float("nan"), float("inf")], rule) == (None, None)


def test_non_numbers_are_ignored_among_numbers():
    assert numbers([1, None, "2", True, 3.5, float("nan")]) == [1.0, 3.5]
    assert axis_range([None, *MARRIAGE, None], "free") == (180000, 250000)


def test_unknown_rule_fails_loudly():
    with pytest.raises(ValueError):
        axis_range([1, 2], "log")


# ── 불변식: 범위는 항상 모든 값을 포함한다 ──────────────────────────
@pytest.mark.parametrize("rule", RULES)
def test_range_always_covers_the_data(rule):
    rnd = random.Random(7)
    for _ in range(300):
        scale = 10 ** rnd.randint(-3, 9)
        sign = rnd.choice((1, 1, -1))
        vals = [sign * rnd.random() * scale if rnd.random() < .5 else rnd.randint(0, 1000) * (scale // 1 or 1)
                for _ in range(rnd.randint(1, 12))]
        if rule in ("zero",):
            vals = [abs(v) for v in vals]
        lo, hi = axis_range(vals, rule)
        assert lo < hi, (rule, vals)
        if rule == "zero":
            assert lo == 0
        if rule == "symmetric":
            assert lo == -hi and hi >= max(abs(v) for v in vals)
        elif rule in ("free", "include_zero"):
            assert lo <= min(vals) + 1e-9 and hi >= max(vals) - 1e-9, (rule, vals, lo, hi)
        else:
            assert hi >= max(vals) - 1e-9


# ── group_sums (누적 막대의 max) ─────────────────────────────────
def test_group_sums_for_stacked_max():
    sums = group_sums(["2021", "2021", "2022", "2022", "2022"], [10, 5, 7, None, 8])
    assert sums == {"2021": 15.0, "2022": 15.0}
    assert axis_range(sums.values(), "zero")[1] >= 15              # 개별 최댓값(10)이 아니라 합계(15) 기준


# ── specs.py 의 차트별 축 규칙 표 ──────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

from backend.agent.chart_calculate.specs import SPECS  # noqa: E402
from backend.main import app  # noqa: E402

# 명세 8장 + 합의한 것 (area 는 겹침, pyramid 값 축은 axis["x"], 덤벨은 start·end 가 가로 값 축 하나)
EXPECTED_AXIS_RULES = {
    "line": {"y": "free", "y2": "free"}, "bar": {"y": "include_zero"}, "stacked_bar": {"y": "zero"},
    "pyramid": {"x": "symmetric"}, "area": {"y": "zero"}, "bubble": {"x": "free", "y": "free"},
    "combo": {"y": "include_zero", "y2": "free"}, "scatter": {"x": "free", "y": "free"}, "dumbbell": {"x": "free"},
    "pie": {}, "donut": {}, "radar": {}, "map": {}, "heatmap": {}, "treemap": {},
}


def test_axis_rules_table_matches_what_we_agreed():
    assert {name: spec.axis_rules for name, spec in SPECS.items()} == EXPECTED_AXIS_RULES


def test_every_rule_is_known_and_on_an_axis_chartcontent_can_hold():
    for name, spec in SPECS.items():
        for axis, rule in spec.axis_rules.items():
            assert axis in ("x", "y", "y2"), (name, axis)        # schemas.chart.ChartContent.axis 의 키
            assert rule in RULES, (name, rule)


def test_charts_without_axes_have_no_rules():
    for name in ("pie", "donut", "treemap", "map", "radar", "heatmap"):
        assert SPECS[name].axis_rules == {}


def test_y2_rule_exists_only_where_a_second_axis_exists():
    for name, spec in SPECS.items():
        assert ("y2" in spec.axis_rules) == (name in ("line", "combo")), name


def test_specs_api_exposes_axis_rules():
    body = TestClient(app).get("/api/v1/chart/specs").json()
    assert body["bar"]["axis_rules"] == {"y": "include_zero"} and body["pyramid"]["axis_rules"] == {"x": "symmetric"}
    assert "y_floor" not in body["bar"]
