"""재작성 슬롯 → View 입력 변환 (adapter.py) 과 API 스키마 (HCX·데이터 없음)"""
import typing
from dataclasses import asdict

from backend.rag.query_analyzer.adapter import (VIEW_INTENT, is_out_of_scope, resolve_sub_intents, sub_intents_of,
                                                to_view_bundle)
from backend.rag.query_analyzer.rewrite import make_bundle
from backend.rag.query_analyzer.sentence import build_sentences
from backend.rag.query_analyzer.slots import INTENTS, SLOT_KEYS
from backend.rag.query_analyzer.validate import validate_slots
from backend.schemas.query import EX_VIEW_BUNDLE, Intent, QueryBundle


def _empty(**kw):
    return {**{k: [] for k in SLOT_KEYS}, **kw}


def _run(q, found, slots, subs=()):
    """HCX 응답(slots, subs)을 넣고 검증 → 문장 → 묶기를 코드로 계산 (run_pipeline 과 같은 순서, HCX 없음)"""
    v = validate_slots({"question": q, "input_question": q, "rule_found": found, "term_hits": [],
                        "hcx_slots": _empty(**slots), "hcx_subs": [_empty(**s) for s in subs]})
    return v, make_bundle(q, v, build_sentences(v))


SUB_Q = "2023년 충남 인구랑 시군구별 고령인구비율 순위"
SUB_RUN = (SUB_Q, {"시점": ["2023년"], "지역": ["충청남도"]},
           {"시점": ["2023년"], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수", "고령인구비율"],
            "비교축": ["시군구"], "의도": ["값 조회", "순위"]},
           [{"시점": ["2023년"], "지역": ["충청남도"], "대상": ["인구"], "지표": ["인구수"], "의도": "값 조회"},
            {"시점": ["2023년"], "지역": ["충청남도"], "지표": ["고령인구비율"], "비교축": ["시군구"], "의도": "순위"}])


def test_intents_in_sync():
    assert list(typing.get_args(Intent)) == INTENTS  # API 스키마의 의도 9종 = 재작성 모듈
    assert set(VIEW_INTENT) == set(INTENTS)


def test_sub_intents_follow_each_sub_question():
    v, b = _run(*SUB_RUN)
    assert b.intent == "값 조회" and sub_intents_of(v) == ["값 조회", "순위"]
    vb, notes = to_view_bundle(b, "q1", sub_intents=sub_intents_of(v))
    assert [f["의도"] for f in vb["sub_filters"]] == ["값 조회", "순위"]
    assert vb["filters"]["의도"] == "값 조회" and notes == []
    QueryBundle(**vb)  # View 입력 검증 통과


def test_sub_intents_from_saved_bundle():
    # 하위 의도를 넘기지 않으면 하위 문장 끝 의도어로 정함
    _, b = _run(*SUB_RUN)
    assert resolve_sub_intents(asdict(b)) == ["값 조회", "순위"]
    vb, _ = to_view_bundle(asdict(b), "q1")
    assert [f["의도"] for f in vb["sub_filters"]] == ["값 조회", "순위"]


def test_swagger_example_matches_adapter():
    _, b = _run(*SUB_RUN)
    vb, _ = to_view_bundle(b, "q1", sub_intents=["값 조회", "순위"])
    got = QueryBundle(**vb).model_dump(by_alias=True, exclude_none=True)
    want = QueryBundle(**EX_VIEW_BUNDLE).model_dump(by_alias=True, exclude_none=True)
    assert {k: v for k, v in got.items() if k != "search_text"} == {k: v for k, v in want.items() if k != "search_text"}


def test_out_of_scope_is_not_rewrite_failure():
    v, b = _run("합계출산율이 무슨 뜻이야?", {}, {"대상": ["합계출산율"], "의도": ["범위 밖"]})
    assert b.intent == "범위 밖" and b.filters is None and is_out_of_scope(b)
    vb, notes = to_view_bundle(b, "q1")
    assert vb["filters"] is None and vb["search_text"] == b.original
    assert notes and notes[0].startswith("[의도] 범위 밖")
    assert not any("재작성 슬롯이 비어" in n for n in notes)  # 판단 모듈이 slot_dropped_upstream 으로 읽지 않게


def test_age_target_becomes_age_range():
    # 용어 사전: '노인' → 대상 '고령자' (연령 없음) → View 는 대상 '인구' + 연령 65세 이상으로 자름
    _, b = _run("2025년 서울 노인 몇 명", {"시점": ["2025년"], "지역": ["서울특별시"]},
                {"시점": ["2025년"], "지역": ["서울특별시"], "대상": ["노인"], "지표": ["인구수"], "의도": ["값 조회"]})
    assert b.filters["대상"] == ["고령자"] and "연령" not in b.filters
    vb, notes = to_view_bundle(b)
    assert vb["filters"]["대상"] == ["인구"] and vb["filters"]["연령"] == {"from": 65, "to": None}
    assert any("고령자" in n for n in notes)
    assert vb["search_text"] == "2025년 서울특별시 고령자 인구수"  # 검색 문장은 재작성 그대로


def test_age_target_keeps_explicit_age():
    vb, _ = to_view_bundle({"original": "x", "rewritten": "x", "intent": "값 조회",
                            "filters": {"대상": ["고령자"], "연령": ["70세 이상"], "지표": ["인구수"]}})
    assert vb["filters"]["연령"] == {"from": 70, "to": None} and vb["filters"]["대상"] == ["인구"]


def test_intent_mapping_to_view():
    for it, view in (("증감률", "추이"), ("증감", "추이"), ("구성비", "비교"), ("합계", "값 조회")):
        vb, notes = to_view_bundle({"original": "x", "rewritten": "x", "intent": it, "filters": {"지표": ["인구수"]}})
        assert vb["filters"]["의도"] == view and any(it in n for n in notes)


def _regions(regions, **kw):
    vb, notes = to_view_bundle({"original": "x", "rewritten": "x", "intent": "비교",
                                "filters": {"시점": ["2023년"], "지역": regions, "지표": ["혼인건수"], **kw}})
    return vb["filters"].get("지역"), notes


def test_national_with_other_regions_is_kept():
    # '2023년 전국과 서울의 혼인건수 비교' → 전국 합계 행과 서울 행을 함께 조회 (예전: 전국을 지움)
    q = "2023년 전국과 서울의 혼인건수 비교"
    _, b = _run(q, {"시점": ["2023년"], "지역": ["전국", "서울특별시"]},
                {"시점": ["2023년"], "지역": ["전국", "서울특별시"], "대상": ["혼인"], "지표": ["혼인건수"], "의도": ["비교"]})
    vb, notes = to_view_bundle(b)
    assert vb["filters"]["지역"] == ["전국", "서울특별시"], vb["filters"]
    assert any("전국 합계 행도 같이 조회" in n for n in notes)
    assert _regions(["서울특별시", "전국"])[0] == ["서울특별시", "전국"]     # 순서는 질문대로


def test_national_only_and_regions_only_unchanged():
    assert _regions(["전국"]) == (None, [])                                  # 전국만 → View 기본값(전국 합계)
    assert _regions(["서울특별시", "부산광역시"])[0] == ["서울특별시", "부산광역시"]
    assert _regions(["전국", "전국"])[0] is None
