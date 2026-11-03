"""[NEW] judge/aggregate.py 단위 테스트 — 점수 계산과 판정 규칙 (JudgeConfig 설명 때의 계산 예시 포함)"""
import pytest

from backend.rag.judge.adapters import UnitInput, upstream_checks
from backend.rag.judge.aggregate import judge_question, judge_record, judge_unit
from backend.schemas.judge import JudgeConfig, ReasonCode, SlotTier, UnitJudge, Verdict
from tests.judge._records import make_record

V, R = Verdict, ReasonCode
CFG = JudgeConfig()

# 2023년 대구 남자 인구 (전 연령 합계, 연령 분류 없음)
COLS = ["시점", "행정구역(시도)별", "성별", "항목", "값"]
ROWS = [["2023", "대구광역시", "남자", "인구", 1170000]]
# "작년(2024) 대구 남자 20대 인구 수"
FULL = {"시점": [2024], "지역": ["대구광역시"], "성별": ["남자"], "연령": {"from": 20, "to": 29},
        "지표": ["인구수"], "대상": ["인구"], "의도": "값 조회"}


def test_worked_example_0818_passes():
    # 시점 partial(대체) · 연령 missing(minor) · 나머지 match
    # (1+1+1+0.5)×1.0 + (1+0)×0.5 + 1×0.5 = 4.5,  가중치 합 4×1.0 + 2×0.5 + 0.5 = 5.5  → 0.8182
    rj = judge_record(make_record(COLS, ROWS), FULL, CFG)
    assert rj.score == pytest.approx(0.8182)     # approx: 소수 비교는 작은 오차를 허용해야 한다
    assert rj.verdict == V.pass_
    assert rj.reasons == [R.slot_substituted]
    assert rj.slots["연령"].status.value == "missing"


def test_stricter_threshold_changes_verdict():
    rj = judge_record(make_record(COLS, ROWS), FULL, JudgeConfig(pass_threshold=0.85))
    assert rj.verdict == V.partial               # 같은 0.818 이 기준만 바꾸면 partial


def test_core_missing_is_fail():
    wrong_region = {**FULL, "지역": ["부산광역시"]}   # {**FULL, …} = FULL 을 복사하고 지역만 덮어씀
    rj = judge_record(make_record(COLS, ROWS), wrong_region, CFG)
    assert rj.score == pytest.approx(0.6364)     # 평균만 보면 partial 이지만
    assert rj.verdict == V.fail                  # core(지역) missing → fail
    assert R.core_slot_missing in rj.reasons

    off = judge_record(make_record(COLS, ROWS), wrong_region, JudgeConfig(core_missing_is_fail=False))
    assert off.verdict == V.partial and R.core_slot_missing in off.reasons   # 규칙을 꺼도 사유는 남음


def test_empty_view_fails():
    rj = judge_record(make_record(COLS, [["2023", "대구광역시", "남자", "인구", None]]), FULL, CFG)
    assert rj.verdict == V.fail and rj.score == 0.0 and R.empty_view in rj.reasons


def test_not_requested_excluded_and_no_slots_is_full_score():
    only_region = judge_record(make_record(COLS, ROWS), {"지역": ["대구광역시"]}, CFG)
    assert only_region.score == 1.0              # 나머지 7개는 not_requested → 분모에서 빠짐
    nothing = judge_record(make_record(COLS, ROWS), {}, CFG)
    assert nothing.score == 1.0 and nothing.verdict == V.pass_


def test_upstream_dropped_slot_weighted_as_minor():
    up, _ = upstream_checks(["[국적] ['베트남'] — View 모듈에 아직 없는 슬롯"])
    rj = judge_record(make_record(COLS, ROWS), {"지역": ["대구광역시"]}, CFG, up[0])
    # 지역 1×1.0 + 국적(unsupported) 0×0.5 → 1.0 / 1.5
    assert rj.score == pytest.approx(0.6667) and rj.verdict == V.partial
    assert R.slot_dropped_upstream in rj.reasons

    no_weight = judge_record(make_record(COLS, ROWS), {"지역": ["대구광역시"]}, JudgeConfig(upstream_tier=None), up[0])
    assert no_weight.score == 1.0 and R.slot_dropped_upstream in no_weight.reasons   # 점수 제외, 사유만


def test_upstream_merges_with_view_check():
    up, _ = upstream_checks(["[시점] '2023년 9월' → 2023 (View 모듈은 연도 단위)"])
    rj = judge_record(make_record(COLS, ROWS), {"시점": [2023]}, CFG, up[0])
    chk = rj.slots["시점"]
    assert chk.status.value == "partial"         # View 에는 2023 이 있어 match 였지만 원래는 '9월'
    assert chk.reason == R.slot_dropped_upstream and "9월" in chk.evidence


def test_view_notes_only_in_evidence():
    rj = judge_record(make_record(COLS, ROWS), {"시점": [2023]}, CFG, None, ["시점 2024 은 이 표에 없음"])
    assert rj.slots["시점"].status.value == "match"             # 판정은 그대로
    assert "View 메모" in rj.slots["시점"].evidence


def test_unit_no_views_and_best_record():
    empty = judge_unit(UnitInput(0, "main", "q", FULL, []), CFG)
    assert empty.verdict == V.fail and empty.reasons == [R.no_views]

    bad = make_record(COLS, ROWS, rid="view::bad")
    good = make_record(COLS, ROWS, rid="view::good")
    unit = UnitInput(0, "main", "q", {"지역": ["대구광역시"]}, [bad, good])
    u = judge_unit(unit, CFG)
    assert u.best_record_id == "view::bad"       # 둘 다 pass·1.0 → 먼저 나온(검색 순위 높은) 것


def _u(uid, verdict, score):
    return UnitJudge(unit_id=uid, query="q", verdict=verdict, score=score)


def test_question_aggregate_rules():
    units = [_u("main", V.pass_, 0.9), _u("6-1", V.fail, 0.4)]
    all_ = judge_question("6", units, CFG)
    assert all_.verdict == V.fail and all_.score == 0.4                         # 최악 판정, 최솟값
    any_ = judge_question("6", units, JudgeConfig(unit_aggregate="any"))
    assert any_.verdict == V.pass_ and any_.score == 0.9
    mean = judge_question("6", units, JudgeConfig(unit_aggregate="mean"))
    assert mean.score == pytest.approx(0.65) and mean.verdict == V.partial
    none = judge_question("6", [], CFG)
    assert none.verdict == V.fail and none.reasons == [R.no_views]


def test_reasons_in_enum_order():
    units = [UnitJudge(unit_id="a", query="q", verdict=V.fail, score=0.0,
                       reasons=[R.intent_mismatch, R.no_views]),
             UnitJudge(unit_id="b", query="q", verdict=V.fail, score=0.0, reasons=[R.no_views])]
    res = judge_question("1", units, CFG, [R.slot_dropped_upstream])
    assert res.reasons == [R.no_views, R.slot_dropped_upstream, R.intent_mismatch]   # 중복 제거 + 정의 순서
    assert res.config_used.upstream_tier == SlotTier.minor
