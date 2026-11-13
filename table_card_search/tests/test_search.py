"""카드 검색: 기존 계산과 같은지 · 구성 · 골든셋 읽기 · 평가 계산"""
import json
from pathlib import Path

import table_card_search  # noqa: F401
from backend.rag.retrieval.interfaces import Doc, SearchContext
from table_card_search.cards import CardCorpus, table_card_profile
from table_card_search.compare import evaluate_one, load_golden
from table_card_search.rerankers import CardConditionReranker
from table_card_search.search import method_config

PROF = {"tbl_id": "A", "tbl_nm": "시도별 성별 인구", "periods": [{"se": "Y", "year_from": 2015, "year_to": 2020}],
        "levels": [{"kind": "regions", "names": ["전국", "서울특별시"], "sido": ["서울특별시"]},
                   {"kind": "sex", "names": ["남자", "여자"]}], "items": [{"name": "인구수", "unit": "명"}], "units": ["명"]}
PROF_B = {**PROF, "tbl_id": "B", "periods": [{"se": "Y", "year_from": 2000, "year_to": 2010}], "levels": []}


def test_card_condition_matches_existing_resolve(monkeypatch):
    import backend.rag.ingestion.resolve as R
    monkeypatch.setattr(R, "profile", lambda t: {"A": PROF, "B": PROF_B}[t])
    f = {"시점": [2020], "지역": ["서울특별시"], "성별": ["남자"]}
    old = R.rerank([{"tbl_id": "B"}, {"tbl_id": "A"}], f)
    ctx = SearchContext(filters=f, corpus=None, docs_by_id={"A": Doc("A", "", {"profile": PROF}),
                                                             "B": Doc("B", "", {"profile": PROF_B})})
    new = CardConditionReranker().rerank("q", [{"tbl_id": "B"}, {"tbl_id": "A"}], ctx)
    assert [(c["tbl_id"], c["cost"]) for c in old] == [(c["tbl_id"], c["cost"]) for c in new]
    assert new[0]["tbl_id"] == "A"


def test_method_configs_keep_stages():
    b = method_config("baseline", "none")
    t = method_config("table_card", "hash", dirs=["x"])
    e = method_config("table_card_expend", "hcx")
    assert b["retrievers"] == t["retrievers"] == e["retrievers"]          # 같은 1단계 (BM25 kiwi 50)
    assert [r["type"] for r in b["rerank"]] == ["condition"]
    assert [r["type"] for r in t["rerank"]] == ["card_condition", "card_embed"] and t["rerank"][1]["embedder"]["type"] == "hash"
    assert t["corpus"]["dirs"] == ["x"] and e["rerank"][1]["embedder"]["type"] == "hcx_bge_m3"


def test_table_card_profile_and_corpus(tmp_path):
    card = {"tbl_id": "T", "제목": "성별 인구", "조사명": "인구총조사", "축": ["성별"], "bm25_text": "인구총조사 성별 인구 인구수",
            "dense_text": "인구총조사 | 성별 인구"}
    cond = {"tbl_id": "T", "시점": [{"주기": "년", "시작": 2015, "끝": 2020}], "지역": ["전국", "서울특별시", "서울특별시 중구"]}
    p = table_card_profile(card, cond)
    assert p["levels"][0]["sido"] == ["서울특별시"] and p["levels"][1]["kind"] == "sex"
    for n, r in (("cards.jsonl", card), ("conditions.jsonl", cond)):
        (tmp_path / n).write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
    docs = CardCorpus("table_card", [tmp_path]).docs()
    assert docs[0].text == card["bm25_text"] and docs[0].meta["dense_text"] == card["dense_text"]


def test_load_golden_and_evaluate():
    path = Path(__file__).resolve().parents[2] / "synthetic_gold_pipeline" / "outputs" / "datasets" / "synthetic_gold_dataset.jsonl"
    rows = load_golden(path, ("P",))
    assert rows and all(r["variant"] == "P" and r["gold"] and r["groups"] for r in rows)
    row = {**rows[0], "gold": ["G"], "groups": {"R1": ["G"], "R2": ["H"]}}

    class Pipe:
        docs = [Doc("X", "", {"tbl_nm": "x"}), Doc("G", "", {"tbl_nm": "g", "profile": PROF}), Doc("H", "", {"tbl_nm": "h", "profile": PROF})]
        docs_by_id = {d.id: d for d in docs}

        def search(self, q, f, k):
            return {"hits": [{"rank": 1, "tbl_id": "X"}, {"rank": 2, "tbl_id": "G"}] if q == "main" else
                    [{"rank": 1, "tbl_id": "H"}]}

    class BM:
        def search(self, q, k):
            return [(0, 1.0), (1, 0.5)]

    units = [{"unit": "main", "search_query": "main", "filters": {"시점": [2024]}},
             {"unit": "sub", "search_query": "sub", "filters": None}]
    r = evaluate_one(Pipe(), BM(), row, units, 10, 50)
    # 합친 순위: X(본 질의 1위) · H(서브 1위) · G(본 질의 2위) → 정답 첫 순위 2, 두 근거 그룹 모두 상위 5
    assert r["rank"] == 2 and r["hit@1"] == 0 and r["hit@3"] == 1 and r["groups@5"] == 1
    assert r["top5"] == "X H G" and r["fail"] == ""
    assert r["gold_unmet_any"] == 1 and "2024" in r["gold_unmet"]
    # [NEW 11-12] 완화 기준: X 가 대체 정답(같은 값)이면 1위가 정답 → hit@1_alt = 1, 대체 정답이 없으면 엄격과 같음
    r2 = evaluate_one(Pipe(), BM(), {**row, "alt_groups": {"R1": ["X"]}}, units, 10, 50)
    assert r2["hit@1"] == 0 and r2["hit@1_alt"] == 1 and r2["mrr_alt"] == 1.0 and r2["alt_tables"] == "X"
    r3 = evaluate_one(Pipe(), BM(), {**row, "alt_groups": {}}, units, 10, 50)
    assert r3["mrr_alt"] == r3["mrr"] and r3["alt_tables"] == ""
    assert "mrr_alt" not in r                                           # --alt 없이는 완화 지표 없음


def test_load_manual_retrieval_golden(tmp_path):
    """[NEW 11-12] retrieval_golden.jsonl 형식 (qid · required 그룹 · no_answer)"""
    import json
    p = tmp_path / "retrieval_golden.jsonl"
    lines = [{"qid": "Q1", "split": "test", "qtype": "concept", "source": "s", "question": "q1",
              "required": [["101_DT_A", "101_DT_B"]]},
             {"qid": "Q2", "split": "dev", "qtype": "multi_table", "source": "s", "question": "q2",
              "required": [["101_DT_A"], ["110_TX_C"]]},
             {"qid": "Q3", "split": "test", "qtype": "no_answer", "source": "s", "question": "q3",
              "answerable": False, "no_answer_reason": "out_of_scope"}]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    rows = load_golden(p)
    assert [r["qid"] for r in rows] == ["Q1", "Q2"]                     # no_answer 제외
    assert rows[0]["groups"] == {"G1": ["DT_A", "DT_B"]} and rows[0]["hop_type"] == "SINGLE"
    assert rows[1]["groups"] == {"G1": ["DT_A"], "G2": ["TX_C"]} and rows[1]["hop_type"] == "MULTI_2"
    assert rows[1]["gold"] == ["DT_A", "TX_C"] and rows[1]["reasoning_type"] == "multi_table"
    assert [r["qid"] for r in load_golden(p, split=["dev"])] == ["Q2"]
