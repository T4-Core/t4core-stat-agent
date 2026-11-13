"""[NEW] decide.py — 프롬프트 구성, HCX 응답 파싱, 실패 처리 (HCX 는 가짜 함수로 대신한다)"""
from backend.agent.chart_calculate.decide import MAX_VALUES, build_prompt, decide, parse_decision, sub_question_ids
from backend.agent.chart_calculate.planner import make_plan
from backend.agent.prompts import CHART_PLAN_SCHEMA
from backend.schemas.chart import ChartRequest
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import TRUNCATED, VID, view

BUNDLE = QueryBundle(query_id="27077dec", original="최근 5년 혼인건수와 출생아수 추이, 얼마나 변했어?",
                     sub_questions=["2021~2025년 전국 혼인건수 추이", "2021~2025년 전국 출생아수 추이"])
CHARTS = [ChartRequest(chart_id="c1", sub_question_ids=["27077dec-1"], chart_type="line", fallback_chart="bar"),
          ChartRequest(chart_id="c9", sub_question_ids=["27077dec-2"], chart_type=None)]
YEARS = ["2021", "2022", "2023", "2024", "2025"]
EMPTY_DEN = {"scope": "", "basis": "", "label": "", "record_id": "", "item": "", "conditions": []}
EMPTY = {"from": "", "to": "", "base": "", "agg": "", "top_n": 0, "join_on": [], "denominator": EMPTY_DEN}


def cond(**kw):
    return [{"column": k, "values": v} for k, v in kw.items()]


def pick(item, role="value", **kw):
    return {"role": role, "record_id": VID, "item": item, "conditions": cond(**(kw or {"행정구역별": ["전국"]}))}


# HCX 가 스키마대로 답했을 때의 모양 (쓰지 않는 칸은 "" · [] · 0)
REPLY = {
    "charts": [{"chart_id": "c1", "title": "", "record_id": VID, "series": [], **EMPTY,
                "conditions": cond(행정구역별=["전국"], 항목=["혼인건수(건)"], 시점=YEARS)}],
    "answers": [{"sub_question_id": "27077dec-1", "op": "growth_rate", "operands": [pick("혼인건수(건)")],
                 **EMPTY, "from": "2021", "to": "2025"},
                {"sub_question_id": "27077dec-2", "op": "growth_rate", "operands": [pick("출생아수(명)")],
                 **EMPTY, "from": "2021", "to": "2025"}],
}


def fake(reply, seen=None):
    def chat(messages, schema=None, **kw):
        if seen is not None:
            seen.update(messages=messages, schema=schema, kw=kw)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return chat


def test_prompt_lists_what_hcx_may_choose_from():
    text = build_prompt(BUNDLE, [view(notes=[TRUNCATED])], CHARTS)
    assert "- 27077dec-1: 2021~2025년 전국 혼인건수 추이" in text
    assert "- chart_id=c1 chart_type=line measure=raw 하위질문=27077dec-1" in text and "c9" not in text  # 차트 없음은 뺀다
    assert f"- record_id={VID}" in text
    assert "열 '항목': 혼인건수(건), 출생아수(명), 조혼인율(천명당)" in text and "열 '값'" not in text
    assert "주의: 행이 2000개를 넘어 앞부분만 사용" in text


def test_prompt_caps_long_value_lists_keeping_question_values_first():
    rows = [["2025", f"지역{i:03d}", "인구수(명)", 1.0] for i in range(MAX_VALUES + 10)]
    bundle = QueryBundle(query_id="q", original="지역049 인구")
    line = next(l for l in build_prompt(bundle, [view(rows)], []).splitlines() if "행정구역별" in l)
    assert line.startswith("  열 '행정구역별': 지역049, 지역000") and line.endswith("… 외 10개")


def test_sub_question_ids_fall_back_to_original():
    assert sub_question_ids(QueryBundle(original="서울 인구")) == [("q-1", "서울 인구")]


def test_decide_sends_schema_and_parses_reply():
    seen = {}
    decision, notes = decide(BUNDLE, [view()], CHARTS, chat=fake(REPLY, seen))
    assert notes == [] and seen["schema"] is CHART_PLAN_SCHEMA and seen["messages"][0]["role"] == "system"
    c1 = decision.charts[0]
    assert c1.select == {"행정구역별": ["전국"], "항목": ["혼인건수(건)"], "시점": YEARS} and c1.operands == []
    assert (c1.from_, c1.top_n, c1.denominator, c1.join_on) == (None, None, None, None)      # 빈 칸 = 쓰지 않음
    a1 = decision.answers[0]
    assert (a1.op, a1.from_, a1.to, a1.operands[0].item) == ("growth_rate", "2021", "2025", "혼인건수(건)")


def test_reply_flows_into_plan():
    """HCX 응답 → Decision → ChartPlan 까지 (명세 시나리오)"""
    decision, _ = decide(BUNDLE, [view()], CHARTS, chat=fake(REPLY))
    cp, displays = make_plan(CHARTS, [view()], decision)
    assert [p.chart_id for p in cp.plans] == ["c1"] and [s.step_id for s in cp.answer_steps] == ["a1", "a2"]
    assert cp.notes == ["27077dec-1: growth_rate: 시점마다 직전 시점 대비로 계산 (View 의 모든 시점)",
                        "27077dec-1: 질문용 연산 growth_rate ≠ 모듈 2 measure raw (c1)",       # c9 는 차트가 없어 대조하지 않는다
                        "27077dec-2: growth_rate: 시점마다 직전 시점 대비로 계산 (View 의 모든 시점)"]
    assert set(displays) == {"d1", "d2"}


def test_denominator_and_series_are_converted():
    den = {"scope": "question", "basis": "전국 대비", "label": "전국 대비 비중", "record_id": VID,
           "item": "출생아수(명)", "conditions": cond(행정구역별=["전국"])}
    reply = {"charts": [{"chart_id": "c3", "record_id": "", "conditions": [], **EMPTY, "join_on": ["시점"],
                         "series": [pick("혼인건수(건)", "y"), pick("조혼인율(천명당)", "y2")]}],
             "answers": [{"sub_question_id": "", "op": "share", "operands": [pick("출생아수(명)", "part")],
                          **EMPTY, "denominator": den, "agg": "median", "top_n": 3}]}
    decision, notes = parse_decision(reply)
    assert notes == [] and decision.charts[0].record_id is None
    assert [(p.role, p.item) for p in decision.charts[0].operands] == [("y", "혼인건수(건)"), ("y2", "조혼인율(천명당)")]
    a = decision.answers[0]
    assert a.sub_question_id is None and a.agg is None and a.top_n == 3          # 모르는 agg 는 버린다
    assert (a.denominator.scope, a.denominator.label) == ("question", "전국 대비 비중")
    assert a.denominator.operand.select == {"행정구역별": ["전국"]} and a.denominator.operand.role is None


def test_bad_items_are_dropped_one_by_one():
    reply = {"charts": [REPLY["charts"][0], {"record_id": VID, "conditions": []}, "쓰레기"],
             "answers": [{"sub_question_id": "q-1", "op": "median", "operands": []}, REPLY["answers"][0]]}
    decision, notes = parse_decision(reply)
    assert [c.chart_id for c in decision.charts] == ["c1"] and len(decision.answers) == 1
    assert len(notes) == 3 and notes[2] == "HCX 질문용 계산을 버림 (모르는 연산: median)"
    assert notes[0].startswith("HCX 차트 결정을 버림 (chart_id")


def test_failures_return_empty_decision_with_reason():
    assert decide(BUNDLE, [view()], CHARTS, chat=fake({"_raw": "죄송합니다"}))[1] == ["HCX 응답을 JSON 으로 읽지 못함"]
    decision, notes = decide(BUNDLE, [view()], CHARTS, chat=fake(RuntimeError("HTTP 500 / 50000: boom")))
    assert decision.charts == [] and notes == ["HCX 호출 실패: HTTP 500 / 50000: boom"]
    assert decide(BUNDLE, [], CHARTS, chat=fake(REPLY))[1] == ["View 가 없어 계획을 세우지 않음"]


def test_schema_requires_every_field():
    """구조화 출력은 모든 칸을 required 로 둔다 (기존 ANSWER_SCHEMA 와 같은 방식)"""
    chart = CHART_PLAN_SCHEMA["properties"]["charts"]["items"]
    answer = CHART_PLAN_SCHEMA["properties"]["answers"]["items"]
    assert set(chart["required"]) == set(chart["properties"]) and set(answer["required"]) == set(answer["properties"])
    assert set(REPLY["charts"][0]) == set(chart["properties"]) and set(REPLY["answers"][0]) == set(answer["properties"])


def test_schema_enums_match_code():
    """프롬프트 스키마의 허용값이 코드가 아는 값과 같아야 한다 (한쪽만 고치는 것을 막는다)"""
    from typing import get_args

    from backend.agent.chart_calculate.planner import MULTI_BRANCH
    from backend.agent.prompts import ANSWER_ROLES, CHART_OPS, SERIES_ROLES
    from backend.schemas.chart import Measure, Role
    assert CHART_OPS == list(get_args(Measure))
    assert set(SERIES_ROLES) == {r for roles in MULTI_BRANCH.values() for r in roles} and set(SERIES_ROLES) <= set(get_args(Role))
    assert set(ANSWER_ROLES) == {"value", "part", "a", "b", "term"}
    answer = CHART_PLAN_SCHEMA["properties"]["answers"]["items"]["properties"]
    assert answer["op"]["enum"] == CHART_OPS and answer["operands"]["items"]["properties"]["role"]["enum"] == ANSWER_ROLES


def test_prompt_shows_original_rewritten_and_fixed_conditions():
    """'작년' 이 그대로 가면 HCX 가 스스로 연도를 해석한다 → 재작성 문장과 고정 조건을 함께 보낸다"""
    bundle = QueryBundle(query_id="q", original="작년 미취학아동수는?", rewritten="2025년 전국 영유아 인구수",
                         filters={"시점": [2025], "대상": ["인구"], "연령": {"from": 0, "to": 5}, "지표": ["인구수"],
                                  "의도": "값 조회"})
    lines = build_prompt(bundle, [view()], []).splitlines()
    assert lines[:4] == ["[질문] 작년 미취학아동수는?", "[재작성] 2025년 전국 영유아 인구수",
                         "[고정 조건] 시점 2025 · 대상 인구", "[참고 조건] 지표 인구수 · 연령 0~5세 · 의도 값 조회"]


def test_prompt_shows_sub_question_fixed_conditions():
    bundle = QueryBundle(query_id="q", original="부산 출생아 수 및 대구 사망자 수",
                         sub_questions=["부산의 출생아 수", "대구의 사망자 수"],
                         sub_filters=[{"지역": ["부산광역시"], "대상": ["출생아"]}, {"지역": ["대구광역시"], "대상": ["사망자"]}])
    text = build_prompt(bundle, [view()], [])
    assert "- q-1: 부산의 출생아 수  [고정 조건] 지역 부산광역시 · 대상 출생아" in text
    assert "- q-2: 대구의 사망자 수  [고정 조건] 지역 대구광역시 · 대상 사망자" in text
    assert "[고정 조건] (없음)" in text                  # 상위 filters 가 없을 때


def test_truncated_reply_is_reported_as_cut():
    """출력 한도에서 끊긴 응답은 '읽지 못함' 이 아니라 '중간에 끊김' 으로 (2026-11-11, 6,036자에서 끊김)"""
    decision, notes = parse_decision({"_raw": '{\n  "charts": [\n    {"chart_id": "c1", "record_id": "view::'})
    assert decision.charts == [] and notes[0].startswith("HCX 응답이 중간에 끊김 (길이 ")
    assert parse_decision({"_raw": "죄송합니다"})[1] == ["HCX 응답을 JSON 으로 읽지 못함"]


def test_sign_is_parsed_only_for_plus_minus():
    reply = {"charts": [], "answers": [{"sub_question_id": "q-1", "op": "combine", **EMPTY, "operands": [
        {**pick("출생아수(명)", "term"), "sign": "+"}, {**pick("사망자수(명)", "term"), "sign": "-"},
        {**pick("혼인건수(건)", "term"), "sign": ""}]}]}
    decision, notes = parse_decision(reply)
    assert notes == [] and [p.sign for p in decision.answers[0].operands] == ["+", "-", None]


def test_unit_parsed_and_view_unit_list_in_prompt():
    reply = {"charts": [], "answers": [{"sub_question_id": "q-1", "op": "raw", **EMPTY, "operands": [
        {**pick("출생아수", "value"), "sign": "", "unit": " 명 "}, {**pick("출생아수", "value"), "sign": "", "unit": ""}]}]}
    decision, _ = parse_decision(reply)
    assert [p.unit for p in decision.answers[0].operands] == ["명", None]
    text = build_prompt(QueryBundle(original="q"), [view(unit="명 가임여자 1명당 명")], [])
    assert "  단위: 명 가임여자 1명당 명  (표 전체의 단위 목록. 항목마다 맞는 것을 고른다)" in text
