"""OKF 지식 카탈로그 (backend/rag/okf) — 가짜 프로필로 (네트워크·HCX·duckdb 없음)

  1) 표 생성   schema 1·2 · 큰 차원 → 분류 파일 · 형제 표 · 두 번째 실행은 아무것도 안 씀 · 사람 구간·모르는 키 보존
               · 사라진 표는 deprecated (사람이 적은 superseded_by 보존)
  2) 검사      오류(없는 표·코드·type·YAML·별칭=not) / 경고(이름 바뀜·별칭 충돌·폐기 표 따라감) / 큰 차원은 코드북으로
  3) 빌드      CURRENT 교체 · 같은 입력 재사용 · 검사 오류면 CURRENT 그대로 · 오래된 빌드 정리 · 되돌리기
  4) 조회      코드북(작은·큰 차원) · 질문에 걸린 개념만 (별칭·not·제목) · 규칙(dim_kind) 개념
  5) 관리      vocab_aliases.csv 옮기기 · 학습 사전 승인 → 별칭(verified) · 승인 전 별칭은 쓰지 않음
  6) 정규 어휘 사전 연결  OKF 빌드가 있으면 vocab.json·별칭을 거기서 (okf_use=false 면 예전대로)
"""
import json
import os
import time

import pytest

from backend.core.settings import with_overrides
from backend.rag.okf import build as B
from backend.rag.okf import curate as C
from backend.rag.okf import tables as T
from backend.rag.okf.catalog import Catalog
from backend.rag.okf.doc import Doc, human_block
from backend.rag.okf.lint import alias_active, lint

SIGUNGU = [{"code": "00", "name": "전국", "is_total": True}] + \
          [{"code": f"{i:05d}", "name": f"시군구{i}", "parent": "00"} for i in range(1, 61)] + \
          [{"code": "29010", "name": "세종시"}]


def prof_v2(tbl="DT_1JC1516", title="세대구성 및 가구원수별 가구(일반가구) - 시군구", geo=SIGUNGU, extra_codes=()):
    return {"schema": 2, "table_key": f"101_{tbl}", "org_id": "101", "tbl_id": tbl, "tbl_nm": title, "category": "인구총조사",
            "periods": {"A": [{"prd_de": str(y), "label": str(y)} for y in (2015, 2020, 2025)]},
            "levels": [
                {"level": 1, "obj_nm": "행정구역별(시군구)", "kind": "geo", "n_codes": len(geo), "total_code": "00", "codes": geo},
                {"level": 2, "obj_nm": "세대구성별", "kind": "other", "n_codes": 4, "total_code": "00",
                 "codes": [{"code": "00", "name": "계", "is_total": True}, {"code": "20", "name": "2세대 가구"},
                           {"code": "202", "name": "부+미혼자녀", "parent": "20"},
                           {"code": "203", "name": "모+미혼자녀", "parent": "20"}, *extra_codes]}],
            "items": [{"itm_id": "T10", "nm": "일반가구", "unit": "가구", "role": "count", "additive": True},
                      {"itm_id": "T30", "nm": "평균 가구원 수", "unit": "명", "role": "mean", "additive": False}],
            "n_symbols": 12}


def prof_v1(tbl, title, survey="주민등록인구현황"):
    return {"table_key": f"101_{tbl}", "org_id": "101", "tbl_id": tbl, "tbl_nm": title, "category": "인구", "survey_nm": survey,
            "periods": {"Y": [{"prd_de": "2024", "label": "2024", "year": 2024}]},
            "levels": [{"level": 1, "obj_nm": "행정구역(시도)별", "kind": "regions", "n_codes": 2, "total_code": "00",
                        "codes": [{"code": "00", "name": "전국", "is_total": True}, {"code": "11", "name": "서울특별시"}]},
                       {"level": 2, "obj_nm": "연령별", "kind": "ages", "n_codes": 2, "total_code": "0",
                        "codes": [{"code": "0", "name": "계", "is_total": True}, {"code": "65", "name": "65세 이상"}]}],
            "items": [{"itm_id": "T1", "name": "인구", "unit": "명", "kind": "count", "is_total": True}],
            "symbols": {"-": {"count": 3, "meaning": "해당 없음"}}, "notes": ["주민등록 기준"]}


@pytest.fixture
def env(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir()
    for name, p in [("101_DT_1JC1516.json", prof_v2()), ("101_DT_POP_T.json", prof_v1("DT_POP_T", "시도별 인구(계)")),
                    ("101_DT_POP_M.json", prof_v1("DT_POP_M", "시도별 인구(남)"))]:
        (prof / name).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    (prof / "101_DT_1JC1516_summary.json").write_text(json.dumps({"levels": {"0": 1}, "items": {}}), encoding="utf-8")
    bundle, root = tmp_path / "okf", tmp_path / "okf_build"
    T.generate(bundle, prof, log=lambda *_: None)
    return {"tmp": tmp_path, "prof": prof, "bundle": bundle, "root": root, "recs": T.load_profiles(prof)}


def concept(bundle, rel, meta_extra, body="# 정의\n"):
    p = bundle / "concepts" / f"{rel}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "Stat Concept", "title": rel.rsplit("/", 1)[-1], **meta_extra}
    p.write_text(Doc(meta, body).text(), encoding="utf-8")
    return p


def binds_mo(code="203", name="모+미혼자녀"):
    return {"x-t4-concept": {"aliases": [{"text": "싱글맘"}], "binds": [
        {"table": "/tables/101/DT_1JC1516.md", "dim": "세대구성별", "code": code, "name": name}]}}


# ── 1) 표 생성 ──────────────────────────────────────────────────
def test_generate_files(env):
    b = env["bundle"]
    assert len(env["recs"]) == 3  # 요약 파일은 건너뜀
    d = Doc.read(b / "tables/101/DT_1JC1516.md")
    assert d.type == "Stat Table" and d.meta["resource"].endswith("orgId=101&tblId=DT_1JC1516")
    xt = d.meta["x-t4-table"]
    geo, hh = xt["dims"]
    # 코드 62개 → 분류 파일 + 예시만 / 4개 → 코드 전부
    assert "codes" not in geo and geo["classification"].startswith("/classifications/geo-") and len(geo["examples"]) == T.N_EXAMPLES
    assert {"code": "203", "name": "모+미혼자녀", "parent": "20"} in hh["codes"]
    assert xt["items"][1] == {"id": "T30", "name": "평균 가구원 수", "unit": "명", "role": "mean", "additive": False}
    assert xt["periods"] == {"A": ["2015", "2020", "2025"]} and xt["symbols"] == {"*": {"count": 12}}
    cls = Doc.read(b / (geo["classification"].lstrip("/")))
    assert cls.type == "Classification" and cls.meta["x-t4-classification"]["n_codes"] == 62
    # schema 1: 종류 이름 정리 · 부호 뜻 · 주석 · 형제 표 (계)/(남)
    p1 = Doc.read(b / "tables/101/DT_POP_T.md")
    x1 = p1.meta["x-t4-table"]
    assert [dm["kind"] for dm in x1["dims"]] == ["geo", "age"] and x1["symbols"]["-"]["meaning"] == "해당 없음"
    assert x1["siblings"] == [{"path": "/tables/101/DT_POP_M.md", "rel": "성별판"}]
    assert "주민등록 기준" in p1.body and "[시도별 인구(남)](/tables/101/DT_POP_M.md)" in p1.body
    # 목록 · 루트 index (v0.3 번들 정보) · log
    root = Doc.read(b / "index.md")
    assert root.meta["okf_version"] == "0.3" and "(/tables/index.md)" in root.body
    assert "DT_1JC1516.md" in (b / "tables/101/index.md").read_text(encoding="utf-8")
    assert "**tables** 표 3개 — 새 3" in (b / "log.md").read_text(encoding="utf-8")


def test_generate_idempotent_and_preserves_human(env):
    b, prof = env["bundle"], env["prof"]
    f = b / "tables/101/DT_1JC1516.md"
    before = f.read_text(encoding="utf-8")
    log_before = (b / "log.md").read_text(encoding="utf-8")
    s = T.generate(b, prof, log=lambda *_: None)
    assert (s["new"], s["changed"], s["same"]) == (0, 0, 3) and f.read_text(encoding="utf-8") == before
    assert (b / "log.md").read_text(encoding="utf-8") == log_before  # 바뀐 게 없으면 기록도 없음
    # 사람이 메모·검증·모르는 키를 넣음 → 프로필이 바뀌어 다시 생성돼도 보존
    d = Doc.read(f)
    d.meta["verified"] = [{"by": "human:toast", "at": "2026-11-23T10:00:00+09:00"}]
    d.meta["x-acme-owner"] = "data-team"
    d.body = d.body.replace(human_block(), human_block("세종시(29010)는 세종특별자치시(29)와 값이 같음"))
    f.write_text(d.text(), encoding="utf-8")
    (prof / "101_DT_1JC1516.json").write_text(json.dumps(prof_v2(extra_codes=[{"code": "60", "name": "비친족 가구"}]),
                                                         ensure_ascii=False), encoding="utf-8")
    s = T.generate(b, prof, log=lambda *_: None)
    assert s["changed"] == 1
    d2 = Doc.read(f)
    assert d2.meta["verified"][0]["by"] == "human:toast" and d2.meta["x-acme-owner"] == "data-team"
    assert "값이 같음" in d2.human() and any(c["code"] == "60" for c in d2.meta["x-t4-table"]["dims"][1]["codes"])


def test_removed_table_deprecated(env):
    b, prof = env["bundle"], env["prof"]
    (prof / "101_DT_POP_M.json").unlink()
    f = b / "tables/101/DT_POP_M.md"
    d = Doc.read(f)
    d.meta["superseded_by"] = "/tables/101/DT_POP_T.md"
    f.write_text(d.text(), encoding="utf-8")
    s = T.generate(b, prof, log=lambda *_: None)
    d = Doc.read(f)
    assert s["deprecated"] == 1 and d.meta["status"] == "deprecated" and d.meta["superseded_by"] == "/tables/101/DT_POP_T.md"
    assert "(폐기)" in (b / "tables/101/index.md").read_text(encoding="utf-8")


# ── 2) 검사 ─────────────────────────────────────────────────────
def test_lint_errors_and_warnings(env):
    b = env["bundle"]
    cbs = B.codebooks_from(env["recs"])
    assert lint(b, cbs).summary() == {"error": 0, "warn": 0, "info": 0}
    concept(b, "household/ok", binds_mo())
    concept(b, "household/renamed", binds_mo(name="모자가구"))                       # 이름 바뀜 → 경고
    concept(b, "household/no-code", binds_mo(code="299"))                           # 없는 코드 → 오류
    concept(b, "household/no-table", {"x-t4-concept": {"binds": [{"table": "/tables/101/NOPE.md", "dim": "x", "code": "1"}]}})
    concept(b, "household/self-clash", {"x-t4-concept": {"aliases": [{"text": "미혼모"}], "not": [{"text": "미혼모"}],
                                                         "binds": binds_mo()["x-t4-concept"]["binds"]}})
    concept(b, "geo/sejong", {"x-t4-concept": {"binds": [{"table": "/tables/101/DT_1JC1516.md", "dim": "행정구역별(시군구)",
                                                          "code": "29010", "name": "세종특별자치시"}]}})   # 큰 차원 · 이름 다름
    (b / "concepts/bad").mkdir(parents=True)
    (b / "concepts/bad/no-type.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (b / "concepts/bad/broken.md").write_text("---\ntype: [\n---\n", encoding="utf-8")
    (b / "concepts/README.md").write_text("설명 (프론트매터 없음)", encoding="utf-8")
    rep = lint(b, cbs)
    errs = {(i["where"], i["msg"].split(" ")[0]) for i in rep.of("error")}
    msgs = " | ".join(i["msg"] for i in rep.issues)
    assert not rep.ok
    assert any(w.endswith("no-code.md") for w, _ in errs) and "코드 '299' 가 없음" in msgs
    assert any(w.endswith("no-table.md") for w, _ in errs) and any(w.endswith("self-clash.md") for w, _ in errs)
    assert any(w.endswith("no-type.md") for w, _ in errs) and any(w.endswith("broken.md") for w, _ in errs)
    assert "이름이 '모+미혼자녀' (개념에는 '모자가구')" in msgs
    assert "이름이 '세종시' (개념에는 '세종특별자치시')" in msgs                           # 코드북으로 확인
    assert "별칭 '싱글맘' 이 개념 2개에 걸림" in msgs or "별칭 '싱글맘' 이 개념 3개에 걸림" in msgs
    assert not any(w.endswith("README.md") for w, _ in errs)  # 프론트매터 없는 설명 파일은 건너뜀 (OKF v0.3)
    assert any(i["where"].endswith("README.md") for i in rep.of("info"))
    # 코드북 없이: 큰 차원 코드 확인은 info
    infos = " | ".join(i["msg"] for i in lint(b, None).of("info"))
    assert "코드가 많아 프로필(코드북) 없이 확인 못 함" in infos


def test_lint_follows_superseded(env):
    b = env["bundle"]
    f = b / "tables/101/DT_POP_M.md"
    d = Doc.read(f)
    d.meta.update(status="deprecated", superseded_by="/tables/101/DT_POP_T.md")
    f.write_text(d.text(), encoding="utf-8")
    concept(b, "pop/old", {"x-t4-concept": {"binds": [{"table": "/tables/101/DT_POP_M.md", "dim": "연령별", "code": "65"}]}})
    rep = lint(b)
    assert rep.ok and any("폐기됨 → '/tables/101/DT_POP_T.md' 로 따라가" in i["msg"] for i in rep.of("warn"))


# ── 3) 빌드 ─────────────────────────────────────────────────────
def _build(env, **kw):
    return B.build(env["bundle"], env["root"], env["prof"], None, log=lambda *_: None, **kw)


def test_build_swap_reuse_and_refuse(env):
    concept(env["bundle"], "household/single-mother", binds_mo())
    m = _build(env)
    root = env["root"]
    assert m["ok"] and B.current(root) == m["hash"] and m["tables"] == 3 and m["concepts"] == 1 and m["codebooks"] == 1
    out = root / m["hash"]
    assert {p.name for p in out.iterdir()} >= {"catalog.json", "codebooks.json", "concepts.json", "backlinks.json",
                                               "aliases.json", "vocab.json", "manifest.json"}
    assert json.loads((out / "aliases.json").read_text(encoding="utf-8"))["싱글맘"][0]["canon"] == "모+미혼자녀"
    assert _build(env).get("reused")                                     # 같은 입력 → 다시 만들지 않음
    # 검사 오류 → 빌드 안 함, CURRENT 그대로
    concept(env["bundle"], "household/bad", binds_mo(code="999"))
    bad = _build(env)
    assert not bad["ok"] and B.current(root) == m["hash"]
    assert _build(env, force=True)["ok"] and B.current(root) != m["hash"]   # --force
    B.set_current(root, m["hash"])                                        # 되돌리기
    assert Catalog.current(with_overrides({"okf_build_dir": str(root)})).hash == m["hash"]


def test_build_prune(env):
    root = env["root"]
    hashes = []
    for i in range(5):
        concept(env["bundle"], f"x/c{i}", binds_mo())
        hashes.append(_build(env)["hash"])
        time.sleep(0.02)
        os.utime(root / hashes[-1])
    left = {d.name for d in root.iterdir() if d.is_dir()}
    assert len(left) == B.KEEP and hashes[-1] in left and hashes[0] not in left


# ── 4) 조회 ─────────────────────────────────────────────────────
def test_catalog_lookup(env):
    b = env["bundle"]
    concept(b, "household/single-mother", {"description": "어머니와 미혼 자녀 가구", "x-t4-concept": {
        "aliases": [{"text": "싱글맘"}, {"text": "모자가정", "by": "vector+hcx/1"}],
        "not": [{"text": "미혼모", "why": "혼인 상태까지 정함"}], "calc": ["식구 합계 = Σ(N × N인 가구 수)"],
        "binds": binds_mo()["x-t4-concept"]["binds"]}})
    concept(b, "pop/elderly", {"x-t4-concept": {"aliases": [{"text": "노인"}], "binds": [{"dim_kind": "age", "from": 65}]}})
    _build(env)
    cat = Catalog.current(with_overrides({"okf_build_dir": str(env["root"])}))
    assert cat.table("DT_1JC1516")["dims"][0]["classification"].startswith("geo-")
    assert cat.has_code("DT_1JC1516", "세대구성별", name="모+미혼자녀") == {"code": "203", "name": "모+미혼자녀"}
    assert cat.has_code("DT_1JC1516", "행정구역별(시군구)", code="29010") == {"code": "29010", "name": "세종시"}  # 코드북
    assert cat.has_code("DT_1JC1516", "행정구역별(시군구)", name="없는구") is None
    # 질문에 걸린 개념만 — 별칭('싱글맘') · 경계('미혼모') · 규칙 개념('노인')
    hit = cat.concepts_for(["DT_1JC1516"], "2020년 세종 싱글맘 가정 식구")
    assert [c["id"] for c in hit] == ["/concepts/household/single-mother.md"] and hit[0]["matched"] == {"별칭": "싱글맘"}
    assert hit[0]["calc"] and hit[0]["not"][0]["text"] == "미혼모"
    assert cat.concepts_for(["DT_1JC1516"], "세종 미혼모 가구 수")[0]["matched"] == {"같은 뜻 아님": "미혼모"}
    assert cat.concepts_for(["DT_1JC1516"], "세종 모자가정 가구 수") == []     # 승인 전 별칭은 쓰지 않음
    assert cat.concepts_for(["DT_1JC1516"], "세종 일반가구 수") == []
    assert [c["id"] for c in cat.concepts_for(["DT_POP_T"], "서울 노인 인구")] == ["/concepts/pop/elderly.md"]
    assert cat.concept("/concepts/household/single-mother.md")["pending"] == ["모자가정"]


def test_alias_active_rules():
    assert alias_active({}, {"text": "a"})
    assert not alias_active({"status": "draft"}, {"text": "a"})
    assert not alias_active({}, {"text": "a", "by": "vector+hcx/1"})
    assert not alias_active({}, {"text": "a", "by": "vector+hcx/1", "verified": {"by": "process:nightly"}})
    assert alias_active({}, {"text": "a", "by": "vector+hcx/1", "verified": {"by": "human:toast"}})
    assert alias_active({}, {"text": "a", "by": "x", "verified": [{"by": "process:x"}, {"by": "human:y"}]})


# ── 5) 관리 ─────────────────────────────────────────────────────
def test_migrate_aliases(env):
    res = C.migrate_aliases(env["bundle"], env["recs"], log=lambda *_: None)
    p = env["bundle"] / "concepts/household/single-mother-with-children.md"
    d = Doc.read(p)
    c = d.meta["x-t4-concept"]
    assert [a["text"] for a in c["aliases"]] == ["싱글맘", "한부모 엄마", "엄마 혼자 키우는"]
    assert c["binds"] == [{"table": "/tables/101/DT_1JC1516.md", "dim": "세대구성별", "code": "203", "name": "모+미혼자녀"}]
    assert c["not"][0]["text"] == "미혼모" and d.meta["generated"]["by"] == C.MIGRATOR
    assert (env["bundle"] / "concepts/household/single-father-with-children.md").exists()
    assert {r[3] for r in res} == {"added"}
    assert {r[3] for r in C.migrate_aliases(env["bundle"], env["recs"], log=lambda *_: None)} == {"exists"}  # 다시 돌려도 그대로
    assert lint(env["bundle"], B.codebooks_from(env["recs"])).ok
    assert "single-mother-with-children.md" in (env["bundle"] / "concepts/index.md").read_text(encoding="utf-8")


class FakeLex:
    """Lexicon 의 학습 사전 부분만 (curate 는 .learned · .save() 만 씀). learn 은 Lexicon.learn 과 같은 모양"""

    def __init__(self, path):
        self.path, self.learned = path, {}

    def learn(self, surface, value, slot=None, source="llm", status="pending", example=""):
        from backend.rag.csv_index.store import norm
        self.learned[norm(surface)] = {"surface": surface, "value": value, "slot": slot, "source": source, "status": status,
                                       "count": 1, "examples": [example] if example else [], "added": "2026-11-23T10:00:00+09:00"}

    def save(self):
        self.path.write_text(json.dumps(self.learned, ensure_ascii=False), encoding="utf-8")


def test_approve_pending_to_concept(env):
    lx = FakeLex(env["tmp"] / "learned.json")
    C.migrate_aliases(env["bundle"], env["recs"], log=lambda *_: None)
    lx.learn("모자가정", "모+미혼자녀", slot="조건", source="vector+hcx", status="pending", example="세종 모자가정 수")
    lx.learn("홀몸 아빠", "부+미혼자녀", slot="조건", source="vector+hcx", status="pending")
    lx.save()
    pend = C.pending(env["bundle"], lx)
    assert {p["surface"] for p in pend} == {"모자가정", "홀몸 아빠"}
    assert next(p for p in pend if p["surface"] == "모자가정")["concept"].endswith("single-mother-with-children.md")
    r = C.approve(env["bundle"], env["recs"], lx, "모자가정", by="toast", log=lambda *_: None)
    assert r["result"] == "added" and r["concept"].endswith("single-mother-with-children.md")
    a = Doc.read(env["bundle"] / r["concept"].lstrip("/")).meta["x-t4-concept"]["aliases"][-1]
    assert a["text"] == "모자가정" and a["by"] == "vector+hcx" and a["verified"]["by"] == "human:toast"
    assert lx.learned["모자가정"]["status"] == "okf" and json.loads((env["tmp"] / "learned.json").read_text(encoding="utf-8"))["모자가정"]["status"] == "okf"
    # 개념이 없는 값 → _inbox 에 새 개념 (binds 는 프로필에서)
    r2 = C.approve(env["bundle"], env["recs"], lx, "고령 1인", value="2세대 가구", by="toast", log=lambda *_: None)
    assert r2["concept"].startswith("/concepts/_inbox/") and lint(env["bundle"], B.codebooks_from(env["recs"])).ok
    m = _build(env)
    aliases = json.loads((env["root"] / m["hash"] / "aliases.json").read_text(encoding="utf-8"))
    assert "모자가정" in aliases and aliases["모자가정"][0]["canon"] == "모+미혼자녀"


# ── 6) 정규 어휘 사전 연결 ──────────────────────────────────────
def test_vocab_reads_okf_build(env):
    from backend.rag.query_analyzer import vocab as V
    C.migrate_aliases(env["bundle"], env["recs"], log=lambda *_: None)
    m = _build(env)
    s = with_overrides({"okf_build_dir": str(env["root"]), "vocab_path": ""})
    assert V.vocab_path(s) == env["root"] / m["hash"] / "vocab.json"
    v = V.get_vocab(settings=s)
    assert v.lookup("모 미혼자녀", "조건")["entries"] and v.lookup("평균 가구원수", "지표")["entries"]
    hits = v.alias_hits("2020년 세종 싱글맘 가정 식구")
    assert hits[0]["canon"] == "모+미혼자녀" and hits[0]["concept"].endswith("single-mother-with-children.md")
    # okf_use=false · 직접 지정한 vocab_path 는 OKF 보다 먼저
    off = with_overrides({"okf_build_dir": str(env["root"]), "okf_use": False, "vocab_path": ""})
    assert V.vocab_path(off) != V.vocab_path(s) and V.okf_vocab_path(off) is None
    direct = with_overrides({"okf_build_dir": str(env["root"]), "vocab_path": str(env["tmp"] / "mine.json")})
    assert V.vocab_path(direct) == env["tmp"] / "mine.json"
    # vocab 의 build 명령은 OKF 빌드 폴더에 쓰지 않음
    assert V.vocab_path(s, okf=False).name == "vocab.json" and env["root"] not in V.vocab_path(s, okf=False).parents
