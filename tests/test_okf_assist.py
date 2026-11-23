"""개념 초안 채우기 (okf/assist.py) — 가짜 번들 + HCX 는 가짜 응답

  1) 사실 정의   drafts --write 가 표 정보로 정의를 채움 ('(초안)' 문장이 남지 않음) · 별칭에 예문 · '# 표' 다시 씀
  2) 주석 고르기 개념을 설명하는 줄만 (이름 · 단서) — 공표·변경 같은 행정 줄 · 약한 단서만 있는 줄은 뺌
  3) 사람이 고친 것  정의 · '# 헷갈리는 말' 본문은 다시 쓰지 않음
  4) HCX 보조   정의(근거에 없는 숫자면 버림) · 별칭 판정 · 예문 안의 좁은 별칭 제안 · 후보 안의 헷갈리는 말
  5) verify      판정이 broad·wrong 인 별칭은 기본 승인에서 빠짐 (--alias 로 고르면 승인)
"""
import pytest

from backend.rag.okf import assist as A
from backend.rag.okf import drafts as D
from backend.rag.okf.doc import Doc
from tests.test_okf import env  # noqa: F401 (pytest 픽스처)
from tests.test_okf_drafts import run  # noqa: F401 (pytest 픽스처)


def _draft(env, run):  # noqa: F811
    b = env["bundle"]
    _, drafts, _, _ = D.collect([run], b)
    res = D.write_drafts(b, drafts, log=lambda *_: None)
    cid = next(c for c, _, _ in res if "203" in c)
    return b, b / cid.lstrip("/")


def _concept(b, rel, binds, aliases=(), desc="(초안) …", body="# 정의\n\n(초안) …\n"):
    p = b / "concepts" / f"{rel}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(Doc({"type": "Stat Concept", "title": rel.rsplit("/", 1)[-1], "description": desc, "status": "draft",
                      "x-t4-concept": {"aliases": list(aliases), "not": [], "binds": binds}}, body).text(), encoding="utf-8")
    return p


def _add_notes(b, tbl, lines):
    p = b / f"tables/101/{tbl}.md"
    d = Doc.read(p)
    d.body = A.set_section(d.body, "주석", "\n".join(f"- {x}" for x in lines))
    p.write_text(d.text(), encoding="utf-8")


def test_write_fills_fact_definition(env, run):  # noqa: F811
    b, p = _draft(env, run)
    d = Doc.read(p)
    desc = d.meta["description"]
    assert not desc.startswith(D.DRAFT_MARK) and "분류 '세대구성별'" in desc and "'모+미혼자녀' (203)" in desc
    assert d.meta["x-t4-draft"]["definition"] == "facts" and d.meta["x-t4-draft"]["by"] == A.FACTS_BY
    assert "# 정의\n\n" + desc in d.body and "— 분류 '세대구성별' 코드 203" in d.body
    al = d.meta["x-t4-concept"]["aliases"]
    assert al[0]["example"].startswith("2020년 세종특별자치시 싱글맘")        # 예문 (P 질문)
    v = D.verify(b, str(p), by="toast", to="household/single-mother-test")
    assert not any("초안" in w for w in v["warnings"])                     # 정의를 손으로 안 써도 경고 없음


def test_concept_notes_pick_definitions(env):  # noqa: F811
    b = env["bundle"]
    _add_notes(b, "DT_POP_T", ["2023.6.11. '강원도' -> '강원특별자치도'로 명칭변경",   # 행정 줄
                                "* 계는 제3의 성을 포함한 수치입니다.",                 # 약한 단서
                                "주1) 인구의 개념 : 주민등록상 거주자",
                                "인구 / 면적 x 100"])
    item = [{"table": "/tables/101/DT_POP_T.md", "item": "T1", "name": "인구"}]
    assert [t for t, _ in A.concept_notes(b, item, "인구")] == ["주1) 인구의 개념 : 주민등록상 거주자", "인구 / 면적 x 100"]
    table = [{"table": "/tables/101/DT_POP_T.md", "name": "시도별 인구(계)"}]
    got = [t for t, _ in A.concept_notes(b, table, "시도별 인구(계)")]
    assert "계는 제3의 성을 포함한 수치입니다." not in got and all("명칭변경" not in t for t in got)
    f = A.facts(b, item)
    assert f["kind"] == "item" and f["unit"] == "명" and f["survey"] == "주민등록인구현황" and "연령" in f["dims"]
    assert "통계표의 항목 '인구' (단위 명)" in A.fact_definition(f)


def test_refresh_keeps_human_edits(env):  # noqa: F811
    b = env["bundle"]
    binds = [{"table": "/tables/101/DT_POP_T.md", "name": "시도별 인구(계)"}]
    p = _concept(b, "_inbox/x", binds, body="# 정의\n\n(초안) …\n\n# 헷갈리는 말\n\n- 세대수 — 사람이 적음\n\n# 표\n\n- 항목 None\n")
    r = A.refresh(b, p)
    d = Doc.read(p)
    assert r["definition"] == "facts" and "(표 전체)" in d.meta["description"]
    assert "- 세대수 — 사람이 적음" in d.body and "항목 None" not in d.body and "— 표 전체" in d.body
    d.meta["description"] = "사람이 쓴 정의"
    p.write_text(d.text(), encoding="utf-8")
    assert A.refresh(b, p)["definition"] == "kept" and Doc.read(p).meta["description"] == "사람이 쓴 정의"


def _stub(definition, verdict="broad", suggest="싱글맘 가정", choice=2, calls=None):
    def chat(msgs, schema=None, max_tokens=0):
        if calls is not None:
            calls.append(msgs[1]["content"])
        return {"definition": definition, "aliases": [{"text": "싱글맘", "verdict": verdict, "reason": "이유", "suggest": suggest},
                                                      {"text": "가정", "verdict": "wrong", "reason": "가구 일반"},
                                                      {"text": "없는말", "verdict": "same"}],
                "not": [{"choice": choice, "reason": "아버지 쪽"}, {"choice": 99}]}
    return chat


def test_assist_hcx_proposals_and_verify(env, run):  # noqa: F811
    b, p = _draft(env, run)
    calls = []
    r = A.assist(b, p, chat_fn=_stub("세대구성별 분류에서 어머니와 미혼 자녀로 된 가구 (코드 203).", calls=calls))
    assert "헷갈리기 쉬운 말 후보:\n1) 2세대 가구\n2) 부+미혼자녀" in calls[0] and "예문: 2020년 세종특별자치시 싱글맘" in calls[0]
    assert r["hcx"] == "ok" and r["verdicts"] == {"싱글맘": "broad", "가정": "wrong"} and r["suggested"] == ["싱글맘 가정"]
    d = Doc.read(p)
    c = d.meta["x-t4-concept"]
    assert d.meta["description"].startswith("세대구성별 분류에서") and d.meta["x-t4-draft"]["definition"] == "hcx"
    assert "근거(표 정보):" in d.body
    sug = next(a for a in c["aliases"] if a["text"] == "싱글맘 가정")
    assert sug["by"] == A.HCX_BY and sug["review"]["verdict"] == "same" and "verified" not in sug   # 제안일 뿐
    assert c["not"] == [{"text": "부+미혼자녀", "why": "아버지 쪽", "by": A.HCX_BY}] and "- 부+미혼자녀 — 아버지 쪽" in d.body
    assert "&id" not in p.read_text(encoding="utf-8")
    # 다시 불러도 판정이 끝났으면 HCX 를 안 부름
    assert A.assist(b, p, chat_fn=_stub("x", calls=calls))["hcx"] == "done" and len(calls) == 1
    v = D.verify(b, str(p), by="toast")
    assert "싱글맘 가정" in v["verified_aliases"] and "싱글맘" not in v["verified_aliases"]
    assert [x.split(" (")[0] for x in v["skipped_aliases"]] == ["싱글맘", "가정"]
    v = D.verify(b, str(p), aliases=["싱글맘"], by="toast")                  # 사람이 고르면 승인
    assert v["verified_aliases"] == ["싱글맘"]


def test_assist_rejects_ungrounded(env, run):  # noqa: F811
    b, p = _draft(env, run)
    fact = Doc.read(p).meta["description"]
    r = A.assist(b, p, chat_fn=_stub("1999년부터 집계한 가구 수.", suggest="예문에 없는 말", choice=0))
    d = Doc.read(p)
    assert d.meta["description"] == fact and r["definition_hcx"].startswith("(버림")   # 근거에 없는 숫자
    assert r["suggested"] == [] and d.meta["x-t4-concept"]["not"] == []               # 예문 밖 제안 · 후보 밖 번호
    def boom(*a, **k):
        raise RuntimeError("down")
    q = A.assist(b, p, chat_fn=boom, force=True)
    assert q["hcx"].startswith("오류") and Doc.read(p).meta["description"] == fact      # HCX 가 안 되면 사실 정의까지


def test_write_drafts_with_hcx_and_inbox(env, run):  # noqa: F811
    b = env["bundle"]
    _, drafts, _, _ = D.collect([run], b)
    calls = []
    D.write_drafts(b, drafts, log=lambda *_: None, hcx=True, chat_fn=_stub("어머니와 미혼 자녀 가구.", calls=calls))
    assert calls and all(Doc.read(x).meta.get("x-t4-draft") for x in A.inbox(b))
    with pytest.raises(ValueError):
        D.verify(b, "/tables/101/DT_1JC1516.md")
