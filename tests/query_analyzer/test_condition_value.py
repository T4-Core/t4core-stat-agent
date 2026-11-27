"""근거 없는 값 지우기 — 재작성 지시대로 쓴 '축=값' 조건 (HCX·네트워크 없음)

재작성 지시문은 조건을 '출생연도=1983년생' 처럼 '축=값' 으로 쓰게 한다 (slots.py).
'질문 원문' 판정이 '축=값' 전체 글자만 봐서, 값 부분이 질문에 그대로 있어도 지워졌다.
값 부분이 질문에 있으면 남기고, 지어낸 값과 기준값('>=')은 전처럼 판정한다.
"""
import json

import pandas as pd
import pytest

from backend.rag.csv_index.store import CsvIndex, postings_of
from backend.rag.query_analyzer.vocab import build_vocab, check_value, prune_slots

SCANS = [
    {"tbl_id": "DT_BIRTH", "tbl_nm": "출생아수", "selected": True, "n_rows": 8, "years": [2016, 2022],
     "dims": [{"level": 1, "obj_nm": "성별", "kind": "sex", "slot": "성별", "n_values": 2,
               "values": [{"code": "1", "name": "남자", "n": 4, "n_value": 4}, {"code": "2", "name": "여자", "n": 4, "n_value": 4}]}],
     "items": [{"itm_id": "T1", "name": "출생아수", "unit": "명", "n_value": 8}]},
]
Q = "1983년생 남자의 경우, 결혼 후 아이를 낳은 비율이 2016년에 비해 2022년에 얼마나 변했을까요?"


@pytest.fixture(scope="module")
def vocab(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv_index")
    pd.DataFrame([r for s in SCANS for r in postings_of(s)]).to_parquet(d / "values.parquet")
    (d / "tables.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in SCANS), encoding="utf-8")
    return build_vocab(idx=CsvIndex(d), alias_path=tmp_path_factory.mktemp("al") / "none.json")


@pytest.mark.parametrize("v", ["출생연도=1983년생", "출생 연도 = 1983년생"])
def test_axis_value_kept_when_value_in_question(vocab, v):
    r = check_value(v, "조건", Q, vocab, hints=[])
    assert r["verdict"] == "keep" and "질문 원문" in r["why"]


@pytest.mark.parametrize("v", ["출생연도=1990년생", "출생아수>=1983", "=1983년생", "출생연도="])
def test_other_values_still_dropped(vocab, v):
    # 질문에 없는 값 · 기준값(>=, 다른 단계가 다룸) · 한쪽이 빈 꼴은 전처럼 지움
    assert check_value(v, "조건", Q, vocab, hints=[])["verdict"] == "drop"


def test_prune_keeps_condition(vocab):
    slots = {"조건": ["출생연도=1983년생", "혼인상태=사별"], "지표": ["출생아수"]}
    out, _ = prune_slots(slots, Q, vocab, hints=[], alias_fill=False)
    assert out["조건"] == ["출생연도=1983년생"]
