"""[NEW] pipeline.py · graph.py · v1_answer.py — 모듈 6 전체 흐름 (HCX 는 가짜 함수)"""
import pytest
from fastapi.testclient import TestClient

from backend.agent.answer_compose.graph import NO_CALC_ANSWER
from backend.agent.answer_compose.pipeline import run_module6, run_module6_trace
from backend.agent.chart_calculate.pipeline import run_module3
from backend.api.v1_answer import EX_COMPOSE
from backend.main import app
from backend.schemas.answer import Module6Request
from backend.schemas.chart import Module3Request
from tests.answer_compose._data import fake, growth, request
from tests.chart_calculate.test_decide import BUNDLE, CHARTS, REPLY
from tests.chart_calculate._views import view

GOOD = {"answer": "혼인건수는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} 증가했습니다."}
FILLED = "혼인건수는 2021년 192,507건에서 2025년 240,326건으로 24.8% 증가했습니다."
RAW_NUMBER = {"answer": "혼인건수는 24.8% 증가했습니다 {a1}."}
NOTE = {"slot": "시점", "type": "latest_shift", "requested": [2026], "applied": [2025], "text": "2026년 자료가 없어 2025년으로 대체"}


def test_first_try_passes_and_numbers_come_from_calc_results():
    chat = fake(GOOD)
    out = run_module6(request(), chat=chat)
    assert (out.answer, out.method, out.used_step_ids, out.insufficient, out.notes) == (FILLED, "hcx", ["a1"], False, [])
    assert [t.kind for t in out.tables] == ["calc_summary", "view"] and out.query_id == "27077dec"
    assert len(chat.calls) == 1


def test_prompt_shows_placeholders_previews_and_caveats():
    chat = fake(GOOD)
    run_module6(request(records=[view(notes=[NOTE])]), chat=chat)
    system, user = (m["content"] for m in chat.calls[0])
    assert "자리표시자" in system
    assert "a1 | 혼인건수 증감률 | 값 {a1} (미리보기: 24.8%)" in user
    assert "{a1.in0}(미리보기: 2021년 192,507건)" in user and "{a1.in1.key}" in user
    assert "[주의사항]\n- 2026년 자료가 없어 2025년으로 대체" in user


def test_retry_after_raw_number_then_pass():
    chat = fake(RAW_NUMBER, GOOD)
    out = run_module6(request(), chat=chat)
    assert (out.method, out.answer) == ("hcx_retry", FILLED)
    assert out.notes == ["1차 시도 실패: 자리표시자 밖에 숫자를 직접 씀: 24.8 — 숫자는 자리표시자로만 쓴다"]
    retry = chat.calls[1]
    assert [m["role"] for m in retry] == ["system", "user", "assistant", "user"]
    assert "자리표시자 밖에 숫자를 직접 씀" in retry[3]["content"] and "24.8% 증가" in retry[2]["content"]


def test_falls_back_to_template_after_two_failures():
    chat = fake(RAW_NUMBER, {"answer": "{zz}"})
    out = run_module6(request(), chat=chat)
    assert out.method == "template" and len(chat.calls) == 2 and len(out.notes) == 2
    assert out.answer == "전국 혼인건수는 2021년 192,507건에서 2025년 240,326건으로 24.8% 증가했습니다."
    assert out.used_step_ids == ["a1"]


def test_hcx_error_goes_straight_to_template():
    chat = fake(RuntimeError("HTTP 500 / boom"))
    out = run_module6(request(), chat=chat)
    assert out.method == "template" and len(chat.calls) == 1
    assert out.notes == ["1차 시도 실패: HCX 호출 실패: HTTP 500 / boom"]


def test_string_and_raw_fallback_replies_are_accepted():
    assert run_module6(request(), chat=fake(GOOD["answer"])).method == "hcx"
    assert run_module6(request(), chat=fake({"_raw": GOOD["answer"]})).method == "hcx"


def test_unquoted_calculation_triggers_retry():
    both = request(results=[growth(), growth("a2")])
    chat = fake({"answer": "혼인건수는 {a1} 늘었습니다."}, {"answer": "{a1} 그리고 {a2} 입니다."})
    out = run_module6(both, chat=chat)
    assert out.method == "hcx_retry" and out.used_step_ids == ["a1", "a2"]
    assert "인용하지 않은 계산 결과: a2" in out.notes[0]


def test_no_calc_results_skips_hcx():
    chat = fake()
    out = run_module6(request(results=[]), chat=chat)
    assert (out.method, out.insufficient, chat.calls) == ("none", True, [])
    assert out.answer == NO_CALC_ANSWER and [t.kind for t in out.tables] == ["view"]       # 받은 View 는 그래도 보여 준다


def test_all_calculations_failed_uses_template_without_hcx():
    chat = fake()
    out = run_module6(request(results=[growth(value=None).model_copy(update={"note": "기준값 0"})]), chat=chat)
    assert (out.method, out.insufficient, chat.calls) == ("template", True, [])
    assert "계산하지 못했습니다(기준 값이 0이라 비율을 계산할 수 없습니다)" in out.answer and out.used_step_ids == []
    assert [c.source for c in out.caveats] == ["calc_note"]


def test_trace_has_attempts_and_same_output():
    trace = run_module6_trace(request(), chat=fake(RAW_NUMBER, GOOD))
    assert [bool(a.problems) for a in trace.attempts] == [True, False]
    assert trace.attempts[1].filled == FILLED and trace.output.method == "hcx_retry"


def test_after_module3_end_to_end():
    """모듈 3 의 실제 출력(시점별 값 목록 포함)을 이어 붙여도 돈다"""
    m3_req = Module3Request(records=[view()], query_bundle=BUNDLE, charts=CHARTS)
    m3 = run_module3(m3_req, chat=lambda messages, schema=None, **kw: REPLY)
    req = Module6Request(query_bundle=BUNDLE, records=m3_req.records, calc_results=m3.calc_results, displays=m3.displays,
                         answer_steps=m3.chart_plan.answer_steps)
    answer = " ".join(f"{{{r.step_id}.r{n}.key}}: {{{r.step_id}.r{n}}}" for r in m3.calc_results for n in range(len(r.value)))
    out = run_module6(req, chat=fake({"answer": answer}))
    assert out.method == "hcx" and "2025년: 8.1%" in out.answer          # (240326 − 222412) ÷ 222412 × 100 = 8.05
    assert {t.table_id for t in out.tables} >= {"t_a1", "t_a2", "t_view_1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.agent.answer_compose.graph.ask", lambda messages, chat=None: (GOOD, GOOD["answer"], None))
    return TestClient(app)


def test_api_compose_and_trace(client):
    r = client.post("/api/v1/answer/compose", json=EX_COMPOSE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == FILLED and body["method"] == "hcx" and body["tables"][0]["rows"][0][3] == "24.8%"
    t = client.post("/api/v1/answer/compose/trace", json=EX_COMPOSE).json()
    assert t["output"]["answer"] == FILLED and t["attempts"][0]["problems"] == []


def test_api_rejects_missing_fields(client):
    assert client.post("/api/v1/answer/compose", json={"records": []}).status_code == 422
