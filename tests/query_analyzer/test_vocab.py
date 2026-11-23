"""정규 어휘 사전 + 근거 없는 재작성 값 지우기 (HCX·duckdb·네트워크 없음)

작은 CSV 값 사전(표 3개)을 직접 만들고, 프로필은 업로드된 DT_1JC1516 schema 2 와 같은 모양으로 만든다.
확인하는 것:
  1) 사전 만들기 — 프로필(schema 1·2) + CSV 값 사전, 항목·분류 코드·지역, role/additive 보존, 저장·읽기
  2) 조회 — 정확 · 표기 변형('모 미혼자녀') · 어간('혼인' ← '혼인건수') · 핵심('가구원수' ← '평균 가구원 수') · 항목+단위('1인가구')
  3) 판정 — 지어낸 값은 지움, 질문 원문·용어 사전·별칭·계산 단어는 남김, 지표 칸의 지역 이름은 지역으로 옮김
  4) analyze 안에서 — HCX 를 다시 부르지 않게 previous state 로 이어서: 지운 값이 접지·View 입력에서 빠지고 재작성 문장도 바뀜
"""
import json

import pandas as pd
import pytest

from backend.rag.csv_index.store import CsvIndex, postings_of
from backend.rag.query_analyzer.vocab import (
    build_vocab,
    changed,
    check_value,
    describe,
    load_vocab,
    prune_slots,
    save_vocab,
)

SIDO = [("00", "전국"), ("11", "서울특별시"), ("29", "세종특별자치시"), ("34", "충청남도")]
SGG = SIDO + [("34310", "청양군")]


def _dim(level, obj_nm, kind, slot, codes, **extra):
    return {"level": level, "obj_nm": obj_nm, "kind": kind, "slot": slot, "n_values": len(codes),
            "values": [{"code": c, "name": n, "n": 10, "n_value": 10, **({"std": n} if slot == "지역" else {}),
                        **extra.get(c, {})} for c, n in codes]}


SCANS = [
    {"tbl_id": "DT_1B83A35", "tbl_nm": "시도별 혼인건수", "selected": True, "n_rows": 40, "years": [2023, 2024, 2025],
     "dims": [_dim(1, "행정구역(시도)별", "regions", "지역", SIDO)],
     "items": [{"itm_id": "T1", "name": "혼인건수", "unit": "건", "n_value": 12}]},
    {"tbl_id": "DT_1IN1503", "tbl_nm": "성 및 연령별 인구", "selected": True, "n_rows": 90, "years": [2015, 2020, 2025],
     "dims": [_dim(1, "행정구역별(시군구)", "regions", "지역", SGG),
              _dim(2, "성별", "sex", "성별", [("0", "계"), ("1", "남자"), ("2", "여자")])],
     "items": [{"itm_id": "T00", "name": "인구", "unit": "명", "n_value": 90}]},
    {"tbl_id": "DT_1JC1516", "tbl_nm": "세대구성 및 가구원수별 가구(일반가구) - 시군구", "selected": True, "n_rows": 60,
     "years": [2015, 2020, 2025],
     "dims": [_dim(1, "행정구역별(시군구)", "regions", "지역", SIDO),
              _dim(2, "세대구성별", "other", "분류", [("00", "계"), ("202", "부+미혼자녀"), ("203", "모+미혼자녀")])],
     "items": [{"itm_id": "T10", "name": "일반가구", "unit": "가구", "n_value": 60},
               {"itm_id": "T21", "name": "1인", "unit": "가구", "n_value": 60},
               {"itm_id": "T30", "name": "평균 가구원 수", "unit": "명", "n_value": 60}]},
]

# 업로드된 101_DT_1JC1516.json (schema 2) 과 같은 모양 — role · additive · parallel 이 있음
PROFILE_V2 = {
    "schema": 2, "table_key": "101_DT_1JC1516", "org_id": "101", "tbl_id": "DT_1JC1516",
    "tbl_nm": "세대구성 및 가구원수별 가구(일반가구) - 시군구",
    "levels": [
        {"level": 1, "obj_nm": "행정구역별(시군구)", "kind": "geo", "n_codes": 3, "total_code": "00",
         "codes": [{"code": "00", "name": "전국", "depth": 0, "is_total": True, "parent": "", "parallel": False},
                   {"code": "03", "name": "03 동부", "depth": 0, "is_total": False, "parent": "", "parallel": True},
                   {"code": "29", "name": "세종특별자치시", "depth": 0, "is_total": False, "parent": "", "parallel": False}]},
        {"level": 2, "obj_nm": "세대구성별", "kind": "other", "n_codes": 3, "total_code": "00",
         "codes": [{"code": "00", "name": "계", "depth": 0, "is_total": True, "parent": ""},
                   {"code": "20", "name": "2세대 가구", "depth": 0, "is_total": False, "parent": ""},
                   {"code": "203", "name": "모+미혼자녀", "depth": 1, "is_total": False, "parent": "20"}]}],
    "items": [{"itm_id": "T10", "nm": "일반가구", "unit": "가구", "role": "count", "additive": True},
              {"itm_id": "T27", "nm": "7인 이상", "unit": "가구", "role": "count", "additive": True},
              {"itm_id": "T30", "nm": "평균 가구원 수", "unit": "명", "role": "mean", "additive": False}],
}
# 같은 이름의 요약 파일(levels 가 dict) — 사전 만들기에서 건너뛰어야 함
PROFILE_SUMMARY = {"table_key": "101_DT_1JC1516", "geo_col": "c1", "levels": {"0": {"n_regions": 18}},
                   "items": {"T10": {"A": ["2015", "2025"]}}, "summary": "전국·시도 2015~2025"}


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv_index")
    rows = [r for s in SCANS for r in postings_of(s)]
    pd.DataFrame(rows).to_parquet(d / "values.parquet")
    (d / "tables.jsonl").write_text("\n".join(json.dumps({k: v for k, v in s.items()}, ensure_ascii=False)
                                              for s in SCANS), encoding="utf-8")
    return CsvIndex(d)


@pytest.fixture(scope="module")
def profiles(tmp_path_factory):
    d = tmp_path_factory.mktemp("profiles")
    (d / "101_DT_1JC1516.json").write_text(json.dumps(PROFILE_V2, ensure_ascii=False), encoding="utf-8")
    (d / "101_DT_1JC1516_summary.json").write_text(json.dumps(PROFILE_SUMMARY, ensure_ascii=False), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def vocab(idx, profiles):
    return build_vocab(profiles, idx)


@pytest.fixture(scope="module")
def lex(idx, tmp_path_factory):
    from backend.core.settings import with_overrides
    from backend.rag.query_analyzer.lexicon import Lexicon
    return Lexicon(idx=idx, settings=with_overrides({"csv_scope": "all"}),
                   learned_path=tmp_path_factory.mktemp("lex") / "learned.json")


def _entry(vocab, name, slot):
    return next(e for e in vocab.entries if e["name"] == name and e["slot"] == slot)


# ── 1) 사전 만들기 ──────────────────────────────────────────────
def test_build_from_profiles_and_index(vocab, tmp_path):
    assert vocab.source == "profiles:2+csv_index:all" and vocab.n_tables == 3
    slots = {e["slot"] for e in vocab.entries}
    assert {"지표", "분류", "지역", "성별"} <= slots
    mo = _entry(vocab, "모+미혼자녀", "분류")
    assert mo["dim"] == "세대구성별" and "203" in mo["codes"] and mo["tables"] == ["DT_1JC1516"]
    # 프로필의 role·additive 는 사전에 남음 (CSV 값 사전에는 없음). 평균은 더할 수 없는 값
    assert _entry(vocab, "일반가구", "지표")["additive"] is True
    avg = _entry(vocab, "평균 가구원 수", "지표")
    assert (avg["role"], avg["additive"], avg["unit"]) == ("mean", False, "명")
    assert _entry(vocab, "계", "분류")["is_total"] is True
    # 프로필의 '03 동부' 는 지역 값으로 (geo kind). 같은 이름은 표가 달라도 한 줄
    assert any(e["name"] == "03 동부" and e["slot"] == "지역" for e in vocab.entries)
    assert sum(e["name"] == "세종특별자치시" for e in vocab.entries) == 1
    # 저장 → 읽기 (별칭은 파일이 아니라 dictionary/vocab_aliases.csv 에서 다시 읽음)
    p = save_vocab(vocab, tmp_path / "vocab.json")
    v2 = load_vocab(p)
    assert len(v2) == len(vocab) and v2.lookup("모 미혼자녀", "조건")["entries"]
    assert v2.aliases


def test_build_profiles_only(profiles):
    v = build_vocab(profiles)
    assert v.source == "profiles:2" and v.n_tables == 1
    assert v.lookup("7인 이상 가구", "지표")["entries"][0]["name"] == "7인 이상"


# ── 2) 조회 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("value,slot,match,name", [
    ("혼인건수", "지표", "exact", "혼인건수"),
    ("모 미혼자녀", "조건", "exact", "모+미혼자녀"),       # 띄어쓰기·'+' 무시
    ("모미혼자녀", "조건", "exact", "모+미혼자녀"),        # 기호를 뺀 키도 정확 일치로 봄
    ("출생아", "대상", "", ""),                          # 사전에 없는 말 → 근거 없음 (아래에서 따로 확인)
    ("혼인", "대상", "core", "혼인건수"),                 # 어간
    ("가구원수", "지표", "core", "평균 가구원 수"),        # 계산 단어('평균')를 뺀 핵심
    ("1인가구", "대상", "exact", "1인"),                 # 항목 '1인' + 단위 '가구'
    ("동부", "지역", "", ""),                            # 지역 칸은 이 사전 판정 대상이 아님 (SLOT_VOCAB 에 없음)
])
def test_lookup(vocab, value, slot, match, name):
    h = vocab.lookup(value, slot)
    if not match and slot != "지역":
        assert h == {"match": "", "slot": "", "entries": []}
        return
    if slot == "지역":
        assert vocab.lookup(value)["entries"][0]["name"] == "03 동부"  # 슬롯을 안 주면 코드 접두를 뺀 이름으로 찾음
        return
    assert h["match"] == match and h["entries"][0]["name"] == name, h


def test_lookup_slot_filter_and_other_slot(vocab):
    assert vocab.lookup("청양군", "지표")["entries"] == []   # 지역 값은 지표로 근거가 되지 않음
    assert vocab.other_slot("청양군") == "지역"
    assert vocab.other_slot("서울") == "지역"                # 표준명으로 ('서울' → '서울특별시')
    assert vocab.other_slot("여자") == "성별"
    assert vocab.other_slot("혼인건수") is None


def test_aliases(vocab):
    hits = vocab.alias_hits("2020년 세종의 싱글맘 가정 식구")
    assert [(a["alias"], a["canon"], a["dim"]) for a in hits] == [("싱글맘", "모+미혼자녀", "세대구성별")]
    # '미혼모' 는 별칭이 아님 (혼인 상태까지 정하는 말)
    assert vocab.alias_hits("미혼모 가구 수") == []


# ── 3) 판정 ─────────────────────────────────────────────────────
def test_invented_values_dropped(vocab, lex):
    q = "2023년 서울 혼인 건수"
    new, log = prune_slots({"지역": ["서울"], "대상": ["혼인"], "지표": ["혼인건수", "재혼율"], "조건": ["초혼"]}, q, vocab, lex)
    assert new == {"지역": ["서울"], "대상": ["혼인"], "지표": ["혼인건수"]}
    assert {(r["slot"], r["value"]) for r in changed(log)} == {("지표", "재혼율"), ("조건", "초혼")}
    assert all("근거 없음" in m for m in describe(log))


def test_question_words_and_measures_kept(vocab, lex):
    # 사전에 없어도 질문에 쓴 말('반려동물')·계산 단어('비율')·일반 말('가구')은 남김
    q = "서울 반려동물 키우는 가구 비율"
    new, log = prune_slots({"지역": ["서울"], "대상": ["반려동물", "가구"], "지표": ["비율"]}, q, vocab, lex)
    assert new["대상"] == ["반려동물", "가구"] and new["지표"] == ["비율"] and not changed(log)
    why = {r["value"]: r["why"] for r in log}
    assert why["반려동물"] == "질문 원문" and why["비율"].startswith("계산 단어")


def test_region_in_indicator_moved(vocab, lex):
    q = "청양군 인구 비율"
    new, log = prune_slots({"지표": ["청양군", "비율"], "대상": ["인구"]}, q, vocab, lex)
    assert new == {"지표": ["비율"], "대상": ["인구"], "지역": ["청양군"]}
    assert [(r["value"], r["verdict"], r["to"]) for r in changed(log)] == [("청양군", "move", "지역")]
    # 지역 칸에 이미 있으면 겹쳐 넣지 않음
    new, _ = prune_slots({"지역": ["청양군"], "지표": ["청양군"]}, q, vocab, lex)
    assert new == {"지역": ["청양군"]}


def test_term_dictionary_and_lexicon_kept(vocab, lex):
    # 용어 사전·동의어 사전이 질문의 말을 바꾼 값은 질문에 그 글자가 없어도 남김 ('결혼' → '혼인')
    q = "작년 서울 결혼 몇 건?"
    hints = ["혼인", "혼인건수"]
    r = check_value("혼인건수", "지표", q, vocab, lex, hints)
    assert r["verdict"] == "keep" and r["why"].startswith("사전")
    r = check_value("혼인신고", "대상", q, vocab, lex, ["혼인신고"])
    assert r["verdict"] == "keep" and r["why"].startswith("용어")
    r = check_value("혼인신고", "대상", q, vocab, lex, [])
    assert r["verdict"] == "drop"


def test_single_mom_alias(vocab, lex):
    q = "2020년 세종의 싱글맘 가정 식구를 다 합치면 몇명이나 되?"
    raw = {"시점": ["2020년"], "지역": ["세종"], "대상": ["한부모가구"], "지표": ["가구원수"]}
    new, log = prune_slots(raw, q, vocab, lex, hints=[])
    # '한부모가구' 는 이 사전에 없는 지어낸 상위어 → 지움. '가구원수' 는 '평균 가구원 수' 의 핵심 → 남김
    # 질문의 '싱글맘' → 세대구성별 '모+미혼자녀' 를 조건에 더함 (View 가 그 분류 코드를 고름)
    assert new == {"시점": ["2020년"], "지역": ["세종"], "지표": ["가구원수"], "조건": ["모+미혼자녀"]}
    add = next(r for r in log if r["verdict"] == "add")
    assert "싱글맘" in add["why"] and "세대구성별" in add["why"]
    # 별칭 자체가 값이면 남김 (정규 이름은 canon 에)
    r = check_value("싱글맘", "대상", q, vocab, lex, [])
    assert r["verdict"] == "keep" and r["canon"] == ["모+미혼자녀"]
    # alias_fill=False 면 조건에 더하지 않음
    assert "조건" not in prune_slots(raw, q, vocab, lex, hints=[], alias_fill=False)[0]


def test_modes_and_protect(vocab, lex):
    q = "2023년 서울 혼인 건수"
    raw = {"지표": ["혼인건수", "재혼율"]}
    assert prune_slots(raw, q, vocab, lex, mode="off") == (raw, [])
    new, log = prune_slots(raw, q, vocab, lex, mode="log")
    assert new["지표"] == ["혼인건수", "재혼율"] and [r["value"] for r in changed(log)] == ["재혼율"]
    new, _ = prune_slots(raw, q, vocab, lex, protect={"재혼율"})  # 되묻기에서 사용자가 고른 값
    assert new["지표"] == ["혼인건수", "재혼율"]
    # 숫자 조건은 다른 단계(drop_number_conditions)가 다룸
    assert prune_slots({"조건": ["99,000명"]}, q, vocab, lex)[0] == {"조건": ["99,000명"]}


# ── 4) analyze 안에서 ───────────────────────────────────────────
def _state(q, raw, intents=("값 조회",), subs=()):
    return {"bundle": {"original": q, "rewritten": q, "intent": intents[0], "sub_questions": []},
            "raw_slots": raw, "sub_slots": list(subs), "intents": list(intents), "sub_intents": [],
            "hcx_ok": True, "hcx_error": "", "thresholds": []}


def _analyze(q, raw, idx, tmp_path, **over):
    from backend.rag.query_analyzer.analyze import analyze
    o = {"csv_scope": "all", "clarify_mode": "soft", "base_year_mode": "fixed", "base_year": 2025,
         "vocab_path": str(tmp_path / "no_vocab.json"), **over}
    return analyze(q, previous={"state": _state(q, raw)}, idx=idx, overrides=o)


def test_analyze_drops_invented_indicator(idx, tmp_path):
    q = "2023년 서울 혼인 건수"
    a = _analyze(q, {"시점": ["2023년"], "지역": ["서울"], "지표": ["혼인건수", "재혼율"], "조건": ["초혼"]}, idx, tmp_path)
    assert a["status"] == "ok"
    f = a["view_bundle"]["filters"]
    assert f["지표"] == ["혼인건수"] and not f.get("조건")
    rw = a["view_bundle"]["rewritten"]  # 재작성 문장도 지운 슬롯으로 다시 (모듈 2·3 이 이 문장을 읽음)
    assert "혼인건수" in rw and "재혼율" not in rw and "초혼" not in rw
    assert any(n.startswith("[어휘] [지표] '재혼율' 지움") for n in a["notes"])
    step = next(t for t in a["trace"] if t["step"].startswith("근거 없는 값 지우기"))
    assert {r["value"] for r in step["output"]} == {"재혼율", "초혼"}


def test_analyze_log_mode_keeps(idx, tmp_path):
    q = "2023년 서울 혼인 건수"
    a = _analyze(q, {"시점": ["2023년"], "지역": ["서울"], "지표": ["혼인건수", "재혼율"]}, idx, tmp_path, vocab_check="log")
    assert "재혼율" in a["view_bundle"]["filters"]["지표"]
    assert any(n.startswith("[어휘·기록만] [지표] '재혼율'") for n in a["notes"])


def test_analyze_off_has_no_step(idx, tmp_path):
    q = "2023년 서울 혼인 건수"
    a = _analyze(q, {"시점": ["2023년"], "지역": ["서울"], "지표": ["혼인건수", "재혼율"]}, idx, tmp_path, vocab_check="off")
    assert not any(t["step"].startswith("근거 없는 값 지우기") for t in a["trace"])
    assert "재혼율" in a["view_bundle"]["filters"]["지표"]


def test_analyze_empty_target_refilled_from_question(idx, tmp_path):
    # 대상·지표가 모두 지어낸 값이라 지워지면 '대상 보충' 단계가 질문의 CSV 표현으로 다시 채움
    q = "2023년 서울 혼인건수"
    a = _analyze(q, {"시점": ["2023년"], "지역": ["서울"], "지표": ["재혼율"]}, idx, tmp_path)
    assert a["view_bundle"]["filters"]["지표"] == ["혼인건수"]


def test_analyze_single_mom(idx, tmp_path):
    q = "2020년 세종의 싱글맘 가정 식구를 다 합치면 몇명이나 되?"
    a = _analyze(q, {"시점": ["2020년"], "지역": ["세종"], "대상": ["한부모가구"], "지표": ["가구원수"]}, idx, tmp_path)
    f = a["view_bundle"]["filters"]
    assert f["조건"] == ["모+미혼자녀"] and not f.get("대상")
    assert "모+미혼자녀" in a["view_bundle"]["rewritten"]


def test_analyze_uses_saved_vocab_file(idx, profiles, tmp_path):
    # 파일이 있으면 그 사전 (여기선 프로필만으로 만든 사전 → 혼인건수 표가 없음 → 질문 원문 근거로 남음)
    p = save_vocab(build_vocab(profiles), tmp_path / "vocab.json")
    q = "2023년 서울 혼인 건수"
    a = _analyze(q, {"시점": ["2023년"], "지역": ["서울"], "지표": ["혼인건수", "재혼율"]}, idx, tmp_path, vocab_path=str(p))
    assert a["view_bundle"]["filters"]["지표"] == ["혼인건수"]
