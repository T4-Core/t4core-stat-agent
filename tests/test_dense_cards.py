"""dense 카드 (ingestion/dense_cards.py) · dense 문서 묶음 (index.dense_doc_views) · compare 의 dense 문서 비교 — 저장소·HCX 없이

  · 코드 템플릿: 슬롯 정규문이 질문 쪽 렌더러 모양, 정의문에 연도·지역 이름 없음, 구분은 메타데이터 차이로
  · LLM 결과 검사: 재료에 없는 슬롯 값 · 연도 · 지역 이름 · 비슷한 표의 말 · 금지 표현 문장을 버림
  · 재료가 같으면 다시 만들지 않음 · 검색이 slot+def(+rw) 로 돌고 표마다 최댓값 · compare 가 문서 구성을 나란히
"""
import json

import numpy as np
import pytest

from backend.rag.ingestion import dense_cards as dc
from tests.test_search import Corpus


@pytest.fixture(scope="module")
def builder():
    # 이 PC 의 CSV 값 사전·메타 프로필을 읽지 않게 (테스트 코퍼스의 프로필만)
    docs = Corpus().docs()
    return dc.Builder(docs, profiles={d.id: d.meta["profile"] for d in docs}, csv_tables={}, log=lambda m: None,
                      facets_source="meta")


def test_template_card_shapes(builder):
    c = builder.card("DT_1GA9008", use_llm=False)
    assert c["mode"] == "tmpl" and c["slot_text"] == c["tslot_text"] and c["def_text"] == c["tmpl_text"]
    assert c["slot_text"].startswith("가구 일반가구 점유형태별 시도별 | ")       # 슬롯 순서 = slots_to_sentence
    assert "구분: 가구주의 연령 · 시도 단위" in c["def_text"]                  # 시군구판 형제와의 차이 (코드)
    for t in (c["slot_text"], c["def_text"]):
        assert not dc.YEAR_RE.search(t) and "서울" not in t and "부산" not in t


def test_period_paren_removed_and_sex_restriction(builder):
    c = builder.card("TX_A011", use_llm=False)                                   # '…유학생(계)(2008~2015)'
    assert "2008" not in c["slot_text"] + c["def_text"]
    f = builder.facets["DT_1BZ05011"]
    s = dc.template_slots(f, {}, builder.vocab)
    assert "자료=장래가구추계" in s["조건"] and "추계가구" in s["지표"]          # 항목이 연령 값뿐이면 제목 끝 덩어리
    assert "장래 추계(전망)" in builder.card("DT_1BZ05011", use_llm=False)["def_text"]


def test_title_segments_and_distinct(builder):
    assert set(dc.title_segments("시도/가구주의 연령/거처의 점유형태별 가구").values()) == {"가구주의 연령", "거처의 점유형태", "가구"}
    assert set(dc.title_segments("시도/전입사유별 이동자수").values()) == {"전입사유", "이동자수"}
    labels, banned = dc.distinct(builder.facets["DT_1B26001"], builder.nbs["DT_1B26001"], builder.facets,
                                 builder.profiles, builder.vocab)
    assert "월간 자료" in labels and "전입사유" not in " ".join(labels)       # 이웃에만 있는 말은 구분에 넣지 않음
    assert "전입사유" in banned


def test_llm_output_is_checked(builder):
    seen = []

    def fake(messages, schema=None, **kw):
        seen.append(messages[1]["content"])
        return {"slots": {"대상": ["가구", "외계인"], "지표": ["일반가구수"], "조건": ["초혼"], "이동": [],
                          "비교축": ["점유형태"], "성별": ["남자"], "연령": []},
                "정의": "인구총조사에서 일반가구를 거처의 종류와 점유형태별로 집계한 연간 실적 통계다. 서울과 부산의 가구도 포함된다. "
                        "1990년 자료이다. 다른 표와 달리 시군구 단위로 볼 수 있다. 우주선 행성 은하도 다룬다."}
    c = builder.card("DT_1GA9009", True, fake)
    assert c["mode"] == "llm"
    assert "가구주의 연령" not in seen[0]                                         # 비슷한 표의 이름은 LLM 에게 주지 않음
    assert "일반가구수" in c["slots"]["지표"]                                      # '수' 를 뗀 말이 재료에 있으면 통과
    assert "외계인" not in c["slot_text"] and not c["slots"]["성별"]
    body = c["def_text"].split("\n")[-1]
    assert body == "인구총조사에서 일반가구를 거처의 종류와 점유형태별로 집계한 연간 실적 통계다."
    fl = " ".join(c["flags"])
    for why in ("지역 이름", "연도", "금지 표현", "모르는 말"):
        assert why in fl, c["flags"]


def test_llm_failure_falls_back(builder):
    c = builder.card("INH_03", True, lambda *a, **k: {"_raw": "not json"})
    assert c["mode"] == "llm_error" and c["def_text"] == c["tmpl_text"]
    c2 = builder.card("INH_03", True, lambda *a, **k: {"slots": {}, "정의": "서울 1990년"})
    assert "def_fallback" in c2["flags"] and c2["def_text"] == c2["tmpl_text"]


def test_build_is_incremental(tmp_path, builder):
    out = tmp_path / "cards.jsonl"
    calls = []

    def fake(messages, schema=None, **kw):
        calls.append(1)
        return {"slots": {}, "정의": "통계다."}
    dc.build(builder.docs, out, use_llm=True, limit=3, chat_fn=fake, builder=builder, log=lambda m: None)
    assert len(calls) == 3 and len(dc.load_cards(out)) == 3
    dc.build(builder.docs, out, use_llm=True, limit=3, chat_fn=fake, builder=builder, log=lambda m: None)
    assert len(calls) == 3                                                       # 재료 해시가 같으면 다시 부르지 않음
    st = dc.stats(dc.load_cards(out), builder)
    assert st["coverage"] == f"3/{len(builder.docs)}" and st["stale"] == 0


@pytest.fixture()
def cards_file(tmp_path, builder, monkeypatch):
    from backend.rag.search import index
    monkeypatch.setattr(index, "CACHE_DIR", tmp_path / "cache")
    out = tmp_path / "cards.jsonl"
    dc.build(builder.docs, out, use_llm=False, builder=builder, log=lambda m: None)
    return out


def test_dense_doc_views_and_max(cards_file, tmp_path):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder, dense_doc_views, parse_docs
    assert parse_docs("slot+def+rw") == ([["slot", "def"]], True) and parse_docs(None) == ([["rule"]], False)
    assert parse_docs("rule,def+vals") == ([["rule"], ["def", "vals"]], False)
    with pytest.raises(ValueError):
        parse_docs("card")
    c = Corpus()
    views = dense_doc_views(c, "rule+tslot", cards_file)
    assert list(views) == ["rule", "tslot"] and views["rule"][0] == c.docs()[0].text
    k14 = tmp_path / "k14.jsonl"
    k14.write_text(json.dumps({"tbl_id": "INH_03", "dense_text": "혼인 카드"}, ensure_ascii=False) + "\n", encoding="utf-8")
    kv = dense_doc_views(c, "kos14", kos14=k14)["kos14"]
    assert kv[[d.id for d in c.docs()].index("INH_03")] == "혼인 카드" and kv[0] == c.docs()[0].text  # 없는 표는 설명문
    s = TableSearch(c, embedder=HashEmbedder(), facets_source="meta", llm_rerank=False,
                    settings={"dense_docs": "slot+def+rw", "dense_cards": str(cards_file)})
    q = "시도별 이동자수"
    one = [TableSearch(c, embedder=HashEmbedder(), facets_source="meta", llm_rerank=False,
                       settings={"dense_docs": v, "dense_cards": str(cards_file)}).ch.dense.scores(q) for v in ("slot", "def")]
    assert np.allclose(s.ch.dense.scores(q), np.maximum(*one))
    prep = s.prepare("이동자수 시도별", None, "작년 시도별 이사 간 사람 수", "main", "2026-11-12")
    assert "rw_dense" in prep["scores"] and "q_dense" in prep["scores"]
    base = TableSearch(c, embedder=HashEmbedder(), facets_source="meta", llm_rerank=False)
    assert "rw_dense" not in base.prepare("이동자수 시도별", None, "작년 시도별 이사 간 사람 수", "main", "2026-11-12")["scores"]
    assert base.dense_scores("이동자수 시도별", "작년 시도별 이사 간 사람 수")["rw"] is None


def test_compare_runs_doc_arms(cards_file, monkeypatch):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder
    from backend.rag.search.tuning import compare as C

    def fake_get(dense="hcx", llm=False, settings=None):
        return TableSearch(Corpus(), name=f"t[{dense}]", embedder=HashEmbedder(), facets_source="meta", llm_rerank=False,
                           settings=settings)
    monkeypatch.setattr(C, "get_search_for", fake_get)
    rows = [{"qid": "q1", "record_id": "r1", "variant": "P", "question": "작년 시도별로 이사 간 사람 수", "gold": ["DT_1B26001"],
             "groups": {"G1": ["DT_1B26001"]}, "hop_type": "SINGLE", "reasoning_type": "", "subtype": "", "survey": "",
             "difficulty": ""},
            {"qid": "q2", "record_id": "r2", "variant": "P", "question": "시도별 결혼 건수", "gold": ["INH_03"],
             "groups": {"G1": ["INH_03"], "G2": ["DT_1B8000H"]}, "hop_type": "MULTI_2", "reasoning_type": "", "subtype": "",
             "survey": "", "difficulty": ""}]
    analysis = {r["qid"]: [{"unit": "main", "text": r["question"], "search_query": "이동자수 시도별", "filters": None}]
                for r in rows}
    per, info = C.run(rows, analysis, ["hash"], False, 10, 50, log=lambda m: None, docs=["rule", "tslot+tmpl+rw"],
                      cards=str(cards_file))
    assert {r["dense"] for r in per} == {"hash|rule", "hash|tslot+tmpl+rw"}, info
    r0 = next(r for r in per if r["dense"] == "hash|rule")
    r1 = next(r for r in per if r["dense"] == "hash|tslot+tmpl+rw")
    assert r0["dense@10"] in (0, 1) and r0["rwdense@10"] is None and r1["rwdense@10"] in (0, 1)
    assert "near_confusion" in r0
    dv = C.dense_vs_base(per)
    assert {d["metric"] for d in dv} >= {"hit@1", "groups@10", "dense@10", "mrr"}
    table, fails, wins = C.summarize(per)
    md = C.report_md({"created": "x", "golden": "g", "n_rows": 2, "variants": ["P"], "analyze": "none",
                      "analysis_status": {}, "top_k": 10, "pool": 50, "dense": ["hash"], "dense_docs": ["rule", "tslot"],
                      "configs": info}, table, fails, wins, per)
    assert "dense@10" in md and "hash|tslot+tmpl+rw" in md


def test_tuned_path_per_docs(tmp_path):
    from backend.rag.search.tuning.tune import load_tuned, tuned_path
    assert tuned_path("bge-m3-ko", tmp_path, "slot+def+rw").name == "search.tuned.bge-m3-ko.slot-def-rw.yaml"
    assert tuned_path("bge-m3-ko", tmp_path, "rule").name == "search.tuned.bge-m3-ko.yaml"
    (tmp_path / "search.tuned.bge-m3-ko.yaml").write_text("weights: {q_dense: 2.0}\n", encoding="utf-8")
    assert load_tuned("bge-m3-ko", tmp_path) == {"weights": {"q_dense": 2.0}}
    assert load_tuned("bge-m3-ko", tmp_path, "def") is None                     # 다른 문서로 맞춘 가중치는 섞지 않음


def test_compare_from_run_reuses_paths(tmp_path, monkeypatch, capsys):
    from backend.rag.search.tuning import compare as C
    runs = tmp_path / "search_compare"
    prev = runs / "20261118_101010_hard"
    prev.mkdir(parents=True)
    gold = tmp_path / "hard.jsonl"
    gold.write_text(json.dumps({"qid": "g1", "question": "시도별 이동자수", "required": [["DT_1B26001"]]}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    (prev / "config.json").write_text(json.dumps({"golden": str(gold), "alt": None, "variants": ["P"], "dense": ["hcx"]}),
                                      encoding="utf-8")
    (prev / "analysis_cache.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(C, "_runs_dir", lambda: runs)
    C.main(["--list-runs"])
    assert "20261118_101010_hard" in capsys.readouterr().out
    assert C.find_run("hard") == prev
    seen = {}

    def fake_run(rows, analysis, denses, llm, top_k, pool, **kw):
        seen.update(rows=rows, analysis=analysis, docs=kw.get("docs"))
        return [], {}
    monkeypatch.setattr(C, "run", fake_run)
    monkeypatch.setattr(C, "analyze_all", lambda rows, mode, today, cache, log=print: (seen.update(cache=cache) or {}))
    C.main(["--from-run", "hard", "--dense", "hash", "--dense-docs", "rule", "--analyze", "none", "--out", str(tmp_path / "o")])
    assert seen["rows"][0]["qid"] == "g1" and seen["docs"] == ["rule"]
    assert (tmp_path / "o" / "analysis_cache.jsonl").exists()                   # 이전 실행의 캐시를 복사해 씀
    out = capsys.readouterr().out
    assert "[이전 실행] 20261118_101010_hard" in out


def test_separate_channels_and_value_chunks(cards_file):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder
    c = Corpus()
    s = TableSearch(c, embedder=HashEmbedder(), facets_source="meta", llm_rerank=False,
                    settings={"dense_docs": "rule,tmpl+vals", "dense_cards": str(cards_file)})
    assert [g for g, _ in s.ch.denses] == ["rule", "tmpl+vals"] and s.s["weights"]["q_dense_tmpl+vals"] == 1.0
    prep = s.prepare("이동자수 시도별", None, "작년 시도별 이사 간 사람 수", "main", "2026-11-12")
    assert {"q_dense", "q_dense_tmpl+vals"} <= set(prep["scores"]) and prep["ranks"]["q_dense_tmpl+vals"].max() > 0
    d = s.dense_scores("이동자수 시도별", "작년 시도별 이사 간 사람 수")
    assert len(d["q"]) == 2
    # vals: 표 하나 = 여러 조각, 표 점수 = 조각 중 최댓값
    f = s.facets["DT_1GA9009"]
    ch = dc.value_chunks(f)
    assert any("점유형태: 자기집, 전세, 보증부월세" in x for x in ch) and all(x.startswith("인구총조사 | ") for x in ch)
    v = TableSearch(c, embedder=HashEmbedder(), facets_source="meta", llm_rerank=False, settings={"dense_docs": "vals"})
    r = v.ch.dense
    assert r.owners[0] is not None and len(r.owners[0]) >= len(c.docs())
    i = [x.id for x in c.docs()].index("DT_1GA9009")
    q = HashEmbedder().embed_queries(["보증부월세"])[0]
    want = max(float(HashEmbedder().embed_docs([x])[0] @ q) for x in ch)
    assert abs(v.ch.dense.scores("보증부월세")[i] - want) < 1e-5


def test_value_chunks_split_long_dims():
    from backend.rag.search.facets import Facet
    f = Facet("T", "시도/직업별 취업자", "조사", items=["취업자"],
              dims=[("직업별", "other", [f"직업{i}" for i in range(70)] + ["계"]), ("성별", "sex", ["남자", "여자"]),
                    ("연령별", "ages", ["15~19세"])])
    ch = dc.value_chunks(f)
    assert len(ch) == 1 + 3 and ch[1].endswith("직업29") and "계" not in ch[3].split(": ")[1].split(", ")
    assert not any("남자" in x or "15~19세" in x for x in ch)                  # 성별·연령 값은 조각에 넣지 않음
    assert len(dc.value_chunks(f, max_chunks=2)) == 2


def test_region_words_skip_level_names(builder):
    from backend.rag.search.facets import Facet
    f = Facet("X")
    f.regions = {"시군구", "읍면동", "동읍면부", "청주시", "부산진구"}
    rs = dc.region_words({"X": f})
    assert {"청주시", "부산진구"} <= rs and not ({"시군구", "읍면동", "동읍면부"} & rs)
    body, flags = dc.check_def("전국의 시도, 시군구, 읍면동 수준에서 인구를 집계한 통계다.", "", builder.vocab, set(), rs)
    assert body and not flags


def test_recheck_without_llm(tmp_path, builder):
    out = tmp_path / "c.jsonl"
    cards = dc.build(builder.docs, out, use_llm=True, limit=1, builder=builder, log=lambda m: None,
                     chat_fn=lambda *a, **k: {"slots": {}, "정의": "일반 통계다. 서울 통계다."})
    t = next(iter(cards))
    assert "서울" not in cards[t]["def_text"]
    cards[t]["llm_def"] = "가구를 집계한 통계다. 시군구 단위로 나뉜다."
    dc.recheck(cards, builder, log=lambda m: None)
    assert "시군구 단위로 나뉜다." in cards[t]["def_text"]


def test_report_escapes_pipes_and_rebuild(tmp_path, cards_file, monkeypatch):
    import re
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.index import HashEmbedder
    from backend.rag.search.tuning import compare as C
    monkeypatch.setattr(C, "get_search_for", lambda dense="hcx", llm=False, settings=None: TableSearch(
        Corpus(), embedder=HashEmbedder(), facets_source="meta", llm_rerank=False, settings=settings))
    rows = [{"qid": "q1", "record_id": "r1", "variant": "P", "question": "시도별 이동자수", "gold": ["DT_1B26001"],
             "groups": {"G1": ["DT_1B26001"]}, "hop_type": "SINGLE", "reasoning_type": "", "subtype": "", "survey": "",
             "difficulty": ""}]
    an = {"q1": [{"unit": "main", "text": "시도별 이동자수", "search_query": "이동자수 시도별", "filters": None}]}
    per, info = C.run(rows, an, ["hash"], False, 10, 50, log=lambda m: None, docs=["rule", "rule,tmpl"], cards=str(cards_file))
    table, fails, wins = C.summarize(per)
    meta = {"created": "x", "golden": "g", "n_rows": 1, "variants": ["P"], "analyze": "none", "analysis_status": {},
            "top_k": 10, "pool": 50, "dense": ["hash"], "dense_docs": ["rule", "rule,tmpl"], "configs": info}
    md = C.report_md(meta, table, fails, wins, per)
    rows_md = [x for x in md.splitlines() if x.startswith("| search")]
    head = next(x for x in md.splitlines() if x.startswith("| 구성 | 값 | n | hit@1 | hit@3"))
    want = len(head.split("|"))
    assert rows_md and all(len(re.split(r"(?<!\\)\|", x)) in (want, 11, 8) for x in rows_md), rows_md[:2]
    d = tmp_path / "run"
    d.mkdir()
    import csv as _csv
    with (d / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(per[0]))
        w.writeheader()
        w.writerows(per)
    (d / "summary.json").write_text(json.dumps({"meta": meta}, ensure_ascii=False), encoding="utf-8")
    C.main(["--rebuild-report", str(d)])
    assert "hash\\|rule,tmpl" in (d / "report.md").read_text(encoding="utf-8")


def test_value_coverage_reports_what_is_left_out():
    from backend.rag.search.facets import Facet
    f = Facet("T", "시도/직업별 취업자", "조사", items=["취업자"], geo={"시도"},
              dims=[("직업별", "other", [f"직업{i}" for i in range(70)] + ["계"]), ("성별", "sex", ["남자", "여자"])])
    cov = {r["분류"]: r for r in dc.value_coverage(f, max_chunks=2)}
    assert cov["항목"]["조각에 든 값"] == 1
    assert cov["직업"]["값 수"] == 71 and cov["직업"]["조각에 든 값"] == 30 and "상한" in cov["직업"]["빠진 이유"]
    assert cov["성별"]["조각에 든 값"] == 0 and "지역" in cov
