"""[NEW] judge() 전체 흐름 테스트 — ViewResult(서브질문 포함) → JudgeResult"""
from backend.rag.judge import judge
from backend.schemas.judge import JudgeRequest, ReasonCode, Verdict
from tests.judge._records import make_record

COLS = ["시점", "행정구역(시도)별", "항목", "값"]
BUSAN_BIRTH = make_record(COLS, [["2023", "부산광역시", "출생아수", 13000]], rid="view::birth::Y::6-1-1::value")
DAEGU_DEATH = make_record(COLS, [["2023", "대구광역시", "사망자수", 20000]], rid="view::death::Y::6-2-1::value")


def _request(upstream_notes=None):
    """EX_QUERY_6 모양: '부산 출생아 수 및 대구 사망자 수' → main + 서브 2개"""
    main_f = {"지역": ["부산광역시", "대구광역시"], "대상": ["출생아", "사망자"], "의도": "값 조회"}
    sub1 = {"지역": ["부산광역시"], "대상": ["출생아"], "지표": ["출생아수"], "의도": "값 조회"}
    sub2 = {"지역": ["대구광역시"], "대상": ["사망자"], "지표": ["사망자수"], "의도": "값 조회"}
    views = {"query_id": "6", "original": "부산 출생아 수 및 대구 사망자 수", "filters": main_f, "units": [
        {"unit_id": "main", "query": "부산 출생아 수 및 대구 사망자 수", "filters": main_f, "candidates": [],
         "views": [{"record": BUSAN_BIRTH, "notes": [], "rank": 1, "tbl_id": "birth"}]},
        {"unit_id": "6-1", "query": "부산의 연도별 출생아 수", "filters": sub1, "candidates": [],
         "views": [{"record": BUSAN_BIRTH, "notes": [], "rank": 1, "tbl_id": "birth"}]},
        {"unit_id": "6-2", "query": "대구의 연도별 사망자 수", "filters": sub2, "candidates": [],
         "views": [{"record": DAEGU_DEATH, "notes": [], "rank": 1, "tbl_id": "death"}]},
    ]}
    bundle = {"query_id": "6", "original": "부산 출생아 수 및 대구 사망자 수", "filters": main_f,
              "sub_questions": ["부산의 연도별 출생아 수", "대구의 연도별 사망자 수"], "sub_filters": [sub1, sub2]}
    return {"bundle": bundle, "views": views, "upstream_notes": upstream_notes or []}


def test_sub_units_judged_with_own_slots():
    res = judge(_request())
    by_id = {u.unit_id: u for u in res.units}
    assert by_id["6-1"].verdict == Verdict.pass_     # 부산 출생아 View ↔ 부산 출생아 슬롯
    assert by_id["6-2"].verdict == Verdict.pass_     # 대구 사망자 View ↔ 대구 사망자 슬롯
    # main 은 부산·대구 둘 다 요청인데 View 에는 부산만 → 지역 partial, 대상(사망자) 없음
    assert by_id["main"].records[0].slots["지역"].status.value == "partial"
    assert res.verdict == by_id["main"].verdict     # all: 가장 나쁜 단위가 전체 판정
    assert res.score == min(u.score for u in res.units)


def test_upstream_note_reaches_result():
    res = judge(_request(["(하위 1) [국적] ['베트남'] — View 모듈에 아직 없는 슬롯"]))
    sub1 = next(u for u in res.units if u.unit_id == "6-1")   # next(…): 조건에 맞는 첫 번째
    assert sub1.records[0].slots["국적"].status.value == "unsupported"
    assert ReasonCode.slot_dropped_upstream in res.reasons


def test_dict_and_model_inputs_same():
    req = _request()
    assert judge(req) == judge(JudgeRequest.model_validate(req))
