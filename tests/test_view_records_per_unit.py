"""단위마다 Record N개 (settings.view_records_per_unit) — 답변 쪽이 단위(본 질의 · 서브쿼리)마다 여러 표를 받게

  1) run_query(fill=True)  View 생성 실패는 건너뛰고, 요청 지표 없는 표는 남기되 세지 않고, 쓸 수 있는 View 가 N개가 될 때까지
  2) unit_records          자동 선택이면 고르지 않은 무리도 뒤에 (match.selected=False). 사람이 고른 선택은 그대로 고른 무리만
  3) build_viewset         서브쿼리마다 따로 N개 · 기본값 0 이면 기존 동작
DuckDB·검색·HCX 없음 — build_view · search_fn · connect 를 가짜로
"""
import pytest

from backend.rag.view import run as R


class Con:
    def close(self):
        pass


def _rec(tid, num, missing=False):
    return {"id": f"view::{tid}::Y::{num}::value", "source": {"tbl_id": tid}, "notes": [], "table": {"rows": [[1]]},
            "metadata": {"indicator_missing": ["다른 지표"] if missing else []}}


@pytest.fixture
def fake(monkeypatch):
    def build(tid, f, num, con=None):
        if tid == "B":
            raise FileNotFoundError("원본 CSV 없음")
        return _rec(tid, num, missing=tid == "C"), []
    monkeypatch.setattr(R, "connect", lambda: Con())
    monkeypatch.setattr(R, "build_view", build)
    return lambda q, k, filters=None, question=None, unit=None: [
        {"tbl_id": t, "rank": i} for i, t in enumerate("ABCDEF", 1)][:k]


VB = {"query_id": "q", "original": "질문", "filters": {"지표": ["x"]}, "search_text": "x",
      "sub_questions": ["가 지표", "나 지표"], "sub_filters": [{"지표": ["가"]}, {"지표": ["나"]}]}


def test_run_query_fill(fake):
    old = R.run_query(VB, 10, 3, search_fn=fake, skip_main=True)
    assert [v["tbl_id"] for v in old["units"][0]["views"]] == ["A", "C"]                # 기존: 상위 3개를 시도 (B 실패)
    new = R.run_query(VB, 10, 3, search_fn=fake, skip_main=True, fill=True)
    assert [u["unit_id"] for u in new["units"]] == ["q-1", "q-2"]                        # 서브쿼리마다
    for u in new["units"]:
        assert [v["tbl_id"] for v in u["views"]] == ["A", "C", "D", "E"]                  # 쓸 수 있는 A·D·E 3개 (C 는 세지 않음)
        assert any("B View 생성 실패" in n for n in u["notes"]) and any("C 는 요청 지표가 없어" in n for n in u["notes"])
    few = R.run_query(VB, 2, 3, search_fn=fake, skip_main=True, fill=True)               # top_k 안에서만
    assert [v["tbl_id"] for v in few["units"][0]["views"]] == ["A"]


def _view(tid, rank, missing=False):
    return {"record": _rec(tid, f"q-{rank}", missing), "notes": [], "rank": rank, "tbl_id": tid}


def _unit(auto, keep=True):
    vs = [_view("A", 1), _view("D", 2), _view("E", 3), _view("C", 4, missing=True)]
    sel = {"option_id": "opt-1", "dropped_ids": [vs[1]["record"]["id"], vs[2]["record"]["id"]], "rebuilt": [],
           "records": [vs[0]["record"]], **({"auto": True} if auto else {})}
    return {"conflict": {"status": "ambiguous", "views": []}, "views": vs, "selected": sel, "keep_others": keep}


def test_unit_records_keep_others():
    from backend.rag.view.viewset import unit_records
    recs = unit_records(_unit(auto=True))
    assert [r["source"]["tbl_id"] for r in recs] == ["A", "D", "E"]                      # 고른 무리 먼저, 지표 없는 C 는 빠짐
    assert "selected" not in (recs[0].get("match") or {}) and recs[1]["match"]["selected"] is False
    assert [r["source"]["tbl_id"] for r in unit_records(_unit(auto=False))] == ["A"]     # 사람이 고르면 고른 무리만
    assert [r["source"]["tbl_id"] for r in unit_records(_unit(auto=True, keep=False))] == ["A"]   # 설정 0 = 기존


def test_build_viewset_per_unit(fake, monkeypatch):
    from backend.rag.view import viewset as V
    monkeypatch.setattr("backend.rag.search.search_fn", lambda: fake, raising=False)
    seen = {}
    real = R.run_query

    def spy(b, top_k, n_views, **kw):
        seen.update(n_views=n_views, fill=kw.get("fill"))
        return real(b, top_k, n_views, **{**kw, "search_fn": fake})
    monkeypatch.setattr(R, "run_query", spy)
    monkeypatch.setattr(V, "detect", lambda views, f, s, uid: {"status": "ok", "n_compared_keys": 0, "differing_points": [],
                                                                   "clusters": [], "views": [], "notes": []})
    vs = V.build_viewset(dict(VB), overrides={"view_records_per_unit": 3, "view_main_with_subs": False})  # 설정 파일 값과 무관하게
    assert seen == {"n_views": 3, "fill": True}
    by_unit = {}
    for u in vs["units"]:
        by_unit[u["unit_id"]] = [r["source"]["tbl_id"] for r in V.unit_records(u)]
    assert by_unit == {"q-1": ["A", "D", "E"], "q-2": ["A", "D", "E"]} and len(vs["records"]) == 6
    V.build_viewset(dict(VB), overrides={"view_records_per_unit": 0, "view_n_views": 3, "view_main_with_subs": False})
    assert seen == {"n_views": 3, "fill": False}


def test_default_off_in_code():
    from backend.core.settings import Settings
    assert Settings().view_records_per_unit == 0                                          # 켜는 곳은 configs/pipeline.yaml


def test_searched_units_main_copy():
    """역할 단위와 함께 들어간 본 질의 복사본(roles.py) → 그 결과 = 본 질의 방식 검색. 복사본이 없으면 기존처럼 main 을 건너뜀"""
    vb = {"query_id": "q", "original": "질문", "filters": {"지표": ["x"]}, "search_text": "일반가구 보증부월세",
          "sub_questions": ["일반가구 보증부월세", "일반가구"],
          "sub_filters": [{"지표": ["x"]}, {"지표": ["일반가구"], "역할": "분모"}]}
    units = R.units_of(vb)
    assert R.main_copy(units) == 1 and R.searched_units(units) == [0, 2]   # main 방식 결과 + 분모
    assert R.searched_units(units, skip_main=False) == [0, 1, 2]
    assert R.searched_units(R.units_of(VB)) == [1, 2]              # 복사본 없음 → main 건너뜀 (기존)
    # 문장이 같아도 역할 단위면 복사본이 아님
    vb2 = {**vb, "sub_questions": ["일반가구 보증부월세"], "sub_filters": [{"지표": ["x"], "역할": "조건"}]}
    assert R.searched_units(R.units_of(vb2)) == [1]
    # 지표마다 나눈 하위 질의(역할 단위 없음)가 우연히 본 질의 문장과 같아도 기존처럼 main 을 건너뜀
    vb3 = {**vb, "sub_questions": ["일반가구 보증부월세", "총전입"], "sub_filters": [{"지표": ["x"]}, {"지표": ["총전입"]}]}
    assert R.searched_units(R.units_of(vb3)) == [1, 2]


def test_run_query_searches_main_for_copy(fake):
    seen = []
    vb = {"query_id": "q", "original": "질문", "filters": {"지표": ["x"]}, "search_text": "x 지표",
          "sub_questions": ["x 지표", "인구"], "sub_filters": [{"지표": ["x"]}, {"지표": ["인구"], "역할": "분모"}]}

    def fn(q, k, filters=None, question=None, unit=None):
        seen.append(unit)
        return fake(q, k)
    out = R.run_query(vb, 10, 3, search_fn=fn, skip_main=True)
    # 단위 목록·이름은 그대로 (답변 모듈이 하위 질문과 문장·순서로 짝지음), 복사본만 본 질의 방식으로 검색
    assert [u["unit_id"] for u in out["units"]] == ["q-1", "q-2"] and seen == ["main", "q-2"]


def test_main_copy_needs_same_filters_and_skip():
    # 문장이 같아도 슬롯(지역 등)이 다르면 복사본이 아님 · main 도 검색하는 설정이면 복사본을 바꿔 검색하지 않음
    vb = {"query_id": "q", "original": "질문", "filters": {"지표": ["입국"], "지역": ["전국"]}, "search_text": "입국",
          "sub_questions": ["입국", "인구"], "sub_filters": [{"지표": ["입국"], "지역": ["서울특별시"]}, {"지표": ["인구"], "역할": "분모"}]}
    assert R.main_copy(R.units_of(vb)) is None
    vb["sub_filters"][0] = {"지표": ["입국"], "지역": ["전국"]}
    assert R.main_copy(R.units_of(vb)) == 1
    seen = []
    R.run_query(vb, 10, 3, search_fn=lambda q, k, filters=None, question=None, unit=None: seen.append(unit) or [],
                skip_main=False)
    assert seen == ["main", "q-1", "q-2"]
