"""[NEW] placeholder.py — 치환 문법과 검사 3가지"""
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.placeholder import check, fill
from backend.schemas.answer import Caveat
from backend.schemas.chart import CalcResult
from tests.answer_compose._data import growth, request
from tests.chart_calculate._views import VID

GOOD = "혼인건수는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} 증가했습니다."


def facts(*results):
    return Facts(request(results=list(results) or None))


def run(text, f=None, caveats=()):
    f = f or facts()
    filled = fill(text, f)
    return filled, check(text, filled, f, list(caveats))


def test_fill_values_with_displays():
    filled, problems = run(GOOD)
    assert filled.text == "혼인건수는 2021년 192,507건에서 2025년 240,326건으로 24.8% 증가했습니다."
    assert (filled.used, problems) == (["a1"], [])


def test_abs_and_signed_values():
    f = facts(growth(value=-2.3875315663834327))
    assert fill("{a1} / {a1.abs}", f).text == "-2.4% / 2.4%"


def test_list_result_placeholders():
    r = CalcResult.model_validate({
        "step_id": "a3", "op": "rank", "unit": "건", "display_ref": "d2", "record_ids": [VID],
        "value": [{"key": {"시점": "2025"}, "value": 240326, "rank": 1}, {"key": {"시점": "2024"}, "value": 222412, "rank": 2}]})
    f = facts(r)
    assert fill("{a3.r0.rank}위 {a3.r0.key} {a3.r0}, {a3.r1.rank}위 {a3.r1.key} {a3.r1}", f).text == "1위 2025년 240,326건, 2위 2024년 222,412건"
    assert "값이 2개라 번호가 필요함" in fill("{a3}", f).problems[0]
    assert "2번째가 없음" in fill("{a3.r2}", f).problems[0]


def test_single_point_list_allows_plain_and_key():
    r = CalcResult.model_validate({"step_id": "a4", "op": "extreme", "unit": "건", "display_ref": "d2",
                                   "value": [{"key": {"시점": "2025"}, "value": 240326}]})
    assert fill("{a4.key} {a4}", facts(r)).text == "2025년 240,326건"


def test_unresolvable_placeholders_are_reported_and_left_in_place():
    filled = fill("{zz} {a1.in5} {a1.bogus} {a1.rank} {a1.in0.rank}", facts())
    assert filled.text == "{zz} {a1.in5} {a1.bogus} {a1.rank} {a1.in0.rank}"
    assert len(filled.problems) == 5 and "없는 계산 ID" in filled.problems[0]


def test_failed_calculation_cannot_be_quoted():
    f = facts(growth(), growth("a2", None))
    assert fill("{a1} {a2}", f).problems == ["계산하지 못한 값을 인용함: {a2}"]


def test_unbalanced_brace():
    assert "짝이 맞지 않는 중괄호" in fill("{a1} }", facts()).problems


def test_raw_numbers_are_rejected_but_years_from_question_and_calc_are_fine():
    _, problems = run("혼인건수는 2021년에서 2025년으로 {a1} 늘었고 약 25% 입니다.")
    assert len(problems) == 1 and "25" in problems[0] and "2021" not in problems[0]
    _, problems = run("최근 5년 동안 {a1} 늘었습니다.")                     # 5 는 질문에 있는 숫자
    assert problems == []


def test_numbers_from_caveats_are_allowed():
    c = Caveat(source="view_note", ref=VID, text="2026년 자료가 없어 2025년으로 대체")
    assert run("2026년 자료가 없어 {a1} ...", caveats=[c])[1] == []
    assert "2026" in run("2026년 자료가 없어 {a1} ...")[1][0]


def test_every_computed_result_must_be_quoted_but_failed_ones_need_not():
    f = facts(growth(), growth("a2"), growth("a3", None))
    assert "인용하지 않은 계산 결과: a2" in run("{a1} 입니다.", f)[1][0]
    assert run("{a1} {a2} 입니다. 마지막은 계산하지 못했습니다.", f)[1] == []


def test_empty_answer():
    assert run("  ")[1] == ["답변이 비어 있음"]
