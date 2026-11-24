"""빌드 전 골든셋 검사 (okf/gate.py) — 검색은 가짜 (빌드 해시마다 정해 둔 결과), 빌드·CURRENT 는 실제

  1) OKF_BUILD_OVERRIDE  build.current 가 그 빌드를 봄 ('-' = 없음) · 밖에서는 그대로
  2) load_run            이전 compare 실행의 설정 · 질의 분석 캐시만 씀 (캐시 없는 질문은 건너뜀 — HCX 안 부름)
  3) gate                잃은 질문 − 얻은 질문 > max_loss 또는 mrr 하락 > mrr_drop 이면 불합격 · 잃은 질문에 걸린 새 별칭
  4) build(gate=…)       불합격이면 새 빌드는 남고 CURRENT 는 그대로 · 합격이면 바뀜
"""
import hashlib
import json

from backend.rag.okf import build as B
from backend.rag.okf import gate as G
from tests.test_okf import concept, env  # noqa: F401 (pytest 픽스처)


def test_override_current(tmp_path, monkeypatch):
    root = tmp_path / "b"
    for h in ("aaa", "bbb"):
        (root / h).mkdir(parents=True)
        (root / h / "manifest.json").write_text("{}", encoding="utf-8")
    B.set_current(root, "aaa")
    monkeypatch.delenv(G.OVERRIDE_ENV, raising=False)
    with G.use_build("bbb"):
        assert B.current(root) == "bbb"
    with G.use_build(None):
        assert B.current(root) == ""
    with G.use_build("zzz"):          # 없는 빌드
        assert B.current(root) == ""
    assert B.current(root) == "aaa"


def _run(tmp_path, cached=("q1", "q2")):
    run = tmp_path / "run"
    run.mkdir()
    golden = tmp_path / "golden.jsonl"
    qs = {"q1": "서울 출생아 수", "q2": "부산 혼인 건수", "q3": "캐시 없는 질문"}
    golden.write_text("".join(json.dumps({"qid": q, "question": t, "required": [["DT_A"]]}, ensure_ascii=False) + "\n"
                              for q, t in qs.items()), encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"golden": str(golden), "variants": ["O"], "analyze": "analyze",
                                                 "today": "2026-11-23", "dense": ["none"], "raw_units": True}), encoding="utf-8")
    lines = []
    for q in cached:
        key = hashlib.sha1(f"analyze|2026-11-23|{qs[q]}".encode()).hexdigest()[:16]
        lines.append(json.dumps({"key": key, "question": qs[q], "units": [{"unit": "main", "search_query": qs[q], "filters": None}]},
                                ensure_ascii=False))
    (run / "analysis_cache.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run


def test_load_run_uses_cache_only(tmp_path):
    _cfg, rows, analysis, skipped = G.load_run(_run(tmp_path))
    assert [r["qid"] for r in rows] == ["q1", "q2"] and skipped == 1 and set(analysis) == {"q1", "q2"}


def _fake_eval(results):
    """{해시: {qid: (hit@5, mrr, rank)}} → evaluate 대신"""
    def ev(h, rows, analysis, cfg, log=print):
        return {r["qid"]: {"qid": r["qid"], "question": r["question"], "hit@5": results[h][r["qid"]][0],
                           "mrr": results[h][r["qid"]][1], "rank": results[h][r["qid"]][2]} for r in rows}
    return ev


def _builds(root, base_aliases, new_aliases):
    for h, al in (("base", base_aliases), ("new", new_aliases)):
        (root / h).mkdir(parents=True, exist_ok=True)
        (root / h / "manifest.json").write_text("{}", encoding="utf-8")
        (root / h / "concepts.json").write_text(json.dumps([{"id": "/concepts/x/birth.md", "aliases": al}], ensure_ascii=False),
                                                encoding="utf-8")


def test_gate_rule_and_alias_attribution(tmp_path, monkeypatch):
    run, root = _run(tmp_path), tmp_path / "okf_build"
    _builds(root, [], ["출생아"])
    monkeypatch.setattr(G, "evaluate", _fake_eval({"base": {"q1": (1, 1.0, 1), "q2": (1, 0.5, 2)},
                                                   "new": {"q1": (0, 0.1, 9), "q2": (1, 0.5, 2)}}))
    r = G.gate(root, "new", "base", run, log=lambda *_: None)
    assert not r["ok"] and r["n"] == 2 and r["skipped"] == 1
    assert r["lost"][0]["qid"] == "q1" and r["lost"][0]["aliases"] == ["출생아"] and r["lost"][0]["rank"] == [1, 9]
    assert r["aliases_added"] == {"출생아": ["/concepts/x/birth.md"]}
    assert G.gate(root, "new", "base", run, max_loss=1, mrr_drop=1.0, log=lambda *_: None)["ok"]
    # 하나 잃고 하나 얻으면 순손실 0 → mrr 이 크게 안 떨어지면 통과
    monkeypatch.setattr(G, "evaluate", _fake_eval({"base": {"q1": (1, 1.0, 1), "q2": (0, 0.1, 8)},
                                                   "new": {"q1": (0, 0.2, 6), "q2": (1, 1.0, 1)}}))
    assert G.gate(root, "new", "base", run, log=lambda *_: None)["ok"]


def test_build_keeps_current_when_gate_fails(env):  # noqa: F811
    b, root = env["bundle"], env["root"]
    m1 = B.build(b, root, env["prof"], None, log=lambda *_: None)
    assert m1["ok"] and B.current(root) == m1["hash"]
    concept(b, "x/single-mom", {"x-t4-concept": {"aliases": [{"text": "싱글맘"}], "binds": [
        {"table": "/tables/101/DT_1JC1516.md", "dim": "세대구성별", "code": "203", "name": "모+미혼자녀"}]}})
    seen = []
    m2 = B.build(b, root, env["prof"], None, log=lambda *_: None,
                 gate=lambda new, base: seen.append((new, base)) or {"ok": False, "lost": ["q1"]})
    assert not m2["ok"] and m2["gate"]["lost"] == ["q1"] and seen == [(m2["hash"], m1["hash"])]
    assert B.current(root) == m1["hash"] and (root / m2["hash"] / "manifest.json").exists()   # 새 빌드는 남음
    m3 = B.build(b, root, env["prof"], None, log=lambda *_: None, gate=lambda new, base: {"ok": True})
    assert m3["ok"] and m3["reused"] and B.current(root) == m2["hash"]


def test_gate_searcher_error_is_reported(tmp_path, monkeypatch):
    """검색기를 못 만들면 (compare.run 이 그 구성을 건너뛰어 빈 결과) 0 으로 나누지 않고 그 오류를 보여 줌"""
    from backend.rag.search.tuning import compare as C
    run = _run(tmp_path)
    monkeypatch.setattr(C, "run", lambda *a, **k: ([], {"search[hcx|okf-on]": {"error": "RuntimeError: HCX 임베딩 401"}}))
    _cfg, rows, analysis, _ = G.load_run(run)
    try:
        G.evaluate("base", rows, analysis, {"dense": ["hcx"]})
        raise AssertionError("오류가 나야 함")
    except RuntimeError as e:
        assert "HCX 임베딩 401" in str(e) and "base" in str(e)
    logs = []
    g = B._gate(lambda new, base: G.gate(tmp_path, new, base, run, log=lambda *_: None), "new", "base", logs.append)
    assert g["ok"] is False and "HCX 임베딩 401" in g["error"] and "검사를 못 함" in logs[0]
