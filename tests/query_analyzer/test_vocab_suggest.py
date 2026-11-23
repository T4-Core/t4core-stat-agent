"""벡터 후보 (vocab_suggest.py) — 가짜 임베더·가짜 HCX 로 (네트워크·모델 없음)

가짜 임베더: 낱말 → '개념' 축 (엄마 쪽 한부모 · 아빠 쪽 한부모 · 식구 · 혼인 · 반려동물). 같은 개념의 말끼리 코사인이 높다.
확인하는 것
  1) 질문 낱말 고르기 — 사전·별칭·지역·풀이말·물음말·슬롯에 이미 담긴 말은 빼고 남은 것만
  2) 벡터 파일 만들기·읽기 · 후보 top-k · 점수 하한 · 사전이 바뀌어도 파일 재사용 · 임베더가 다르면 건너뜀
  3) 모드 — log: 후보만 · hcx: 후보 안에서만 고름(0·범위 밖 번호는 무시) · 학습 사전 '승인 대기' · 승인된 짝은 바로 적용
  4) analyze 안에서 — 조건에 더해져 View 입력·재작성 문장에, 응답 vocab_suggestions, 되묻기 응답 때 HCX 다시 안 부름
"""
import hashlib
import itertools

import numpy as np
import pytest

from backend.core.settings import with_overrides
from backend.rag.query_analyzer import vocab_suggest as VS
from backend.rag.query_analyzer.vocab import build_vocab
from tests.query_analyzer.test_vocab import _analyze, idx, lex, profiles, vocab  # noqa: F401 (pytest 픽스처)

AXES = [("모자", "엄마", "어머니", "모+미혼자녀"), ("부자", "아빠", "아버지", "부+미혼자녀"), ("식구", "가구원"),
        ("혼인", "결혼", "재혼"), ("반려", "애완")]


class FakeEmbedder:
    id = "fake:axes"

    def _one(self, t):
        v = np.zeros(len(AXES) + 256, dtype=np.float32)
        for i, words in enumerate(AXES):
            if any(w in t for w in words):
                v[i] += 1.0
        for a, b in itertools.pairwise(t):  # 글자 2-gram 조금 (개념이 없는 말끼리는 낮은 점수)
            v[len(AXES) + int(hashlib.md5((a + b).encode()).hexdigest()[:6], 16) % 256] += 0.25
        return v / max(np.linalg.norm(v), 1e-6)

    def embed_queries(self, texts):
        return np.vstack([self._one(t) for t in texts])

    embed_docs = embed_queries


class OtherEmbedder(FakeEmbedder):
    id = "fake:other"


def _settings(tmp_path, **over):
    return with_overrides({"vocab_path": str(tmp_path / "vocab.json"), "vocab_suggest_embedder": "fake",
                           "vocab_suggest": "log", "vocab_suggest_min_score": 0.6, **over})


@pytest.fixture
def vectors(vocab, tmp_path):  # noqa: F811
    p, n = VS.build_vectors(vocab, FakeEmbedder(), tmp_path / "vocab_vectors.fake.npz")
    assert n > 0
    return p


class FakeChat:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, messages, schema=None, max_tokens=None):
        self.calls.append(messages)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _no_chat(*a, **k):
    raise AssertionError("HCX 를 부르면 안 됨")


# ── 1) 질문 낱말 ────────────────────────────────────────────────
def test_unmatched_terms(vocab, lex):  # noqa: F811
    q = "2020년 세종의 싱글맘 가정 식구를 다 합치면 몇명이나 되?"
    terms = VS.unmatched_terms(q, {"지역": ["세종"], "지표": ["가구원수"]}, vocab, lex)
    assert "식구" in terms
    for w in ("2020년", "세종", "싱글맘", "합치면", "몇명", "다"):
        assert w not in terms, (w, terms)
    # 사전·CSV 에 있는 말, 슬롯에 담긴 말은 빼고
    assert VS.unmatched_terms("서울 혼인건수 모자가정", {"지역": ["서울"]}, vocab, lex) == ["모자가정"]
    assert VS.unmatched_terms("서울 모자가정 수", {"조건": ["모자가정"]}, vocab, lex) == []
    assert len(VS.unmatched_terms("가나다 라마바 사아자 차카타 파하가", {}, vocab, lex, max_terms=3)) == 3


# ── 2) 벡터 ─────────────────────────────────────────────────────
def test_vectors_search(vocab, vectors):  # noqa: F811
    vv = VS.VocabVectors(vectors, vocab)
    assert vv.embedder_id == "fake:axes"
    names = {e["name"] for e in vv.entries}
    assert "모+미혼자녀" in names and "계" not in names and "청양군" not in names  # 합계·지역은 후보가 아님
    top = vv.search(FakeEmbedder().embed_queries(["모자가정"])[0], k=3, min_score=0.6)
    assert top[0]["name"] == "모+미혼자녀" and top[0]["slot"] == "분류" and top[0]["dim"] == "세대구성별"
    assert all(c["score"] >= 0.6 for c in top)
    assert vv.search(FakeEmbedder().embed_queries(["슬레이트"])[0], k=3, min_score=0.6) == []  # 하한 미달
    # 사전을 다시 만들어 이름이 빠지면 그 줄만 후보에서 빠짐
    smaller = build_vocab(idx=None)
    assert VS.VocabVectors(vectors, smaller).entries == []


# ── 3) 모드 ─────────────────────────────────────────────────────
def test_log_mode_records_only(vocab, lex, vectors, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    s = _settings(tmp_path)
    raw = {"지역": ["세종"], "지표": ["일반가구"]}
    new, recs, choices, skipped = VS.suggest_for_question("세종 모자가정 가구 수", raw, vocab, lex, s, chat_fn=_no_chat)
    assert skipped == "" and new == raw and choices == {}
    r = recs[0]
    assert r["term"] == "모자가정" and r["candidates"][0]["name"] == "모+미혼자녀" and r["choice"] is None
    assert "후보 모+미혼자녀" in VS.describe(recs)[0]


def test_hcx_mode_picks_within_candidates(vocab, idx, vectors, tmp_path, monkeypatch):  # noqa: F811
    from backend.rag.query_analyzer.lexicon import Lexicon
    lx = Lexicon(idx=idx, settings=with_overrides({"csv_scope": "all"}), learned_path=tmp_path / "learned.json")
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    s = _settings(tmp_path, vocab_suggest="hcx")
    chat = FakeChat({"items": [{"term": "모자가정", "choice": 1, "reason": "어머니와 미혼 자녀 가구"}]})
    q = "세종 모자가정 가구 수"
    new, recs, choices, _ = VS.suggest_for_question(q, {"지역": ["세종"], "지표": ["일반가구"]}, vocab, lx, s, chat_fn=chat)
    assert new["조건"] == ["모+미혼자녀"] and new["지표"] == ["일반가구"]
    assert recs[0]["applied"] == "조건" and recs[0]["by"] == "hcx" and recs[0]["learned"] == "pending"
    assert choices["모자가정"]["choice"]["name"] == "모+미혼자녀"
    # HCX 프롬프트에는 후보 목록만 (지어낸 이름을 고를 수 없게)
    user = chat.calls[0][1]["content"]
    assert "낱말 '모자가정'" in user and "1) 모+미혼자녀 (분류 '세대구성별')" in user
    # 학습 사전에는 '승인 대기' 로 저장 → 승인 전엔 Lexicon 이 쓰지 않음
    e = lx.learned["모자가정"]
    assert (e["value"], e["status"], e["source"]) == ("모+미혼자녀", "pending", "vector+hcx")
    assert (tmp_path / "learned.json").exists()
    assert not any(h.source == "learned" for h in lx.resolve("모자가정", "조건"))


@pytest.mark.parametrize("answer,why", [
    ({"items": [{"term": "모자가정", "choice": 0, "reason": "미혼모만 뜻할 수 있음"}]}, "미혼모만 뜻할 수 있음"),
    ({"items": [{"term": "모자가정", "choice": 99}]}, "같은 뜻 후보 없음"),       # 후보 밖 번호
    ({"items": [{"term": "딴말", "choice": 1}]}, "HCX 응답에 없음"),             # 묻지 않은 낱말
    (RuntimeError("HTTP 500"), "HCX 오류: RuntimeError"),
])
def test_hcx_mode_rejects(vocab, lex, vectors, tmp_path, monkeypatch, answer, why):  # noqa: F811
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    s = _settings(tmp_path, vocab_suggest="hcx", vocab_suggest_learn=False)
    raw = {"지역": ["세종"], "지표": ["일반가구"]}
    new, recs, _, _ = VS.suggest_for_question("세종 모자가정 가구 수", raw, vocab, lex, s, chat_fn=FakeChat(answer))
    assert new == raw and recs[0]["choice"] is None and recs[0]["why"] == why


def test_previous_choices_reused(vocab, lex, vectors, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    s = _settings(tmp_path, vocab_suggest="hcx", vocab_suggest_learn=False)
    prev = {"모자가정": {"choice": {"name": "모+미혼자녀", "slot": "분류", "dim": "세대구성별", "score": 0.9}, "why": "", "by": "hcx"}}
    new, _, _, _ = VS.suggest_for_question("세종 모자가정 가구 수", {"지표": ["일반가구"]}, vocab, lex, s,
                                           previous=prev, chat_fn=_no_chat)
    assert new["조건"] == ["모+미혼자녀"]


def test_indicator_candidate_only_when_target_missing(vocab, lex, vectors, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    s = _settings(tmp_path, vocab_suggest="hcx", vocab_suggest_learn=False)
    pick = {"items": [{"term": "식구", "choice": 1}]}
    q = "세종 식구 다 합치면"
    new, recs, _, _ = VS.suggest_for_question(q, {"지역": ["세종"]}, vocab, lex, s, chat_fn=FakeChat(pick))
    assert new["지표"] == ["평균 가구원 수"] and recs[0]["applied"] == "지표"
    # 지표가 이미 사전에 근거가 있으면 더하지 않음 (서브쿼리가 늘지 않게)
    new, recs, _, _ = VS.suggest_for_question(q, {"지역": ["세종"], "지표": ["일반가구"]}, vocab, lex, s, chat_fn=FakeChat(pick))
    assert new["지표"] == ["일반가구"] and recs[0]["choice"] == "평균 가구원 수" and recs[0]["applied"] == ""


def test_learned_active_applied_without_vectors(vocab, idx, tmp_path):  # noqa: F811
    from backend.rag.query_analyzer.lexicon import Lexicon
    lx = Lexicon(idx=idx, settings=with_overrides({"csv_scope": "all"}), learned_path=tmp_path / "learned.json")
    lx.learn("모자가정", "모+미혼자녀", slot="조건", source="vector+hcx", status="pending")
    lx.approve("모자가정")
    s = _settings(tmp_path)  # log 모드 · 벡터 파일 없음
    new, recs, _, skipped = VS.suggest_for_question("세종 모자가정 가구 수", {"지표": ["일반가구"]}, vocab, lx, s, chat_fn=_no_chat)
    assert new["조건"] == ["모+미혼자녀"] and recs[0]["by"] == "learned" and skipped == ""


def test_skips(vocab, lex, vectors, tmp_path, monkeypatch):  # noqa: F811
    raw = {"지표": ["일반가구"]}
    q = "세종 모자가정 가구 수"
    _, _, _, skipped = VS.suggest_for_question(q, raw, vocab, lex, _settings(tmp_path, vocab_suggest="off"))
    assert skipped == "off"
    _, _, _, skipped = VS.suggest_for_question(q, raw, vocab, lex, _settings(tmp_path / "none"))
    assert skipped.startswith("벡터 파일 없음")
    monkeypatch.setattr(VS, "get_embedder", lambda name: OtherEmbedder())
    new, recs, _, skipped = VS.suggest_for_question(q, raw, vocab, lex, _settings(tmp_path))
    assert "임베더" in skipped and new == raw and recs == []


# ── 4) analyze 안에서 ───────────────────────────────────────────
def test_analyze_hcx_mode_and_previous(idx, vectors, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(VS, "get_embedder", lambda name: FakeEmbedder())
    assert vectors.parent == tmp_path  # 벡터 파일은 vocab_path(=tmp/no_vocab.json) 옆
    over = {"vocab_suggest": "hcx", "vocab_suggest_embedder": "fake", "vocab_suggest_min_score": 0.6,
            "vocab_suggest_learn": False}
    q = "2020년 세종 모자가정 가구 수"
    chat = FakeChat({"items": [{"term": "모자가정", "choice": 1, "reason": "같은 뜻"}]})
    from backend.rag.query_analyzer.analyze import analyze
    raw = {"시점": ["2020년"], "지역": ["세종"], "지표": ["일반가구"]}
    from tests.query_analyzer.test_vocab import _state
    o = {"csv_scope": "all", "clarify_mode": "soft", "base_year_mode": "fixed", "base_year": 2025,
         "vocab_path": str(tmp_path / "no_vocab.json"), **over}
    a = analyze(q, previous={"state": _state(q, raw)}, idx=idx, overrides=o, chat_fn=chat)
    f = a["view_bundle"]["filters"]
    assert f["조건"] == ["모+미혼자녀"] and "모+미혼자녀" in a["view_bundle"]["rewritten"]
    assert a["vocab_suggestions"][0]["term"] == "모자가정" and a["vocab_suggestions"][0]["applied"] == "조건"
    assert any(n.startswith("[어휘 후보] '모자가정' → 조건 '모+미혼자녀'") for n in a["notes"])
    assert a["state"]["vocab_choices"]["모자가정"]["choice"]["name"] == "모+미혼자녀"
    # 응답 모양 (API 의 QueryAnalysis 로 검증)
    from backend.schemas.query import QueryAnalysis
    m = QueryAnalysis.model_validate(a)
    assert m.vocab_suggestions and m.state.vocab_choices
    # 되묻기 응답: 직전 state 를 돌려보내면 HCX 다시 안 부름
    a2 = analyze(q, previous={"state": m.state.model_dump()}, idx=idx, overrides=o, chat_fn=_no_chat)
    assert a2["view_bundle"]["filters"]["조건"] == ["모+미혼자녀"]


def test_analyze_log_mode_default_no_vectors(idx, tmp_path):  # noqa: F811
    # 기본 설정(log) · 벡터 파일 없음 → 슬롯 그대로, 응답에 후보 없음, trace 에 건너뛴 사유
    q = "2020년 세종 모자가정 가구 수"
    a = _analyze(q, {"시점": ["2020년"], "지역": ["세종"], "지표": ["일반가구"]}, idx, tmp_path)
    assert not a["view_bundle"]["filters"].get("조건") and a["vocab_suggestions"] == []
    step = next(t for t in a["trace"] if t["step"].startswith("사전에 없는 낱말의 벡터 후보"))
    assert step["output"]["skipped"].startswith("벡터 파일 없음")
