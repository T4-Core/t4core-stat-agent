"""재정렬 개선 (11/24): keep 버그 · 구분 줄(traits.py) · HCX-007 추론 (llm.chat thinking · llm_rerank.thinking) · compare 변형

HCX 없음 — llm._post 와 chat_fn 을 가짜로
  1) chat(thinking)   추론이면 responseFormat 을 빼고 effort·토큰·시간 제한을 바꿈 · 글에서 JSON · 시간 초과 재시도는 짧게
  2) rerank 추론      chat_fn 에 thinking 을 넘기고 형식을 프롬프트로 · 실패·빈 답이면 추론 없이 한 번 더 · 추론 글은 파일 캐시에
  3) traits           후보끼리 다른 성질만 · 총괄표·비율·성별 · 형제 차이 · 조사 공통 정의
  4) 엔진 keep        LLM 이 불확실하면 결과가 LLM 없는 검색과 같음 (형제 규칙을 다시 돌리지 않음)
  5) compare          변형 조각 · 놓친 질문만
"""
import csv
import json
from types import SimpleNamespace

import pytest
import requests

from backend.core import llm as L
from backend.rag.search import llm_rerank as LR
from backend.rag.search import traits as TR
from backend.rag.search.engine import TableSearch
from backend.rag.search.tuning.compare import llm_variant, missed_qids
from tests.test_search import Corpus


# ── 1) chat(thinking) ──────────────────────────────────────────
@pytest.fixture
def post(monkeypatch):
    calls = []

    def fake(path, body, timeout=60):
        calls.append({"path": path, "body": json.loads(json.dumps(body)), "timeout": timeout})
        if calls[-1]["body"].get("thinking", {}).get("effort") not in (None, "none"):
            return {"message": {"content": '생각 끝.\n```json\n{"order": [2, 1]}\n```', "thinkingContent": "2번이 성별을 나눔"},
                    "finishReason": "stop"}
        return {"message": {"content": '{"order": [1, 2]}'}}
    monkeypatch.setenv("HCX_API_KEY", "x")
    monkeypatch.setattr(L, "_post", fake)
    return calls


def test_chat_default_unchanged(post):
    out = L.chat([{"role": "user", "content": "q"}], schema={"type": "object"}, max_tokens=200)
    b = post[0]["body"]
    assert out == {"order": [1, 2]} and b["thinking"] == {"effort": "none"} and "responseFormat" in b
    assert b["maxCompletionTokens"] == 200 and post[0]["timeout"] == 60


def test_chat_thinking(post):
    out = L.chat([{"role": "user", "content": "q"}], schema={"type": "object"}, max_tokens=200, thinking="low",
                 with_thinking=True)
    b = post[0]["body"]
    assert b["thinking"] == {"effort": "low"} and "responseFormat" not in b       # 추론 + 구조화 출력은 못 함
    assert b["maxCompletionTokens"] == 5120 and post[0]["timeout"] == 180          # 추론 토큰 포함 · 긴 시간 제한
    assert out["order"] == [2, 1] and out["_thinking"] == "2번이 성별을 나눔" and out["_finish"] == "stop"
    L.chat([{"role": "user", "content": "q"}], thinking="none")
    assert post[1]["body"]["thinking"] == {"effort": "none"}
    with pytest.raises(ValueError):
        L.chat([{"role": "user", "content": "q"}], thinking="max")


def test_chat_thinking_other_model(post):
    L.chat([{"role": "user", "content": "q"}], schema={"type": "object"}, thinking="low", model="HCX-005")
    b = post[0]["body"]
    assert "thinking" not in b and "responseFormat" in b                          # 추론 모델이 아니면 일반 호출


def test_retry_timeout_budget(monkeypatch):
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    n = []

    def slow():
        n.append(1)
        raise requests.Timeout("느림")
    with pytest.raises(requests.Timeout):
        L.with_retry(slow, timeout_tries=2)
    assert len(n) == 2                                                             # 추론 호출은 긴 요청을 8번 되풀이하지 않음
    assert L.parse_json('앞말 ```json\n{"a": 1}\n``` 뒷말') == {"a": 1} and "_raw" in L.parse_json("없음")


# ── 2) rerank 추론 ─────────────────────────────────────────────
H = [{"tbl_id": t, "score": 1.0, "rank": i} for i, t in enumerate("ABC", 1)]
F = {t: None for t in "ABC"}
QV = SimpleNamespace(years=[2024], sido=[], subs=[], axis=None, want_age=False, want_sex=False)


@pytest.fixture
def plain_card(monkeypatch):
    monkeypatch.setattr(LR, "card", lambda n, h, f, sib_of=None, con_of=None, okf_lines=None:
                        f"[{n}] {h['tbl_id']}" + "".join(f"\n    {x}" for x in (okf_lines or [])))
    LR._cache.clear()
    yield
    LR.use_cache_file(None)


def test_rerank_thinking(plain_card, tmp_path):
    calls = []

    def chat(messages, schema=None, max_tokens=0, **kw):
        calls.append({"sys": messages[0]["content"], **kw, "max_tokens": max_tokens})
        return {"order": [3, 1], "_thinking": "C 가 맞음"}
    LR.use_cache_file(tmp_path / "rc.jsonl")
    hits, note = LR.rerank("q", QV, H, F, 3, chat, thinking="low", think_tokens=3000)
    assert [h["tbl_id"] for h in hits] == ["C", "A", "B"] and note == "llm+think:low"
    assert calls[0]["thinking"] == "low" and calls[0]["with_thinking"] and calls[0]["max_tokens"] == 3000
    assert '{"order": [3, 1, 2]}' in calls[0]["sys"]                                # 형식을 프롬프트로
    rec = json.loads((tmp_path / "rc.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["why"] == "C 가 맞음" and rec["note"] == "llm+think:low"
    LR.rerank("q", QV, H, F, 3, chat)                                              # 추론 없는 같은 질문은 다른 캐시
    assert len(calls) == 2 and "thinking" not in calls[1]


def test_rerank_thinking_fallback(plain_card):
    calls = []

    def chat(messages, schema=None, max_tokens=0, **kw):
        calls.append(kw.get("thinking"))
        if kw.get("thinking"):
            return {"_raw": "", "_finish": "length"}                                # 추론이 토큰을 다 씀
        return {"order": [2]}
    hits, note = LR.rerank("q2", QV, H, F, 3, chat, thinking="low")
    assert calls == ["low", None] and note == "llm 추론 실패(빈 답(length)) → 일반" and hits[0]["tbl_id"] == "B"

    def boom(messages, schema=None, max_tokens=0, **kw):
        if kw.get("thinking"):
            raise requests.Timeout()
        return {"order": [3]}
    _, note = LR.rerank("q3", QV, H, F, 3, boom, thinking="low")
    assert note == "llm 추론 실패(Timeout) → 일반"


# ── 3) traits ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ts():
    return TableSearch(Corpus(), facets_source="meta", llm_rerank=False)


def test_traits_basic(ts):
    f = ts.facets
    b = TR.basic(f["DT_1B8000H"])
    assert b["유형"].startswith("총괄표") and b["비율"].startswith("건수")
    assert TR.basic(f["DT_1B81A23"])["비율"] == "비율 직접 제공(합계출산율)"
    assert TR.basic(f["INH_03"])["비율"] == "비율 직접 제공(조혼인율)"
    assert TR.basic(f["DT_1B85003"])["성별"] == "성별 분류 있음" and TR.basic(f["DT_1B85003"])["연령"] == "연령 분류 있음"
    assert TR.basic(f["DT_1B26001"])["주기"] == "월·연 자료" or TR.basic(f["DT_1B26001"])["주기"].startswith("월")


def test_traits_lines_only_differences(ts):
    head = [{"tbl_id": t} for t in ("DT_1B8000H", "DT_1B81A23", "DT_1B85003")]
    tl = TR.traits_lines(head, ts.facets)
    assert tl["DT_1B8000H"][0].startswith("구분: 총괄표") and "비율 직접 제공(합계출산율)" in tl["DT_1B81A23"][0]
    assert all("주기" not in x and "연 자료" not in x for v in tl.values() for x in v)   # 모두 연간 → 빼고
    same = TR.traits_lines([{"tbl_id": "DT_1IN8501"}, {"tbl_id": "DT_1IN9001"}], ts.facets)
    assert same == {}                                                               # 다른 점이 없으면 줄도 없음
    assert TR.traits_lines([{"tbl_id": "DT_1IN8501"}], ts.facets) == {}


def test_sibling_diffs(ts):
    head = [{"tbl_id": "TX_A011"}, {"tbl_id": "TX_A011_A"}, {"tbl_id": "DT_1B040A3"}]
    sd = TR.sibling_diffs(head, ts.facets, {"TX_A011": "A", "TX_A011_A": "A"})
    assert sd == {"TX_A011": "이 표만 '2008~2015'", "TX_A011_A": "무리에서 가장 일반적인 이름"}


def test_survey_definitions(tmp_path, monkeypatch):
    root = tmp_path / "b" / "h1"
    root.mkdir(parents=True)
    cat = {"T1": {"survey": "외국인주민현황", "definitions": ["외국인주민 = 귀화자·자녀 포함"]},
           "T2": {"survey": "외국인주민현황", "definitions": ["외국인주민 = 귀화자·자녀 포함", "x"]},
           "T3": {"survey": "외국인주민현황", "definitions": []},
           "T4": {"survey": "주민등록", "definitions": ["등록외국인 = 90일 초과"]},
           "T5": {"survey": "주민등록", "definitions": []}}
    (root / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    from backend.rag.okf.catalog import Catalog
    c = Catalog(root)
    monkeypatch.setattr(Catalog, "current", classmethod(lambda cls, s=None: c))
    sv = TR.survey_definitions(c)
    assert sv == {"외국인주민현황": ["외국인주민 = 귀화자·자녀 포함"], "주민등록": []}       # 한 표뿐인 정의는 조사 공통 아님
    facets = {t: SimpleNamespace(survey_nm="") for t in cat}
    d = TR.definitions(list(cat), facets)
    assert d["T1"] == "집계 기준: 외국인주민 = 귀화자·자녀 포함" and d["T3"] == "집계 기준(조사 공통): 외국인주민 = 귀화자·자녀 포함"
    assert "T5" not in d and d["T4"] == "집계 기준: 등록외국인 = 90일 초과"
    assert "T1" not in TR.definitions(list(cat), facets, own=False)               # okf 의 '정의:' 와 겹치지 않게


def test_rerank_traits_prompt(ts):
    LR._cache.clear()
    calls = []

    def chat(messages, schema=None, max_tokens=0, **kw):
        calls.append(messages)
        return {"order": [1]}
    s = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=chat, settings={"llm_rerank": {"traits": True}})
    r = s.search("출생아수", None, 5, question="2020년 서울 출생아 수", today="2026-11-24")
    assert "구분:" in calls[-1][1]["content"] and "추가 기준 (카드에 '구분'" in calls[-1][0]["content"]
    assert "+traits" in r["llm"]


# ── 4) 엔진 keep ───────────────────────────────────────────────
QS = ["2020년 혼인 건수", "1990년 시군구 전세 가구", "2018년 서울 시군구 남자 인구", "2023년 이혼 건수 아내 40대",
      "2012년 유학생 수"]


def test_keep_unsure_equals_search(ts):
    LR._cache.clear()
    k = TableSearch(Corpus(), facets_source="meta", llm_rerank=True,
                    chat_fn=lambda m, schema=None, max_tokens=0, **kw: {"order": [3, 2, 1], "sure": False},
                    settings={"llm_rerank": {"keep_if_unsure": True}})
    for q in QS:
        base = [h["tbl_id"] for h in ts.search(q, None, 10, question=q, today="2026-11-24")["hits"]]
        r = k.search(q, None, 10, question=q, today="2026-11-24")
        assert [h["tbl_id"] for h in r["hits"]] == base, q
        assert r["llm"] is None or r["llm"].endswith(LR.UNSURE)


# ── 5) compare ─────────────────────────────────────────────────
def test_llm_variant():
    assert llm_variant("base") == {"okf": False, "keep_if_unsure": False, "traits": False, "thinking": None}
    assert llm_variant("okf-keep") == {"okf": True, "keep_if_unsure": True, "traits": False, "thinking": None}
    assert llm_variant("okf+traits+keep+think", "medium") == {"okf": True, "keep_if_unsure": True, "traits": True,
                                                              "thinking": "medium"}
    with pytest.raises(ValueError):
        llm_variant("okf+magic")


def test_missed_qids(tmp_path):
    cols = ["method", "qid", "hit@1", "hit@10", "hit@1_aud", "hit@10_aud", "audit_excluded"]
    rows = [["search+llm", "q1", 0, 1, 0, 1, ""], ["search+llm", "q2", 1, 1, 1, 1, ""], ["search+llm", "q3", 0, 0, 0, 0, ""],
            ["search+llm", "q4", 0, 1, 1, 1, ""], ["search+llm", "q5", 0, 1, 0, 1, "True"], ["search", "q2", 0, 1, 0, 1, ""]]
    with (tmp_path / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)
    assert missed_qids(tmp_path) == ({"q1"}, "search+llm")                          # 검토 반영 판정 · 뺀 변형 제외
    assert missed_qids(tmp_path, "search") == ({"q2"}, "search")


def test_keep_skips_second_sibling_pass(monkeypatch):
    """형제 규칙이 LLM 뒤에 순서를 바꾸는 경우(실제 데이터의 keep 버그) — 불확실이면 그 두 번째 적용을 건너뜀"""
    for sure, n_calls in ((False, 1), (True, 2)):
        LR._cache.clear()
        k = TableSearch(Corpus(), facets_source="meta", llm_rerank=True,
                        chat_fn=lambda m, schema=None, max_tokens=0, sure=sure, **kw: {"order": [1, 2, 3], "sure": sure},
                        settings={"llm_rerank": {"keep_if_unsure": True}})
        orig, seen = k.sib.resolve, []

        def spy(ids, *a, _orig=orig, _seen=seen, **kw):
            _seen.append(1)
            out, notes = _orig(ids, *a, **kw)
            return (list(reversed(out)) if len(_seen) == 2 else out), notes   # 두 번째 적용이 순서를 뒤집는다고 치고
        monkeypatch.setattr(k.sib, "resolve", spy)
        r = k.search("혼인건수", None, 5, question="2020년 혼인 건수", today="2026-11-24")
        assert len(seen) == n_calls, sure
        if not sure:
            base = [h["tbl_id"] for h in TableSearch(Corpus(), facets_source="meta", llm_rerank=False).search(
                "혼인건수", None, 5, question="2020년 혼인 건수", today="2026-11-24")["hits"]]
            assert [h["tbl_id"] for h in r["hits"]] == base
