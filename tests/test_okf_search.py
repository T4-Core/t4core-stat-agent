"""OKF 개념 별칭 → 검색 (search/okf_terms.py · 값 채널 · dense 문서 'okf' · compare --okf)

작은 검색 코퍼스(가구 표 4개)와 작은 OKF 번들(같은 표 id)을 만들고, 빌드 폴더를 config 에 꽂아 확인한다 (HCX·네트워크 없음)
  1) table_aliases   승인된 별칭만 · 표에 묶인 개념만 (규칙 개념 · 폐기 개념 · 승인 전 별칭 제외)
  2) 값 채널         별칭 → 그 표 점수 · 정규 이름도 '찾은 값'으로 (안 쓰는 분류 감점 없음)
  3) 검색기          '세종 싱글맘 가구 수' → 모+미혼자녀 표가 1위 (OKF 를 끄면 별칭을 모름) · 빌드가 바뀌면 새 검색기
  4) dense 'okf'     설명문 + '일상어: …' 줄 (별칭 없는 표는 설명문 그대로)
  5) compare --okf   켬·끔 구성을 같은 분석으로 나란히
"""
import json
from types import SimpleNamespace

import pytest

from backend.rag.ingestion.table_text import table_text
from backend.rag.okf import build as B
from backend.rag.okf import tables as T
from backend.rag.okf.doc import Doc
from backend.rag.search.channels import ValueChannel
from backend.rag.search.engine import TableSearch
from backend.rag.search.index import Doc as SDoc
from backend.rag.search.index import dense_doc_views
from backend.rag.search.okf_terms import alias_line, current_build, table_aliases
from tests.test_okf import prof_v2

SIDO = ["서울특별시", "세종특별자치시", "부산광역시"]
REG = {"kind": "regions", "obj_nm": "행정구역별(시군구)", "names": ["전국", *SIDO], "sido": SIDO, "n_codes": 40,
       "geo_types": {"전국": 1, "시도": 17, "시군구": 22}}


def P(tid, name, items, levels, unit="가구"):
    return {"tbl_id": tid, "tbl_nm": name, "survey_nm": "인구총조사", "path": "인구총조사", "units": [unit],
            "items": [{"name": i, "unit": unit} for i in items], "levels": levels,
            "periods": [{"se": "Y", "se_raw": "년", "year_from": 2015, "year_to": 2025}]}


GEN = {"kind": "other", "obj_nm": "세대구성별", "names": ["계", "부부+미혼자녀", "부+미혼자녀", "모+미혼자녀"], "n_codes": 4}
PROFILES = [
    P("DT_1JC1516", "세대구성 및 가구원수별 가구(일반가구) - 시군구", ["일반가구", "1인", "2인", "평균 가구원 수"], [REG, GEN]),
    P("DT_1JA0001", "가구원수별 가구(일반가구) - 시군구", ["일반가구", "1인", "2인", "3인"], [REG]),
    P("DT_1GA0002", "가구주의 혼인상태별 가구 - 시군구", ["일반가구"],
      [REG, {"kind": "other", "obj_nm": "혼인상태별", "names": ["계", "미혼", "배우자있음", "사별", "이혼"], "n_codes": 5}]),
    P("DT_1JC1517", "세대구성별 가구(일반가구) - 시도", ["일반가구"], [REG, GEN]),
]


class Corpus:
    name = "okf-test"

    def __init__(self):
        self._docs = [SDoc(p["tbl_id"], table_text(p), {"tbl_nm": p["tbl_nm"], "survey_nm": p["survey_nm"], "profile": p})
                      for p in PROFILES]

    def docs(self):
        return self._docs

    def signature(self):
        import hashlib
        return "test:okf:" + hashlib.sha1("|".join(d.text for d in self._docs).encode()).hexdigest()[:12]


def concept(bundle, rel, meta):
    p = bundle / "concepts" / f"{rel}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(Doc({"type": "Stat Concept", "title": rel.rsplit("/", 1)[-1], **meta}, "# 정의\n").text(), encoding="utf-8")


@pytest.fixture
def okf(tmp_path, monkeypatch):
    """번들(표 2개 + 개념 4개) → 빌드 → config 의 빌드 폴더를 이 빌드로"""
    prof = tmp_path / "profiles"
    prof.mkdir()
    for tid, title in [("DT_1JC1516", "세대구성 및 가구원수별 가구(일반가구) - 시군구"), ("DT_1JC1517", "세대구성별 가구(일반가구) - 시도")]:
        (prof / f"101_{tid}.json").write_text(json.dumps(prof_v2(tid, title), ensure_ascii=False), encoding="utf-8")
    bundle, root = tmp_path / "okf", tmp_path / "okf_build"
    T.generate(bundle, prof, log=lambda *_: None)
    mo = [{"table": f"/tables/101/{t}.md", "dim": "세대구성별", "code": "203", "name": "모+미혼자녀"} for t in ("DT_1JC1516", "DT_1JC1517")]
    concept(bundle, "household/single-mother", {"x-t4-concept": {
        "aliases": [{"text": "싱글맘"}, {"text": "모자가정", "by": "vector+hcx"}], "not": [{"text": "미혼모"}], "binds": mo}})
    concept(bundle, "household/old", {"status": "deprecated", "x-t4-concept": {"aliases": [{"text": "옛말"}], "binds": mo}})
    concept(bundle, "pop/elderly", {"x-t4-concept": {"aliases": [{"text": "노인"}], "binds": [{"dim_kind": "age", "from": 65}]}})
    m = B.build(bundle, root, prof, None, log=lambda *_: None)
    assert m["ok"]
    from backend.core import config
    monkeypatch.setattr(config, "OKF_BUILD_DIR", root)
    return {"root": root, "hash": m["hash"], "bundle": bundle, "prof": prof}


# ── 1) table_aliases ───────────────────────────────────────────
def test_table_aliases(okf):
    al = table_aliases()
    assert al["build"] == okf["hash"] and current_build() == okf["hash"]
    assert set(al["by_tbl"]) == {"DT_1JC1516", "DT_1JC1517"} and al["n_alias"] == 2
    e = al["by_tbl"]["DT_1JC1516"]
    assert [x["alias"] for x in e] == ["싱글맘"]                    # 승인 전 '모자가정' · 폐기 개념 '옛말' · 규칙 개념 '노인' 제외
    assert e[0]["canon"] == "모+미혼자녀" and e[0]["concept"].endswith("single-mother.md")
    assert alias_line(e) == "일상어: 싱글맘 (모+미혼자녀)"


def test_table_aliases_without_build(tmp_path, monkeypatch):
    from backend.core import config
    monkeypatch.setattr(config, "OKF_BUILD_DIR", tmp_path / "none")
    assert table_aliases() == {"build": None, "by_tbl": {}, "n_alias": 0, "n_tables": 0} and current_build() == ""


# ── 2) 값 채널 ──────────────────────────────────────────────────
def test_value_channel_alias():
    f = [SimpleNamespace(items=["일반가구"], dims=[("세대구성별", "other", ["계", "모+미혼자녀"])]),
         SimpleNamespace(items=["일반가구"], dims=[("혼인상태별", "other", ["계", "미혼"])])]
    plain = ValueChannel(f)
    s0, found0 = plain.scores("세종싱글맘가구수")
    assert "싱글맘" not in found0 and s0[0] == 0
    vc = ValueChannel(f, [[{"alias": "싱글맘", "canon": "모+미혼자녀"}], None], alias_w=0.9)
    s, found = vc.scores("세종싱글맘가구수")
    assert s[0] > 0 and s[1] == 0
    assert found[0] == "싱글맘" and "모+미혼자녀" in found              # 정규 이름도 연결된 값 (feasibility 의 분류 사용)


# ── 3) 검색기 ───────────────────────────────────────────────────
def _hits(s, q):
    r = s.search(q, None, 4, question=q, today="2026-11-23")
    return [h["tbl_id"] for h in r["hits"]], r


def test_search_uses_aliases(okf):
    on = TableSearch(Corpus(), facets_source="meta", llm_rerank=False)
    off = TableSearch(Corpus(), facets_source="meta", llm_rerank=False, settings={"okf": {"enabled": False}})
    assert on.okf == {"enabled": True, "build": okf["hash"], "n_alias": 2, "n_tables": 2}
    assert off.okf["enabled"] is False and off.okf["build"] is None and on.info()["okf"]["build"] == okf["hash"]
    q = "2020년 세종 싱글맘 가구 수"
    ids_on, r_on = _hits(on, q)
    ids_off, _ = _hits(off, q)
    assert ids_on[0] in ("DT_1JC1516", "DT_1JC1517")                 # 모+미혼자녀 가 있는 표 (시군구판·시도판은 형제 규칙이 고름)
    assert set(ids_on[:2]) == {"DT_1JC1516", "DT_1JC1517"}
    linked = r_on["parsed"]["linked"]["q"]
    assert "싱글맘" in linked and "모+미혼자녀" in linked              # 정규 이름도 연결된 값으로
    # OKF 없이는 '싱글맘' 을 모름 → 두 표가 함께 위로 오지 않음 (혼인상태 표 등과 섞임)
    assert set(ids_off[:2]) != {"DT_1JC1516", "DT_1JC1517"} or ids_off != ids_on
    # 질문에 별칭이 없으면 같은 결과
    assert _hits(on, "2020년 세종 일반가구 수")[0] == _hits(off, "2020년 세종 일반가구 수")[0]


def test_feasibility_counts_alias_as_used_dim(okf):
    # OKF 켬: 별칭의 정규 이름(모+미혼자녀)이 '연결된 값' → 세대구성별 분류를 쓴다고 봄 (감점 없음)
    #         '싱글맘' 은 드문 표현이라 그 말이 없는 같은 조사 표에 조건 누락 감점 (기존 cond_miss 규칙)
    # OKF 끔: 세대구성별 분류를 안 쓰는 분류로 셈
    on = TableSearch(Corpus(), facets_source="meta", llm_rerank=False)
    off = TableSearch(Corpus(), facets_source="meta", llm_rerank=False, settings={"okf": {"enabled": False}})
    ids = [d.id for d in on.docs]
    q = "세종 싱글맘 가구 수"
    p_on, p_off = on.prepare(q, None, q), off.prepare(q, None, q)
    i, j = ids.index("DT_1JC1516"), ids.index("DT_1JA0001")
    assert p_on["why"][i] == [] and p_on["feas"][i] == 1.0
    assert "안 쓰는 분류 1" in p_off["why"][i] and p_off["feas"][i] < 1.0
    assert "조건 없음(싱글맘)" in p_on["why"][j] and p_on["feas"][j] < p_off["feas"][j]


def test_get_search_rebuilds_on_new_okf_build(okf):
    from backend.rag.search import engine as E
    k1 = current_build()
    B.set_current(okf["root"], "0" * 12)  # 다른 빌드로 바뀌면 캐시 키가 달라짐 (빌드 폴더가 없으면 별칭 없음)
    assert current_build() != k1 and table_aliases()["build"] is None
    B.set_current(okf["root"], k1)
    from pathlib import Path
    assert "current_build()" in Path(E.__file__).read_text(encoding="utf-8")


# ── 4) dense 문서 'okf' ─────────────────────────────────────────
def test_dense_view_okf(okf):
    c = Corpus()
    out = dense_doc_views(c, "okf")
    by = dict(zip([d.id for d in c.docs()], out["okf"]))
    rule = {d.id: d.text for d in c.docs()}
    assert by["DT_1JC1516"].startswith(rule["DT_1JC1516"]) and by["DT_1JC1516"].endswith("일상어: 싱글맘 (모+미혼자녀)")
    assert by["DT_1JA0001"] == rule["DT_1JA0001"]                    # 별칭 없는 표는 그대로 (임베딩 캐시 재사용)
    from backend.rag.search.index import parse_docs
    assert parse_docs("rule,okf") == ([["rule"], ["okf"]], False)


def test_dense_search_with_okf_view(okf):
    # 같은 임베더로 rule 과 okf 문서를 비교: 별칭이 붙은 표만 '싱글맘' 질문과 더 가까워짐 (다른 표는 그대로)
    from backend.rag.search.index import HashEmbedder
    def mk(docs):
        return TableSearch(Corpus(), embedder=HashEmbedder(), facets_source="meta", llm_rerank=False,
                           settings={"dense_docs": docs})
    rule, okfv = mk("rule"), mk("okf")
    assert okfv.info()["dense_docs"] == ["okf"]
    q = "세종 싱글맘 가구"
    a, b = rule.dense_scores(q, q)["q"][0], okfv.dense_scores(q, q)["q"][0]
    ids = [d.id for d in rule.docs]
    for t in ("DT_1JC1516", "DT_1JC1517"):
        assert b[ids.index(t)] > a[ids.index(t)]
    for t in ("DT_1JA0001", "DT_1GA0002"):
        assert b[ids.index(t)] == pytest.approx(a[ids.index(t)])


# ── 5) compare --okf ───────────────────────────────────────────
def test_compare_okf_arms(okf, monkeypatch):
    from backend.rag.search.tuning import compare as CMP
    made = []

    def fake_get(dense, llm, settings):
        made.append(settings)
        return TableSearch(Corpus(), facets_source="meta", llm_rerank=False, settings=settings)
    monkeypatch.setattr(CMP, "get_search_for", fake_get)
    q = "2020년 세종 싱글맘 가구 수"
    rows = [{"qid": "Q1", "record_id": "Q1", "variant": "P", "hop_type": "", "reasoning_type": "", "subtype": "", "survey": "",
             "difficulty": "", "question": q, "gold": ["DT_1JC1516"], "groups": {"G1": ["DT_1JC1516", "DT_1JC1517"]},
             "alt_groups": {}}]
    analysis = {"Q1": [{"unit": "main", "text": q, "search_query": q, "filters": None, "status": "ok"}]}
    per, info = CMP.run(rows, analysis, ["none"], False, 5, 20, log=lambda *_: None, okf=["off", "on"])
    assert [s.get("okf") for s in made] == [{"enabled": False}, {"enabled": True}]
    assert {r["config"] for r in per} == {"search[none|okf-off]", "search[none|okf-on]"}
    assert info["search[none|okf-on]"]["okf"]["build"] == okf["hash"] and info["search[none|okf-off]"]["okf"]["enabled"] is False
    on = next(r for r in per if r["config"] == "search[none|okf-on]")
    assert on["hit@5"] == 1


# ── 6) 빌드 전 검사 (okf/gate.py) — 실제 compare.run 이 바꾼 빌드로 검색하는지 ─────
def test_gate_evaluate_uses_override_build(okf, monkeypatch):
    from backend.rag.okf import gate as G
    from backend.rag.search.tuning import compare as CMP
    seen = []

    def fake_get(dense, llm, settings):
        seen.append(current_build())
        return TableSearch(Corpus(), facets_source="meta", llm_rerank=False, settings=settings)
    monkeypatch.setattr(CMP, "get_search_for", fake_get)
    q = "2020년 세종 싱글맘 가구 수"
    rows = [{"qid": "Q1", "record_id": "Q1", "variant": "P", "hop_type": "", "reasoning_type": "", "subtype": "", "survey": "",
             "difficulty": "", "question": q, "gold": ["DT_1JC1516"], "groups": {"G1": ["DT_1JC1516", "DT_1JC1517"]}}]
    analysis = {"Q1": [{"unit": "main", "text": q, "search_query": q, "filters": None, "status": "ok"}]}
    a = G.evaluate(None, rows, analysis, {"dense": ["none"]})
    b = G.evaluate(okf["hash"], rows, analysis, {"dense": ["none"]})
    assert seen == ["", okf["hash"]] and current_build() == okf["hash"]   # 검사 뒤에는 원래 CURRENT
    assert set(a) == set(b) == {"Q1"} and b["Q1"]["hit@5"] == 1
