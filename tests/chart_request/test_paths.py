"""T-10 · T-16: 일반 경로(modules.run_modules)가 최종 결과와 안내를 응답에 싣는다 (QA 경로는 QA 담당 범위라 이 브랜치에서 다루지 않는다)

HCX 와 실제 모듈 5 를 쓰지 않는다. 모듈 2 · 3 · 5 · 6 의 결과를 가짜로 바꿔 끼워 연결(배선)만 시험한다.
"""
import json
from pathlib import Path

import pytest

from backend.agent import modules
from backend.schemas.answer import Module6Output
from backend.schemas.chart import ChartContent, ChartPlan, ChartRequest, Module3Output
from backend.schemas.record import Record

BASE = Path(__file__).parent.parent / "chart" / "baseline"
REQUEST = {"preferred": [{"text": "히스토그램", "code": None, "supported": False}], "excluded": [], "scope": ["c1"],
           "stage": {"reason": "unsupported_type", "selected": "bar", "applied": True}}
KEYS = ("render_status", "request_outcomes", "chart_notices")


def _qb():
    return json.loads((BASE / "request.json").read_text(encoding="utf-8"))["query_bundle"]


def _m3(with_content=True):
    cc = [ChartContent(chart_id="c1", chart_type="bar", measure="raw", title="인구수", encoding={}, columns=[], rows=[])] if with_content else []
    return Module3Output(chart_plan=ChartPlan(), chart_contents=cc)


def _charts():
    return [ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="bar", request=REQUEST)]


@pytest.fixture
def general(monkeypatch):
    """run_modules 의 모듈 2 · 3 · 6 을 가짜로 바꾸고 모듈 5(_draw) 결과를 시험이 정한다"""
    state = {"drawn": [{"chart_id": "c1", "status": "drawn", "reason": None, "merged_from": []}], "error": None, "m3": _m3()}

    monkeypatch.setattr(modules, "view_input_of", lambda vs: {"query_id": "q", "units": []})
    monkeypatch.setattr(modules, "split_roles", lambda vb, vi: (vb, vi, []))
    monkeypatch.setattr(modules, "decide_charts", lambda bundle, vi, use_llm=True: {
        "charts": _charts(), "errors": [], "records": [], "chart_plan": {"query_id": "q", "charts": []}})

    def fake_draw(plan, m3, notes, errors=None):
        if state["error"]:
            notes.append("모듈 5 실패: " + state["error"])
            errors.append(state["error"])
            return []
        return state["drawn"]
    monkeypatch.setattr(modules, "_draw", fake_draw)
    import backend.agent.answer_compose.pipeline as p6
    import backend.agent.chart_calculate.pipeline as p3
    monkeypatch.setattr(p3, "run_module3", lambda req, decision=None, chat=None: state["m3"])
    monkeypatch.setattr(p6, "run_module6", lambda req, chat=None: Module6Output(answer="값입니다", method="template"))

    def run(draw=True):
        vs = {"query_id": "q", "view_bundle": _qb(), "original": "시도별 인구를 히스토그램으로"}
        return modules.run_modules(vs, use_llm_chart=False, draw=draw)
    return state, run


def test_general_path_adds_status_outcomes_and_notices(general):
    _, run = general
    out = run()
    assert all(k in out for k in KEYS)
    assert out["request_outcomes"][0]["outcome"] == "substituted" and out["request_outcomes"][0]["reason"] == "unsupported_type"
    assert out["chart_notices"] == ["히스토그램은 지원하지 않는 차트라 막대 그래프로 보여 드립니다."]
    assert "히스토그램" not in out["answer"]["answer"]                      # 모듈 6 은 차트 상태를 말하지 않는다
    assert out["charts"][0]["request"]["stage"]["reason"] == "unsupported_type"       # 응답 charts 에 요청이 보존된다


def test_general_path_draw_disabled_is_not_failure(general):
    _, run = general
    out = run(draw=False)
    assert out["render_status"]["c1"]["reason"] == "draw_disabled"
    assert out["request_outcomes"][0]["outcome"] == "not_rendered" and out["chart_notices"] == []


def test_general_path_renderer_exception_is_failure(general):
    state, run = general
    state["error"] = "RuntimeError: boom"
    out = run()
    assert out["render_status"]["c1"]["state"] == "failed" and out["render_status"]["c1"]["reason"] == "exception"
    assert out["request_outcomes"][0]["outcome"] == "render_failed" and "표시하지 못했습니다" in out["chart_notices"][0]


def test_general_path_no_chart_content_explains_reason(general):
    state, run = general
    state["m3"] = _m3(with_content=False)
    out = run()
    assert out["render_status"]["c1"]["reason"] == "no_chart_content"
    assert out["request_outcomes"][0]["outcome"] == "table_only" and out["chart_notices"]
