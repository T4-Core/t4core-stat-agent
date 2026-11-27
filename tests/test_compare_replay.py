"""compare 질의 분석 재생 — 재작성(HCX) 답을 캐시에 남기고, 그 답으로 후처리만 다시 (HCX·저장소 파일 없음)

분석 캐시에는 검색 단위만 있어 분석기 후처리를 고쳐도 캐시 회귀에 반영되지 않았다.
새로 분석할 때 재작성 직후의 답(state)을 남기고, --replay-state 면 그 답으로 analyze 를 다시 돌린다.
"""
import hashlib
import json

import pandas as pd
import pytest

import backend.rag.query_analyzer.analyze as A
from backend.rag.csv_index.store import CsvIndex, postings_of
from backend.rag.search.tuning.compare import analyze_all, analyze_units, analyzer_sig

Q = "장안구에서 외국인 주민의 자녀 수가 2020년에 비해 2023년에 얼마나 증가했나요?"
TODAY = "2026-11-24"
SCANS = [
    {"tbl_id": "DT_CHILD", "tbl_nm": "시군구별 외국인주민 자녀", "selected": True, "n_rows": 8, "years": [2020, 2023],
     "dims": [{"level": 1, "obj_nm": "대상별", "kind": "other", "slot": "분류", "n_values": 2,
               "values": [{"code": str(i), "name": n, "n": 4, "n_value": 4} for i, n in enumerate(["계", "외국인주민자녀"])]}],
     "items": [{"itm_id": "T1", "name": "인구수", "unit": "명", "n_value": 8}]},
]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    d = tmp_path / "csv_index"
    d.mkdir()
    pd.DataFrame([r for s in SCANS for r in postings_of(s)]).to_parquet(d / "values.parquet")
    (d / "tables.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in SCANS), encoding="utf-8")
    idx = CsvIndex(d)
    o = {"csv_scope": "all", "clarify_mode": "soft", "base_year_mode": "fixed", "base_year": 2024,
         "vocab_path": str(tmp_path / "no_vocab.json"), "vocab_suggest": "off", "save_runs": False}
    calls = []

    def rewrite(question, today=None):  # 가짜 재작성 (HCX 대신). 부를 때마다 셈
        calls.append(question)
        raw = {"시점": ["2020년", "2023년"], "지역": ["장안구"], "대상": ["외국인 주민의 자녀"], "지표": ["인구수"]}
        return {"bundle": {"original": question, "rewritten": "장안구 외국인 주민의 자녀 인구수", "intent": "값 조회",
                           "sub_questions": []}, "raw_slots": raw, "sub_slots": [], "intents": ["값 조회"],
                "sub_intents": [], "hcx_ok": True, "hcx_error": "", "thresholds": []}
    real = A.analyze
    monkeypatch.setattr(A, "rewrite_state", rewrite)
    monkeypatch.setattr(A, "analyze", lambda q, today=None, previous=None: real(q, today=today, previous=previous,
                                                                                 idx=idx, overrides=o))
    return calls


def test_record_then_replay_same_units(fake):
    rec = {}
    first = analyze_units(Q, today=TODAY, record=rec)
    assert len(fake) == 1 and rec["state"]["raw_slots"]["대상"] == ["외국인 주민의 자녀"]  # 후처리 전 값
    assert A.rewrite_state.__name__ == "rewrite"                                       # 기록용 감싸기를 되돌림
    again = analyze_units(Q, today=TODAY, state=rec["state"])
    assert len(fake) == 1                                                              # 재작성을 다시 부르지 않음
    assert json.loads(json.dumps(again, default=str)) == json.loads(json.dumps(first, default=str))


def test_analyze_all_stores_state_and_replays(fake, tmp_path):
    cache = tmp_path / "analysis_cache.jsonl"
    rows = [{"qid": "q1", "question": Q}]
    out = analyze_all(rows, "analyze", TODAY, cache, log=lambda *_: None)
    line = json.loads(cache.read_text(encoding="utf-8").splitlines()[-1])
    assert "state" in line and line["sig"] == analyzer_sig() and len(fake) == 1

    # 옛 코드로 만든 줄(서명 다름) + 다른 단위 → 재생하면 재작성 답으로 다시 분석, HCX 0
    stale = {**line, "sig": "000000000000", "units": [{"unit": "main", "search_query": "옛 분석", "filters": {}}]}
    key = lambda q: hashlib.sha1(f"analyze|{TODAY}|{q}".encode()).hexdigest()[:16]
    old = {"key": key("옛 질문"), "question": "옛 질문", "units": [{"unit": "main", "search_query": "옛"}], "sig": "x"}
    cache.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in (stale, old)), encoding="utf-8")
    logs = []
    rows2 = rows + [{"qid": "q2", "question": "옛 질문"}]
    again = analyze_all(rows2, "analyze", TODAY, cache, log=logs.append, replay=True)
    assert len(fake) == 1
    assert again["q1"] == json.loads(json.dumps(out["q1"], default=str))
    assert again["q2"][0]["search_query"] == "옛"                                    # 재작성 답이 없는 줄은 그대로
    assert any("후처리 다시 1" in x and "그대로 1" in x for x in logs)

    # 캐시를 다시 읽으면 뒤에 덧붙인 줄이 이김 → 재생 없이도 새 분석
    plain = analyze_all(rows, "analyze", TODAY, cache, log=lambda *_: None)
    assert plain["q1"] == again["q1"] and len(fake) == 1


def test_no_replay_keeps_cached_units(fake, tmp_path):
    cache = tmp_path / "analysis_cache.jsonl"
    rows = [{"qid": "q1", "question": Q}]
    analyze_all(rows, "analyze", TODAY, cache, log=lambda *_: None)
    line = json.loads(cache.read_text(encoding="utf-8").splitlines()[-1])
    cache.write_text(json.dumps({**line, "sig": "old", "units": [{"unit": "main", "search_query": "옛"}]},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    assert analyze_all(rows, "analyze", TODAY, cache, log=lambda *_: None)["q1"][0]["search_query"] == "옛"
