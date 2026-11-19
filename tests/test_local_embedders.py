"""로컬 임베딩 모델 (search/embedders.py) — 진짜 모델 없이 가짜 sentence_transformers 로 연결만 확인

  · arctic-ko 는 질문에만 prompt_name='query', 문서는 그대로 / bge-m3-ko 는 둘 다 그대로
  · ens-ko 의 내적 = 두 모델 코사인의 평균, 단일 모델과 같은 인스턴스·문서 캐시를 씀
  · --dense 이름으로 검색(TableSearch)이 돈다
"""
import hashlib
import sys
import types

import numpy as np
import pytest

CALLS = []


class FakeST:
    def __init__(self, model_id, device=None, **kw):
        self.model_id, self.max_seq_length = model_id, 512
        self.prompts = {"query": "query: "} if "arctic" in model_id else {}

    def encode(self, texts, prompt_name=None, normalize_embeddings=False, convert_to_numpy=True, batch_size=8,
               show_progress_bar=False):
        prefix = self.prompts.get(prompt_name, "") if prompt_name else ""
        CALLS.append((self.model_id, prompt_name, list(texts)))
        out = []
        for t in texts:
            seed = int(hashlib.md5(f"{self.model_id}|{prefix}{t}".encode()).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).normal(size=16).astype(np.float32)
            out.append(v / np.linalg.norm(v) if normalize_embeddings else v)
        return np.vstack(out)


@pytest.fixture()
def emb(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST))
    from backend.rag.search import embedders, index
    monkeypatch.setattr(index, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(embedders, "_instances", {})
    CALLS.clear()
    return embedders


def test_query_prompt_only_for_arctic(emb):
    a, b = emb.local_embedder("arctic-ko"), emb.local_embedder("bge-m3-ko")
    a.embed_queries(["서울 인구"])
    a.embed_docs(["표 설명"])
    b.embed_queries(["서울 인구"])
    assert CALLS[0][:2] == ("dragonkue/snowflake-arctic-embed-l-v2.0-ko", "query")
    assert CALLS[1][:2] == ("dragonkue/snowflake-arctic-embed-l-v2.0-ko", None)
    assert CALLS[2][:2] == ("dragonkue/BGE-m3-ko", None)
    assert a.model().max_seq_length == 2048                     # EMBED_MAX_LEN 기본


def test_ensemble_is_mean_cosine_and_reuses_members(emb):
    a, b, e = (emb.local_embedder(n) for n in ("arctic-ko", "bge-m3-ko", "ens-ko"))
    assert e.members[0] is a and e.members[1] is b             # 같은 모델 인스턴스
    docs, q = ["출생아수 표", "혼인건수 표", "인구 표"], ["작년 출생아 수"]
    want = ((a.embed_docs(docs) @ a.embed_queries(q)[0]) + (b.embed_docs(docs) @ b.embed_queries(q)[0])) / 2
    n = len(CALLS)
    got = e.embed_docs(docs) @ e.embed_queries(q)[0]
    assert np.allclose(got, want, atol=1e-6)
    assert len(CALLS) == n                                      # 문서·질문 모두 캐시에서 (모델을 다시 돌리지 않음)


def test_doc_cache_survives_new_instance(emb, monkeypatch):
    emb.local_embedder("bge-m3-ko").embed_docs(["a", "b"])
    monkeypatch.setattr(emb, "_instances", {})
    n = len(CALLS)
    emb.local_embedder("bge-m3-ko").embed_docs(["a", "b"])
    assert len(CALLS) == n                                      # 파일 캐시
    emb.local_embedder("bge-m3-ko").embed_docs(["a", "c"])
    assert len(CALLS) == n + 1                                  # 문서가 바뀌면 다시


def test_dense_names_and_search(emb):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import dense_names, embedder
    assert {"hcx", "arctic-ko", "bge-m3-ko", "ens-ko", "none"} <= set(dense_names())
    with pytest.raises(ValueError):
        embedder("nope")
    from tests.test_search import Corpus
    for name in ("arctic-ko", "bge-m3-ko", "ens-ko"):
        s = TableSearch(Corpus(), name=f"search[{name}]", embedder=embedder(name), facets_source="meta", llm_rerank=False)
        hits = s.search("2023년 시도별 혼인건수", None, 5, question="2023년 시도별 혼인건수", today="2026-11-12")["hits"]
        assert len(hits) == 5 and all(h["dense"] is not None for h in hits), (name, hits[:1])
