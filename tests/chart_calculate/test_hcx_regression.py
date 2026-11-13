"""[NEW] 실제 HCX 응답 회귀 테스트 — 테스트 화면에서 받은 원 응답을 그대로 넣어, 같은 실수에도 계산이 살아남는지 본다

  2026-11-10 테스트 화면 첫 실행: "최근 5년 전국 혼인건수 추이와 증감률"
    차트는 맞았지만 질문용 계산 a1(change)·a2(growth_rate)가 모두 null 이었다.
    - change 에 피연산자를 a(2024)·b(2021) 두 개로 주고, 피연산자가 아닌 것(role "join_on", item "시점")을 붙였다
    - 피연산자 conditions 의 시점을 2024 하나로 좁혀 from=2021 값이 사라졌다
    - 갈래가 하나인 꺾은선에 series 를 role "combo" 로 채웠다
  2026-11-11 같은 질문 재실행 (프롬프트·스키마 개선 후): 바로잡을 것 없이 계산이 모두 나왔다 → 기준 사례로 함께 둔다.

  View 는 11-11 실행에서 받은 실제 행이다 (같은 표 DT_1B8000G, 같은 열 구조).
  실제 KOSIS View 는 '항목' 열이 표 단위 고정값("출생사망혼인이혼")이고, 지표는 분류 열('종류별')에 들어 있다.
"""
import pytest

from backend.agent.chart_calculate.pipeline import run_module3_trace
from backend.schemas.chart import ChartRequest, Module3Request
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import view

VID = "view::101_DT_1B8000G::Y::263f9c80-1::trend"
YEARS = ["2021", "2022", "2023", "2024", "2025"]
VALUES = {"혼인건수(건)": [192507, 191690, 193657, 222412, 240326], "조혼인율(천명당)": [3.8, 3.7, 3.8, 4.4, 4.7],
          "일반혼인율(남편)": [8.6, 8.5, 8.6, 9.9, 10.6], "일반혼인율(아내)": [8.5, 8.4, 8.5, 9.7, 10.5]}
RECORD = view([[y, "전국", item, "출생사망혼인이혼", vs[i]] for i, y in enumerate(YEARS) for item, vs in VALUES.items()],
              ["시점", "행정구역별", "종류별", "항목", "값"], rid=VID, unit="명 건")
BUNDLE = QueryBundle(query_id="263f9c80", original="최근 5년 전국 혼인건수 추이와 증감률")
CHARTS = [ChartRequest(chart_id="c1", sub_question_ids=["263f9c80-1"], chart_type="line", measure="raw",
                       requirements=["time_axis_required", "min_points_3"], fallback_chart="bar")]

_EMPTY_DEN = {"basis": "", "conditions": [], "item": "", "label": "", "record_id": "", "scope": ""}
_BLANK = {"agg": "", "base": "", "denominator": _EMPTY_DEN, "join_on": [], "top_n": 0}


def _cond(*years):
    return [{"column": "시점", "values": list(years)}]


# 테스트 화면 ③-a 의 "HCX 원 응답" 그대로 (빈 칸 포함)
HCX_REPLY_20261110 = {
    "answers": [
        {**_BLANK, "from": "2021", "to": "2025", "op": "change", "sub_question_id": "263f9c80-1", "operands": [
            {"conditions": _cond("2024"), "item": "혼인건수(건)", "record_id": VID, "role": "a"},
            {"conditions": _cond("2021"), "item": "혼인건수(건)", "record_id": VID, "role": "b"},
            {"conditions": [], "item": "시점", "record_id": VID, "role": "join_on"}]},
        {**_BLANK, "from": "2021", "to": "2025", "op": "growth_rate", "sub_question_id": "263f9c80-1", "operands": [
            {"conditions": _cond("2024"), "item": "혼인건수(건)", "record_id": VID, "role": "value"}]},
    ],
    "charts": [
        {**_BLANK, "from": "2021", "to": "2025", "chart_id": "c1", "record_id": VID, "conditions": _cond(*YEARS),
         "series": [{"conditions": _cond(*YEARS), "item": "혼인건수(건)", "record_id": VID, "role": "combo"}]},
    ],
}


def fake_chat(*_, **__):
    return HCX_REPLY_20261110


@pytest.fixture(scope="module")
def trace():
    return run_module3_trace(Module3Request(records=[RECORD], query_bundle=BUNDLE, charts=CHARTS), chat=fake_chat)


def test_chart_survives(trace):
    """어제도 통과했던 부분 — 바로잡기를 넣은 뒤에도 그대로여야 한다"""
    (c1,) = trace.output.chart_contents
    assert (c1.chart_type, c1.title) == ("line", "2021~2025 혼인건수 연도별 추이")
    assert [r[-1] for r in c1.rows] == [192507.0, 191690.0, 193657.0, 222412.0, 240326.0]


def test_change_with_split_operands_is_computed(trace):
    """a(2024)·b(2021) 로 쪼갠 같은 항목 + 피연산자가 아닌 '시점' → 혼인건수 하나로, View 의 시점마다 직전 대비 증감"""
    a1 = trace.output.calc_results[0]
    assert (a1.op, a1.unit, a1.note) == ("change", "건", None)
    assert [(v["key"]["시점"], v["value"]) for v in a1.value] == [("2022", -817.0), ("2023", 1967.0), ("2024", 28755.0),
                                                                   ("2025", 17914.0)]
    assert [i.key["시점"] for i in a1.inputs] == YEARS


def test_growth_rate_with_narrowed_period_is_computed(trace):
    """conditions 의 시점을 2024 하나로 좁혔어도 증감률은 View 의 시점마다 계산된다"""
    a2 = trace.output.calc_results[1]
    assert a2.note is None and a2.value[0]["value"] == pytest.approx((191690 - 192507) / 192507 * 100)
    assert [c.display_text for c in trace.calcs] == [["-817건", "1,967건", "28,755건", "17,914건"], ["-0.4%", "1.0%", "14.8%", "8.1%"]]


def test_corrections_are_visible_to_qa(trace):
    """바로잡은 것은 조용히 넘기지 않고 ChartPlan.notes 에 남긴다 (테스트 화면 ③-b, QA 가 본다)"""
    notes = trace.chart_plan.notes
    assert not any("항목 없음: 시점" in n for n in notes)          # 피연산자가 아닌 것은 검사 전에 버린다
    assert any("피연산자가 아님" in n for n in notes)
    assert any("피연산자를 하나로 합침" in n for n in notes)
    assert any("시점마다 직전 시점 대비" in n for n in notes)


# ── 2026-11-11 재실행 (프롬프트·스키마 개선 후) ───────────────────
VID2 = "view::101_DT_1B8000G::Y::64c693a0-1::trend"
_NATION = {"column": "행정구역별", "values": ["전국"]}
HCX_REPLY_20261111 = {
    "answers": [
        {**_BLANK, "from": "2021", "to": "2025", "op": "raw", "sub_question_id": "64c693a0-1", "operands": [
            {"conditions": [_NATION, *_cond(*YEARS)], "item": "혼인건수(건)", "record_id": VID2, "role": "value"}]},
        {**_BLANK, "from": "2021", "to": "2025", "op": "growth_rate", "sub_question_id": "64c693a0-1", "operands": [
            {"conditions": [_NATION, *_cond("2021", "2025")], "item": "혼인건수(건)", "record_id": VID2, "role": "value"}]},
    ],
    "charts": [
        {**_BLANK, "from": "2021", "to": "2025", "chart_id": "c1", "record_id": VID2,
         "conditions": [_NATION, {"column": "종류별", "values": ["혼인건수(건)"]}],
         "series": [{"conditions": _cond(*YEARS), "item": "혼인건수(건)", "record_id": VID2, "role": "y"}]},
    ],
}


def test_improved_reply_needs_no_correction():
    """개선된 프롬프트의 응답: 피연산자 실수는 없다. 증감률 방식만 시점마다 직전 대비로 바뀐다"""
    record = RECORD.model_copy(update={"id": VID2})
    charts = [CHARTS[0].model_copy(update={"sub_question_ids": ["64c693a0-1"]})]
    t = run_module3_trace(Module3Request(records=[record], query_bundle=BUNDLE.model_copy(update={"query_id": "64c693a0"}),
                                         charts=charts), chat=lambda *a, **k: HCX_REPLY_20261111)
    # HCX 는 증감률을 2021→2025 두 시점(from·to)으로 골랐다 → 시점마다 직전 대비로 바로잡는다 (2026-11-11 사용자 요구)
    assert t.chart_plan.notes == ["64c693a0-1: growth_rate: 시점마다 직전 시점 대비로 계산 (View 의 모든 시점)",
                                  "64c693a0-1: 질문용 연산 growth_rate ≠ 모듈 2 measure raw (c1)"]
    assert [c.display_text for c in t.calcs] == [["192,507건", "191,690건", "193,657건", "222,412건", "240,326건"], ["-0.4%", "1.0%", "14.8%", "8.1%"]]
    (c1,) = t.output.chart_contents
    assert (c1.chart_type, c1.title, len(c1.rows)) == ("line", "2021~2025 혼인건수 연도별 추이", 5)


# ── 2026-11-11 다른 연산 질문 (고정 데이터: tests/chart_calculate/fixtures/hcx_20261111_*.json) ──
def _load(name):
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    req = Module3Request(records=d["records"], query_bundle=d["query_bundle"], charts=d["charts"])
    return run_module3_trace(req, chat=lambda *a, **k: d["hcx_reply"])


def test_diff_between_regions():
    """'최근 5년 서울과 부산 인구 차이' — HCX 가 line 차트에 series 를 y·y2 로 채운 것은 같은 항목이라 하나로 합쳐진다"""
    t = _load("hcx_20261111_diff_regions")
    (a1,) = t.calcs
    assert a1.result.op == "diff" and a1.result.note is None and len(a1.result.value) == 5
    assert a1.display_text[0] == "6,159,078명"
    assert {i.role for i in a1.result.inputs} == {"a", "b"}
    (c1,) = t.output.chart_contents
    assert (c1.chart_type, len(c1.rows), c1.encoding["series"]) == ("line", 10, "행정구역(시군구)별")
    assert any("하나로 합침" in n for n in t.chart_plan.notes)


def test_share_without_total_in_views_is_refused_with_reason():
    """'2024년 전국 출생아수 중 서울 비중' — 재작성이 '전국'을 빼서 View 에 분모가 없다.
    틀린 숫자를 내지 않고 계산 불가 + 사유, 차트도 만들지 않는다 (앞 단계 문제를 모듈 3 이 덮지 않는다)"""
    t = _load("hcx_20261111_share_missing_total")
    (a1,) = t.calcs
    assert a1.result.value is None and "행정구역별에 없는 값: ['전국']" in a1.result.note
    assert t.output.chart_contents == [] and t.output.validation["c1"].original.failed == ["data_present"]


# ── 2026-11-11 '최근 2년 미취학아동수' — 나이를 item 으로, 나이마다 계산을 하나씩 (응답이 출력 한도에서 끊겼다) ──
def test_ages_written_as_items_become_one_sum():
    """HCX 가 차트 갈래·질문용 계산을 나이마다 따로(item "0세" …) 만든 응답 → 조건으로 옮기고 합쳐 해마다 합계 하나"""
    vid = "view::101_DT_1B04006::Y::7af3b6f6-1::trend"
    ages = ["0세", "1세", "2세", "3세", "4세", "5세"]
    base = {"2024": [238000, 245000, 252000, 268000, 280000, 300000], "2025": [252212, 243765, 235297, 255233, 269000, 281000]}
    rows = [[y, "전국", a, "총인구수", float(v)] for y, vs in base.items() for a, v in zip(ages, vs)]
    record = view(rows, ["시점", "행정구역(시군구)별", "연령별", "항목", "값"], rid=vid)
    bundle = QueryBundle(query_id="7af3b6f6", original="최근 2년 미취학아동수", rewritten="2024~2025년 전국 영유아 인구수 연도별 추이",
                         filters={"시점": [2024, 2025], "대상": ["인구"], "연령": {"from": 0, "to": 5}, "지표": ["인구수"],
                                  "비교축": "연도", "의도": "추이"})
    cond = [{"column": "시점", "values": ["2024", "2025"]}, {"column": "행정구역(시군구)별", "values": ["전국"]}]
    reply = {"charts": [{**_BLANK, "from": "", "to": "", "chart_id": "c1", "record_id": vid, "conditions": cond,
                         "series": [{"role": "y", "record_id": vid, "item": a, "conditions": cond} for a in ages]}],
             "answers": [{**_BLANK, "from": "", "to": "", "sub_question_id": "7af3b6f6-1", "op": "raw",
                          "operands": [{"role": "value", "record_id": vid, "item": a, "conditions": cond}]} for a in ages]}
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["7af3b6f6-1"], chart_type="line", measure="raw",
                           requirements=["time_axis_required", "min_points_3"], fallback_chart="bar")]
    t = run_module3_trace(Module3Request(records=[record], query_bundle=bundle, charts=charts), chat=lambda *a, **k: reply)
    sums = [sum(base["2024"]), sum(base["2025"])]
    (a1,) = t.output.calc_results                                      # 6개 → 1개
    assert (a1.op, [v["value"] for v in a1.value]) == ("aggregate", sums)
    (c1,) = t.output.chart_contents                                     # 나이별 6개 선 → 해마다 합계
    assert [r[-1] for r in c1.rows] == sums and c1.chart_type == "bar"  # 점 2개라 꺾은선 → 막대
    notes = t.chart_plan.notes
    assert "7af3b6f6-1: 같은 raw 계산 6개를 하나로 합침 (범주마다 따로 적은 것)" in notes
    assert "c1: item ['0세', '1세', '2세', '3세', '4세', '5세'] 은 지표가 아니라 연령별 값 → 조건으로 옮김" in notes
    assert any("aggregate(sum)" in n for n in notes)


def test_age_narrowed_to_one_is_widened_to_question_range():
    """'최근 2년 미취학아동수' (2026-11-11): HCX 가 연령을 ['0세'] 하나로 좁혔다 → 질문 범위 0~5세 전체로 넓혀 합계"""
    vid = "view::101_DT_1B04006::Y::ca1805b3-1::trend"
    ages = ["0세", "1세", "2세", "3세", "4세", "5세"]
    base = {"2024": [235337, 234405, 254654, 267456, 279924, 309988], "2025": [252212, 243765, 235297, 255233, 269000, 281000]}
    rows = [[y, "전국", a, "총인구수", float(v)] for y, vs in base.items() for a, v in zip(ages, vs)]
    record = view(rows, ["시점", "행정구역(시군구)별", "연령별", "항목", "값"], rid=vid)
    bundle = QueryBundle(query_id="ca1805b3", original="최근 2년 미취학아동수", rewritten="2024~2025년 전국 영유아 인구수 연도별 추이",
                         filters={"시점": [2024, 2025], "대상": ["인구"], "연령": {"from": 0, "to": 5}, "지표": ["인구수"],
                                  "비교축": "연도", "의도": "추이"})
    cond = [{"column": "시점", "values": ["2024", "2025"]}, {"column": "행정구역(시군구)별", "values": ["전국"]}]
    zero = [{"column": "연령별", "values": ["0세"]}]
    reply = {"charts": [{**_BLANK, "from": "", "to": "", "chart_id": "c1", "title": "2024~2025년 전국 미취학아동수",
                         "record_id": vid, "conditions": cond,
                         "series": [{"role": "y", "record_id": vid, "item": "총인구수", "conditions": zero}]}],
             "answers": [{**_BLANK, "from": "", "to": "", "sub_question_id": "ca1805b3-1", "op": "raw",
                          "operands": [{"role": "value", "record_id": vid, "item": "총인구수", "conditions": cond + zero}]}]}
    charts = [ChartRequest(chart_id="c1", sub_question_ids=["ca1805b3-1"], chart_type="bar", measure="raw",
                           requirements=["max_categories_20"])]
    t = run_module3_trace(Module3Request(records=[record], query_bundle=bundle, charts=charts), chat=lambda *a, **k: reply)
    sums = [sum(base["2024"]), sum(base["2025"])]
    (a1,) = t.output.calc_results
    assert (a1.op, [v["value"] for v in a1.value]) == ("aggregate", sums)
    (c1,) = t.output.chart_contents
    assert ([r[-1] for r in c1.rows], c1.title) == (sums, "2024~2025년 전국 미취학아동수")
    assert "ca1805b3-1: 연령별 ['0세'] → 질문 연령 0~5세에 드는 값 전체 ['0세', '1세', '2세', '3세', '4세', '5세']" in t.chart_plan.notes


# ── 2026-11-11 표 단위로만 단위를 주는 표 (DT_1B81A23: 모든 행이 '명 가임여자 1명당 명') ──
def births_view():
    rows = [["2024", r, "출생아수", v] for r, v in [("서울특별시", 41605.0), ("부산광역시", 13063.0), ("대구광역시", 10103.0)]]
    return view(rows, ["시점", "시군구별", "항목", "값"], rid="view::101_DT_1B81A23::Y::9866c642-1::value",
                unit="명 가임여자 1명당 명")


def _combine_reply(unit):
    vid = "view::101_DT_1B81A23::Y::9866c642-1::value"
    terms = [("서울특별시", "+"), ("부산광역시", "+"), ("대구광역시", "-")]
    return {"charts": [], "answers": [{**_BLANK, "from": "", "to": "", "sub_question_id": "9866c642-1", "op": "combine",
            "operands": [{"role": "term", "sign": s, "record_id": vid, "item": "출생아수", "unit": unit,
                          "conditions": [{"column": "시군구별", "values": [r]}]} for r, s in terms]}]}


def test_hcx_unit_checked_against_view_unit_list():
    """'2024년 서울 출생아수에 부산 출생아수를 더하고 대구 출생아수를 뺀 값' — 단위를 HCX 가 고르고 코드는 목록 안인지 검사"""
    bundle = QueryBundle(query_id="9866c642", original="2024년 서울 출생아수에 부산 출생아수를 더하고 대구 출생아수를 뺀 값")
    req = Module3Request(records=[births_view()], query_bundle=bundle, charts=[])
    t = run_module3_trace(req, chat=lambda *a, **k: _combine_reply("명"))
    (c,) = t.calcs
    assert (c.result.value, c.result.unit, c.display_text) == (44565.0, "명", "44,565명")
    t = run_module3_trace(req, chat=lambda *a, **k: _combine_reply("건"))      # 목록에 없는 단위 → 믿지 않는다
    (c,) = t.calcs
    assert (c.result.unit, c.display_text) == (None, "44,565")
    assert "9866c642-1: HCX 단위 '건' 은 View 단위 목록 '명 가임여자 1명당 명' 의 단위로 확인되지 않음 → 단위 없음" in t.chart_plan.notes


# ── GPT 2차 검토 (2026-11-11) P1. HCX 단위는 표시에만, 단위 호환 검사에는 쓰지 않는다 ──
def test_hcx_unit_not_trusted_for_compatibility():
    """합계출산율에 HCX 가 '명' 을 붙이면 출생아수(명)와 계산됐다 (238,317 − 0.748 = 238,316.252명). 원본 DT_1B81A23 2024 전국 값"""
    vid = "view::101_DT_1B81A23::Y::r2-1::value"
    rec = view([["2024", "전국", "출생아수", 238317], ["2024", "전국", "합계출산율", 0.748]],
               ["시점", "시군구별", "항목", "값"], rid=vid, unit="명 가임여자 1명당 명")
    reply = {"charts": [], "answers": [{**_BLANK, "from": "", "to": "", "sub_question_id": "r2-1", "op": "combine",
             "operands": [{"role": "term", "sign": "+", "record_id": vid, "item": "출생아수", "unit": "명", "conditions": []},
                          {"role": "term", "sign": "-", "record_id": vid, "item": "합계출산율", "unit": "명", "conditions": []}]}]}
    t = run_module3_trace(Module3Request(records=[rec], query_bundle=QueryBundle(query_id="r2", original="q"), charts=[]),
                          chat=lambda *a, **k: reply)
    (c,) = t.calcs
    assert c.result.value is None
    assert c.result.note == "단위를 확인할 수 없음: ? / ? (출생아수 / 합계출산율) — HCX 가 고른 단위는 확인용으로 쓰지 않음"
    assert [o.unit_source for o in t.chart_plan.answer_steps[0].operands] == ["hcx", "hcx"]
