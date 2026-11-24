"""개념 초안 모으기 (okf/drafts.py) — 가짜 번들 + 가짜 compare 결과 (Kiwi 형태소 분석은 실제)

  1) 문항 고르기   P 가 1위를 놓쳤고 O 보다 나쁜 레코드만 (둘 다 실패 · P 가 나음 · heldout 은 빼고)
  2) 분류          어휘(코드·항목) · 표를 못 정함 의심(분류 이름만) · 일상어 후보 (흔한 말·지역·O 에 있는 말 제외)
  3) 보고서        drafts.md · 용어 후보
  4) 쓰기          _inbox/draft-*.md (status draft) · 있는 개념엔 미승인 별칭 · 다시 써도 그대로 · 검사 통과
  5) verify        stable + 승인 → 빌드의 aliases.json 에 들어감 · --to 로 _inbox 에서 옮김 · 초안 흔적 경고
  6) 초안 품질     옆 코드는 안 묶음 · 성별 표현·colloquial 용어는 일상어 후보가 아님 · 동사는 어절 끝까지 · 같은 이름의 표로 넓힘
"""
import csv
import json

import pytest

from backend.rag.okf import build as B
from backend.rag.okf import curate as C
from backend.rag.okf import drafts as D
from backend.rag.okf.doc import Doc
from backend.rag.okf.lint import lint
from tests.test_okf import env  # noqa: F401 (pytest 픽스처)

FIELDS = ["method", "dense", "config", "qid", "record_id", "variant", "split", "question", "gold", "rank", "rank_alt",
          "top1", "top1_nm", "fail"]


def row(rid, v, q, rank, split="dev", gold="DT_1JC1516", config="search[hcx]"):
    return {"method": "search", "dense": "hcx", "config": config, "qid": f"{rid}-{v}", "record_id": rid, "variant": v,
            "split": split, "question": q, "gold": gold, "rank": rank, "rank_alt": rank, "top1": "DT_POP_T",
            "top1_nm": "시도별 인구(계)", "fail": ""}


ROWS = [
    # 어휘: '싱글맘' ↔ 세대구성별 '모+미혼자녀'
    row("R1", "O", "2020년 세종특별자치시 모+미혼자녀 일반가구 수는?", "1"),
    row("R1", "P", "2020년 세종특별자치시 싱글맘 가정은 몇 곳이야?", "5"),
    # 표를 못 정함 의심: O 에만 분류 이름('세대구성별')
    row("R2", "O", "2020년 세대구성별 일반가구 수는?", "1"),
    row("R2", "P", "2020년 일반가구는 얼마나 되나요?", "3"),
    # 둘 다 못 찾음 → 어휘 문제가 아님
    row("R3", "O", "2020년 모+미혼자녀 가구", ""),
    row("R3", "P", "2020년 싱글맘 가구", ""),
    # P 가 더 나음 → 빼기
    row("R4", "O", "모+미혼자녀 가구 수", "3"),
    row("R4", "P", "싱글맘 가구 수", "1"),
    # heldout → 기본(dev)에서는 빼기
    row("R5", "O", "2015년 모+미혼자녀 일반가구", "1", split="heldout"),
    row("R5", "P", "2015년 엄마 혼자 키우는 집", "4", split="heldout"),
]


@pytest.fixture
def run(env, tmp_path):  # noqa: F811
    d = tmp_path / "run"
    d.mkdir()
    with (d / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ROWS)
    # C 모드 벡터 후보 기록 (analysis_cache.jsonl) — '싱글맘' 의 후보에 모+미혼자녀
    (d / "analysis_cache.jsonl").write_text(json.dumps({"key": "k", "question": ROWS[1]["question"], "units": [{"notes": [
        "[어휘 후보] '싱글맘' 사전에 없음 · 후보 모+미혼자녀(0.71), 부+미혼자녀(0.66)"]}]}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return d


def test_gap_records_selection(run):
    rows, cfg = D.load_rows(run / "per_query.csv")
    assert cfg == "search[hcx]"
    assert [r["record_id"] for r in D.gap_records(rows)] == ["R1", "R2"]
    assert {r["record_id"] for r in D.gap_records(rows, "all")} == {"R1", "R2", "R5"}
    assert D.vector_notes([run / "analysis_cache.jsonl"])["싱글맘"] == {"모+미혼자녀", "부+미혼자녀"}


def test_collect_kinds_and_drafts(env, run):  # noqa: F811
    recs, drafts, terms, used = D.collect([run], env["bundle"])
    by = {r["record_id"]: r for r in recs}
    assert by["R1"]["kind"] == "어휘" and by["R2"]["kind"] == "표를 못 정함 의심"
    assert "싱글맘" in by["R1"]["phrases"]
    assert not any("세종" in p for p in by["R1"]["phrases"])       # 지역 이름은 일상어 후보가 아님
    assert not any(p in ("몇", "곳") for p in by["R1"]["phrases"])  # 흔한 말
    assert "세대구성별" in by["R2"]["structural"]
    mo = next(d for d in drafts if d["name"] == "모+미혼자녀")
    assert mo["dim"] == "세대구성별" and mo["binds"][0]["code"] == "203" and mo["binds"][0]["table"] == "/tables/101/DT_1JC1516.md"
    a = next(x for x in mo["aliases"] if x["text"] == "싱글맘")
    assert a["records"] == ["R1"] and a["evidence"] == ["벡터 후보 일치"]
    assert used[0]["file"].endswith("per_query.csv")
    md = D.report_md(recs, drafts, used, "dev", terms)
    assert "| 모+미혼자녀 | 세대구성별 | DT_1JC1516 | 싱글맘 (1 · 벡터 후보 일치)" in md and "표를 못 정함 의심" in md


def test_write_drafts_and_verify(env, run):  # noqa: F811
    b = env["bundle"]
    _, drafts, _, _ = D.collect([run], b)
    res = D.write_drafts(b, drafts, log=lambda *_: None)
    created = sorted({cid for cid, _, _ in res})
    assert any(c.startswith("/concepts/_inbox/draft-dt-1jc1516-203") for c in created)
    p = b / next(c for c in created if "203" in c).lstrip("/")
    d = Doc.read(p)
    assert d.meta["status"] == "draft" and d.meta["generated"]["by"] == D.PRODUCER
    al = d.meta["x-t4-concept"]["aliases"]
    assert al[0]["text"] == "싱글맘" and al[0]["by"] == D.ALIAS_BY and al[0]["records"] == ["R1"]
    cbs = B.codebooks_from(env["recs"])
    assert lint(b, cbs).ok
    assert {st for _, _, st in D.write_drafts(b, drafts, log=lambda *_: None)} == {"exists"}  # 다시 써도 그대로
    # 승인 전: 빌드의 별칭에 없음 → verify 후: 들어감
    m = B.build(b, env["root"], env["prof"], None, log=lambda *_: None)
    assert "싱글맘" not in json.loads((env["root"] / m["hash"] / "aliases.json").read_text(encoding="utf-8"))
    v = D.verify(b, str(p.relative_to(b)), by="toast")
    assert v["status"] == "stable" and "싱글맘" in v["verified_aliases"]   # 초안의 다른 후보('가정')도 함께 — 사람이 지우고 승인
    d = Doc.read(p)
    assert d.meta["verified"][-1]["by"] == "human:toast" and d.meta["x-t4-concept"]["aliases"][0]["verified"]["by"] == "human:toast"
    m = B.build(b, env["root"], env["prof"], None, log=lambda *_: None)
    assert json.loads((env["root"] / m["hash"] / "aliases.json").read_text(encoding="utf-8"))["싱글맘"][0]["canon"] == "모+미혼자녀"


def test_write_into_existing_concept(env, run):  # noqa: F811
    b = env["bundle"]
    C.migrate_aliases(b, env["recs"], log=lambda *_: None)   # 모+미혼자녀 개념이 이미 있음 ('싱글맘' 별칭도)
    _, drafts, _, _ = D.collect([run], b, split="all")
    res = D.write_drafts(b, drafts, log=lambda *_: None)
    mo = [x for x in res if x[0].endswith("single-mother-with-children.md")]
    assert ("싱글맘" in {t for _, t, _ in mo}) and {t: st for _, t, st in mo}["싱글맘"] == "exists"
    assert not any("_inbox/draft-dt-1jc1516-203" in c for c, _, _ in res)   # 있는 개념에 붙임 (새 초안 안 만듦)


def test_verify_selected_alias_only(env):  # noqa: F811
    b = env["bundle"]
    p = b / "concepts/x/c.md"
    p.parent.mkdir(parents=True)
    p.write_text(Doc({"type": "Stat Concept", "title": "c", "status": "draft", "x-t4-concept": {
        "aliases": [{"text": "가", "by": "draft:compare"}, {"text": "나", "by": "draft:compare"}], "binds": []}}, "").text(),
        encoding="utf-8")
    v = D.verify(b, "/concepts/x/c.md", aliases=["나"], by="human:toast")
    al = Doc.read(p).meta["x-t4-concept"]["aliases"]
    assert v["verified_aliases"] == ["나"] and "verified" not in al[0] and al[1]["verified"]["by"] == "human:toast"
    with pytest.raises(ValueError):
        D.verify(b, "/tables/101/DT_1JC1516.md")


# ── 초안 품질 (흔한 말 · 옆 코드 · 어절 끝 · 묶을 표 넓히기) ─────
def _rec(o, p, gold):
    return {"record_id": "R", "O": o, "P": p, "gold": gold}


def test_whole_name_picks_one_sibling(env):  # noqa: F811
    tv = D.TableVocab(env["bundle"])
    st = D.Stats(tv, ["x"])
    r = D.analyze_record(_rec("2020년 모+미혼자녀 일반가구 수는?", "2020년 엄마랑 자녀만 있는 집은 몇 곳이야?", ["DT_1JC1516"]), tv, st)
    codes = {b.get("code") for _, _, b in r["binds"] if "dim" in b}
    assert codes == {"203"}   # '미혼' 은 부+미혼자녀에도 있지만 O 에 통째로 있는 건 모+미혼자녀
    # 이름 일부만 맞고 통째로도 없으면 코드 짝을 만들지 않음 (둘 다 묶지 않음)
    r = D.analyze_record(_rec("2020년 미혼자녀 일반가구 수는?", "2020년 싱글맘 가정은 몇 곳이야?", ["DT_1JC1516"]), tv, st)
    assert not any("dim" in b for _, _, b in r["binds"])


def test_phrases_skip_sex_words_and_extend_verbs(env):  # noqa: F811
    tv = D.TableVocab(env["bundle"])
    st = D.Stats(tv, ["x"])
    r = D.analyze_record(_rec("2024년 서울특별시 인구는?", "2024년 서울에 남성이랑 아이를 낳은 사람은?", ["DT_POP_T"]), tv, st)
    assert "아이를 낳은" in r["phrases"]                      # 동사 줄기('낳')로 끝나면 어절 끝까지
    assert not any("남성" in p for p in r["phrases"])          # 성별 표현은 표 하나의 개념이 아님
    assert not any(p.endswith("낳") for p in r["phrases"])


def test_colloquial_term_only_phrase_is_skipped(env, monkeypatch):  # noqa: F811
    tv = D.TableVocab(env["bundle"])
    st = D.Stats(tv, ["x"])
    st.name_df["남자"] = 999                                    # '남자' 는 많은 표에 있는 성별 코드
    monkeypatch.setattr(D, "GENERIC", D.GENERIC - {"남성"})    # 흔한 말 목록이 없어도 colloquial 규칙(남성 → 남자)으로 빠짐
    assert D.colloquial_targets("남성") == ["남자"]
    r = D.analyze_record(_rec("2024년 서울특별시 인구는?", "2024년 서울 남성 사람 수는?", ["DT_POP_T"]), tv, st)
    assert "남성" not in r["phrases"]


def test_binds_widen_to_same_item(env, tmp_path):  # noqa: F811
    tv = D.TableVocab(env["bundle"])
    b = {"table": "/tables/101/DT_POP_T.md", "item": "T1", "name": "인구"}
    assert [x["table"] for x in tv.same(b)] == ["/tables/101/DT_POP_T.md", "/tables/101/DT_POP_M.md"]
    assert tv.same(b, limit=1) == [b]                          # 너무 많은 표면 넓히지 않음
    t = {"table": "/tables/101/DT_POP_T.md", "name": "시도별 인구(계)"}
    assert tv.same(t) == [t]                                   # 표 이름 짝은 그 표만
    d = tmp_path / "run2"
    d.mkdir()
    with (d / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows([row("R9", "O", "2024년 서울특별시 인구는?", "1", gold="DT_POP_T"),
                     row("R9", "P", "2024년 서울 주민등록 머릿수는?", "4", gold="DT_POP_T")])
    _, drafts, _, _ = D.collect([d], env["bundle"])
    pop = next(x for x in drafts if x["name"] == "인구")
    assert [x["table"] for x in pop["gold"]] == ["/tables/101/DT_POP_T.md"] and len(pop["binds"]) == 2
    _, drafts, _, _ = D.collect([d], env["bundle"], gold_only=True)
    assert len(next(x for x in drafts if x["name"] == "인구")["binds"]) == 1
    md = D.report_md([], drafts, [], "dev")
    assert "| 인구 | item | DT_POP_T |" in md


def test_merge_binds_verify_move_and_lint(env, run):  # noqa: F811
    b = env["bundle"]
    _, drafts, _, _ = D.collect([run], b)
    res = D.write_drafts(b, drafts, log=lambda *_: None)
    cid = next(c for c, _, _ in res if "203" in c)
    p = b / cid.lstrip("/")
    extra = {"table": "/tables/101/DT_POP_T.md", "name": "시도별 인구(계)"}
    assert D.merge_binds(p, [extra]) == 1 and D.merge_binds(p, [extra]) == 0
    d = Doc.read(p)
    assert d.meta["x-t4-concept"]["binds"][-1] == extra and "— 표 전체" in d.body and "None" not in d.body
    with pytest.raises(ValueError):
        D.verify(b, cid, to="Household/X")                     # 영어 소문자 이름만
    v = D.verify(b, cid, aliases=["싱글맘"], by="toast", to="household/single-mother-draft")
    assert v["concept"] == "/concepts/household/single-mother-draft.md" and not p.exists()
    assert any("초안 별칭" in w for w in v["warnings"])           # '가정' 은 고르지 않아 미승인으로 남음
    moved = b / v["concept"].lstrip("/")
    d = Doc.read(moved)
    d.meta["description"] = "(초안) 손으로 되돌린 정의"
    moved.write_text(d.text(), encoding="utf-8")
    rep = lint(b, B.codebooks_from(env["recs"]))
    assert any("(초안)" in i["msg"] for i in rep.of("warn") if i["where"] == v["concept"])
    assert D.merge_binds(b / v["concept"].lstrip("/"), [{"table": "/tables/101/DT_POP_M.md", "name": "x"}]) == 0  # 승인된 개념은 그대로
    q = b / "concepts/x/other.md"
    q.parent.mkdir(parents=True)
    q.write_text(Doc({"type": "Stat Concept", "title": "o", "status": "draft", "x-t4-concept": {"binds": []}}, "").text(),
                 encoding="utf-8")
    with pytest.raises(FileExistsError):
        D.verify(b, "/concepts/x/other.md", to="household/single-mother-draft")
