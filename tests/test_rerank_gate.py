"""조건부 LLM 재정렬 (llm_rerank.gate) — 1·2위가 경합할 때만 HCX 를 부름. 가짜 chat_fn (HCX 없음)"""
from backend.rag.search.engine import TableSearch
from tests.test_search import Corpus


def _search(gate):
    calls = []

    def fake_chat(messages, schema=None, max_tokens=0):
        calls.append(1)
        return {"order": [2, 1]}
    s = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=fake_chat,
                    settings={"llm_rerank": {"gate": gate}})
    return s, calls


def test_gate_none_always_calls():
    s, calls = _search(None)
    s.search("혼인건수", None, 5, question="2020년 혼인 건수 (게이트 없음)")
    assert len(calls) == 1


def test_gate_skips_clear_winner():
    s, calls = _search({"ratio": 1.01, "same_group": False})   # 점수 비는 1 을 넘을 수 없음 → 늘 건너뜀
    r = s.search("혼인건수", None, 5, question="2020년 혼인 건수 (경합 아님)")
    base = TableSearch(Corpus(), facets_source="meta", llm_rerank=False).search(
        "혼인건수", None, 5, question="2020년 혼인 건수 (경합 아님)")
    assert calls == [] and "경합 아님" in str(r.get("llm") or r.get("llm_note") or r)
    assert [h["tbl_id"] for h in r["hits"]] == [h["tbl_id"] for h in base["hits"]]   # LLM 없는 검색과 같음


def test_gate_calls_when_close():
    s, calls = _search({"ratio": 0.0})                          # 비 ≥ 0 → 늘 경합
    s.search("혼인건수", None, 5, question="2020년 혼인 건수 (경합)")
    assert len(calls) == 1


def test_gate_ratio_never_above_one():
    # 형제 해소로 1·2위 순서가 원래 점수와 반대여도 비는 ≤ 1 (경합 아님이면 부르지 않음)
    import numpy as np
    from types import SimpleNamespace
    s = SimpleNamespace(_pos={"A": 0, "B": 1}, sib=SimpleNamespace(of={}), concept_of={})
    use, note = TableSearch._rerank_gate(s, ["A", "B"], np.array([0.3, 0.9]), {"ratio": 0.95})
    assert use is False and "0.33" in note
