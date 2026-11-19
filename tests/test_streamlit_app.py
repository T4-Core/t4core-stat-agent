"""Streamlit 확인용 화면 (frontend/streamlit_app) — 백엔드 없이

  view_model  /api/v1/chat 응답 → 화면 값 (조건 → 질문 · 결과 · 선택 카드 · 히스토리)       항상 실행
  app.py      화면마다 예외 없이 그려지는지 (streamlit.testing.AppTest)                      streamlit 이 있을 때만
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app"
sys.path.insert(0, str(APP_DIR))

import view_model as vm  # noqa: E402

RID = "view::101_DT_1B040A3::Y::q-1::trend"
URL = "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B040A3"
ROWS = [[str(y), "대구광역시", "총인구수", 97250.0 + i] for i, y in enumerate(range(2021, 2026))]


def _base(**kw):
    return {"question": "2021년부터 2025년까지 대구 인구 추이", "status": "ok",
            "analysis": {"view_bundle": {"rewritten": "2021~2025년 대구광역시 인구 추이",
                                         "filters": {"시점": [2021, 2022, 2023, 2024, 2025], "지역": ["대구광역시"], "지표": ["인구"]}}},
            "views": {"status": "ok", "pending": [], "units": [{"candidates": [
                {"tbl_id": "DT_1B040A3", "tbl_nm": "행정구역(시군구)별, 성별 인구수", "survey_nm": "주민등록인구현황"}]}]},
            "records": [{"id": RID, "lexical_text": "행정구역(시군구)별, 성별 인구수", "table": {"columns": ["시점", "지역", "항목", "값"], "rows": ROWS},
                         "source": {"tbl_id": "DT_1B040A3", "kosis_url": URL}, "metadata": {"unit": "명"}}],
            "timings": {"analyze": 0.1, "views": 0.2, "answer": 0.3}, "notes": [], **kw}


def modules_resp(n_charts=1):
    fig = {"data": [{"type": "scatter", "x": [r[0] for r in ROWS], "y": [r[3] for r in ROWS], "mode": "lines+markers"}],
           "layout": {}}
    return _base(
        result={"answer": "대구 인구는 2021년 97,250명에서 2025년 97,254명으로 0.0% 변했습니다.", "key_points": [],
                "sources": [URL], "caveats": [], "unverified_numbers": []},
        modules={"charts": [{"chart_id": f"c{i}", "view_ids": [RID]} for i in range(1, n_charts + 1)],
                 "drawn": [{"chart_id": f"c{i}", "status": "drawn", "title": f"차트 {i}", "figure": fig} for i in range(1, n_charts + 1)],
                 "answer": {"answer": "…", "caveats": [{"source": "calc_note", "ref": "a1", "text": "2020년 자료가 없습니다"}],
                            "tables": [{"kind": "calc_summary", "title": "계산 요약", "columns": ["계산", "기준", "입력값", "결과", "비고"],
                                        "rows": [["총인구수 증감률", "2021 → 2025", "97,250명 → 97,254명", "0.0%", ""]]},
                                       {"kind": "view", "title": "주민등록인구현황", "columns": ["시점", "지역", "항목", "값"],
                                        "rows": ROWS, "record_ids": [RID]}]}})


def default_resp():
    return _base(result={"answer": "자료 기준 값은 97,250명입니다.", "key_points": ["97,250명"],
                         "sources": [f"주민등록인구현황 행정구역(시군구)별, 성별 인구수 {URL}"], "caveats": ["시점 일부 없음"],
                         "chart": {"record_id": RID, "type": "line", "title": "인구수", "x": "시점", "y": "값", "unit": "명",
                                   "columns": ["시점", "지역", "항목", "값"], "rows": ROWS}}, modules=None)


def selection_resp():
    opt = lambda i, tid, v: {"option_id": f"opt-{i}", "tbl_nm": f"표 {tid}", "survey_nm": "조사", "kosis_url": URL,
                             "basis": {"조사": "조사", "기간": "2015~2025", "주기": "Y", "단위": "명", "검색 순위": i},
                             "value_preview": [{"key": {"시점": "2025", "지역": "대구광역시", "성별": "남자"}, "value": v}],
                             "description": "조사 | 표\n분류: 연령별(20~24세, 25~29세)"}
    r = _base(status="needs_selection", result=None, records=[])
    r["views"] = {"status": "needs_selection", "units": [],
                  "pending": [{"unit_id": "main", "selection_token": "tok", "options": [opt(1, "A", 93913.0), opt(2, "B", 62999.0)]}]}
    return r


# ── view_model ─────────────────────────────────────────────────
def test_compose_question():
    c = vm.Conditions(regions=["서울"], time_mode="기간", years=(2015, 2020), targets=["1인 가구"])
    assert vm.compose_question("", c) == "2015년부터 2020년까지 서울 1인 가구 수 추이"
    assert vm.compose_question("2020년 서울 1인 가구 몇 가구야?", c) == "2020년 서울 1인 가구 몇 가구야?"  # 문장에 다 있음
    assert vm.compose_question("1인 가구 몇 가구야?", c) == "2015년부터 2020년까지 서울 1인 가구 몇 가구야?"
    assert vm.compose_question("혼인 건수", vm.Conditions(regions=["부산"], time_mode="최신", cycle="월간")) == "최신 부산 월별 혼인 건수"
    assert vm.compose_question("그냥 질문", None) == "그냥 질문"
    assert vm.Conditions(time_mode="기간", years=(2015, 2020)).chips() == ["2015~2020"]


def test_result_from_modules():
    r = vm.to_result(modules_resp())
    assert r.chips == ["대구광역시", "2021~2025", "인구"]
    assert len(r.charts) == 1 and r.charts[0].figure and r.charts[0].rows == ROWS and r.charts[0].highlight == ["2021", "2025"]
    assert r.summary == [("총인구수 증감률 (2021 → 2025)", "0.0%")]
    assert r.caveats == ["2020년 자료가 없습니다"]  # 모듈 6 주의사항 {source, ref, text} → 문자열
    assert r.sources == [("주민등록인구현황 · 행정구역(시군구)별, 성별 인구수", URL)]
    assert [t["kind"] for t in r.tables] == ["calc_summary", "view"]


def test_result_from_default():
    r = vm.to_result(default_resp())
    assert r.charts[0].spec["type"] == "line" and r.points == ["97,250명"] and r.caveats == ["시점 일부 없음"]
    assert r.sources == [("주민등록인구현황 행정구역(시군구)별, 성별 인구수", URL)]
    assert r.tables and r.tables[0]["rows"] == ROWS  # 근거 표가 없으면 넘긴 카드


def test_choices():
    [cards] = vm.to_choices(selection_resp())
    assert [c.option_id for c in cards] == ["opt-1", "opt-2"] and cards[0].value == "93,913"
    assert ("주기", "연간") in cards[0].rows and cards[0].tag.startswith("A")


def test_history_groups():
    now = datetime(2026, 11, 19, 15, 0)
    items = [{"at": "2026-11-19T14:32:00"}, {"at": "2026-11-18T09:00:00"}, {"at": "2026-11-14T09:00:00"}, {"at": "2026-10-01T09:00:00"}]
    assert [g for g, _ in vm.group_history(items, now)] == ["오늘", "어제", "지난 7일", "이전"]
    assert vm.time_label("2026-11-19T14:32:00", now) == "14:32" and vm.time_label("2026-11-14T09:00:00", now) == "11.14"


def test_charts_and_markup():
    pytest.importorskip("plotly")
    import charts
    import ui
    r = vm.to_result(default_resp())
    assert charts.figure_of(r.charts[0]).data[0].type == "scatter"
    bad = {"data": [{"type": "bar", "x": ["a"], "y": [1], "marker": {"size": [3]}}], "layout": {}}  # 막대에 없는 속성
    assert charts.from_module(bad).data[0].type == "bar"
    assert "&#126;" in ui.escape("20~24세") and ui.md("2015~2020") == "2015\\~2020"  # 마크다운 취소선 방지
    assert "<b>97,250명</b>" in ui.answer_html("2021년 97,250명") and "<b>2021" not in ui.answer_html("2021년 97,250명")


# ── app.py (AppTest) ────────────────────────────────────────────
@pytest.fixture
def app(tmp_path, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    pytest.importorskip("plotly")
    monkeypatch.setenv("UI_HISTORY_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("STAT_AGENT_API", "http://127.0.0.1:9")  # 닫힌 포트 — 연결 확인은 바로 실패

    def make(**state):
        at = st_testing.AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        return at
    return make


def test_app_home(app):
    at = app()
    assert any("어떤 통계가 궁금하세요?" in m.value for m in at.markdown)
    assert any(b.label == "➤" for b in at.button)


def test_app_result_and_modes(app):
    at = app(resp=modules_resp(), screen="result")
    assert len(at.get("plotly_chart")) == 1 and any("핵심 요약" in m.value for m in at.markdown)
    at = app(resp=modules_resp(2), screen="result")
    assert len(at.get("plotly_chart")) == 1  # 한 개씩
    at = app(resp=modules_resp(2), screen="result", vizmTrue="한번에")
    assert len(at.get("plotly_chart")) == 2
    at = app(resp=modules_resp(2), screen="result", wide_t=True)
    assert len(at.get("plotly_chart")) == 2
    at = app(resp=default_resp(), screen="result", vizmFalse="표")
    assert len(at.dataframe) >= 1


def test_app_choose_and_history(app):
    at = app(resp=selection_resp(), screen="choose")
    assert sum(b.label == "이 통계표로 보기" for b in at.button) == 2
    at = app(page="History")
    assert any("아직 물어본 질문이 없어요" in m.value for m in at.markdown)
    h = [{"id": "x1", "question": "q", "chips": ["대구"], "at": datetime.now().isoformat(timespec="seconds"), "star": False,
          "resp": modules_resp()}]
    at = app(page="History", history=h)
    assert any(b.label == "결과 다시 열기" for b in at.button) and len(at.get("plotly_chart")) == 1
