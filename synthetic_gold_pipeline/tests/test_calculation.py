"""Atomic Calculator · 값 파싱 · 단위 · SQL 안전성 · TableCalculationEngine."""
from __future__ import annotations

from decimal import Decimal

import duckdb
import pytest

from synthetic_gold_pipeline.schemas.calculation import CalcErrorCode
from synthetic_gold_pipeline.schemas.planning import (FilterSpec, Operand, OperationGraph, OperationPlan, OperationStep,
                                                       ReasoningType)
from synthetic_gold_pipeline.tests.conftest import find_view
from synthetic_gold_pipeline.tools.calculation_tool import (CalculationError, SqlSafetyValidator, TableCalculationEngine,
                                                             convert_unit, difference, growth_rate, make_numeric,
                                                             mean_values, percentage_point_difference, rank_values,
                                                             share_ratio, sum_values, top_k_values, weighted_mean)
from synthetic_gold_pipeline.tools.units import conversion_factor, parse_value, unit_info

D = Decimal


# ── Atomic ─────────────────────────────────────────────────────────
def test_growth_and_share_and_difference():
    assert growth_rate(D(8), D(7)).value == D(1) / D(7) * 100
    assert difference(D(-5), D(3)).value == D(-8)
    assert share_ratio(D(1), D(7)).value == D(1) / D(7) * 100
    assert percentage_point_difference(D("65.6"), D("66.9")).value == D("-1.3")
    with pytest.raises(CalculationError) as e:
        growth_rate(D(1), D(0))
    assert e.value.code == CalcErrorCode.DENOMINATOR_ZERO
    with pytest.raises(CalculationError) as e:
        growth_rate(D(1), D(-3))
    assert e.value.code == CalcErrorCode.STATISTICALLY_INCOMPATIBLE
    with pytest.raises(CalculationError):
        share_ratio(D(1), D(0))


def test_sum_mean_weighted():
    assert sum_values([D(1), D(-2), D(0)]).value == D(-1)        # 0·음수는 유효
    assert mean_values([D(1), D(2)]).value == D("1.5")
    assert weighted_mean([D(10), D(20)], [D(1), D(3)]).value == D("17.5")
    with pytest.raises(CalculationError):
        weighted_mean([D(1)], [D(0)])


def test_rank_ties_and_top_k_boundary():
    r = rank_values([("a", D(3)), ("b", D(5)), ("c", D(5)), ("d", D(1))])
    assert [x[0] for x in r] == [1, 1, 3, 4]
    top, tie = top_k_values([("a", D(3)), ("b", D(5)), ("c", D(3))], 2)
    assert tie is True
    top, tie = top_k_values([("a", D(3)), ("b", D(5)), ("c", D(1))], 2)
    assert [t[1] for t in top] == ["b", "a"] and tie is False


def test_numeric_result_format_matches_spec_example():
    n = make_numeric(D(1) / D(7) * 100, "%")
    assert n.exact_decimal.startswith("14.2857142857142857")
    assert (n.round_1, n.round_2) == (14.3, 14.29)
    assert "14.3%" in n.formatted_candidates and "14.29%" in n.formatted_candidates
    c = make_numeric(D(1234567), "명")
    assert c.display == "1,234,567명" and "1234567명" in c.formatted_candidates


def test_parse_value_symbols_are_never_zero():
    for raw in ["-", "*", "X", "x", "NaN", "", None, float("nan")]:
        p = parse_value(raw)
        assert not p.ok and p.value is None
    assert parse_value("1,234,567").value == D(1234567)
    assert parse_value("-12.5").value == D("-12.5")
    assert parse_value("0").value == D(0) and parse_value("0").ok


def test_units():
    assert conversion_factor("천명", "명") == D(1000)
    assert conversion_factor("억원", "백만원") == D(100)
    assert unit_info("%").kind.value == "RATE" and not unit_info("%").additive
    assert unit_info("천 가구").family == "HOUSEHOLD"
    assert convert_unit(D(5), "천명", "명").value == D(5000)
    with pytest.raises(CalculationError):
        convert_unit(D(1), "명", "가구")


# ── SQL 안전성 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("sql", [
    "DROP TABLE view_1", "SELECT * FROM view_1; DELETE FROM view_1", "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM '/etc/passwd'", "SELECT * FROM secret_table", "INSTALL httpfs", "COPY view_1 TO 'x.csv'",
    "SELECT * FROM view_1 -- comment", "ATTACH 'x.db'", "SELECT system('ls') FROM view_1", "PRAGMA database_list",
])
def test_sql_validator_rejects(sql):
    assert SqlSafetyValidator({"view_1"}, {"DT", "C1"}).validate(sql)


def test_sql_validator_accepts_read_only():
    v = SqlSafetyValidator({"view_1", "view_2"}, {"DT", "C1", "ITM_ID"})
    assert v.validate('WITH a AS (SELECT "C1", sum(1) AS n FROM view_1 GROUP BY "C1") '
                      'SELECT a."C1" FROM a JOIN view_2 ON a."C1" = view_2."C1" WHERE view_2."ITM_ID" = \'T1\'') == []


# ── Engine ─────────────────────────────────────────────────────────
def _plan(ops, steps, final, filters=()):
    return OperationPlan(plan_id="t", reasoning_type=ReasoningType.CROSS_TABLE_RATIO, operands=list(ops),
                         filters=list(filters), operation=OperationGraph(steps=list(steps), final_step_id=final))


@pytest.fixture(scope="module")
def eng(demo_env):
    return TableCalculationEngine(demo_env["index"], demo_env["cfg"]["calculation"])


def test_engine_scale_conversion_and_coordinates(demo_env, eng):
    idx = demo_env["index"]
    e = find_view(idx, "101_DT_DEMO_ECON", "T1", "2024")
    p = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    plan = _plan([Operand(operand_id="A", view_id=e, itm_id="T1", prd_de="2024", coordinates={"C1": "11"}),
                  Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", coordinates={"C1": "11"})],
                 [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])], "s")
    r = eng.run(plan, [e, p])
    assert r.success and r.final.unit == "%"
    a = next(f for f in r.intermediate_facts if f.operand_id == "A")
    b = next(f for f in r.intermediate_facts if f.operand_id == "B")
    assert a.coordinate.applied_multiplier == "1000" and a.coordinate.normalized_unit == "명"
    expect = D(a.coordinate.raw_value) * 1000 / D(b.coordinate.raw_value) * 100
    assert r.final.value.exact_decimal == make_numeric(expect, "%").exact_decimal
    assert r.unit_conversion_trace and r.unit_conversion_trace[0].factor == "1000"
    assert a.coordinate.csv_line_number == a.coordinate.row_number + 1
    assert all("view_" in s for s in r.executed_sql)


def test_engine_drops_missing_and_zero_denominator(demo_env, eng):
    idx = demo_env["index"]
    v = find_view(idx, "101_DT_DEMO_POP", "T22", "2022")
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T22", prd_de="2022", coordinates={"C1": "29"})],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.MISSING_VALUE and not r.retryable
    p = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    m = find_view(idx, "101_INH_DEMO_MARRY", "T1", "2024")
    r = eng.run(_plan([Operand(operand_id="A", view_id=m, itm_id="T1", prd_de="2024", coordinates={"C1": "11"}),
                       Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", coordinates={"C1": "99"})],
                      [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"], params={"scale": 1000})], "s"), [m, p])
    assert r.error_code == CalcErrorCode.DENOMINATOR_ZERO and not r.retryable


def test_engine_zero_and_negative_values_are_kept(demo_env, eng):
    idx = demo_env["index"]
    v = find_view(idx, "101_DT_DEMO_MOVE_M", "T30", "202403")
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T30", prd_de="202403", coordinates={"C1": "30"})],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.success and r.final.value.raw == 0.0
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T30", prd_de="202403", group_by_level="C1")],
                      [OperationStep(step_id="s", op="MIN", inputs=["A"])], "s"), [v])
    assert r.success and r.final.entity.value.raw < 0


def test_engine_detects_row_amplification(demo_env, eng):
    v = find_view(demo_env["index"], "101_DT_DEMO_DUP", "T1", "2024")
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T1", prd_de="2024", group_by_level="C1")],
                      [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.JOIN_AMPLIFICATION and not r.retryable


def test_engine_structural_errors_are_retryable(demo_env, eng):
    idx = demo_env["index"]
    v = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T20", prd_de="2024", coordinates={"C1": "ZZ"})],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.UNKNOWN_CODE and r.retryable
    h = find_view(idx, "101_DT_DEMO_PROJ", "T1", "2024", {"C1": ["1"]})
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T20", prd_de="2024")],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.CARDINALITY_ERROR and r.retryable
    r = eng.run(_plan([Operand(operand_id="A", view_id=v, itm_id="T20", prd_de="2019", coordinates={"C1": "11"})],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.MISSING_PERIOD and not r.retryable
    r = eng.run(_plan([Operand(operand_id="A", view_id=h, itm_id="T1", prd_de="2024", coordinates={"C2": "11"})],
                      [OperationStep(step_id="s", op="LOOKUP", inputs=["A"])], "s"), [v])
    assert r.error_code == CalcErrorCode.UNKNOWN_VIEW and r.retryable


def test_engine_rejects_non_additive_sum_and_pp_rules(demo_env, eng):
    idx = demo_env["index"]
    a = find_view(idx, "101_DT_DEMO_ECON", "T3", "2023")
    b = find_view(idx, "101_DT_DEMO_ECON", "T3", "2024")
    r = eng.run(_plan([Operand(operand_id="A", view_id=a, itm_id="T3", prd_de="2023", group_by_level="C1")],
                      [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s"), [a])
    assert r.error_code == CalcErrorCode.STATISTICALLY_INCOMPATIBLE
    ops = [Operand(operand_id="A", view_id=a, itm_id="T3", prd_de="2023", coordinates={"C1": "11"}),
           Operand(operand_id="B", view_id=b, itm_id="T3", prd_de="2024", coordinates={"C1": "11"})]
    r = eng.run(_plan(ops, [OperationStep(step_id="s", op="DIFFERENCE", inputs=["B", "A"])], "s"), [a, b])
    assert r.error_code == CalcErrorCode.PLAN_STRUCTURE_ERROR           # % 차이는 %p 로
    r = eng.run(_plan(ops, [OperationStep(step_id="s", op="PERCENTAGE_POINT_DIFFERENCE", inputs=["B", "A"])], "s"), [a, b])
    assert r.success and r.final.unit == "%p"


def test_engine_code_system_mismatch(demo_env, eng):
    idx = demo_env["index"]
    a = find_view(idx, "101_DT_DEMO_SGG", "T1", "2024")
    b = find_view(idx, "101_DT_DEMO_SGG_HH", "T1", "2024")
    r = eng.run(_plan([Operand(operand_id="A", view_id=b, itm_id="T1", prd_de="2024", group_by_level="C1"),
                       Operand(operand_id="B", view_id=a, itm_id="T1", prd_de="2024", group_by_level="C1")],
                      [OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"], params={"scale": 1000}),
                       OperationStep(step_id="t", op="MAX", inputs=["s"])], "t"), [a, b])
    assert r.error_code == CalcErrorCode.JOIN_CODE_SYSTEM_MISMATCH


def test_engine_filter_quantile_and_count(demo_env, eng):
    idx = demo_env["index"]
    m = find_view(idx, "101_INH_DEMO_MARRY", "T1", "2024")
    p = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    plan = _plan([Operand(operand_id="A", view_id=m, itm_id="T1", prd_de="2024", group_by_level="C1"),
                  Operand(operand_id="B", view_id=p, itm_id="T20", prd_de="2024", group_by_level="C1")],
                 [OperationStep(step_id="s", op="COUNT", inputs=["f"])], "s",
                 [FilterSpec(filter_id="f", target_ref="A", condition_ref="B", comparator=">=", threshold_mode="QUANTILE",
                             quantile=0.5)])
    r = eng.run(plan, [m, p])
    assert r.success and r.final.unit == "개" and "f" in r.resolved_thresholds
    assert r.join_diagnostics and not r.join_diagnostics[0].amplified
    flt = next(s for s in r.step_results if s.op == "FILTER")
    thr = D(r.resolved_thresholds["f"].exact_decimal)
    pop = {f.key_code: D(f.coordinate.raw_value) for f in r.intermediate_facts if f.operand_id == "B"}
    assert {e.key_code for e in flt.vector} == {k for k, v in pop.items() if v >= thr and k in
                                                 {f.key_code for f in r.intermediate_facts if f.operand_id == "A"}}


def test_engine_connection_is_sandboxed(demo_env, eng):
    con, alias = eng._connect([find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")])
    try:
        with pytest.raises(duckdb.Error):
            con.execute("SELECT * FROM read_csv('/etc/passwd')").fetchall()
        with pytest.raises(duckdb.Error):
            con.execute("SET enable_external_access=true")
    finally:
        con.close()
