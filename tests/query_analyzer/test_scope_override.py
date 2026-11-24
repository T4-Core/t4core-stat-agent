"""'범위 밖' 판정 뒤집기 — 조사 결과 표(만족도)처럼 값 사전 항목·분류에 없는 말 (HCX·네트워크 없음)

HCX 가 '○○실태조사의 한국 생활 전반적 만족도' 를 '범위 밖'(의견 요청)으로 판정하고, domain_terms 는 항목·분류 값만 봐서
근거를 못 찾던 문제. table_terms 가 표 이름·열 이름에서 근거를 찾는다. 용어 뜻을 묻는 질문은 그대로 '범위 밖'
"""
import json

import pandas as pd
import pytest

from backend.rag.csv_index.store import CsvIndex, postings_of

SCANS = [
    {"tbl_id": "DT_SAT01", "tbl_nm": "성별 한국생활 전반적 만족도", "selected": True, "n_rows": 12, "years": [2021],
     "dims": [{"level": 1, "obj_nm": "만족도별", "kind": "other", "slot": "분류", "n_values": 3,
               "values": [{"code": c, "name": n, "n": 4, "n_value": 4} for c, n in (("1", "매우 만족"), ("2", "보통"), ("3", "불만"))]}],
     "items": [{"itm_id": "T1", "name": "응답자 비율", "unit": "%", "n_value": 12}]},
    {"tbl_id": "DT_TFR", "tbl_nm": "시도별 합계출산율", "selected": True, "n_rows": 18, "years": [2024],
     "dims": [], "items": [{"itm_id": "T1", "name": "합계출산율", "unit": "명", "n_value": 18}]},
]


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv_index")
    pd.DataFrame([r for s in SCANS for r in postings_of(s)]).to_parquet(d / "values.parquet")
    (d / "tables.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in SCANS), encoding="utf-8")
    return CsvIndex(d)


@pytest.fixture(scope="module")
def lex(idx, tmp_path_factory):
    from backend.core.settings import with_overrides
    from backend.rag.query_analyzer.lexicon import Lexicon
    return Lexicon(idx=idx, settings=with_overrides({"csv_scope": "all"}),
                   learned_path=tmp_path_factory.mktemp("lex") / "learned.json")


Q = "사할린동포실태조사에서 한국 생활 전반적 만족도를 원그래프로 그려줘"


def test_table_terms(lex):
    from backend.rag.query_analyzer.analyze import domain_terms, table_terms
    assert domain_terms(Q, lex) == []                                   # 항목·분류 값으로는 근거가 없음 (실제 증상)
    assert table_terms(Q, lex) == ["전반적", "만족도"]                   # 표 이름·열 이름 ('원그래프로'·'그려줘' 는 제외)
    assert table_terms("만족도가 무슨 뜻이야?", lex) == []               # 용어 뜻을 묻는 질문은 뒤집지 않음
    assert table_terms("오늘 날씨 그래프로 보여줘", lex) == []


def _analyze(q, idx, tmp_path, intents=("범위 밖",)):
    from backend.rag.query_analyzer.analyze import analyze
    st = {"bundle": {"original": q, "rewritten": q, "intent": intents[0], "sub_questions": []}, "raw_slots": {},
          "sub_slots": [], "intents": list(intents), "sub_intents": [], "hcx_ok": True, "hcx_error": "", "thresholds": []}
    o = {"csv_scope": "all", "clarify_mode": "soft", "base_year_mode": "fixed", "base_year": 2025,
         "vocab_path": str(tmp_path / "no_vocab.json"), "vocab_suggest": "off"}
    return analyze(q, previous={"state": st}, idx=idx, overrides=o)


def test_analyze_overrides_out_of_scope(idx, tmp_path):
    a = _analyze(Q, idx, tmp_path)
    assert a["status"] != "out_of_scope", a["notes"]
    assert any("표 이름·열 이름" in n for n in a["notes"]), a["notes"]


def test_analyze_keeps_definition_question_out(idx, tmp_path):
    a = _analyze("한국생활 만족도가 무슨 뜻이야?", idx, tmp_path)
    assert a["status"] == "out_of_scope"
