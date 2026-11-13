"""Statistical Validation Tool: 계산 전(plan) · 계산 후(result) 검사, 재시도 가능/즉시 폐기 구분."""
from __future__ import annotations

import pytest

from synthetic_gold_pipeline.schemas.planning import (FilterSpec, HopType, Operand, OperationGraph, OperationPlan,
                                                       OperationStep, ReasoningType, SampledCluster)
from synthetic_gold_pipeline.tests.conftest import find_view
from synthetic_gold_pipeline.tools.calculation_tool import TableCalculationEngine
from synthetic_gold_pipeline.tools.statistical_validation_tool import StatisticalValidator


@pytest.fixture(scope="module")
def sv(demo_env):
    cfg = demo_env["cfg"]
    return StatisticalValidator(demo_env["index"], demo_env["graph"], {**cfg["statistics"], **cfg["compatibility"]})


def cluster(views, rt=ReasoningType.CROSS_TABLE_RATIO, hop=HopType.MULTI_TABLE_MULTI_VIEW):
    return SampledCluster(sample_id="S", attempt_index=0, random_seed=1, reasoning_type=rt, subtype="X", hop_type=hop,
                          view_ids=list(views), table_ids=[])


def plan(ops, steps, final, rt=ReasoningType.CROSS_TABLE_RATIO, filters=()):
    return OperationPlan(plan_id="p", reasoning_type=rt, operands=list(ops), filters=list(filters),
                         operation=OperationGraph(steps=list(steps), final_step_id=final))


def scalar(oid, v, itm, prd, code="11", lv="C1", extra=None):
    return Operand(operand_id=oid, view_id=v, itm_id=itm, prd_de=prd, coordinates={lv: code, **(extra or {})})


def codes(rep):
    return {i.code for i in rep.errors}


def test_valid_share_passes(sv, demo_env):
    idx = demo_env["index"]
    e, p = find_view(idx, "101_DT_DEMO_ECON", "T1", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    rep = sv.validate_plan(plan([scalar("A", e, "T1", "2024"), scalar("B", p, "T20", "2024")],
                                [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s"), cluster([e, p]))
    assert rep.passed, rep.issues


def test_unused_view_is_retryable(sv, demo_env):
    idx = demo_env["index"]
    e, p = find_view(idx, "101_DT_DEMO_ECON", "T1", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    rep = sv.validate_plan(plan([scalar("A", e, "T1", "2024")], [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"),
                           cluster([e, p]))
    assert "UNUSED_VIEW" in codes(rep) and rep.retryable


def test_observed_projected_mix_is_dropped(sv, demo_env):
    idx = demo_env["index"]
    p = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    j = find_view(idx, "101_DT_DEMO_PROJ", "T1", "2024", {"C1": ["1"]})
    rep = sv.validate_plan(plan([scalar("A", p, "T20", "2024"), scalar("B", j, "T1", "2024", "11", "C2")],
                                [OperationStep(step_id="s", op="DIFFERENCE", inputs=["A", "B"])], "s"), cluster([p, j]))
    assert "OBSERVED_PROJECTED_MIXED" in codes(rep) and not rep.retryable


def test_frequency_mismatch_is_dropped(sv, demo_env):
    idx = demo_env["index"]
    m, q = find_view(idx, "101_DT_DEMO_MOVE_M", "T10", "202401"), find_view(idx, "101_DT_DEMO_MOVE_Q", "T10", "202401")
    rep = sv.validate_plan(plan([scalar("A", m, "T10", "202401"), scalar("B", q, "T10", "202401")],
                                [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s"), cluster([m, q]))
    assert "FREQUENCY_MISMATCH" in codes(rep) and not rep.retryable


def test_cross_table_growth_rate_rejected(sv, demo_env):
    idx = demo_env["index"]
    a, b = find_view(idx, "101_DT_DEMO_POP", "T20", "2023"), find_view(idx, "101_DT_DEMO_POP_OLD", "T20", "2024")
    rep = sv.validate_plan(plan([scalar("A", a, "T20", "2023"), scalar("B", b, "T20", "2024")],
                                [OperationStep(step_id="s", op="GROWTH_RATE", inputs=["B", "A"])], "s",
                                ReasoningType.TIME_SERIES_COMPARISON),
                           cluster([a, b], ReasoningType.TIME_SERIES_COMPARISON))
    assert "TIME_SERIES_INCOMPATIBLE" in codes(rep)


def test_total_double_count_retryable_and_non_additive(sv, demo_env):
    idx = demo_env["index"]
    m, p = find_view(idx, "101_INH_DEMO_MARRY", "T1", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    ops = [Operand(operand_id="A", view_id=m, itm_id="T1", prd_de="2024", group_by_level="C1", exclude_totals=False),
           Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", group_by_level="C1")]
    flt = [FilterSpec(filter_id="f", target_ref="A", condition_ref="B", comparator=">=", threshold_mode="QUANTILE", quantile=.5)]
    rep = sv.validate_plan(plan(ops, [OperationStep(step_id="s", op="SUM", inputs=["f"])], "s",
                                ReasoningType.CONDITIONAL_AGGREGATION, flt),
                           cluster([m, p], ReasoningType.CONDITIONAL_AGGREGATION))
    assert "TOTAL_DOUBLE_COUNT" in codes(rep) and rep.retryable
    r = find_view(idx, "101_DT_DEMO_ECON", "T3", "2024")
    ops = [Operand(operand_id="A", view_id=r, itm_id="T3", prd_de="2024", group_by_level="C1"),
           Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", group_by_level="C1")]
    flt = [FilterSpec(filter_id="f", target_ref="A", condition_ref="B", comparator=">=", threshold_mode="QUANTILE", quantile=.5)]
    rep = sv.validate_plan(plan(ops, [OperationStep(step_id="s", op="SUM", inputs=["f"])], "s",
                                ReasoningType.CONDITIONAL_AGGREGATION, flt),
                           cluster([r, p], ReasoningType.CONDITIONAL_AGGREGATION))
    assert "NON_ADDITIVE_AGGREGATION" in codes(rep) and not rep.retryable
    # 조건 View 가 % 여도 합산 대상(지표)이 수량이면 허용
    ops = [Operand(operand_id="A", view_id=p, itm_id="T20", prd_de="2024", group_by_level="C1"),
           Operand(operand_id="B", view_id=r, itm_id="T3", prd_de="2024", group_by_level="C1")]
    rep = sv.validate_plan(plan(ops, [OperationStep(step_id="s", op="SUM", inputs=["f"])], "s",
                                ReasoningType.CONDITIONAL_AGGREGATION, flt),
                           cluster([p, r], ReasoningType.CONDITIONAL_AGGREGATION))
    assert "NON_ADDITIVE_AGGREGATION" not in codes(rep)


def test_weighted_mean_requires_justified_pair(sv, demo_env):
    idx = demo_env["index"]
    r, p = find_view(idx, "101_DT_DEMO_ECON", "T3", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    ops = [Operand(operand_id="A", view_id=r, itm_id="T3", prd_de="2024", group_by_level="C1"),
           Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", group_by_level="C1")]
    rep = sv.validate_plan(plan(ops, [OperationStep(step_id="s", op="WEIGHTED_MEAN", inputs=["A", "B"])], "s",
                                ReasoningType.CONDITIONAL_AGGREGATION), cluster([r, p], ReasoningType.CONDITIONAL_AGGREGATION))
    assert "UNJUSTIFIED_WEIGHT" in codes(rep)
    ok = StatisticalValidator(idx, demo_env["graph"], {"weighted_mean_pairs": [{"value_item": "경제활동참가율",
                                                                                "weight_item": "총인구수"}]})
    rep = ok.validate_plan(plan(ops, [OperationStep(step_id="s", op="WEIGHTED_MEAN", inputs=["A", "B"])], "s",
                                ReasoningType.CONDITIONAL_AGGREGATION), cluster([r, p], ReasoningType.CONDITIONAL_AGGREGATION))
    assert "UNJUSTIFIED_WEIGHT" not in codes(rep)


def test_narrower_denominator_rejected(sv, demo_env):
    idx = demo_env["index"]
    a = find_view(idx, "101_DT_DEMO_HH", "T2", "2020", {"C2": ["2"]})       # 여자 가구주 1인가구
    b = find_view(idx, "101_DT_DEMO_HH", "T1", "2020", {"C2": ["1"]})       # 남자 가구주 일반가구
    c = find_view(idx, "101_DT_DEMO_HH", "T1", "2020", {"C2": ["2"]})       # 여자 가구주 일반가구
    st = [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])]
    rep = sv.validate_plan(plan([scalar("A", a, "T2", "2020"), scalar("B", b, "T1", "2020")], st, "s"),
                           cluster([a, b], hop=HopType.SINGLE_TABLE_MULTI_VIEW))
    assert "DENOMINATOR_NARROWER_THAN_NUMERATOR" in codes(rep)
    rep = sv.validate_plan(plan([scalar("A", a, "T2", "2020"), scalar("B", c, "T1", "2020")], st, "s"),
                           cluster([a, c], hop=HopType.SINGLE_TABLE_MULTI_VIEW))
    assert "DENOMINATOR_NARROWER_THAN_NUMERATOR" not in codes(rep)


def test_foreign_population_scope_incompatible(sv, demo_env):
    idx = demo_env["index"]
    f, p = find_view(idx, "101_DT_DEMO_FOREIGN", "T1", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    rep = sv.validate_plan(plan([scalar("A", f, "T1", "2024"), scalar("B", p, "T20", "2024")],
                                [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s"), cluster([f, p]))
    assert {"RATIO_INCOMPATIBLE", "POPULATION_SCOPE_INCOMPATIBLE"} & codes(rep)


def test_missing_period_not_retryable(sv, demo_env):
    idx = demo_env["index"]
    e, p = find_view(idx, "101_DT_DEMO_ECON", "T1", "2024"), find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    rep = sv.validate_plan(plan([scalar("A", e, "T1", "2020"), scalar("B", p, "T20", "2024")],
                                [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s"), cluster([e, p]))
    assert "MISSING_PERIOD" in codes(rep) and not rep.retryable


def test_post_calc_share_over_100_rejected(sv, demo_env):
    idx = demo_env["index"]
    p, e = find_view(idx, "101_DT_DEMO_POP", "T20", "2024"), find_view(idx, "101_DT_DEMO_ECON", "T1", "2024")
    pl = plan([scalar("A", p, "T20", "2024"), scalar("B", e, "T1", "2024")],
              [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s")
    calc = TableCalculationEngine(idx, demo_env["cfg"]["calculation"]).run(pl, [p, e])
    assert calc.success
    rep = sv.validate_result(pl, cluster([p, e]), calc)
    assert "SHARE_EXCEEDS_100" in codes(rep)
    rep_plan = sv.validate_plan(pl, cluster([p, e]))
    assert "SHARE_DENOMINATOR_NOT_TOTAL" in codes(rep_plan)
