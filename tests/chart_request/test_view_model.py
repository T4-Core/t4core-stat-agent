"""T-19 · T-20: chart_notices 가 화면까지 간다 (view_model.to_result → app.py). 차트가 없는 응답에서도 안내가 보인다

응답 필드를 만드는 것만으로는 사용자에게 보이지 않는다. to_result 는 필요한 필드만 골라 Result 로 옮기므로 새 필드는 거기서 사라진다.
"""
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))                # tests/ (test_streamlit_app 의 도우미)

import view_model as vm  # noqa: E402
from test_streamlit_app import modules_resp  # noqa: E402

NOTICE = "히스토그램은 지원하지 않는 차트라 막대 그래프로 보여 드립니다."
NO_CHART_NOTICE = "이 자료로는 인구 피라미드를 그릴 수 없어 차트 없이 표로 보여 드립니다."


def with_notices(resp, notices, outcomes=(), drawn=None):
    m = resp["modules"]
    m["chart_notices"] = list(notices)
    m["request_outcomes"] = list(outcomes)
    if drawn is not None:
        m["drawn"] = drawn
    return resp


def test_to_result_carries_chart_notices():
    r = vm.to_result(with_notices(modules_resp(), [NOTICE]))
    assert r.chart_notices == [NOTICE]


def test_to_result_without_notices_is_empty_list():
    assert vm.to_result(modules_resp()).chart_notices == []


def test_no_chart_response_keeps_notice_and_has_no_charts():
    """T-19: 차트가 없는 응답 (표만)"""
    resp = with_notices(modules_resp(), [NO_CHART_NOTICE], drawn=[],
                        outcomes=[{"chart_id": "c1", "outcome": "table_only", "reason": "data_mismatch", "final_chart": None}])
    r = vm.to_result(resp)
    assert r.charts == [] and r.chart_notices == [NO_CHART_NOTICE]
    assert r.tables                                                          # 표는 그대로 있다


def test_table_only_outcome_never_draws_the_default_chart():
    """T-20: modules 모드에서 table_only 인데 default 차트 스펙(result.chart)으로 차트가 그려지면 안 된다"""
    resp = with_notices(modules_resp(), [NO_CHART_NOTICE], drawn=[],
                        outcomes=[{"chart_id": "c1", "outcome": "table_only", "reason": "data_mismatch", "final_chart": None}])
    resp["result"]["chart"] = {"title": "예전 차트", "unit": "명", "columns": ["시점", "값"], "rows": [["2021", 1]], "record_id": None}
    r = vm.to_result(resp)
    assert r.charts == []


def test_app_shows_notice_when_there_is_no_chart(tmp_path, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    pytest.importorskip("plotly")
    monkeypatch.setenv("UI_HISTORY_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("STAT_AGENT_API", "http://127.0.0.1:9")
    resp = with_notices(modules_resp(), [NO_CHART_NOTICE], drawn=[],
                        outcomes=[{"chart_id": "c1", "outcome": "table_only", "reason": "data_mismatch", "final_chart": None}])
    at = st_testing.AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=60)
    at.session_state["resp"] = resp
    at.session_state["screen"] = "result"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    shown = [x.value for x in at.info] + [m.value for m in at.markdown]
    assert any(NO_CHART_NOTICE in s for s in shown)
    assert len(at.get("plotly_chart")) == 0


def test_app_shows_notice_above_chart(tmp_path, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    pytest.importorskip("plotly")
    monkeypatch.setenv("UI_HISTORY_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("STAT_AGENT_API", "http://127.0.0.1:9")
    at = st_testing.AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=60)
    at.session_state["resp"] = with_notices(modules_resp(), [NOTICE])
    at.session_state["screen"] = "result"
    at.run()
    assert not at.exception
    assert any(NOTICE in x.value for x in at.info) and len(at.get("plotly_chart")) == 1
