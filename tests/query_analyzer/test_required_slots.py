"""필수 슬롯 되묻기 — 지역만 고른 질문 · 지역 없는 질문 (HCX·네트워크 없음)

1) '서울 통계 보여줘' (화면에서 지역만 고름): 질문 속 '서울' 이 CSV 분류 값(성씨본관별 '서울')과 같아
   '대상 보충' 단계가 지표로 넣었고, 대상이 채워진 것으로 보여 대상을 되묻지 않았다
2) 지역 없는 질문: 재작성 검증이 '전국' 을 채워 지역을 되묻지 않았다. 질문에 '전국' 이 있을 때만 '전국'
"""
import json
from datetime import date

import pandas as pd
import pytest

from backend.rag.csv_index.store import CsvIndex, postings_of


def _dim(obj, kind, slot, names):
    return {"level": 1, "obj_nm": obj, "kind": kind, "slot": slot, "n_values": len(names),
            "values": [{"code": str(i), "name": n, "n": 4, "n_value": 4} for i, n in enumerate(names)]}


SCANS = [
    {"tbl_id": "DT_POP", "tbl_nm": "행정구역별 주민등록인구", "selected": True, "n_rows": 12, "years": [2023, 2024],
     "dims": [_dim("행정구역별", "regions", "지역", ["전국", "서울특별시", "부산광역시"])],
     "items": [{"itm_id": "T1", "name": "인구수", "unit": "명", "n_value": 12}]},
    {"tbl_id": "DT_SURNAME", "tbl_nm": "성씨 본관별 인구", "selected": True, "n_rows": 8, "years": [2015],
     "dims": [_dim("성씨본관별", "other", "분류", ["서울", "부산", "김해"])],
     "items": [{"itm_id": "T1", "name": "성씨인구", "unit": "명", "n_value": 8}]},
]


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv_index")
    pd.DataFrame([r for s in SCANS for r in postings_of(s)]).to_parquet(d / "values.parquet")
    (d / "tables.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in SCANS), encoding="utf-8")
    return CsvIndex(d)


def _analyze(q, raw, idx, tmp_path, mode="strict", intent="값 조회"):
    from backend.rag.query_analyzer.analyze import analyze
    st = {"bundle": {"original": q, "rewritten": q, "intent": intent, "sub_questions": []}, "raw_slots": raw,
          "sub_slots": [], "intents": [intent], "sub_intents": [], "hcx_ok": True, "hcx_error": "", "thresholds": []}
    o = {"csv_scope": "all", "clarify_mode": mode, "base_year_mode": "fixed", "base_year": 2024,
         "vocab_path": str(tmp_path / "no_vocab.json"), "vocab_suggest": "off"}
    return analyze(q, previous={"state": st}, idx=idx, overrides=o)


def _asked(a):
    return sorted(c["slot"] for c in a["clarifications"])


# ── 1) 지역만 고른 질문 ──
@pytest.mark.parametrize("q, region", [("서울 통계 보여줘", "서울특별시"), ("서울특별시 통계 보여줘", "서울특별시"),
                                       ("부산 통계 보여줘", "부산광역시")])
def test_region_only_asks_time_and_target(q, region, idx, tmp_path):
    a = _analyze(q, {"지역": [region]}, idx, tmp_path)
    assert a["status"] == "needs_clarification"
    assert _asked(a) == ["대상", "시점"]                    # 지역 이름은 대상이 아니다
    assert not a["slots"].get("지표") and not a["slots"].get("대상")


def test_target_fill_keeps_real_terms(idx, tmp_path):
    a = _analyze("2024년 서울 인구수 보여줘", {"지역": ["서울특별시"], "시점": ["2024년"]}, idx, tmp_path)
    assert a["status"] == "ok"                              # 지역 말고 통계 용어는 그대로 채움
    assert [v["value"] for v in a["slots"]["지표"]] == ["인구수"]


def test_missing_region_asked_in_strict(idx, tmp_path):
    a = _analyze("2024년 인구수 보여줘", {"시점": ["2024년"], "지표": ["인구수"]}, idx, tmp_path)
    assert _asked(a) == ["지역"]
    assert [o["value"] for o in a["clarifications"][0]["options"]][:1] == ["전국"]   # 후보 첫째는 전국


def test_missing_region_soft_goes_nationwide(idx, tmp_path):
    a = _analyze("2024년 인구수 보여줘", {"시점": ["2024년"], "지표": ["인구수"]}, idx, tmp_path, mode="soft")
    assert a["status"] == "ok"                              # soft: 되묻지 않고 View 기본값(전국 합계)
    assert not (a["view_bundle"]["filters"] or {}).get("지역")


# ── 1-1) HCX 가 조건만 있는 통계 요청을 '범위 밖' 으로 판정 (strict) ──
@pytest.mark.parametrize("q, asked", [("서울 통계 보여줘", ["대상", "시점"]), ("2024년 부산 자료 보여줘", ["대상"]),
                                      ("2024년 통계 보여줘", ["대상", "지역"])])
def test_condition_request_not_out_of_scope(q, asked, idx, tmp_path):
    a = _analyze(q, {}, idx, tmp_path, intent="범위 밖")
    assert a["status"] == "needs_clarification" and _asked(a) == asked   # 끝내지 않고 빠진 칸을 되묻기
    assert any("범위 밖" in n for n in a["notes"])


@pytest.mark.parametrize("q", ["서울 날씨 어때?", "합계출산율이 무슨 뜻이야?", "통계가 뭐야?"])
def test_out_of_scope_kept(q, idx, tmp_path):
    assert _analyze(q, {}, idx, tmp_path, intent="범위 밖")["status"] == "out_of_scope"   # 통계 요청 말 또는 지역·시점이 없음


# ── 2) 재작성 검증: '전국' 은 질문에 있을 때만 ──
TODAY = date(2026, 11, 27)


def _v(q, hcx):
    from backend.rag.query_analyzer.extract import rule_extract
    from backend.rag.query_analyzer.terms import lookup_terms
    from backend.rag.query_analyzer.validate import validate_slots
    q2, found, _ = rule_extract(q, TODAY)
    return validate_slots({"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
                           "hcx_slots": {**hcx, "의도": "값 조회"}, "hcx_subs": []})["slots"]


@pytest.mark.parametrize("hcx", [{"시점": ["2024년"], "지표": ["인구수"]},
                                 {"시점": ["2024년"], "지역": ["전국"], "지표": ["인구수"]}])
def test_no_region_not_filled_nationwide(hcx):
    assert _v("2024년 인구수 알려줘", hcx)["지역"] == []      # HCX 가 '전국' 을 넣어도, 비워도 채우지 않음


@pytest.mark.parametrize("q", ["2024년 전국 인구수 알려줘", "2024년 우리나라 인구수 알려줘"])
def test_nationwide_kept_when_asked(q):
    assert _v(q, {"시점": ["2024년"], "지역": ["전국"], "지표": ["인구수"]})["지역"] == ["전국"]
