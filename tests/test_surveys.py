"""조사 읽기·지정·선택지 (search/surveys.py · engine._survey_fit · view/run survey_options) — HCX·저장소 없음"""
from types import SimpleNamespace

import numpy as np

from backend.rag.search.engine import TableSearch
from backend.rag.search.surveys import detect_surveys, survey_options


def test_detect_surveys():
    assert detect_surveys("인구주택총조사 기준 서울 인구") == {"인구총조사", "주택총조사"}
    assert detect_surveys("센서스로 본 가구 수") == {"인구총조사", "주택총조사"}
    assert detect_surveys("세종시 특별센서스 가구") == {"세종시 특별센서스"}          # 긴 말이 먼저 — '센서스' 로 다시 안 셈
    assert detect_surveys("인구동향 혼인 건수") == {"인구동향조사"}
    assert detect_surveys("주민등록 인구") == {"주민등록인구현황"}
    assert detect_surveys("주민등록 연앙인구") == {"주민등록인구현황", "국내인구이동통계"}
    assert detect_surveys("2025년 서울 인구") == set()


def _s(miss=0.3, alias=1.35):
    facets = [SimpleNamespace(survey_nm="인구총조사"), SimpleNamespace(survey_nm="주민등록인구현황"),
              SimpleNamespace(survey_nm="인구동향조사")]
    return SimpleNamespace(s={"feas": {"survey_miss": miss, "survey_alias": alias}}, ch=SimpleNamespace(facets=facets))


def test_survey_fit_explicit_and_alias():
    qv = SimpleNamespace(link="")
    f, why = TableSearch._survey_fit(_s(), np.ones(3), [None] * 3, qv, "서울 인구", {"조사": ["주민등록인구현황"]})
    assert list(np.round(f, 2)) == [0.3, 1.0, 0.3] and "지정한 조사 아님" in why[0]
    f, _ = TableSearch._survey_fit(_s(), np.ones(3), [None] * 3, qv, "인구동향 혼인 건수", None)
    assert list(np.round(f, 2)) == [1.0, 1.0, 1.35]
    f, _ = TableSearch._survey_fit(_s(), np.ones(3), [None] * 3, SimpleNamespace(link="인구동향조사"), "인구동향조사 혼인", None)
    assert list(f) == [1.0, 1.0, 1.0]                                   # 이름이 글자 그대로면 survey_hit 이 이미 올림 (두 번 올리지 않음)
    f, _ = TableSearch._survey_fit(_s(alias=1.0), np.ones(3), [None] * 3, qv, "인구동향 혼인", None)
    assert list(f) == [1.0, 1.0, 1.0]                                   # 꺼짐


def test_survey_options():
    c = [{"rank": 1, "tbl_id": "A", "survey_nm": "인구총조사", "score": 1.0},
         {"rank": 2, "tbl_id": "B", "survey_nm": "인구총조사", "score": 0.98},
         {"rank": 3, "tbl_id": "C", "survey_nm": "주민등록인구현황", "score": 0.95},
         {"rank": 4, "tbl_id": "D", "survey_nm": "장래인구추계", "score": 0.5}]
    assert [o["tbl_id"] for o in survey_options(c)] == ["A", "C"]       # 비슷한 점수의 다른 조사만
    assert survey_options(c[:2]) == []                                  # 한 조사뿐
    assert survey_options([c[0], c[3]]) == []                           # 점수 차 큼


def test_run_query_survey_options(monkeypatch):
    from backend.rag.view import run as R
    monkeypatch.setattr(R, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(R, "build_view", lambda tid, f, num, con=None: ({"id": f"v::{tid}", "source": {"tbl_id": tid},
                                                                        "table": {"rows": []}, "metadata": {}}, []))
    cands = [{"rank": 1, "tbl_id": "A", "survey_nm": "인구총조사", "score": 1.0},
             {"rank": 2, "tbl_id": "C", "survey_nm": "주민등록인구현황", "score": 0.97}]
    vb = {"query_id": "q", "original": "서울 인구", "filters": {"지표": ["인구"]}, "search_text": "인구"}
    out = R.run_query(vb, 10, 2, search_fn=lambda *a, **k: [dict(x) for x in cands])
    assert [o["survey_nm"] for o in out["units"][0]["survey_options"]] == ["인구총조사", "주민등록인구현황"]
    vb["filters"]["조사"] = ["주민등록인구현황"]
    out = R.run_query(vb, 10, 2, search_fn=lambda *a, **k: [dict(x) for x in cands])
    assert "survey_options" not in out["units"][0]                     # 지정했으면 묻지 않음
