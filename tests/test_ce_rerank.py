"""교차 인코더 재정렬 (search/ce_rerank.py) — 모델 없이 가짜 점수로: 순서 바꾸기 · 순위 융합 · 엔진 연결 · compare 'search+ce'"""
import pytest

from backend.rag.search import ce_rerank as C
from tests.test_search import Corpus


def _hits(ids):
    return [{"rank": r, "tbl_id": t, "score": 1.0 / r, "stages": {}} for r, t in enumerate(ids, 1)]


@pytest.fixture(scope="module")
def facets():
    from backend.rag.search.facets import build_facets
    return build_facets(Corpus().docs(), "meta")


def test_replace_and_blend(facets):
    ids = ["INH_03", "DT_1B85003", "DT_1B26001", "DT_1GA9009"]
    want = {"DT_1GA9009": 0.9, "DT_1B26001": 0.5, "INH_03": 0.1, "DT_1B85003": 0.0}
    fake = lambda q, texts, keys: [want[k.split("|")[0]] for k in keys]
    out, note = C.rerank("q", _hits(ids), facets, {"mode": "replace", "top_n": 4}, score_fn=fake)
    assert [h["tbl_id"] for h in out] == ["DT_1GA9009", "DT_1B26001", "INH_03", "DT_1B85003"] and note == "ce:replace"
    assert out[0]["stages"]["ce"]["rank"] == 1 and out[0]["stages"]["fused"]["rank"] == 4
    # blend: 원래 1위(INH_03)와 교차 인코더 1위(DT_1GA9009)를 함께 — 같은 무게면 원래 2위 안쪽을 크게 넘어서지 않음
    out, _ = C.rerank("q", _hits(ids), facets, {"mode": "blend", "top_n": 4, "k": 1, "weight": 1.0}, score_fn=fake)
    top2 = [h["tbl_id"] for h in out[:2]]
    assert set(top2) == {"INH_03", "DT_1GA9009"}
    out, _ = C.rerank("q", _hits(ids), facets, {"mode": "blend", "top_n": 4, "k": 1, "weight": 3.0}, score_fn=fake)
    assert out[0]["tbl_id"] == "DT_1GA9009"                                   # 교차 인코더 무게를 키우면 1위로
    out, _ = C.rerank("q", _hits(ids), facets, {"top_n": 2}, score_fn=fake)   # top_n 밖은 그대로
    assert [h["tbl_id"] for h in out[2:]] == ["DT_1B26001", "DT_1GA9009"] and [h["rank"] for h in out] == [1, 2, 3, 4]
    bad = C.rerank("q", _hits(ids), facets, {}, score_fn=lambda *a: 1 / 0)
    assert bad[0][0]["tbl_id"] == "INH_03" and bad[1].startswith("실패")


def test_doc_text_uses_card(facets):
    f = facets["DT_1GA9009"]
    s = C.doc_text(f)
    assert s.startswith(f.tbl_nm) and "점유형태별(계, 자기집" in s and "지역: 시도·시군구" in s
    card = {"def_text": "인구총조사 | 행정구역/거처의 종류/점유형태별 가구\n구분: 시군구 단위\n일반가구를 집계한 통계다."}
    s2 = C.doc_text(f, card)
    assert s2.endswith("구분: 시군구 단위 일반가구를 집계한 통계다.") and C.doc_text(f, card, "struct") == s


def test_engine_and_compare_with_ce(monkeypatch):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder
    from backend.rag.search.tuning import compare as CMP
    calls = []

    def fake(q, texts, keys):
        calls.append(len(texts))
        return [1.0 if k.startswith("DT_1B26001|") else 0.0 for k in keys]

    def fake_get(dense="hcx", llm=False, settings=None):
        s = TableSearch(Corpus(), embedder=HashEmbedder(), facets_source="meta", llm_rerank=False, settings=settings)
        s.ce_score_fn = fake
        return s
    s = fake_get(settings={"ce_rerank": {"enabled": True, "mode": "replace", "top_n": 8}})
    r = s.search("이동자수", None, 3, question="작년 시도별 이사 간 사람 수", today="2026-11-12")
    assert r["hits"][0]["tbl_id"] == "DT_1B26001" and "ce" in r["hits"][0]["stages"] and r["llm"] == "ce:replace"
    monkeypatch.setattr(CMP, "get_search_for", fake_get)
    rows = [{"qid": "q1", "record_id": "r1", "variant": "P", "question": "작년 시도별로 이사 간 사람 수", "gold": ["DT_1B26001"],
             "groups": {"G1": ["DT_1B26001"]}, "hop_type": "SINGLE", "reasoning_type": "", "subtype": "", "survey": "",
             "difficulty": ""}]
    an = {"q1": [{"unit": "main", "text": rows[0]["question"], "search_query": "이동자수 시도별", "filters": None}]}
    per, info = CMP.run(rows, an, ["hash"], False, 10, 50, log=lambda m: None,
                        ce={"mode": "replace", "top_n": 8, "doc": "struct"})
    assert {r["method"] for r in per} == {"search", "search+ce"} and calls
    mv = CMP.method_vs_base(per)
    assert {d["method"] for d in mv} == {"search+ce"} and {"hit@1", "mrr"} <= {d["metric"] for d in mv}
    table, fails, wins = CMP.summarize(per)
    md = CMP.report_md({"created": "x", "golden": "g", "n_rows": 1, "variants": ["P"], "analyze": "none",
                        "analysis_status": {}, "top_k": 10, "pool": 50, "dense": ["hash"], "configs": info},
                       table, fails, wins, per)
    assert "## 방법 비교" in md and "search+ce" in md
