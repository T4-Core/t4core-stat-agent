"""[NEW 11-13] 리뷰 지적 수정: 월·분기 CAGR 경과 기간, 음수 기준값, 지역 불일치 보류, 세트 밖 분모 보류"""
import pytest

from backend.agent.chart_calculate.calculate import run_answer_steps, time_in_years
from backend.agent.chart_calculate.pipeline import run_module3
from backend.schemas.chart import ChartRequest, Module3Request, Step
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import view

COLS = ["시점", "행정구역별", "항목", "값"]


def calc(op, rows, prd_se="Y", **kw):
    rec = view(rows, COLS, rid="v", prd_se=prd_se)
    st = Step.model_validate({"step_id": "a1", "op": op, "operands": [
        {"role": "value", "record_id": "v", "item": "인구수(명)", "select": {}}], **kw})
    r = run_answer_steps([st], [rec])[0]
    return r.value, r.note


def two(a_label, a, b_label, b):
    return [[a_label, "전국", "인구수(명)", a], [b_label, "전국", "인구수(명)", b]]


# ── CAGR 경과 기간 ──────────────────────────────────────────────
def test_monthly_cagr_uses_elapsed_months_not_year_digits():
    """2024.01 → 2025.07 은 18개월. 앞 네 자리만 빼서 1년으로 보면 21.0% 가 된다"""
    v, note = calc("cagr", two("2024.01", 100.0, "2025.07", 121.0), "M", **{"from": "2024.01", "to": "2025.07"})
    assert v == pytest.approx((1.21 ** (1 / 1.5) - 1) * 100) and round(v, 2) == 13.55 and note is None


def test_cagr_within_one_year_no_longer_fails_and_quarters_halves_work():
    v, _ = calc("cagr", two("2024.01", 100.0, "2024.07", 110.0), "M", **{"from": "2024.01", "to": "2024.07"})
    assert v == pytest.approx((1.1 ** 2 - 1) * 100)                                  # 0.5년
    q, _ = calc("cagr", two("2024 1분기", 100.0, "2025 3분기", 121.0), "Q", **{"from": "2024 1분기", "to": "2025 3분기"})
    assert q == pytest.approx((1.21 ** (1 / 1.5) - 1) * 100)
    h, _ = calc("cagr", two("2024 상반기", 100.0, "2025 하반기", 121.0), "H", **{"from": "2024 상반기", "to": "2025 하반기"})
    assert h == pytest.approx((1.21 ** (1 / 1.5) - 1) * 100)
    y, _ = calc("cagr", two("2021", 100.0, "2025", 121.0), **{"from": "2021", "to": "2025"})
    assert y == pytest.approx((1.21 ** 0.25 - 1) * 100)                              # 연간은 예전과 같다


def test_time_labels():
    assert [time_in_years(x) for x in ("2024", "2024.07", "2024 3분기", "2024 하반기")] == [2024, 2024.5, 2024.5, 2024.5]
    assert time_in_years("이상한 시점") is None
    assert calc("cagr", two("가", 1.0, "나", 2.0), **{"from": "가", "to": "나"}) == (None, "연수를 알 수 없음")


# ── 음수 기준값 ─────────────────────────────────────────────────
def test_growth_rate_with_negative_base_is_not_computed():
    """-100명 → -50명 은 50명 증가인데 식은 -50% (감소처럼 보인다)"""
    rows = two("2021", -100.0, "2025", -50.0)
    assert calc("growth_rate", rows, **{"from": "2021", "to": "2025"}) == (None, "기준값이 음수라 증감률을 정할 수 없음")
    assert calc("change", rows, **{"from": "2021", "to": "2025"}) == (50.0, None)             # 증감(차이)은 그대로 계산
    assert calc("index", rows, base="2021")[1] == "기준값이 음수라 지수를 정할 수 없음"
    assert calc("growth_rate", two("2021", 100.0, "2025", -50.0), **{"from": "2021", "to": "2025"})[0] == -150.0   # 끝값 음수는 방향이 맞다


# ── 지역 불일치 · 세트 밖 분모 ─────────────────────────────────────
def run(rows, answer, filters=None, charts=None, extra_records=()):
    bundle = QueryBundle(query_id="q", original="서울 출생아 수", sub_questions=["서울 출생아 수"], filters=filters)
    rec = view(rows, COLS, rid="v1")
    req = Module3Request(records=[rec, *extra_records], query_bundle=bundle,
                         charts=charts or [ChartRequest(chart_id="c9", sub_question_ids=["q-1"], chart_type=None, view_ids=["v1"])])
    return run_module3(req, decision={"answers": [answer]})


def raw(select, item="출생아수(명)"):
    return {"sub_question_id": "q-1", "op": "raw", "operands": [{"role": "value", "record_id": "v1", "item": item, "select": select}]}


BUSAN = [["2025", "부산광역시", "출생아수(명)", 900.0]]


def test_region_missing_from_view_withholds_calculation_and_warns():
    out = run(BUSAN, raw({"행정구역별": ["부산광역시"]}), filters={"지역": ["서울특별시"]})
    assert out.calc_results == [] and out.chart_plan.answer_steps == []                       # 부산 900명을 서울 값처럼 돌려주지 않는다
    assert out.chart_plan.warnings == ["질문의 지역(서울특별시) 자료가 없어 계산하지 못했습니다 (받은 자료의 지역: 부산광역시)."]
    assert any("서울특별시" in n and "계산하지 않음" in n for n in out.chart_plan.notes)


def test_region_present_or_not_a_real_region_is_not_withheld():
    seoul = BUSAN + [["2025", "서울특별시", "출생아수(명)", 5000.0]]
    ok = run(seoul, raw({"행정구역별": ["서울특별시"]}), filters={"지역": ["서울특별시"]})
    assert [r.value for r in ok.calc_results] == [5000.0] and ok.chart_plan.warnings == []
    odd = run(BUSAN, raw({"행정구역별": ["부산광역시"]}), filters={"지역": ["지역"]})            # 재작성 모듈의 '지역' 같은 말은 지역이 아니다
    assert [r.value for r in odd.calc_results] == [900.0] and odd.chart_plan.warnings == []
    nation = run([["2025", "전국", "출생아수(명)", 250000.0]], raw({}), filters={"지역": ["서울특별시"]})
    assert nation.chart_plan.warnings != [] and nation.calc_results == []                    # 전국 View 로 서울 질문에 답하지 않는다


def test_share_denominator_outside_the_set_is_withheld():
    """세트(view_ids=[v1]) 밖 View v2 의 총계로 나누면 40% 가 20% 로 바뀐다"""
    v1 = [["2025", "서울특별시", "출생아수(명)", 400.0]]
    v2 = view([["2025", "서울특별시", "출생아수(명)", 2000.0]], COLS, rid="v2")
    share = lambda rid: {"sub_question_id": "q-1", "op": "share", "operands": [  # noqa: E731
        {"role": "part", "record_id": "v1", "item": "출생아수(명)", "select": {}}],
        "denominator": {"scope": "question", "label": "전국 대비", "operand": {
            "record_id": rid, "item": "출생아수(명)", "select": {}}}}
    bad = run(v1, share("v2"), extra_records=[v2])
    assert bad.calc_results == [] and bad.chart_plan.warnings == [
        "비중의 분모로 쓸 자료가 이 질문에 정해진 자료가 아니라서 비중을 계산하지 못했습니다."]
    v1_total = view([["2025", "서울특별시", "출생아수(명)", 1000.0]], COLS, rid="v1b")
    good = run(v1, share("v1"), extra_records=[v1_total])                                    # 같은 세트의 View 면 계산한다
    assert good.chart_plan.warnings == [] and len(good.calc_results) == 1


def test_reused_chart_calculation_keeps_the_missing_value_note():
    """차트 계산을 질문용 계산이 재사용(answer_reuse)해도 '값이 비어 제외한 행' 사유가 CalcResult.note 에 남는다"""
    rows = [["2021", "전국", "혼인건수(건)", 100.0], ["2022", "전국", "혼인건수(건)", None],
            ["2023", "전국", "혼인건수(건)", 120.0], ["2024", "전국", "혼인건수(건)", 130.0]]
    rec = view(rows, COLS, rid="v1")
    pick = {"role": "value", "record_id": "v1", "item": "혼인건수(건)", "select": {"행정구역별": ["전국"]}}
    req = Module3Request(records=[rec], query_bundle=QueryBundle(query_id="q", original="혼인건수 추이", sub_questions=["혼인건수 추이"]),
                         charts=[ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="raw", view_ids=["v1"])])
    out = run_module3(req, decision={"charts": [{"chart_id": "c1", "record_id": "v1", "operands": [pick]}],
                                     "answers": [{"sub_question_id": "q-1", "op": "raw", "operands": [pick]}]})
    assert out.chart_plan.answer_reuse == {"a1": "c1.s1"}                                    # 실제로 재사용된 경우
    assert out.calc_results[0].note == "값이 비어 제외한 행 1개" == out.chart_contents[0].warnings[0]
