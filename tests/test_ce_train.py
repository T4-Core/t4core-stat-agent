"""리랭커 미세조정 (tuning/ce_train.py) — 학습 묶음 만들기 · 오프라인 채점 · blend 가 추론(ce_rerank)과 같은 식인지 ·
(torch·transformers 가 있으면) 아주 작은 모델로 학습 고리가 돌고 손실이 줄어드는지"""
import pytest

from backend.rag.search import ce_rerank
from backend.rag.search.tuning import ce_train as T
from tests.test_search import Corpus


def _pipe():
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder
    return TableSearch(Corpus(), embedder=HashEmbedder(), facets_source="meta", llm_rerank=False)


def test_build_groups_labels_and_missing():
    pipe = _pipe()
    rows = [{"qid": "q1", "record_id": "r1", "split": "dev", "variant": "P", "question": "작년 시도별로 이사 간 사람 수",
             "gold": ["DT_1B26001"], "groups": {"G1": ["DT_1B26001"]}},
            {"qid": "q2", "record_id": "r2", "split": "heldout", "variant": "O", "question": "혼인건수",
             "gold": ["INH_03"], "groups": {"G1": ["INH_03"]}, "alt_groups": {"G1": ["DT_1B8000H"]}},
            {"qid": "q3", "record_id": "r3", "split": "dev", "variant": "O", "question": "외계인 수",
             "gold": ["NOPE"], "groups": {"G1": ["NOPE"]}}]
    units = {"작년 시도별로 이사 간 사람 수": [{"unit": "main", "search_query": "이동자수 시도별", "filters": None}]}
    g, skipped = T.build_groups(pipe, rows, units, top_n=8, doc="struct", set_name="t")
    assert skipped == 1 and [x["qid"] for x in g] == ["q1", "q2"]           # 정답이 코퍼스에 없는 문항은 버림
    q1 = g[0]
    assert sum(c["label"] for c in q1["cands"]) >= 1 and all(c["doc"].startswith(pipe.facets[c["tbl_id"]].tbl_nm)
                                                             for c in q1["cands"])
    q2 = {c["tbl_id"]: c["label"] for c in g[1]["cands"]}
    assert q2.get("INH_03") == 1 and q2.get("DT_1B8000H", 1) == 1             # 대체 정답(같은 값)도 정답
    # 정답이 후보 밖이면 붙임 (top_n=1 이라 후보에 없을 때)
    g2, _ = T.build_groups(pipe, rows[:1], units, top_n=1, doc="struct")
    if g2:
        assert any(c["label"] and c["base_rank"] is None for c in g2[0]["cands"]) or g2[0]["cands"][0]["label"]


def test_blend_matches_inference_and_metrics():
    cands = [{"tbl_id": f"T{i}", "base_rank": i + 1, "label": int(i == 3), "doc": f"d{i}"} for i in range(6)]
    sc = [0.1, 0.2, 0.0, 0.9, 0.3, 0.5]
    for k, w in ((1, 1.0), (5, 2.0), (20, 0.5)):
        mine = [cands[i]["tbl_id"] for i in T.blend_order(cands, sc, k, w)]
        hits = [{"rank": c["base_rank"], "tbl_id": c["tbl_id"], "score": 1.0, "stages": {}} for c in cands]
        from backend.rag.search.facets import Facet
        fac = {c["tbl_id"]: Facet(c["tbl_id"], c["tbl_id"], "조사") for c in cands}
        out, _ = ce_rerank.rerank("q", hits, fac, {"mode": "blend", "top_n": 6, "k": k, "weight": w, "doc": "struct"},
                                  score_fn=lambda q, t, keys: sc)
        assert mine == [h["tbl_id"] for h in out], (k, w)
    g = [{"question": "q", "cands": cands}]
    ev = T.evaluate(g, [sc])
    assert ev["base"]["hit@1"] == 0 and ev["ce"]["hit@1"] == 1 and ev["best"]["k"] in T.GRID_K
    assert T.metrics(g, [[3, 0, 1]])["mrr"] == 1.0 and T.metrics(g, [[0, 1, 3]])["mrr"] == round(1 / 3, 3)


def test_make_batches_shape():
    groups = [{"question": f"q{i}", "cands": [{"doc": f"p{i}", "label": 1, "base_rank": 3}]
               + [{"doc": f"n{i}-{j}", "label": 0, "base_rank": j + 1} for j in range(3)]} for i in range(5)]
    groups.append({"question": "only-pos", "cands": [{"doc": "p", "label": 1, "base_rank": 1}]})
    bs = T.make_batches(groups, negs=4, batch=2, seed=1)
    items = [x for b in bs for x in b]
    assert len(items) == 5 and all(len(docs) == 5 and docs[0].startswith("p") for _, docs in items)
    assert [len(b) for b in bs] == [2, 2, 1]


def test_train_loop_tiny_model():
    torch = pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    torch.manual_seed(0)
    model = tr.BertForSequenceClassification(tr.BertConfig(vocab_size=97, hidden_size=32, num_hidden_layers=1,
                                                           num_attention_heads=2, intermediate_size=64, num_labels=1))

    class Enc(dict):
        def to(self, device):
            return Enc({k: v.to(device) for k, v in self.items()})

    def tok(qs, ds, truncation=True, max_length=32, padding=True, return_tensors="pt"):
        seqs = [[1] + [ord(c) % 90 + 5 for c in q][:8] + [2] + [ord(c) % 90 + 5 for c in d][:20] for q, d in zip(qs, ds)]
        n = max(map(len, seqs))
        ids = torch.tensor([s + [0] * (n - len(s)) for s in seqs])
        return Enc(input_ids=ids, attention_mask=(ids > 0).long())
    # 정답 글에는 늘 'AAAA', 오답에는 'zzzz' — 작은 모델도 배울 수 있는 신호
    def grp(i):  # 후보는 원래 순위 순서 — 정답이 꼴찌(5위)
        return {"question": f"질문{i}", "split": "dev",
                "cands": [{"doc": f"zzzz{i}{j}", "label": 0, "base_rank": j + 1} for j in range(4)]
                + [{"doc": f"AAAA{i}", "label": 1, "base_rank": 5}]}
    groups = [grp(i) for i in range(24)]
    held = [grp(100 + i) for i in range(6)]
    saved = []
    cfg = {"epochs": 8, "lr": 5e-3, "negs": 3, "batch": 4, "max_length": 32, "accum": 1, "fp16": False, "warmup": 0.1}
    hist = T.train_loop(model, tok, groups, held, cfg, "cpu", log=lambda m: None,
                        save=lambda m, t, ep, rep: saved.append((ep, rep)))
    assert hist[-1]["loss"] < 0.5 * hist[1]["loss"]                           # 손실이 크게 줄고
    assert hist[0]["heldout"]["base"]["hit@1"] == 0 and hist[-1]["heldout"]["ce"]["hit@1"] == 1.0
    # heldout 이 학습 전보다 나아진 에폭만 저장 (학습 전이 이미 만점이면 저장하지 않음)
    pre = hist[0]["heldout"]["blend"]["mrr"]
    assert bool(saved) == any(h["heldout"]["blend"]["mrr"] > pre for h in hist[1:])


def test_build_and_eval_commands(tmp_path, monkeypatch, capsys):
    import argparse
    import json

    from backend.rag.search.tuning import compare as C
    run = tmp_path / "runs" / "20261118_000000_hard"
    run.mkdir(parents=True)
    gold = tmp_path / "g.jsonl"
    rec = {"dataset_id": "SG-1", "answerability_type": "ANSWERABLE", "question_original": "시도별 이동자수",
           "question_paraphrased": "작년 시도별로 이사 간 사람 수",
           "retrieval_eval": {"golden_table_ids": ["DT_1B26001"],
                              "required_evidence_groups": {"G1": {"acceptable_table_ids": ["DT_1B26001"]}}}}
    gold.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"golden": str(gold), "variants": ["O", "P"]}), encoding="utf-8")
    (run / "analysis_cache.jsonl").write_text(json.dumps({"key": "k", "question": "시도별 이동자수", "units": [
        {"unit": "main", "search_query": "이동자수 시도별", "filters": None}]}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(C, "_runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(C, "get_search_for", lambda dense="hcx", llm=False, settings=None: _pipe())
    monkeypatch.setattr(T, "DATA_DIR", tmp_path / "ce_train")
    T.cmd_build(argparse.Namespace(from_run=["hard"], dense="hash", dense_docs="rule", top_n=6, doc="struct",
                                   no_add_missing=False, name="v0"))
    gs = T.load_groups("v0")
    assert len(gs) == 2 and {g["variant"] for g in gs} == {"O", "P"}
    meta = json.loads((tmp_path / "ce_train" / "v0" / "meta.json").read_text(encoding="utf-8"))
    assert meta["sets"]["20261118_000000_hard"]["no_cache"] == 1              # P 질문은 캐시가 없어 원문으로
    monkeypatch.setattr(ce_rerank, "scores", lambda q, docs, cfg, keys=None: [float("이동" in d) for d in docs])
    T.cmd_eval(argparse.Namespace(data="v0", model="fake", max_length=128))
    out = capsys.readouterr().out
    assert "원래 순위 Hit@1" in out and "--ce-model fake --ce-k" in out


def test_freeze_top_layers():
    pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    m = tr.XLMRobertaForSequenceClassification(tr.XLMRobertaConfig(vocab_size=200, hidden_size=16, num_hidden_layers=4,
                                                                   num_attention_heads=2, intermediate_size=32, num_labels=1))
    T.freeze(m, train_layers=1)
    on = {n.split(".")[3] if n.startswith("roberta.encoder.layer.") else n.split(".")[0]
          for n, p in m.named_parameters() if p.requires_grad}
    assert on == {"3", "classifier"}                                          # 맨 위 층 + 분류 머리만
    m2 = tr.XLMRobertaForSequenceClassification(m.config)
    T.freeze(m2, 0, True)
    assert not any(p.requires_grad for p in m2.roberta.embeddings.parameters())
    assert all(p.requires_grad for p in m2.roberta.encoder.parameters())


def test_adafactor_default_lr_moves_weights():
    torch = pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    if not hasattr(torch.optim, "Adafactor"):
        pytest.skip("torch.optim.Adafactor 없음")
    torch.manual_seed(0)
    m = tr.BertForSequenceClassification(tr.BertConfig(vocab_size=97, hidden_size=32, num_hidden_layers=2,
                                                       num_attention_heads=2, intermediate_size=64, num_labels=1))

    class Enc(dict):
        def to(self, device):
            return Enc({k: v.to(device) for k, v in self.items()})

    def tok(qs, ds, **kw):
        seqs = [[1] + [ord(c) % 90 + 5 for c in q + d][:24] for q, d in zip(qs, ds)]
        n = max(map(len, seqs))
        ids = torch.tensor([s + [0] * (n - len(s)) for s in seqs])
        return Enc(input_ids=ids, attention_mask=(ids > 0).long())
    groups = [{"question": f"q{i}", "split": "dev", "cands": [{"doc": f"n{i}{j}", "label": 0, "base_rank": j + 1}
                                                             for j in range(3)] + [{"doc": f"P{i}", "label": 1, "base_rank": 4}]}
              for i in range(12)]
    logs = []
    hist = T.train_loop(m, tok, groups, [], {"epochs": 1, "lr": None, "optimizer": "adafactor", "negs": 2, "batch": 2,
                                             "max_length": 32, "accum": 1, "fp16": False, "log_every": 0},
                        "cpu", log=logs.append)
    assert "학습률 0.001" in " ".join(logs) and hist[-1]["moved"] > 1e-4
