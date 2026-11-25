"""compare 의 앱 기준 지표(app_*) · 질의 분석 캐시 점검 — 가짜 검색기로 (HCX·저장소 파일 없음)"""
import hashlib
import json

from backend.rag.search.tuning.compare import (aggregate, analyze_all, analyzer_sig, app_status, app_units, check_cache,
                                               code_only, evaluate_one)

APP = {"main_with_subs": False, "n_rec": 3}


class FakePipe:
    """질의 → 정해 둔 순위. docs_by_id 가 비어 있어 정답 표 프로필(저장소)을 읽지 않음"""
    docs_by_id = {}
    docs = []

    def __init__(self, by_query):
        self.by = by_query

    def search(self, query, filters=None, top_k=10, question=None, unit="main"):
        ids = self.by[query][:top_k]
        return {"hits": [{"rank": i, "tbl_id": t} for i, t in enumerate(ids, 1)], "pool_ids": ids}


def _u(unit, q, status="ok", filters=None):
    return {"unit": unit, "search_query": q, "filters": {"지표": [q]} if filters is None else filters, "status": status}


ROW = {"question": "2023년 출생아 수와 혼인 건수", "gold": ["G1", "G2"], "groups": {"G1": ["G1"], "G2": ["G2"]}}
# 본 질의(main)는 두 정답을 1·2위로, 하위 질의는 각자의 정답을 4위에 → 합친 순위는 맞히지만 앱은 main 을 검색하지 않음
PIPE = FakePipe({"출생 혼인": ["G1", "G2", "A"], "출생아수": ["X1", "X2", "X3", "G1"], "혼인건수": ["Y1", "Y2", "Y3", "G2"]})
UNITS = [_u("main", "출생 혼인"), _u("q-1", "출생아수"), _u("q-2", "혼인건수")]


def test_app_skips_main_when_subs():
    res = evaluate_one(PIPE, ROW, UNITS, 10, 50, APP)
    assert res["groups@5"] == 1 and res["hit@1"] == 1          # 합친 순위 (기존 지표) — main 덕분
    assert res["app_status"] == "ok" and res["app_stop"] == 0
    assert res["app_hit"] == 0 and res["app_groups"] == 0      # 하위 단위 상위 3 에는 없음
    assert res["app_groups_cand"] == 1                         # 하위 단위 후보(top_k) 에는 있음
    on = evaluate_one(PIPE, ROW, UNITS, 10, 50, {**APP, "main_with_subs": True})
    assert on["app_groups"] == 1 and on["groups@5"] == res["groups@5"]


def test_app_n_rec():
    res = evaluate_one(PIPE, ROW, UNITS, 10, 50, {**APP, "n_rec": 4})
    assert res["app_hit"] == 1 and res["app_groups"] == 1


def test_app_single_unit_matches_merged():
    pipe = FakePipe({"출생아수": ["X1", "G1", "X2", "X3"]})
    row = {**ROW, "gold": ["G1"], "groups": {"G1": ["G1"]}}
    res = evaluate_one(pipe, row, [_u("main", "출생아수")], 10, 50, APP)
    assert res["app_hit"] == res["hit@3"] == 1 and res["app_groups"] == res["groups@5"] == 1


def test_app_stop():
    pipe = FakePipe({"출생아수": ["G1"]})
    row = {**ROW, "gold": ["G1"], "groups": {"G1": ["G1"]}}
    res = evaluate_one(pipe, row, [_u("main", "출생아수", status="needs_clarification")], 10, 50, APP)
    assert res["hit@1"] == 1 and res["app_stop"] == 1 and res["app_hit"] == 0 and res["app_groups_cand"] == 0
    assert app_status([{"unit": "main", "filters": None, "status": "ok"}]) == "out_of_scope"   # 슬롯 없음 → 앱은 검색 안 함
    assert app_status([{"unit": "main", "filters": {}}]) == "ok"                               # 상태 없는 단위 = ok


def test_app_units():
    assert app_units(UNITS, APP) == [1, 2]
    assert app_units(UNITS[:1], APP) == [0]
    assert app_units(UNITS, {**APP, "main_with_subs": True}) == [0, 1, 2]


def test_app_aud():
    row = {**ROW, "alt_groups": {}, "audit": {"alt": ["X1"], "exclude": False, "flags": []}}
    res = evaluate_one(PIPE, row, UNITS, 10, 50, APP)
    assert res["app_hit_aud"] == 1 and res["app_groups_aud"] == 1    # 검토가 준 대체 정답 X1 이 두 그룹 모두를 채움
    assert aggregate([res])["app_groups_aud"] == 1 and aggregate([res])["app_stop"] == 0


def test_code_only():
    assert code_only([{"status": "ok", "notes": ["HCX 슬롯 추출 실패 → 코드 추출 값만 사용: Timeout"]}]) == "hcx_fail"
    assert code_only([{"status": "ok", "notes": ["재작성 단계 오류 → 코드 추출 값으로 진행: X"]}]) == "hcx_fail"
    assert code_only([{"status": "error:ValueError"}]) == "error"      # 분석 예외 — HCX 때문인지 모름
    # HCX 는 답했지만 '범위 밖' 을 뒤집은 경우 — 분석기가 같은 'HCX 슬롯 추출 실패' 안내를 붙이므로 따로 셈
    assert code_only([{"status": "ok", "notes": ["재작성 모듈은 '범위 밖' 이라 했지만 질문에 통계 용어 ['아동'] 가 있어 검색함",
                                                 "HCX 슬롯 추출 실패 → 코드 추출 값만 사용: 범위 밖 판정을 뒤집음"]}]) == "oos_flip"
    assert code_only([{"status": "ok", "notes": ["원문 표현 보충"]}]) == "" and code_only(None) == ""


def test_analyzer_sig(tmp_path):
    (tmp_path / "backend/rag/query_analyzer").mkdir(parents=True)
    f = tmp_path / "backend/rag/query_analyzer/a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    s1 = analyzer_sig(tmp_path)
    assert s1 == analyzer_sig(tmp_path) and len(s1) == 12
    f.write_text("x = 2\n", encoding="utf-8")
    assert analyzer_sig(tmp_path) != s1


def test_analyze_all_cache_stats(tmp_path):
    today, sig = "2026-11-24", analyzer_sig()
    rows = [{"qid": f"q{i}", "question": f"질문 {i}"} for i in range(4)]
    key = lambda q: hashlib.sha1(f"analyze|{today}|{q}".encode()).hexdigest()[:16]  # noqa: E731
    ok = [{"unit": "main", "search_query": "x", "filters": {}, "status": "ok", "notes": []}]
    bad = [{**ok[0], "notes": ["HCX 슬롯 추출 실패 → 코드 추출 값만 사용: Timeout"]}]
    flip = [{**ok[0], "notes": ["HCX 슬롯 추출 실패 → 코드 추출 값만 사용: 범위 밖 판정을 뒤집음"]}]
    lines = [{"key": key("질문 0"), "question": "질문 0", "units": ok, "sig": sig},
             {"key": key("질문 1"), "question": "질문 1", "units": ok, "sig": "000000000000"},
             {"key": key("질문 2"), "question": "질문 2", "units": bad},
             {"key": key("질문 3"), "question": "질문 3", "units": flip, "sig": sig}]
    cache = tmp_path / "analysis_cache.jsonl"
    cache.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    logs = []
    out = analyze_all(rows, "analyze", today, cache, log=logs.append)   # 모두 캐시 → 분석(HCX)을 부르지 않음
    stats = check_cache(rows, out, "analyze", today, cache, log=logs.append)
    assert len(out) == 4 and stats["sig"] == sig
    assert (stats["same"], stats["other"], stats["unknown"], stats["hcx_fail"], stats["oos_flip"]) == (2, 1, 1, ["q2"], ["q3"])
    assert any("캐시 점검" in x for x in logs)
    assert stats["error"] == []
    assert check_cache(rows, out, "none", today, cache) is None and check_cache(rows, out, "analyze", today, tmp_path / "x") is None


def test_analyze_units_keeps_notes_when_stopped(monkeypatch):
    """범위 밖 · 되묻기로 멈춘 분석도 노트를 캐시에 남김 → code_only 가 읽을 수 있음"""
    import backend.rag.query_analyzer.analyze as A
    from backend.rag.search.tuning.compare import analyze_units
    note = "HCX 슬롯 추출 실패 → 코드 추출 값만 사용: Timeout"
    for st in ("out_of_scope", "needs_clarification"):
        monkeypatch.setattr(A, "analyze", lambda q, today=None, st=st: {"status": st, "notes": [note], "view_bundle": None})
        units = analyze_units("질문", today="2026-11-24")
        assert units[0]["status"] == st and units[0]["filters"] is None and code_only(units) == "hcx_fail"
