"""구어 소유격 '의' — '외국인 주민의 자녀' 를 CSV 이름 '외국인주민자녀' 로 (HCX·네트워크 없음)

구어 재작성은 '외국인 주민의 자녀' 처럼 '의' 를 넣는다. 띄어쓰기만 다른 값은 정확 일치로 표 용어가 되지만
'의' 가 끼면 포함 일치('자녀'·'외국인')로만 잡혀 표 용어로 바뀌지 않았다.
'의' 를 뗀 값이 CSV 이름과 정확히 맞을 때만 바꾸고, CSV 이름에 '의' 가 있는 값('미혼모의 자녀')은 그대로 둔다.
"""
import json

import pandas as pd
import pytest

from backend.rag.csv_index.store import CsvIndex, postings_of


def _dim(obj, names):
    return {"level": 1, "obj_nm": obj, "kind": "other", "slot": "분류", "n_values": len(names),
            "values": [{"code": str(i), "name": n, "n": 4, "n_value": 4} for i, n in enumerate(names)]}


SCANS = [
    {"tbl_id": "DT_CHILD", "tbl_nm": "시군구별 외국인주민 자녀", "selected": True, "n_rows": 8, "years": [2020, 2023],
     "dims": [_dim("대상별", ["계", "외국인주민자녀"])],
     "items": [{"itm_id": "T1", "name": "인구수", "unit": "명", "n_value": 8}]},
    {"tbl_id": "DT_SINGLE", "tbl_nm": "미혼모 가구", "selected": True, "n_rows": 8, "years": [2020],
     "dims": [_dim("구분별", ["계", "미혼모의 자녀", "자녀"])],
     "items": [{"itm_id": "T1", "name": "인구수", "unit": "명", "n_value": 8}]},
    {"tbl_id": "DT_FOREIGN", "tbl_nm": "외국인 인구", "selected": True, "n_rows": 8, "years": [2023],
     "dims": [_dim("국적별", ["계", "외국인"])],
     "items": [{"itm_id": "T1", "name": "인구수", "unit": "명", "n_value": 8}]},
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


def test_possessive_dropped_when_exact(lex):
    h = lex.best("외국인 주민의 자녀", "대상")
    assert (h.value, h.source, h.match) == ("외국인주민자녀", "csv", "exact")
    assert h.surface == "외국인 주민의 자녀"
    assert h.tables == lex.best("외국인주민자녀", "대상").tables  # 표 용어를 바로 넣은 것과 같은 근거


@pytest.mark.parametrize("v", ["미혼모의 자녀", "주민의 자녀"])
def test_possessive_kept_otherwise(lex, v):
    # CSV 이름에 '의' 가 있으면 그 이름 그대로, '의' 를 떼도 정확히 맞는 이름이 없으면 원래 값
    assert lex.best(v, "대상").value == v


def test_analyze_filters_use_csv_name(idx, tmp_path):
    from backend.rag.query_analyzer.analyze import analyze
    q = "장안구에서 외국인 주민의 자녀 수가 2020년에 비해 2023년에 얼마나 증가했나요?"
    raw = {"시점": ["2020년", "2023년"], "지역": ["전국"], "대상": ["외국인 주민의 자녀"], "지표": ["인구수"]}
    st = {"bundle": {"original": q, "rewritten": q, "intent": "값 조회", "sub_questions": []}, "raw_slots": raw,
          "sub_slots": [], "intents": ["값 조회"], "sub_intents": [], "hcx_ok": True, "hcx_error": "", "thresholds": []}
    o = {"csv_scope": "all", "clarify_mode": "soft", "base_year_mode": "fixed", "base_year": 2024,
         "vocab_path": str(tmp_path / "no_vocab.json"), "vocab_suggest": "off"}
    a = analyze(q, previous={"state": st}, idx=idx, overrides=o)
    assert a["view_bundle"]["filters"]["대상"] == ["외국인주민자녀"]
