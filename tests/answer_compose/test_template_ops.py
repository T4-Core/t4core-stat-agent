"""[NEW] template.py — extreme · diff · aggregate · combine 를 모듈 3 의 실제 계산 결과로 (단위 · 조사 · 범위 표기)"""
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.template import sentence
from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.agent.chart_calculate.display import make_display, register
from backend.schemas.answer import Module6Request
from backend.schemas.chart import Step
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import view

POP = [47008111, 47278951, 47639618, 47892330, 48082519, 48184561, 48438292, 48683638, 49054708, 49307835]
ROWS = []
for i, v in enumerate(POP):
    y = str(2000 + i)
    ROWS += [[y, "서울특별시", "인구수(명)", v // 5], [y, "부산광역시", "인구수(명)", v // 14], [y, "전국", "인구수(명)", v],
             [y, "전국", "출생아수(명)", 600000 - i * 20000], [y, "전국", "사망자수(명)", 250000 + i * 5000],
             [y, "전국", "고령인구비율(%)", 7.2 + i * 0.4]]
REC = view(ROWS, ["시점", "행정구역별", "항목", "값"], rid="view::pop")
NAT, YEARS = {"행정구역별": ["전국"]}, [str(y) for y in range(2000, 2010)]


def op(item, select, role="value", **kw):
    return {"role": role, "record_id": "view::pop", "item": item, "select": select, **kw}


def say(step: dict, known=True) -> str:
    st = Step.model_validate({"step_id": "a1", **step})
    r = run_answer_steps([st], [REC])[0]
    displays = {}
    r.display_ref = register(displays, make_display(r.unit))
    req = Module6Request(query_bundle=QueryBundle(query_id="q", original="질문"), records=[REC], calc_results=[r],
                         displays=displays, answer_steps=[st] if known else [])
    return sentence(Facts(req), r)


# ── extreme ─────────────────────────────────────────────────────
def test_least_population_year_in_2000s():
    """'2000년대 인구가 가장 적은 해는?'"""
    step = {"op": "extreme", "kind": "min", "operands": [op("인구수(명)", {**NAT, "시점": YEARS})]}
    assert say(step) == "전국 인구수가 가장 적은 해는 2000년으로, 47,008,111명입니다."
    assert say({**step, "kind": "max"}) == "전국 인구수가 가장 많은 해는 2009년으로, 49,307,835명입니다."


def test_extreme_never_guesses_direction_without_answer_steps():
    step = {"op": "extreme", "kind": "min", "operands": [op("인구수(명)", {**NAT, "시점": YEARS})]}
    assert say(step, known=False) == "전국 인구수의 극값(최대 또는 최소)은 2000년 47,008,111명입니다."


def test_extreme_rate_and_place_wording():
    rate = {"op": "extreme", "kind": "max", "operands": [op("고령인구비율(%)", {**NAT, "시점": YEARS})]}
    assert say(rate) == "전국 고령인구비율이 가장 높은 해는 2009년으로, 10.8%입니다."
    place = {"op": "extreme", "kind": "max", "operands": [op("인구수(명)", {"행정구역별": ["서울특별시", "부산광역시"], "시점": ["2009"]})]}
    assert say(place) == "2009년 인구수가 가장 많은 곳은 서울특별시로, 9,861,567명입니다."
    both = {"op": "extreme", "kind": "max", "operands": [op("인구수(명)", {"행정구역별": ["서울특별시", "부산광역시"], "시점": ["2008", "2009"]})]}
    assert say(both) == "인구수 중 가장 큰 값은 2009년 서울특별시 9,861,567명입니다."      # 지역도 시점도 여러 개 중에서 고른 것


# ── diff ────────────────────────────────────────────────────────
def diff(year="2009", **kw):
    return {"op": "diff", "join_on": ["시점"], "operands": [
        op("인구수(명)", {"행정구역별": ["서울특별시"], "시점": [year]}, "a"), op("인구수(명)", {"행정구역별": ["부산광역시"], "시점": [year]}, "b")], **kw}


def test_diff_names_keep_year_and_particles_are_right():
    assert say(diff()) == "2009년 서울특별시 인구수(9,861,567명)가 부산광역시 인구수(3,521,988명)보다 6,339,579명 큽니다."      # 같은 시점은 한 번만
    reverse = {"op": "diff", "join_on": ["시점"], "operands": [
        op("인구수(명)", {"행정구역별": ["부산광역시"], "시점": ["2009"]}, "a"), op("인구수(명)", {"행정구역별": ["서울특별시"], "시점": ["2009"]}, "b")]}
    assert say(reverse).endswith("보다 6,339,579명 작습니다.")


def over_years(order=("서울특별시", "부산광역시")):
    two = diff()
    for o, name in zip(two["operands"], order):
        o["select"] = {"행정구역별": [name], "시점": ["2008", "2009"]}
    return two


def test_diff_over_years_says_who_is_larger_and_by_how_much():
    assert say(over_years()) == "서울특별시 인구수가 부산광역시보다 2008년 6,307,034명, 2009년 6,339,579명 큽니다."
    assert say(over_years(("부산광역시", "서울특별시"))) == "부산광역시 인구수가 서울특별시보다 2008년 6,307,034명, 2009년 6,339,579명 작습니다."


def test_diff_over_years_with_mixed_signs_uses_the_expression():
    rows = [["2008", "서울특별시", "인구수(명)", 10.0], ["2009", "서울특별시", "인구수(명)", 30.0],
            ["2008", "부산광역시", "인구수(명)", 20.0], ["2009", "부산광역시", "인구수(명)", 20.0]]
    rec = view(rows, ["시점", "행정구역별", "항목", "값"], rid="view::pop")
    st = Step.model_validate({"step_id": "a1", **over_years()})
    r = run_answer_steps([st], [rec])[0]
    req = Module6Request(query_bundle=QueryBundle(original="q"), records=[rec], calc_results=[r],
                         displays={"d": make_display("명")}, answer_steps=[st])
    r.display_ref = "d"
    assert sentence(Facts(req), r) == "서울특별시 인구수 − 부산광역시 인구수 차이는 2008년 -10명, 2009년 10명입니다."


def test_diff_over_years_names_the_year_it_could_not_compute():
    part = over_years()
    part["operands"][1]["select"]["시점"] = ["2009"]
    assert say(part) == "서울특별시 인구수가 부산광역시보다 2009년 6,339,579명 큽니다. (2008년은 계산할 수 없습니다)"


# ── aggregate ───────────────────────────────────────────────────
def test_aggregate_says_what_was_summed_and_keeps_unit():
    both = op("인구수(명)", {"행정구역별": ["서울특별시", "부산광역시"], "시점": ["2009"]})
    assert say({"op": "aggregate", "agg": "sum", "operands": [both]}) == "2009년 서울특별시·부산광역시 인구수의 합계는 13,383,555명입니다."
    assert say({"op": "aggregate", "agg": "mean", "operands": [both]}) == "2009년 서울특별시·부산광역시 인구수의 평균은 6,691,778명입니다."
    rate = {"op": "aggregate", "agg": "mean", "operands": [op("고령인구비율(%)", {**NAT, "시점": YEARS})]}
    assert say(rate) == "2000~2009년 전국 고령인구비율의 평균은 9.0%입니다."              # % 는 소수 1자리


def test_aggregate_many_places_are_counted_not_listed():
    names = ["서울특별시", "부산광역시", "대구광역시", "인천광역시"]
    rows = [["2009", n, "인구수(명)", 100.0 * i] for i, n in enumerate(names, 1)]
    rec = view(rows, ["시점", "행정구역별", "항목", "값"], rid="view::pop")
    st = Step.model_validate({"step_id": "a1", "op": "aggregate", "agg": "sum", "operands": [op("인구수(명)", {})]})
    r = run_answer_steps([st], [rec])[0]
    req = Module6Request(query_bundle=QueryBundle(original="q"), records=[rec], calc_results=[r],
                         displays={"d": make_display("명")}, answer_steps=[st])
    r.display_ref = "d"
    assert sentence(Facts(req), r) == "2009년 4개 행정구역 인구수의 합계는 1,000명입니다."


# ── combine ─────────────────────────────────────────────────────
def test_combine_shows_the_expression_and_unit():
    step = {"op": "combine", "join_on": ["시점"], "operands": [
        op("출생아수(명)", {**NAT, "시점": ["2009"]}, "term", sign="+"), op("사망자수(명)", {**NAT, "시점": ["2009"]}, "term", sign="-")]}
    assert say(step) == "2009년 전국 출생아수 − 사망자수는 125,000명입니다."          # 600000−180000 − (250000+45000)
    over_time = {**step, "operands": [{**o, "select": {**NAT, "시점": ["2008", "2009"]}} for o in step["operands"]]}
    assert say(over_time) == "전국 출생아수 − 사망자수는 2008년 150,000명, 2009년 125,000명입니다."


def test_combine_same_item_different_places():
    step = {"op": "combine", "join_on": ["시점"], "operands": [
        op("인구수(명)", {"행정구역별": ["서울특별시"], "시점": ["2009"]}, "term", sign="+"),
        op("인구수(명)", {"행정구역별": ["부산광역시"], "시점": ["2009"]}, "term", sign="+"),
        op("인구수(명)", {"행정구역별": ["전국"], "시점": ["2009"]}, "term", sign="-")]}
    assert say(step) == "2009년 서울특별시 + 부산광역시 − 전국 인구수는 -35,924,280명입니다."


# ── 계산 불가 ───────────────────────────────────────────────────
def test_failure_reasons_are_shown_as_calculation_notes():
    assert say({"op": "growth_rate", "from": "1999", "to": "2009", "operands": [op("인구수(명)", NAT)]}) == \
        "증감률을 계산하지 못했습니다(1999년 값이 없습니다)."
    unit_mismatch = {"op": "diff", "join_on": ["시점"], "operands": [
        op("인구수(명)", {**NAT, "시점": ["2009"]}, "a"), op("고령인구비율(%)", {**NAT, "시점": ["2009"]}, "b")]}
    assert say(unit_mismatch) == "인구수 차이를 계산하지 못했습니다(단위가 달라 비교할 수 없습니다: 명 / %)."
