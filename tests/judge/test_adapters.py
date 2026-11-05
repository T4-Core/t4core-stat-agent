"""[NEW] judge/adapters.py 단위 테스트 — ViewResult → 단위 입력, adapter notes 해석"""
from backend.rag.judge.adapters import units_from_view_result, upstream_checks, view_note_slots
from backend.schemas.judge import ReasonCode, SlotStatus
from tests.judge._records import make_record

S = SlotStatus


def _view_result():
    # 서브질문 2개짜리 ViewResult. 두 번째 서브 단위는 filters 가 비어 있음 → 질문 전체 filters 사용
    rec = make_record(["시점", "항목", "값"], [["2023", "인구", 1]])
    return {"query_id": "6", "original": "부산 출생아 수 및 대구 사망자 수",
            "filters": {"지역": ["부산광역시", "대구광역시"]},
            "units": [
                {"unit_id": "main", "query": "q", "filters": {"지역": ["부산광역시", "대구광역시"]}, "candidates": [],
                 "views": [{"record": rec, "notes": ["시점 2024 은 이 표에 없음"], "rank": 1, "tbl_id": "DT_TEST"}]},
                {"unit_id": "6-1", "query": "부산 출생아", "filters": {"지역": ["부산광역시"]}, "candidates": [], "views": []},
                {"unit_id": "6-2", "query": "대구 사망자", "filters": None, "candidates": [], "views": []},
            ]}


def test_units_keep_own_filters():
    units = units_from_view_result(_view_result())
    assert [u.index for u in units] == [0, 1, 2]
    assert units[1].filters == {"지역": ["부산광역시"]}           # 서브질문 단위는 자기 슬롯
    assert units[2].filters == {"지역": ["부산광역시", "대구광역시"]}   # 비어 있으면 질문 전체 슬롯
    assert len(units[0].records) == 1 and units[0].view_notes == [["시점 2024 은 이 표에 없음"]]
    assert units[1].records == []                                # View 없는 단위도 목록에 남음 (no_views 판정용)


def test_upstream_unsupported_and_partial():
    per_unit, q = upstream_checks([
        "[국적] ['베트남'] — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)",
        "(하위 2) [시점] '2024년 9월' → 2024 (View 모듈은 연도 단위)",
    ])
    assert per_unit[0]["국적"].status == S.unsupported
    assert per_unit[0]["국적"].reason == ReasonCode.slot_dropped_upstream
    assert per_unit[2]["시점"].status == S.partial                # '(하위 2)' → 2번 서브 단위
    assert q == []


def test_upstream_informational_notes_ignored():
    per_unit, q = upstream_checks([
        "[지역] '전국'과 다른 지역이 함께 있어 '전국'은 뺌 (지역 지정 시 전국 합계는 따로 나오지 않음)",
        "[의도] '증감' → View 종류 '추이'",
    ])
    assert per_unit == {} and q == []


def test_upstream_rewrite_failed_is_question_reason():
    per_unit, q = upstream_checks(["재작성 슬롯이 비어 원 질문으로 검색"])
    assert per_unit == {} and q == [ReasonCode.slot_dropped_upstream]


def test_upstream_same_slot_twice_keeps_worse():
    per_unit, _ = upstream_checks(["[시점] '2024년 9월' → 2024 (View 모듈은 연도 단위)",
                                   "[시점] View 모듈이 읽을 수 없는 값: '상반기'"])
    chk = per_unit[0]["시점"]
    assert chk.status == S.unsupported                           # partial + unsupported → 더 나쁜 쪽
    assert "9월" in chk.evidence and "상반기" in chk.evidence


def test_view_note_slots():
    assert view_note_slots("시점 2024 은 이 표에 없음 (수록 2015~2023)") == ["시점"]
    assert view_note_slots("항목: 지표·대상과 맞는 항목 없음 → '계'") == ["지표", "대상"]
    assert view_note_slots("행이 5000개를 넘어 앞부분만 사용") == []
