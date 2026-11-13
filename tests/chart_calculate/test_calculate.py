"""[NEW] calculate.py — 연산 11종, 여러 View 짝짓기, 계산 불가 시 None + 사유"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps, run_steps
from backend.schemas.chart import Plan, Step
from tests.chart_calculate._views import TRUNCATED, VID, view

NATION = {"행정구역별": ["전국"]}
SEOUL, BUSAN = "view::seoul", "view::busan"
REGION_COLS = ["시점", "행정구역별", "항목", "값"]


def op(item="혼인건수(건)", role="value", rid=VID, select=None, **kw):
    return {"role": role, "record_id": rid, "item": item, "select": NATION if select is None else select, **kw}


def run(step: dict, records=None):
    return run_answer_steps([Step.model_validate({"step_id": "a1", **step})], records or [view()])[0]


def regions(rid, name, values, item="인구수(명)", **meta):
    return view([[t, name, item, v] for t, v in values], REGION_COLS, rid=rid, **meta)


# ── 두 시점 사이 ─────────────────────────────────────────────────
def test_growth_rate_matches_spec_example():
    """명세 6장 a1·a2"""
    r = run({"op": "growth_rate", "from": "2021", "to": "2025", "display_ref": "d3", "operands": [op()]})
    assert r.value == pytest.approx(24.84013568337775, rel=1e-12) and r.unit == "%" and r.note is None
    assert [(i.role, i.key, i.value, i.unit) for i in r.inputs] == [
        ("value", {"시점": "2021"}, 192507.0, "건"), ("value", {"시점": "2025"}, 240326.0, "건")]
    assert r.record_ids == [VID] and r.display_ref == "d3"
    r2 = run({"op": "growth_rate", "from": "2021", "to": "2025", "operands": [op("출생아수(명)")]})
    assert r2.value == pytest.approx(-2.3875315663834327, rel=1e-12)


def test_change_keeps_source_unit():
    r = run({"op": "change", "from": "2021", "to": "2025", "operands": [op()]})
    assert (r.value, r.unit) == (47819.0, "건")


def test_change_defaults_to_first_and_last():
    assert run({"op": "change", "operands": [op()]}).value == 240326.0 - 192507.0


def test_change_prev_gives_one_value_per_period():
    r = run({"op": "change", "base": "prev", "operands": [op()]})
    assert [(p["key"]["시점"], p["value"]) for p in r.value] == [
        ("2022", -817.0), ("2023", 1967.0), ("2024", 28755.0), ("2025", 17914.0)]


def test_cagr():
    r = run({"op": "cagr", "from": "2021", "to": "2025", "operands": [op()]})
    assert r.value == pytest.approx(((240326 / 192507) ** 0.25 - 1) * 100) and r.unit == "%"


def test_growth_rate_zero_base_is_null():
    rec = regions(SEOUL, "서울특별시", [("2021", 0.0), ("2025", 10.0)])
    r = run({"op": "growth_rate", "operands": [op("인구수(명)", rid=SEOUL, select={})]}, [rec])
    assert r.value is None and r.note == "기준값 0"


def test_missing_period_is_null_with_reason():
    r = run({"op": "growth_rate", "from": "2019", "to": "2025", "operands": [op(select={})]})   # select 에 없으면 계산 단계에서
    assert r.value is None and "시점 2019 값 없음" in r.note
    r = run({"op": "growth_rate", "operands": [op(select={**NATION, "시점": ["2019", "2025"]})]})  # select 에 있으면 선택 단계에서
    assert r.value is None and "시점에 없는 값: ['2019']" in r.note


def test_truncated_view_is_null():
    r = run({"op": "change", "operands": [op()]}, [view(notes=[TRUNCATED])])
    assert r.value is None and r.note.startswith("truncated")


# ── 점마다 ───────────────────────────────────────────────────────
def test_raw_single_point_is_scalar():
    r = run({"op": "raw", "operands": [op(select={**NATION, "시점": ["2025"]})]})
    assert r.value == 240326.0 and r.unit == "건"


def test_index_base_100():
    r = run({"op": "index", "base": "2021", "operands": [op()]})
    assert r.unit == "index" and r.value[0] == {"key": {"시점": "2021"}, "value": 100.0}
    assert r.value[-1]["value"] == pytest.approx(240326 / 192507 * 100)


RANK_ROWS = [["2025", n, "인구수(명)", v] for n, v in [("가", 30.0), ("나", 50.0), ("다", 30.0), ("라", 10.0)]]


def test_rank_ties_and_top_n():
    rec = view(RANK_ROWS, REGION_COLS, rid=SEOUL)
    r = run({"op": "rank", "operands": [op("인구수(명)", rid=SEOUL, select={})]}, [rec])
    assert [(p["key"]["행정구역별"], p["rank"]) for p in r.value] == [("나", 1), ("가", 2), ("다", 2), ("라", 4)]
    top = run({"op": "rank", "top_n": 2, "operands": [op("인구수(명)", rid=SEOUL, select={})]}, [rec])
    assert [p["rank"] for p in top.value] == [1, 2, 2]          # 동점은 함께 남긴다


def test_extreme_returns_key_even_for_one():
    rec = view(RANK_ROWS, REGION_COLS, rid=SEOUL)
    r = run({"op": "extreme", "operands": [op("인구수(명)", rid=SEOUL, select={})]}, [rec])
    assert r.value == [{"key": {"시점": "2025", "행정구역별": "나"}, "value": 50.0}]
    low = run({"op": "extreme", "kind": "min", "operands": [op("인구수(명)", rid=SEOUL, select={})]}, [rec])
    assert low.value[0]["key"]["행정구역별"] == "라"


def test_aggregate_sum_mean_by():
    rec = view(RANK_ROWS + [["2024", "가", "인구수(명)", 20.0]], REGION_COLS, rid=SEOUL)
    o = [op("인구수(명)", rid=SEOUL, select={})]
    assert run({"op": "aggregate", "operands": o}, [rec]).value == 140.0
    assert run({"op": "aggregate", "agg": "mean", "operands": o}, [rec]).value == 28.0
    by = run({"op": "aggregate", "by": ["시점"], "operands": o}, [rec])
    assert sorted((p["key"]["시점"], p["value"]) for p in by.value) == [("2024", 20.0), ("2025", 120.0)]


# ── 두 피연산자 ──────────────────────────────────────────────────
def pair(opname="diff", **meta_b):
    a = regions(SEOUL, "서울특별시", [("2023", 940.0), ("2024", 930.0), ("2025", 925.0)])
    b = regions(BUSAN, "부산광역시", [("2023", 330.0), ("2024", 0.0)], **meta_b)
    step = {"op": opname, "join_on": ["시점"], "operands": [
        op("인구수(명)", "a", SEOUL, {}), op("인구수(명)", "b", BUSAN, {})]}
    return run(step, [a, b])


def test_diff_joins_two_views_and_marks_missing_side():
    """명세 4장 '여러 View 를 쓰는 계산'"""
    r = pair()
    assert [(p["key"], p["value"]) for p in r.value] == [
        ({"시점": "2023"}, 610.0), ({"시점": "2024"}, 930.0), ({"시점": "2025"}, None)]
    assert r.unit == "명" and r.record_ids == [SEOUL, BUSAN] and "한쪽 값 없음" in r.note
    assert {i.role for i in r.inputs} == {"a", "b"}


def test_ratio_zero_denominator():
    r = pair("ratio")
    assert r.unit == "배" and r.value[0]["value"] == pytest.approx(940 / 330) and r.value[1]["value"] is None
    assert "분모 0" in r.note


def test_diff_rejects_different_units_and_periods():
    a = regions(SEOUL, "서울특별시", [("2024", 1.0)])
    b = regions(BUSAN, "부산광역시", [("2024", 1.0)], item="혼인건수(건)")
    r = run({"op": "diff", "join_on": ["시점"], "operands": [
        op("인구수(명)", "a", SEOUL, {}), op("혼인건수(건)", "b", BUSAN, {})]}, [a, b])
    assert r.value is None and r.note == "단위가 다름: 명 / 건"
    assert pair(prd_se="M").note == "수록 주기가 다름: Y / M"


def test_diff_duplicate_key_is_null():
    a = view([["2024", "서울특별시", "인구수(명)", 1.0], ["2024", "인천광역시", "인구수(명)", 2.0]], REGION_COLS, rid=SEOUL)
    b = regions(BUSAN, "부산광역시", [("2024", 1.0)])
    r = run({"op": "diff", "join_on": ["시점"], "operands": [
        op("인구수(명)", "a", SEOUL, {}), op("인구수(명)", "b", BUSAN, {})]}, [a, b])
    assert r.value is None and "키 중복" in r.note


def test_diff_needs_join_on_for_many_points():
    a = regions(SEOUL, "서울특별시", [("2023", 1.0), ("2024", 2.0)])
    b = regions(BUSAN, "부산광역시", [("2023", 1.0), ("2024", 2.0)])
    r = run({"op": "diff", "operands": [op("인구수(명)", "a", SEOUL, {}), op("인구수(명)", "b", BUSAN, {})]}, [a, b])
    assert r.value is None and r.note.startswith("join_on 필요")


# ── share ────────────────────────────────────────────────────────
SHARE_ROWS = [["2025", n, "출생아수(명)", v] for n, v in [("전국", 200.0), ("서울특별시", 40.0), ("부산광역시", 10.0)]]
PARTS = {"행정구역별": ["서울특별시", "부산광역시"]}


def test_share_of_selected_items():
    r = run({"op": "share", "operands": [op("출생아수(명)", "part", select=PARTS)]}, [view(SHARE_ROWS)])
    assert [p["value"] for p in r.value] == [80.0, 20.0]
    assert r.scope_label == "선택 항목 내 비중" and r.unit == "%"


def test_share_of_question_total():
    den = {"scope": "question", "basis": "질문의 '전국 대비'", "label": "전국 대비 비중",
           "operand": {"record_id": VID, "item": "출생아수(명)", "select": NATION}}
    r = run({"op": "share", "denominator": den, "operands": [
        op("출생아수(명)", "part", select={"행정구역별": ["서울특별시"]})]}, [view(SHARE_ROWS)])
    assert r.value == 20.0 and r.scope_label == "전국 대비 비중"
    assert [(i.role, i.value) for i in r.inputs] == [("part", 40.0), ("total", 200.0)]


def test_share_total_absent_or_zero():
    den = {"scope": "question", "operand": {"record_id": VID, "item": "출생아수(명)", "select": {"행정구역별": ["세종"]}}}
    r = run({"op": "share", "denominator": den, "operands": [op("출생아수(명)", "part", select=PARTS)]},
            [view(SHARE_ROWS)])
    assert r.value is None and "행정구역별에 없는 값: ['세종']" in r.note
    zero = view([["2025", "가", "출생아수(명)", 0.0]], REGION_COLS)
    r = run({"op": "share", "operands": [op("출생아수(명)", "part", select={})]}, [zero])
    assert r.value is None and "분모 0" in r.note


# ── 단계 연결 ────────────────────────────────────────────────────
def test_chart_step_without_operands_uses_plan():
    plan = Plan(chart_id="c1", record_id=VID, chart_type="line", measure="raw",
                select={**NATION, "항목": ["혼인건수(건)"], "시점": ["2021", "2022", "2023"]},
                steps=[Step(step_id="s1", op="raw", display_ref="d1")])
    calc = run_steps(plan.steps, [view()], default=plan)["s1"]
    assert [(p.key, p.value) for p in calc.points] == [
        ({"시점": "2021"}, 192507.0), ({"시점": "2022"}, 191690.0), ({"시점": "2023"}, 193657.0)]
    assert calc.unit == "건"


def test_input_chains_previous_step():
    rec = view(RANK_ROWS + [["2024", n, "인구수(명)", v] for n, v in [("가", 20.0), ("나", 25.0), ("다", 60.0), ("라", 10.0)]],
               REGION_COLS, rid=SEOUL)
    steps = [Step.model_validate({"step_id": "s1", "op": "growth_rate", "from": "2024", "to": "2025",
                                  "operands": [op("인구수(명)", rid=SEOUL, select={})]}),
             Step.model_validate({"step_id": "s2", "op": "rank", "input": "s1", "top_n": 1})]
    top = run_steps(steps, [rec])["s2"]
    assert [(p.key, p.value, p.extra) for p in top.points] == [({"행정구역별": "나"}, 100.0, {"rank": 1})]
    assert top.unit == "%" and len(top.inputs) == 8          # 근거는 앞 단계의 원래 값


def test_unknown_view_and_missing_operand():
    assert run({"op": "raw", "operands": [op(rid="view::x")]}).note == "View 없음: view::x"
    assert run({"op": "raw"}).note == "피연산자 없음: value"


# ── combine: 여러 값 더하기·빼기 ──────────────────────────────────
POP = ["시점", "행정구역별", "항목", "값"]
BIRTH, DEATH, MOVE = "view::birth", "view::death", "view::move"


def flows(rid, item, values):
    return view([[t, "전국", item, v] for t, v in values], POP, rid=rid)


def term(rid, item, sign="+"):
    return {"role": "term", "sign": sign, "record_id": rid, "item": item, "select": {}}


def test_combine_births_minus_deaths_plus_migration():
    """인구 증가 = 출생 − 사망 + 순이동 (세 표, 시점끼리 짝지음)"""
    recs = [flows(BIRTH, "출생아수(명)", [("2024", 238.0), ("2025", 254.0)]),
            flows(DEATH, "사망자수(명)", [("2024", 358.0), ("2025", 363.0)]),
            flows(MOVE, "순이동자수(명)", [("2024", 50.0), ("2025", 40.0)])]
    r = run({"op": "combine", "operands": [term(BIRTH, "출생아수(명)"), term(DEATH, "사망자수(명)", "-"),
                                           term(MOVE, "순이동자수(명)")]}, recs)
    assert [(v["key"], v["value"]) for v in r.value] == [({"시점": "2024"}, -70.0), ({"시점": "2025"}, -69.0)]
    assert r.unit == "명" and r.note is None and r.record_ids == [BIRTH, DEATH, MOVE]
    assert [i.role for i in r.inputs] == ["+", "+", "-", "-", "+", "+"]          # QA 가 부호까지 보고 다시 계산


def test_combine_refuses_different_units_and_missing_years():
    recs = [flows(BIRTH, "출생아수(명)", [("2024", 1.0), ("2025", 2.0)]), flows(DEATH, "혼인건수(건)", [("2024", 1.0)])]
    r = run({"op": "combine", "operands": [term(BIRTH, "출생아수(명)"), term(DEATH, "혼인건수(건)", "-")]}, recs)
    assert r.value is None and r.note == "단위가 다름: 명 / 건"
    recs[1] = flows(DEATH, "사망자수(명)", [("2024", 1.0)])
    r = run({"op": "combine", "operands": [term(BIRTH, "출생아수(명)"), term(DEATH, "사망자수(명)", "-")]}, recs)
    assert r.value == [{"key": {"시점": "2024"}, "value": 0.0}, {"key": {"시점": "2025"}, "value": None}]
    assert r.note == "{'시점': '2025'}: 값 없음 (사망자수(명))"


def test_combine_needs_one_value_per_key_and_two_terms():
    """피연산자 하나가 시점마다 값이 여럿이면(지역 2개) 먼저 aggregate 로 합쳐야 한다"""
    two = view([["2024", r, "출생아수(명)", 1.0] for r in ("서울특별시", "부산광역시")], POP, rid=BIRTH)
    one = flows(DEATH, "사망자수(명)", [("2024", 1.0)])
    r = run({"op": "combine", "operands": [term(BIRTH, "출생아수(명)"), term(DEATH, "사망자수(명)", "-")]}, [two, one])
    assert r.value is None and "키 중복 (출생아수(명)" in r.note
    r = run({"op": "combine", "operands": [term(DEATH, "사망자수(명)")]}, [one])
    assert r.value is None and r.note == "combine 은 피연산자가 2개 이상 필요"


def test_aggregate_refuses_items_with_different_units():
    """'혼인건수(건)' + '조혼인율(천명당)' 을 더하지 않는다 (예전에는 단위 확인 없이 더했다)"""
    r = run({"op": "aggregate", "operands": [{"role": "value", "record_id": VID,
             "select": {**NATION, "시점": ["2025"], "항목": ["혼인건수(건)", "조혼인율(천명당)"]}}]})
    assert r.value is None and r.note == "단위가 다른 값을 합칠 수 없음: 건, 천명당"
    same = run({"op": "aggregate", "operands": [{"role": "value", "record_id": VID,
                "select": {**NATION, "시점": ["2025"], "항목": ["혼인건수(건)"]}}]})
    assert same.value == 240326.0


# ── GPT 검토 (2026-11-11) A. 결합 키 ─────────────────────────────
def test_join_on_typo_is_refused_not_merged():
    """join_on 오타면 모든 점이 'None' 키로 묶여 2024·2025·2026 이 하나로 계산됐다 (75) → 계산하지 않는다"""
    recs = [flows(BIRTH, "출생아수(명)", [("2024", 100.0)]), flows(DEATH, "사망자수(명)", [("2025", 30.0)]),
            flows(MOVE, "순이동자수(명)", [("2026", 5.0)])]
    r = run({"op": "combine", "join_on": ["시점x"], "operands": [
        term(BIRTH, "출생아수(명)"), term(DEATH, "사망자수(명)", "-"), term(MOVE, "순이동자수(명)")]}, recs)
    assert r.value is None and r.note == "결합 열이 View 에 없음: ['시점x'] (출생아수(명))"
    d = run({"op": "diff", "join_on": ["연도"], "operands": [
        {**term(BIRTH, "출생아수(명)"), "role": "a"}, {**term(DEATH, "사망자수(명)"), "role": "b"}]}, recs)
    assert d.value is None and d.note.startswith("결합 열이 View 에 없음: ['연도']")


def regional(rid, item, values):
    return view([["2024", r, item, v] for r, v in values], POP, rid=rid)


def test_join_on_fixed_region_uses_its_value():
    """join_on 에 지역을 적으면 고정된 지역(서울 vs 부산)끼리는 짝짓지 않는다 (예전: 서울 출생 − 부산 사망 = 20)"""
    recs = [regional(BIRTH, "출생아수(명)", [("서울특별시", 100.0), ("부산광역시", 70.0)]),
            regional(DEATH, "사망자수(명)", [("서울특별시", 60.0), ("부산광역시", 80.0)])]
    ops = [{**term(BIRTH, "출생아수(명)"), "select": {"행정구역별": ["서울특별시"]}},
           {**term(DEATH, "사망자수(명)", "-"), "select": {"행정구역별": ["부산광역시"]}}]
    r = run({"op": "combine", "join_on": ["시점", "행정구역별"], "operands": ops}, recs)
    assert r.value == [{"key": {"시점": "2024", "행정구역별": "서울특별시"}, "value": None},
                       {"key": {"시점": "2024", "행정구역별": "부산광역시"}, "value": None}]
    same = [{**o, "select": {"행정구역별": ["서울특별시"]}} for o in ops]
    assert run({"op": "combine", "join_on": ["시점", "행정구역별"], "operands": same}, recs).value == 40.0


def test_cross_region_combine_keeps_regions_in_inputs():
    """시점으로만 짝지으면 지역이 다른 결합(서울 + 부산 − 대구)은 의도된 계산이다 → 그대로 하되 근거에 지역을 남긴다"""
    recs = [regional(BIRTH, "출생아수(명)", [("서울특별시", 100.0), ("부산광역시", 70.0)]),
            regional(DEATH, "사망자수(명)", [("서울특별시", 60.0), ("부산광역시", 80.0)])]
    r = run({"op": "combine", "operands": [{**term(BIRTH, "출생아수(명)"), "select": {"행정구역별": ["서울특별시"]}},
                                           {**term(DEATH, "사망자수(명)", "-"), "select": {"행정구역별": ["부산광역시"]}}]}, recs)
    assert r.value == 20.0
    assert [(i.role, i.key, i.value) for i in r.inputs] == [
        ("+", {"행정구역별": "서울특별시", "시점": "2024"}, 100.0), ("-", {"행정구역별": "부산광역시", "시점": "2024"}, 80.0)]


# ── GPT 검토 (2026-11-11) B. 단위·주기는 모든 피연산자를 함께 본다 ──
U0, U1, U2 = "view::u0", "view::u1", "view::u2"


def units_case():
    return [flows(U0, "출생아수", [("2024", 10.0)]), flows(U1, "사망자수(명)", [("2024", 15.0)]),
            flows(U2, "혼인건수(건)", [("2024", 5.0)])]


def test_unknown_first_unit_no_longer_hides_mismatch():
    """[단위 미상, 명, 건] 을 함께 계산했다 (−10) → 확인할 수 없으면 계산하지 않는다"""
    r = run({"op": "combine", "operands": [term(U0, "출생아수"), term(U1, "사망자수(명)", "-"),
                                           term(U2, "혼인건수(건)", "-")]}, units_case())
    assert r.value is None and r.note == "단위를 확인할 수 없음: ? / 명 / 건 (출생아수 / 사망자수(명) / 혼인건수(건))"
    d = run({"op": "diff", "join_on": ["시점"], "operands": [{**term(U0, "출생아수"), "role": "a"},
                                                             {**term(U2, "혼인건수(건)"), "role": "b"}]}, units_case())
    assert d.value is None and d.note.startswith("단위를 확인할 수 없음: ? / 건")


def test_all_unknown_units_allowed_only_for_same_indicator():
    """단위를 모두 몰라도 같은 지표끼리(서울 + 부산 − 대구 출생아수)는 섞일 일이 없다"""
    recs = [regional(BIRTH, "출생아수", [("서울특별시", 100.0), ("부산광역시", 70.0), ("대구광역시", 30.0)])]
    sel = lambda r: {"행정구역별": [r]}  # noqa: E731
    r = run({"op": "combine", "operands": [{**term(BIRTH, "출생아수"), "select": sel("서울특별시")},
                                           {**term(BIRTH, "출생아수"), "select": sel("부산광역시")},
                                           {**term(BIRTH, "출생아수", "-"), "select": sel("대구광역시")}]}, recs)
    assert r.value == 140.0
    other = [flows(U0, "출생아수", [("2024", 10.0)]), flows(U1, "사망자수", [("2024", 4.0)])]
    r = run({"op": "combine", "operands": [term(U0, "출생아수"), term(U1, "사망자수", "-")]}, other)
    assert r.value is None and r.note.startswith("단위를 확인할 수 없음: ? / ?")


def test_period_must_be_known_for_all():
    recs = [flows(U0, "출생아수(명)", [("2024", 10.0)]), flows(U1, "사망자수(명)", [("2024", 4.0)])]
    recs[1].metadata.pop("prd_se")
    r = run({"op": "combine", "operands": [term(U0, "출생아수(명)"), term(U1, "사망자수(명)", "-")]}, recs)
    assert r.value is None and r.note == "수록 주기를 확인할 수 없음: Y / ?"


# ── GPT 검토 (2026-11-11) C. 합계에 다른 지표가 섞이지 않게 ──────
def test_aggregate_refuses_births_plus_fertility_rate():
    """실제 DT_1B81A23 2024 전국 행: 출생아수 238,317 + 합계출산율 0.748 = 238,317.748 이 경고 없이 나왔다"""
    rec = view([["2024", "전국", "출생아수", 238317.0], ["2024", "전국", "합계출산율", 0.748]], POP, rid="view::fert",
               unit="명 가임여자 1명당 명")
    r = run({"op": "aggregate", "operands": [{"role": "value", "record_id": "view::fert", "select": {}}]}, [rec])
    assert r.value is None and r.note == "서로 다른 지표를 합칠 수 없음: {'항목': ['출생아수', '합계출산율']}"


def test_aggregate_allows_categories_and_same_unit_items():
    """지역·연령·성별 범주는 더해도 되고, 괄호 단위가 같은 지표(남자 + 여자)도 된다"""
    regions = view([["2024", r, "출생아수", v] for r, v in [("서울특별시", 3.0), ("부산광역시", 2.0)]], POP, rid="view::reg")
    assert run({"op": "aggregate", "operands": [{"role": "value", "record_id": "view::reg", "select": {}}]}, [regions]).value == 5.0
    sexes = view([["2024", "전국", i, v] for i, v in [("남자인구수(명)", 3.0), ("여자인구수(명)", 4.0)]], POP, rid="view::sex")
    assert run({"op": "aggregate", "operands": [{"role": "value", "record_id": "view::sex", "select": {}}]}, [sexes]).value == 7.0


def test_aggregate_by_indicator_column_does_not_mix():
    """지표 열로 묶으면(by 항목) 지표마다 따로 더하므로 섞이지 않는다"""
    rec = view([["2024", r, i, 1.0] for r in ("서울특별시", "부산광역시") for i in ("출생아수", "합계출산율")], POP, rid="view::by")
    r = run({"op": "aggregate", "by": ["항목"], "operands": [{"role": "value", "record_id": "view::by", "select": {}}]}, [rec])
    assert [(v["key"], v["value"]) for v in r.value] == [({"항목": "출생아수"}, 2.0), ({"항목": "합계출산율"}, 2.0)]


# ── GPT 검토 (2026-11-11) E. 정수 보존 ───────────────────────────
def test_big_integers_keep_exact_difference():
    """9,007,199,254,740,993 − 9,007,199,254,740,992 가 0 이 됐다 (합을 0.0 에서 시작해 실수로 바뀜)"""
    big = [flows(BIRTH, "가(명)", [("2024", 9007199254740993)]), flows(DEATH, "나(명)", [("2024", 9007199254740992)])]
    r = run({"op": "combine", "operands": [term(BIRTH, "가(명)"), term(DEATH, "나(명)", "-")]}, big)
    assert r.value == 1 and type(r.value) is int
    assert [type(i.value) for i in r.inputs] == [int, int] and r.inputs[0].value == 9007199254740993
    d = run({"op": "diff", "join_on": ["시점"], "operands": [{**term(BIRTH, "가(명)"), "role": "a"},
                                                             {**term(DEATH, "나(명)"), "role": "b"}]}, big)
    assert d.value == 1 and type(d.value) is int


def test_integer_results_stay_int_through_json():
    """API 응답(JSON)에서도 정수는 정수로 (192507 이 192507.0 이 되지 않게)"""
    rec = flows(BIRTH, "출생아수(명)", [("2024", 192507), ("2025", 240326)])
    r = run({"op": "change", "from": "2024", "to": "2025", "operands": [term(BIRTH, "출생아수(명)")]}, [rec])
    assert r.model_dump_json().count('"value":47819') == 1


# ── GPT 2차 검토 (2026-11-11) P2. 범주인지 지표인지는 View 구조로 ──
MARITAL = ["시점", "행정구역(읍면동)별", "혼인상태별", "항목", "값"]


def marital(*rows):
    return view([["2013", "세종특별자치시", s, "인구", v] for s, v in rows], MARITAL, rid="view::101_DT_1SN1006::IR::m-1::value",
                unit="명")


def agg(rec):
    return run({"op": "aggregate", "operands": [{"role": "value", "record_id": rec.id, "select": {}}]}, [rec])


def test_category_column_sum_by_structure():
    """원본 DT_1SN1006: 혼인상태별 15세미만 18,547 + 15세이상 90,159 = 108,706 (일반가구원). 이름 규칙에 없는 분류 열도 범주"""
    r = agg(marital(("15세미만", 18547), ("15세이상", 90159)))
    assert (r.value, r.note) == (108706, None)


def test_total_row_mixed_into_categories_is_refused():
    r = agg(marital(("계", 108706), ("15세미만", 18547)))
    assert r.value is None and r.note == "총계 행이 섞여 두 번 셈: 혼인상태별 ['계'] + 나머지 ['15세미만']"


def test_indicator_like_classification_is_not_summed():
    """분류 열이지만 지표를 담는 이름(종류별)은 항목 열처럼: 단위를 모르면 더하지 않는다"""
    rec = view([["2024", "전국", "출생아수", "인구동향", 238317.0], ["2024", "전국", "합계출산율", "인구동향", 0.748]],
               ["시점", "행정구역별", "종류별", "항목", "값"], rid="view::kind")
    assert agg(rec).note == "서로 다른 지표를 합칠 수 없음: {'종류별': ['출생아수', '합계출산율']}"
