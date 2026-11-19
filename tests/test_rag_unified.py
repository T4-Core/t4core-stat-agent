"""feature/rag-unified — feature/kos14/RAG-hybrid 에서 옮긴 기능이 지금 검색·View 구조에서 동작하는지 (HCX·저장소 파일 없음)

  기간 묶음 · 이어붙이기 계획   backend/rag/search/period_groups.py · engine.TableSearch._attach_periods
  View 1순위만 · 이어붙인 View  backend/rag/view/viewset.py first_only · merge_same_group · add_stitched · unit_records
  지표 핵심어 재확인            backend/rag/view/conflict.py core_hit · view_usage(core_check)
  설정 기본값 · 로컬 임베딩 등록
"""
from types import SimpleNamespace

import pytest

from backend.rag.search.facets import Facet
from backend.rag.search.period_groups import build_groups, load_links, stitch_plan, title_key, year_split


def F(tid, nm, survey, years, cycles=("Y",)):
    return Facet(tid, nm, survey, years=frozenset(years), spans=[(min(years), max(years))], cycles=set(cycles))


# ── 기간 묶음 ───────────────────────────────────────────────────
def test_title_key_ignores_year_marks_and_spelling():
    assert title_key("시도/직업별(~2007) 혼인") == title_key("시도/직업별(2008~) 혼인")
    assert title_key("성별 외국인-시군구 (2010)") == title_key("성별 외국인 - 시군구 (2015~2025)")
    assert title_key("연령/성별 인구-읍면동 (2005)") == title_key("연령 및 성별 인구 – 읍면동 (2015~2025)")
    assert title_key("외국인수-시도") == title_key("외국인-시도")
    assert title_key("유학생(계)") != title_key("유학생(남)")  # 성별판은 다른 통계 (이어붙이지 않음)


FACETS = {f.tbl_id: f for f in [
    F("OLD", "시도별 외국인주민 현황(2006)", "외국인주민현황", [2006]),
    F("MID", "시도별 외국인주민 현황(2007~2015)", "외국인주민현황", range(2007, 2016)),
    F("NEW", "시도별 외국인주민 현황 (2015~2024)", "외국인주민현황", range(2015, 2025)),
    F("OTHER_SURVEY", "시도별 외국인주민 현황(2006)", "다른조사", [2006]),
    F("RENAMED_A", "국제결혼 이주자-시군구", "외국인주민현황", range(2008, 2015)),
    F("RENAMED_B", "결혼이민자-시군구", "외국인주민현황", range(2015, 2025), cycles=("Y", "M")),
    F("ALONE", "행정구역별 인구", "인구총조사", [2020]),
]}


def test_build_groups_by_survey_title_and_links():
    g = build_groups(FACETS, links=[("RENAMED_A", "RENAMED_B")])
    assert [m["tbl_id"] for m in g["NEW"]["members"]] == ["OLD", "MID", "NEW"]  # 오래된 표부터
    assert "OTHER_SURVEY" not in g and "ALONE" not in g  # 조사가 다르면·혼자면 묶음 없음
    assert g["RENAMED_A"] is g["RENAMED_B"] and g["RENAMED_A"]["links"] == [["RENAMED_A", "RENAMED_B"]]
    assert "RENAMED_A" not in build_groups(FACETS, links=[])  # 연결이 없으면 이름이 다른 표는 따로


def test_repo_links_file_reads():
    links = load_links()
    assert len(links) >= 20 and all(a and b and a != b for a, b in links)


def test_stitch_plan_fills_missing_years():
    g = build_groups(FACETS, links=[("RENAMED_A", "RENAMED_B")])
    p = stitch_plan("NEW", [2006, 2010, 2020, 2030], g)
    assert [(t["tbl_id"], t["years"]) for t in p["tables"]] == [("OLD", [2006]), ("MID", [2010]), ("NEW", [2020])]
    assert p["years_have"] == [2006, 2010, 2020] and p["years_missing"] == [2030] and not p["mixed_cycle"]
    assert stitch_plan("NEW", [2020, 2024], g) is None  # 이 표 하나로 충분
    assert stitch_plan("ALONE", [2010], g) is None  # 묶음 없음
    assert stitch_plan("NEW", [], g) is None
    assert stitch_plan("RENAMED_B", [2010, 2020], g)["mixed_cycle"]  # 주기가 다른 표를 이음
    # 2015 는 MID·NEW 둘 다 담음 → 검색된 표(NEW)를 먼저
    assert stitch_plan("NEW", [2010, 2015], g)["tables"] == [{"tbl_id": "MID", "title": FACETS["MID"].tbl_nm, "years": [2010]},
                                                            {"tbl_id": "NEW", "title": FACETS["NEW"].tbl_nm, "years": [2015]}]


def test_year_split():
    assert year_split([2015, 2020], [2010, 2020]) == ([2020], [2010])
    assert year_split(None, [2010]) == (None, None) and year_split([2020], []) == (None, None)


# ── 검색 엔진에 붙임 ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def s():
    from backend.rag.search.engine import TableSearch
    from tests.test_search import Corpus
    return TableSearch(Corpus(), facets_source="meta", llm_rerank=False)


def test_engine_attaches_stitch_without_changing_rank(s):
    from backend.rag.search.engine import TableSearch
    from tests.test_search import Corpus
    q = "1985년과 1995년 행정구역별 인구 및 가구"
    r = s.search(q, {"시점": [1985, 1995]}, 5, question=q, today="2026-11-12")
    top = r["hits"][0]
    assert top["tbl_id"] in {"DT_1IN8501", "DT_1IN9501"}
    assert top["years_missing"] and top["years_have"]
    assert {t["tbl_id"] for t in top["stitch"]["tables"]} == {"DT_1IN8501", "DT_1IN9501"}
    assert top["stitch"]["years_missing"] == []
    # 끄면 계획이 없고, 순위는 같음 (표시용 정보만 붙임)
    off = TableSearch(Corpus(), facets_source="meta", llm_rerank=False, settings={"stitch": {"enabled": False}})
    r2 = off.search(q, {"시점": [1985, 1995]}, 5, question=q, today="2026-11-12")
    assert [h["tbl_id"] for h in r2["hits"]] == [h["tbl_id"] for h in r["hits"]]
    assert all(h.get("stitch") is None for h in r2["hits"])
    # View 단계가 읽는 모양(search_compat)에도 남음
    c = s.search_compat(q, 5, filters={"시점": [1985, 1995]}, question=q)
    assert "stitch" in c[0] and "years_missing" in c[0]


def test_engine_no_years_no_period_fields(s):
    r = s.search("행정구역별 인구 및 가구", None, 3, question="행정구역별 인구 및 가구", today="2026-11-12")
    assert all("stitch" not in h and "years_have" not in h for h in r["hits"])


# ── View: 1순위만 · 이어붙이기 ──────────────────────────────────
def _view(tid, rank):
    return {"record": {"id": f"view::{tid}::Y::q-{rank}::value", "source": {"tbl_id": tid}, "notes": []},
            "notes": [], "rank": rank, "tbl_id": tid}


def test_first_only(monkeypatch):
    from backend.rag.view import points
    from backend.rag.view.viewset import first_only
    keys = {"A": {"k1", "k2"}, "B": {"k1"}, "C": {"k1", "k3"}}
    monkeypatch.setattr(points, "record_points", lambda rec, f=None: (
        [SimpleNamespace(value=1, key_str=lambda k=k: k) for k in keys[rec["source"]["tbl_id"]]], []))
    ok = {"status": "ok", "n_compared_keys": 1}
    assert first_only([_view("A", 1), _view("B", 2)], {}, ok)  # 2순위가 더 주는 교차점 없음
    assert not first_only([_view("A", 1), _view("C", 2)], {}, ok)  # 2순위에만 k3
    assert not first_only([_view("A", 1), _view("B", 2)], {}, {"status": "ambiguous", "n_compared_keys": 1})
    assert not first_only([_view("A", 1), _view("B", 2)], {}, {"status": "ok", "n_compared_keys": 0})  # 비교 불가
    assert not first_only([_view("A", 1)], {}, ok)


def _unit():
    plan = {"group": "G001", "tables": [{"tbl_id": "OLD", "title": "", "years": [2006]},
                                        {"tbl_id": "MID", "title": "", "years": [2010]},
                                        {"tbl_id": "NEW", "title": "", "years": [2020]}],
            "years_have": [2006, 2010, 2020], "years_missing": [2030], "mixed_cycle": False}
    return {"filters": {"시점": [2006, 2010, 2020, 2030]}, "notes": [],
            "candidates": [{"tbl_id": "NEW", "stitch": plan}, {"tbl_id": "MID", "stitch": None}, {"tbl_id": "X"}],
            "views": [_view("NEW", 1), _view("MID", 2), _view("X", 3)]}


def test_merge_same_group_and_add_stitched():
    from backend.rag.view.viewset import add_stitched, merge_same_group, unit_records
    u = _unit()
    merge_same_group(u)
    assert [v["tbl_id"] for v in u["views"]] == ["NEW", "X"]  # 같은 묶음의 2순위는 경쟁 표가 아님
    built = []

    def fake_build(tbl_id, f, num, con=None):
        built.append((tbl_id, f["시점"], num))
        if tbl_id == "OLD":
            raise FileNotFoundError("원본 CSV 없음")
        return {"id": f"view::{tbl_id}::Y::{num}::value", "source": {"tbl_id": tbl_id}, "notes": []}, []

    add_stitched(u, "q", build=fake_build)
    assert built == [("OLD", [2006], "q-1s1"), ("MID", [2010], "q-1s2")]  # 맡은 연도만으로
    assert any("OLD View 생성 실패" in n for n in u["notes"])  # 하나 실패해도 계속
    assert [p["tbl_id"] for p in u["stitched"]["NEW"]] == ["MID"]
    parent = u["views"][0]
    assert parent["stitch"]["tables"] == ["NEW", "MID"] and "2030" in parent["notes"][0]
    assert parent["record"]["notes"][-1]["type"] == "stitched"
    # 답변으로 넘길 때: 부모 바로 뒤에 이어붙인 Record
    unit = {"conflict": {"status": "ok", "views": []}, "views": u["views"], "stitched": u["stitched"], "selected": None}
    ids = [r["source"]["tbl_id"] for r in unit_records(unit)]
    assert ids == ["NEW", "MID", "X"]


def test_unit_records_unchanged_without_stitch():
    from backend.rag.view.viewset import unit_records
    vs = [_view("A", 1), _view("B", 2)]
    unit = {"conflict": {"status": "ok", "views": []}, "views": vs, "selected": None}
    assert [r["source"]["tbl_id"] for r in unit_records(unit)] == ["A", "B"]


# ── 지표 핵심어 재확인 ───────────────────────────────────────────
def test_core_hit():
    from backend.rag.view.conflict import core_hit
    contents = SimpleNamespace(items=["혼인"], dims=[SimpleNamespace(labels=["계", "인천광역시"])])
    assert core_hit(["혼인건수"], contents) == ("혼인건수", "혼인", "혼인")
    assert core_hit(["이혼건수"], contents) is None
    assert core_hit([], contents) is None


def test_view_usage_core_check(monkeypatch):
    from backend.rag.view import conflict
    contents = SimpleNamespace(items=["혼인"], dims=[])
    monkeypatch.setattr(conflict, "extract_contents", lambda rec: contents)
    monkeypatch.setattr(conflict, "check_slots", lambda f, c: {"지표": {"status": "partial", "evidence": "표 이름에만"}})
    rec = {"metadata": {"n_points": 1}, "table": {"rows": [["2020", "혼인", 1]]}}
    on = conflict.view_usage(rec, {"지표": ["혼인건수"]})
    off = conflict.view_usage(rec, {"지표": ["혼인건수"]}, core_check=False)
    assert on["usable"] and on["checks"]["지표"]["status"] == "match"
    assert not off["usable"] and off["checks"]["지표"]["status"] == "partial"


# ── 설정 · 등록 ─────────────────────────────────────────────────
def test_defaults_keep_develop_behaviour():
    from backend.core.settings import Settings, get_settings
    for st in (Settings(), get_settings()):
        assert st.view_stitch is False and st.view_first_only_when_same is False  # Record 수가 바뀌는 기능은 켜야 동작
        assert st.conflict_indicator_core is True
        assert st.view_n_views == 3


def test_kure_registered():
    from backend.rag.search.embedders import DEFAULT_WARM, LOCAL_MODELS
    from backend.rag.search.index import dense_names
    assert LOCAL_MODELS["kure"]["model"] == "nlpai-lab/KURE-v1" and "kure" in dense_names()
    assert "kure" not in DEFAULT_WARM
