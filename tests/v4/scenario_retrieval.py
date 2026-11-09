"""[NEW v4] 검색 실험실 시나리오 — tests/v4/test_retrieval_lab.py 가 별도 프로세스로 실행

① baseline 구성 = 기존 table_search.search (재작성 80문항 전체 검색 단위 + 슬롯 없는 질문, 같은 순위·점수)
② 모든 구성 YAML 이 조립·검색됨 (sentence-transformers 는 가짜 모듈로 대신 — 모델 내려받기 없음)
③ extends · 점 경로 overrides · inline 구성 · register 로 새 리랭커
④ API: configs · search(trace) · compare(보고서·판정표) · 판정 → 점수 · blind · 파일 경로 제한
⑤ /rag/views?retrieval_config=… (구성으로 View 까지) — 지정 안 하면 기존과 같음
"""
import csv
import importlib.machinery
import json
import sys
import time
import types
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import backend.core.llm as llm
import backend.rag.retrieval.dense as dense
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post
dense._post = fake_kosis.fake_dense_post

# ── 가짜 sentence_transformers (SentenceTransformer · CrossEncoder) ──
ST_CALLS = {"encode": 0, "predict": 0, "device": None, "model": None}


def _bigrams(t):
    t = "".join(str(t).split())
    return {t[i:i + 2] for i in range(len(t) - 1)}


class FakeST:
    def __init__(self, name, device="cpu", trust_remote_code=False, **kw):
        ST_CALLS.update(device=device, model=name)
        self.max_seq_length = 512

    def half(self):
        return self

    def encode(self, texts, batch_size=16, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        ST_CALLS["encode"] += len(texts)
        out = np.zeros((len(texts), 64), dtype=np.float32)
        for i, t in enumerate(texts):
            for g in _bigrams(t):
                out[i, hash(g) % 64] += 1
        return out + 1e-3


class FakeCE:
    def __init__(self, name, max_length=512, device="cpu", trust_remote_code=False):
        ST_CALLS.update(device=device, model=name)

    def predict(self, pairs, batch_size=16, show_progress_bar=False):
        ST_CALLS["predict"] += len(pairs)
        return np.array([len(_bigrams(q) & _bigrams(d)) / max(len(_bigrams(q)), 1) * 10 - 5 for q, d in pairs])


st = types.ModuleType("sentence_transformers")
st.SentenceTransformer, st.CrossEncoder = FakeST, FakeCE
st.__spec__ = importlib.machinery.ModuleSpec("sentence_transformers", None)
sys.modules["sentence_transformers"] = st

from backend.core.config import RUNS_DIR  # noqa: E402
from backend.main import app  # noqa: E402
from backend.rag.ingestion.resolve import search_query  # noqa: E402
from backend.rag.retrieval import factory, lab  # noqa: E402
from backend.rag.retrieval.fusion import fuse_rrf, fuse_weighted  # noqa: E402
from backend.rag.retrieval.table_search import search as old_search  # noqa: E402
from backend.rag.retrieval.tokenizers import CharNgramTokenizer, WhitespaceTokenizer  # noqa: E402

c = TestClient(app)


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:1500]}"
    return r.json()


# ⓪ 준비: 메타 프로필 → 표 색인 (18개) + CSV 값 사전
ok(c.post("/api/v1/rag/chunk-and-index"))
for _ in range(200):
    s = ok(c.get("/api/v1/rag/chunk-and-index/status"))
    if not s["running"]:
        break
    time.sleep(0.2)
assert s["error"] is None and s["result"]["index"]["n_tables"] == 18, s
ok(c.post("/api/v1/csv-index/build", json={"scope": "all", "workers": 2}))
print("[⓪] 표 색인:", s["result"]["index"]["n_tables"])

# ① baseline = 기존 검색 (같은 순위·점수·unmet)
base = factory.get_pipeline("baseline")
units = lab.load_queries("bundles")
assert len(units) >= 80, len(units)
n_same = 0
for u in units:
    a = old_search(u["search_query"], 10, filters=u["filters"])
    b = base.search_compat(u["search_query"], 10, filters=u["filters"])
    assert a == b, (u["id"], u["search_query"], [x["tbl_id"] for x in a], [x["tbl_id"] for x in b])
    n_same += 1
gold = lab.load_queries("golden")
for u in gold:                                                      # 슬롯 없음 (filters=None 경로)
    assert old_search(u["search_query"], 10) == base.search_compat(u["search_query"], 10), u["id"]
    n_same += 1
assert base.retrievers[0].fit_info["tokens"] == "corpus index"     # 색인 때 저장한 kiwi 토큰 그대로
print(f"[①] baseline == table_search.search: {n_same}건 (재작성 단위 {len(units)} + 원문 {len(gold)})")

# ① -2 View 까지: run_query(search_fn=baseline) == run_query()
from backend.rag.ingestion.views import records_of, run_query  # noqa: E402
from backend.rag.query_analyzer.adapter import to_view_bundle  # noqa: E402
bundles = json.loads(Path(lab.BUNDLES_PATH).read_text(encoding="utf-8"))
for b in bundles[:2]:
    vb, _ = to_view_bundle(b, query_id="pq")
    r1, r2 = records_of(run_query(vb)), records_of(run_query(vb, search_fn=base.search_compat))
    assert [x["id"] for x in r1] == [x["id"] for x in r2] and [x["source"] for x in r1] == [x["source"] for x in r2]

# ② 모든 구성 YAML
names = factory.list_config_names()
assert {"baseline", "bm25_only", "kiwi_lexicon", "char_ngram", "hybrid_rrf_hcx", "ensemble_rrf", "csv_index_corpus",
        "st_bge_m3", "st_e5_hybrid", "rerank_bge_v2_m3", "offline_hash"} <= set(names), names
F = {"시점": [2025], "지역": ["전국"], "대상": ["1인가구"], "지표": ["가구수"], "의도": "값 조회"}
q = search_query("2025년 전국 1인가구 가구수", F)
got = {}
for n in names:
    r = factory.get_pipeline(n).search(q, F, 5)
    assert [h["rank"] for h in r["hits"]] == list(range(1, len(r["hits"]) + 1)) and r["hits"], n
    got[n] = r
    print(f"    {n:18s} → {[h['tbl_id'] for h in r['hits']]}")
assert set(got["ensemble_rrf"]["hits"][0]["stages"]) >= {"bm25_kiwi", "bm25_char", "dense", "fuse", "condition", "embed",
                                                         "rrf_stages"}, got["ensemble_rrf"]["hits"][0]["stages"]
ce = got["rerank_bge_v2_m3"]["hits"]
assert all("ce" in h for h in ce) and [h["cost"] for h in ce] == sorted(h["cost"] for h in ce)   # respect_cost
assert ST_CALLS["encode"] > 0 and ST_CALLS["predict"] > 0 and ST_CALLS["device"] == "cpu"
lex = factory.get_pipeline("kiwi_lexicon").retrievers[0].tok
assert lex.id != "kiwi:table" and "1인가구" in lex("1인가구 가구수"), lex("1인가구 가구수")       # CSV 값 사전 단어 등록
ct = factory.get_pipeline("csv_index_corpus").docs_by_id["DT_X001"].text
assert "항목: 출생아수, 합계출산율" in ct and "단위:" in ct and "기간: 2021~2025" in ct, ct
assert got["hybrid_rrf_hcx"]["hits"][0]["stages"].get("fuse"), got["hybrid_rrf_hcx"]["hits"][0]
print(f"[②] 구성 {len(names)}개 조립·검색 (가짜 ST encode {ST_CALLS['encode']}, CE predict {ST_CALLS['predict']})")

# 캐시: 같은 구성은 같은 파이프라인, 토큰 디스크 캐시
assert factory.get_pipeline("baseline") is base
assert factory.get_pipeline("char_ngram").retrievers[0].fit_info["tokens"] == "computed"
factory.clear_cache()
assert factory.get_pipeline("char_ngram").retrievers[0].fit_info["tokens"] == "disk cache"

# ③ extends · overrides · inline · register
cfg = factory.load_config("bm25_only")
assert cfg["extends"] == "baseline" and [r["type"] for r in cfg["rerank"]] == ["condition"]
cfg = factory.load_config("baseline", {"rerank.0.top_n": 5, "top_k": 3, "retrievers.0.k": 20})
assert cfg["rerank"][0]["top_n"] == 5 and cfg["top_k"] == 3 and cfg["retrievers"][0]["k"] == 20
from backend.core.tracking import Tracer  # noqa: E402
tr = Tracer("t")
r = factory.get_pipeline(cfg).search(q, F, tracer=tr)
steps = {s["step"]: s for s in r["trace"]}
assert len(r["hits"]) == 3 and steps["rerank:condition"]["output"]["n_out"] == 5 and steps["retrieve:bm25"]["params"]["k"] == 20


@factory.register("reranker", "reverse")
class Reverse:
    def __init__(self, top_n=None, name="reverse"):
        self.top_n, self.name = top_n, name

    def rerank(self, query, cands, ctx):
        return list(reversed(cands))


inline = {"name": "rev", "extends": "bm25_only", "rerank": [{"type": "condition", "top_n": "top_k"}, {"type": "reverse"}]}
a = [h["tbl_id"] for h in factory.get_pipeline("bm25_only").search(q, F, 5)["hits"]]
b = [h["tbl_id"] for h in factory.get_pipeline(inline).search(q, F, 5)["hits"]]
assert b == a[::-1], (a, b)
try:
    factory.build_pipeline({"retrievers": [{"type": "bm25", "tokenizer": {"type": "nope"}}]})
    raise AssertionError("알 수 없는 type 이 통과됨")
except ValueError as e:
    assert "가능:" in str(e) and "kiwi" in str(e)
assert [i for i, _ in fuse_rrf({"a": [(1, 9), (2, 5)], "b": [(2, 1), (3, 0)]})] == [2, 1, 3]
assert [i for i, _ in fuse_weighted({"a": [(1, 9), (2, 5)], "b": [(2, 1), (3, 0)]}, weights={"a": 1, "b": 2})][0] == 2
assert CharNgramTokenizer()("출생아 수") == ["출생", "생아", "출생아", "수"] and WhitespaceTokenizer()("A|b c") == ["a", "b", "c"]
print("[③] extends · overrides · inline · register · fusion · tokenizers")

# ④ API
cl = ok(c.get("/api/v1/retrieval-lab/configs"))
assert len(cl) == len(names) and not any(x["error"] for x in cl) and not any(x["missing"] for x in cl), cl
assert ok(c.get("/api/v1/retrieval-lab/configs/bm25_only"))["extends"] == "baseline"
assert c.get("/api/v1/retrieval-lab/configs/nope").status_code == 409
r = ok(c.post("/api/v1/retrieval-lab/search", json={"query": "2025년 전국 1인가구 가구수", "filters": F, "prep": "resolve",
                                                     "config": "baseline"}))
assert r["search_query"] == q and [h["tbl_id"] for h in r["hits"]] == [x["tbl_id"] for x in old_search(q, 10, filters=F)]
assert [t["step"] for t in r["trace"]] == ["query", "retrieve:bm25", "rerank:condition", "rerank:embed"], r["trace"]
assert r["pipeline"]["n_docs"] == 18 and r["hits"][0]["stages"]["embed"]["rank"] == 1
r = ok(c.post("/api/v1/retrieval-lab/search", json={"query": q, "filters": F, "config_inline": inline, "top_k": 4}))
assert [h["tbl_id"] for h in r["hits"]] == a[:4][::-1]

bad = {"name": "broken", "retrievers": [{"type": "bm25", "tokenizer": {"type": "nope"}}]}
cmp = ok(c.post("/api/v1/retrieval-lab/compare", json={"source": "bundles", "limit": 4, "top_k": 5,
                                                         "configs": ["baseline", "bm25_only", "hybrid_rrf_hcx", bad]}))
assert next(x for x in cmp["configs"] if x["name"] == "broken")["error"].startswith("ValueError")
assert set(cmp["summary"]) == {"baseline", "bm25_only", "hybrid_rrf_hcx"} and cmp["reference"] == "baseline"
assert "vs_baseline" in cmp["summary"]["bm25_only"] and cmp["n_queries"] >= 4
html = c.get(cmp["report_url"])
assert html.status_code == 200 and "검색 구성 비교" in html.text and cmp["queries"][0]["results"]["baseline"]["hits"][0]["tbl_id"] in html.text
rv = c.get(cmp["review_url"])
assert rv.status_code == 200 and rv.text.lstrip("﻿").startswith("query_id,question")
run_dir = Path(RUNS_DIR) / cmp["run_id"]
assert {"params.json", "summary.json", "results.jsonl", "review.csv", "report.md", "report.html"} <= {p.name for p in run_dir.iterdir()}

# 사람 판정: 질의마다 baseline 1위만 2, 나머지 0 → baseline hit1 = 1
top1 = {q_["id"]: q_["results"]["baseline"]["hits"][0]["tbl_id"] for q_ in cmp["queries"]}
with (run_dir / "review.csv").open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
assert all(r_["found_by"] for r_ in rows) and len({(r_["query_id"], r_["tbl_id"]) for r_ in rows}) == len(rows)   # (질의, 표) 한 줄
for r_ in rows:
    r_["label"] = "O" if top1[r_["query_id"]] == r_["tbl_id"] else "X"
with (run_dir / "review.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, list(rows[0]))
    w.writeheader()
    w.writerows(rows)
sc = ok(c.post(f"/api/v1/retrieval-lab/runs/{cmp['run_id']}/score", json={}))
assert sc["by_config"]["baseline"]["hit1"] == 1.0 and sc["by_config"]["baseline"]["mrr"] == 1.0, sc
assert sc["by_config"]["baseline"]["judged"] == 1.0 and sc["n_labeled_queries"] == len(top1)
first = cmp["queries"][0]
sc2 = ok(c.post(f"/api/v1/retrieval-lab/runs/{cmp['run_id']}/score",
                json={"judgments": [{"query_id": first["id"], "tbl_id": first["results"]["bm25_only"]["hits"][0]["tbl_id"],
                                     "label": 2}]}))
assert sc2["by_config"]["bm25_only"]["hit1"] == 1.0 and sc2["n_labels"] == 1
sc3 = ok(c.post(f"/api/v1/retrieval-lab/runs/{cmp['run_id']}/score",       # 숫자 0 도 판정으로 셈
                json={"judgments": [{"query_id": r_["query_id"], "tbl_id": r_["tbl_id"], "label": 2 if r_["label"] == "O" else 0}
                                    for r_ in rows]}))
assert sc3["n_labels"] == len(rows) and sc3["by_config"]["baseline"]["judged"] == 1.0, sc3

bl = ok(c.post("/api/v1/retrieval-lab/compare", json={"queries": [{"id": "G1", "search_text": q, "filters": F, "prep": False,
                                                                   "gold": [top1[first["id"]]]}],
                                                       "configs": ["baseline", "bm25_only"], "blind": True, "top_k": 5}))
assert bl["labels"] == {"baseline": "A", "bm25_only": "B"} and (Path(RUNS_DIR) / bl["run_id"] / "key.json").exists()
assert "gold" in bl["summary"]["baseline"] and "A#" in (Path(RUNS_DIR) / bl["run_id"] / "review.csv").read_text(encoding="utf-8-sig")
assert c.post("/api/v1/retrieval-lab/compare", json={"source": "/etc/passwd", "configs": ["baseline"]}).status_code == 400
assert c.get("/api/v1/retrieval-lab/runs/..%2Fx/report").status_code in (400, 404)
print(f"[④] API compare {cmp['run_id']} (질의 {cmp['n_queries']}) · 판정 점수 · blind · 경로 제한")

# ⑤ /rag/views?retrieval_config=
vb, _ = to_view_bundle(bundles[0], query_id="rv")
v0 = ok(c.post("/api/v1/rag/views", json=vb))
v1 = ok(c.post("/api/v1/rag/views", params={"retrieval_config": "baseline"}, json=vb))
assert [x["id"] for x in v0] == [x["id"] for x in v1] and v0
v2 = ok(c.post("/api/v1/rag/views/detail", params={"retrieval_config": "offline_hash", "n_views": 1}, json=vb))
assert v2["units"][0]["candidates"] and len(v2["units"][0]["views"]) <= 1
print("[⑤] /rag/views?retrieval_config= (지정 안 하면 기존과 같음)")

print(json.dumps({"RETRIEVAL_LAB": "PASS", "parity": n_same, "configs": len(names)}, ensure_ascii=False))
