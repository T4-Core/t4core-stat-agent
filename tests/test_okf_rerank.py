"""OKF 정보를 쓰는 LLM 재정렬 (llm_rerank.okf · keep_if_unsure · okf_terms.rerank_notes · compare --llm-variants)

HCX 없음 — 가짜 chat_fn 이 받은 프롬프트를 보고 순서를 정함
  1) table_definitions  KOSIS 주석 중 정의·대상·산식만 (공표·변경 안내는 뺌) → catalog.json 'definitions'
  2) rerank_notes       표 정의 줄 · 질문에 걸린 개념 (별칭 → '질문의 X = 이 개념', not → 주의) · 초안 개념 제외
  3) rerank             카드에 OKF 줄 · 기준 8·9 · keep_if_unsure=sure false 면 원래 순서 · 캐시 키에 OKF·keep
  4) 검색기             llm_rerank.okf 를 켜면 카드에 정의가 들어감 (끄면 기존 카드 그대로)
  5) compare            방법 이름 · 'search+llm+okf' 를 'search+llm' 과도 견줌 · 재정렬 파일 캐시
"""
import json
from types import SimpleNamespace

import pytest

from backend.rag.okf import build as B
from backend.rag.okf import tables as T
from backend.rag.okf.assist import table_definitions
from backend.rag.okf.doc import Doc
from backend.rag.search import llm_rerank as LR
from backend.rag.search.engine import TableSearch
from backend.rag.search.okf_terms import rerank_notes
from backend.rag.search.tuning.compare import LLM_VARIANTS, method_vs_base
from tests.test_okf import prof_v2
from tests.test_okf_search import Corpus, concept

DEF_1516 = "주1) 모+미혼자녀 가구란 어머니와 미혼 자녀로만 구성된 가구를 말함"
NOTES_1516 = ["2025년 자료는 잠정치로 변경될 수 있음", DEF_1516, "일반가구 = 전체가구 - 집단가구 - 외국인가구",
              "평균 가구원 수 = 가구원 수 / 일반가구 x 100"]


@pytest.fixture
def okf(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    prof.mkdir()
    for tid, title, notes in [("DT_1JC1516", "세대구성 및 가구원수별 가구(일반가구) - 시군구", NOTES_1516),
                              ("DT_1JC1517", "세대구성별 가구(일반가구) - 시도", ["주민등록 기준"])]:
        p = {**prof_v2(tid, title), "notes": notes}
        (prof / f"101_{tid}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    bundle, root = tmp_path / "okf", tmp_path / "okf_build"
    T.generate(bundle, prof, log=lambda *_: None)
    mo = [{"table": f"/tables/101/{t}.md", "dim": "세대구성별", "code": "203", "name": "모+미혼자녀"} for t in ("DT_1JC1516", "DT_1JC1517")]
    concept(bundle, "household/single-mother", {"description": "어머니와 미혼 자녀로 된 가구", "x-t4-concept": {
        "aliases": [{"text": "싱글맘"}], "not": [{"text": "미혼모"}], "binds": mo}})
    concept(bundle, "_inbox/draft-x", {"status": "draft", "description": "(초안) 싱글맘", "x-t4-concept": {
        "aliases": [{"text": "싱글맘 가구"}], "binds": mo}})
    m = B.build(bundle, root, prof, None, log=lambda *_: None)
    assert m["ok"]
    from backend.core import config
    monkeypatch.setattr(config, "OKF_BUILD_DIR", root)
    LR._cache.clear()
    return {"root": root, "bundle": bundle}


# ── 1) table_definitions ───────────────────────────────────────
def test_table_definitions(okf):
    d = Doc.read(okf["bundle"] / "tables" / "101" / "DT_1JC1516.md")
    defs = table_definitions(d)
    assert defs[0].startswith("주1) 모+미혼자녀 가구란")                  # 정의 단서
    assert any("x 100" in x for x in defs)                                # 산식
    assert not any("잠정" in x for x in defs)                             # 공표·변경 안내는 뺌
    assert not any(x.startswith("일반가구 = 전체가구") for x in defs)     # 단서도 산식도 없는 줄
    cat = json.loads((okf["root"] / B.current(okf["root"]) / "catalog.json").read_text(encoding="utf-8"))
    assert cat["DT_1JC1516"]["definitions"] == defs and cat["DT_1JC1517"]["definitions"] == []
    assert B.BUILD_VERSION == "okf-build/2"


# ── 2) rerank_notes ────────────────────────────────────────────
def test_rerank_notes(okf):
    n = rerank_notes(["DT_1JC1516", "DT_1JC1517", "DT_1JA0001"], "2020년 세종 싱글맘 가구 수")
    assert n["DT_1JC1516"][0].startswith("정의: 주1) 모+미혼자녀")
    con = [x for x in n["DT_1JC1516"] if x.startswith("개념")]
    assert con == ["개념 'single-mother' — 어머니와 미혼 자녀로 된 가구 · 질문의 '싱글맘' = 이 개념"]   # 초안 개념은 안 붙음
    assert n["DT_1JC1517"] == con and "DT_1JA0001" not in n               # 정의 없는 표도 개념 줄은 붙음 · 묶이지 않은 표 없음
    w = rerank_notes(["DT_1JC1517"], "2020년 세종 미혼모 가구 수")
    assert w == {"DT_1JC1517": ["개념 'single-mother' — 어머니와 미혼 자녀로 된 가구 · 주의: 질문의 '미혼모' 는 이 개념과 같은 뜻이 아님"]}
    assert rerank_notes(["DT_1JC1517"], "2020년 세종 일반가구 수") == {}   # 질문에 개념이 안 나오고 정의도 없음


def test_rerank_notes_without_build(tmp_path, monkeypatch):
    from backend.core import config
    monkeypatch.setattr(config, "OKF_BUILD_DIR", tmp_path / "none")
    assert rerank_notes(["DT_1JC1516"], "싱글맘") == {}


# ── 3) rerank ──────────────────────────────────────────────────
H = [{"tbl_id": t, "score": 1.0, "rank": i} for i, t in enumerate("ABC", 1)]
F = {t: None for t in "ABC"}
QV = SimpleNamespace(years=[2024], sido=[], subs=[], axis=None, want_age=False, want_sex=False)


def _chat(out, calls):
    def f(messages, schema=None, max_tokens=0):
        calls.append({"sys": messages[0]["content"], "user": messages[1]["content"], "schema": schema})
        return out
    return f


@pytest.fixture
def plain_card(monkeypatch):
    monkeypatch.setattr(LR, "card", lambda n, h, f, sib_of=None, con_of=None, okf_lines=None:
                        f"[{n}] {h['tbl_id']}" + "".join(f"\n    {x}" for x in (okf_lines or [])))
    LR._cache.clear()


def test_rerank_okf_cards(plain_card):
    calls = []
    notes = {"C": ["정의: 체류기간 1년 초과"], "Z": ["후보 밖"]}
    hits, note = LR.rerank("장기 체류 외국인", QV, H, F, 3, _chat({"order": [3, 1]}, calls), okf_notes=notes)
    assert [h["tbl_id"] for h in hits] == ["C", "A", "B"] and note == "llm+okf"
    assert "[3] C\n    정의: 체류기간 1년 초과" in calls[0]["user"] and "후보 밖" not in calls[0]["user"]
    assert "추가 기준" in calls[0]["sys"] and calls[0]["schema"] == LR.SCHEMA
    LR.rerank("장기 체류 외국인", QV, H, F, 3, _chat({"order": [2]}, calls))   # OKF 없는 같은 질문은 다른 캐시
    assert len(calls) == 2 and "추가 기준" not in calls[1]["sys"]
    LR.rerank("장기 체류 외국인", QV, H, F, 3, _chat({"order": [2]}, calls), okf_notes=notes)
    assert len(calls) == 2                                                # OKF 가 같으면 캐시


def test_rerank_keep_if_unsure(plain_card):
    calls = []
    hits, note = LR.rerank("외국인 수", QV, H, F, 3, _chat({"order": [3, 1, 2], "sure": False}, calls), keep_if_unsure=True)
    assert [h["tbl_id"] for h in hits] == ["A", "B", "C"] and note == "llm 불확실 → 원래 순서"
    assert calls[0]["schema"] == LR.SCHEMA_SURE and "sure" in calls[0]["sys"]
    hits, _ = LR.rerank("외국인 수", QV, H, F, 3, _chat({}, calls), keep_if_unsure=True)
    assert len(calls) == 1 and [h["tbl_id"] for h in hits] == ["A", "B", "C"]   # 캐시도 불확실을 기억
    hits, note = LR.rerank("외국인 수", QV, H, F, 3, _chat({"order": [3, 1, 2]}, calls))  # keep 아니면 sure 를 보지 않음
    assert [h["tbl_id"] for h in hits] == ["C", "A", "B"] and note == "llm"
    LR._cache.clear()
    hits, _ = LR.rerank("x", QV, H, F, 3, _chat({"order": [2], "sure": True}, calls), keep_if_unsure=True)
    assert [h["tbl_id"] for h in hits] == ["B", "A", "C"]


def test_rerank_cache_file(plain_card, tmp_path):
    calls, f = [], tmp_path / "rc.jsonl"
    LR.use_cache_file(f)
    try:
        LR.rerank("q", QV, H, F, 3, _chat({"order": [2], "sure": False}, calls), keep_if_unsure=True)
        LR._cache.clear()
        LR.use_cache_file(f)                                              # 다른 실행이 파일을 이어받음
        hits, note = LR.rerank("q", QV, H, F, 3, _chat({"order": [3]}, calls), keep_if_unsure=True)
        assert len(calls) == 1 and note.startswith("cache") and [h["tbl_id"] for h in hits] == ["A", "B", "C"]
    finally:
        LR.use_cache_file(None)


# ── 4) 검색기 ───────────────────────────────────────────────────
def test_search_okf_rerank(okf):
    calls = []
    q = "2020년 세종 싱글맘 가구 수"
    on = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=_chat({"order": [1]}, calls),
                     settings={"llm_rerank": {"okf": True}})
    on.search(q, None, 4, question=q, today="2026-11-23")
    assert "정의: 주1) 모+미혼자녀" in calls[-1]["user"] and "질문의 '싱글맘' = 이 개념" in calls[-1]["user"]
    off = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=_chat({"order": [1]}, calls))
    off.search(q, None, 4, question=q, today="2026-11-23")
    assert "정의:" not in calls[-1]["user"] and "추가 기준" not in calls[-1]["sys"]


# ── 5) compare ─────────────────────────────────────────────────
def test_compare_llm_variants():
    assert LLM_VARIANTS["okf-keep"] == {"okf": True, "keep_if_unsure": True} and LLM_VARIANTS["base"]["okf"] is False

    def row(q, m, h1, mrr):
        return {"dense": "none", "qid": q, "method": m, "hit@1": h1, "hit@3": h1, "hit@5": 1, "groups@5": 1,
                "groups@10": 1, "mrr": mrr}
    per = [row("q1", "search", 0, .5), row("q1", "search+llm", 0, .5), row("q1", "search+llm+okf", 1, 1),
           row("q2", "search", 1, 1), row("q2", "search+llm", 0, .5), row("q2", "search+llm+okf", 1, 1)]
    mv = method_vs_base(per)
    got = {(d["base"], d["method"], d["metric"]): d for d in mv}
    assert ("search", "search+llm", "hit@1") in got and ("search", "search+llm+okf", "hit@1") in got
    d = got[("search+llm", "search+llm+okf", "hit@1")]                    # OKF 가 더한 몫
    assert d["base_value"] == 0 and d["value"] == 1 and d["only"] == 2 and d["base_only"] == 0
    assert ("search+llm", "search+llm", "hit@1") not in got
