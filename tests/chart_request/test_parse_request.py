"""T-6 · T-7 · T-8 · T-14 · T-23 · T-27: 질문에서 차트 지정 요청을 해석한다 (parse_chart_request)

순서: 후보 추출 → 문맥·범위 해석 → 긍정/제외 분류. 문맥을 먼저 걸면 제외·대안·절별 지정의 이름이 탈락한다.
"""
import pytest

from backend.agent.chart_decision.chart_decision_module.chart_type_preference import parse_chart_request


def codes(items):
    return [x["code"] for x in items]


def parse(sub="", original="", rewritten=""):
    return parse_chart_request(sub, original, rewritten)


# ── 제외 · 대안 · 절별 지정 (검토 2번: 문맥 검사가 이것들을 탈락시키면 안 된다) ─────────────
def test_negation_keeps_excluded_and_preferred():
    r = parse(original="시도별 인구를 막대 말고 원그래프로 보여줘")
    assert codes(r["excluded"]) == ["bar"] and codes(r["preferred"]) == ["pie"]


def test_negation_with_particle():
    r = parse(original="시도별 인구를 막대는 빼고 원그래프로 보여줘")
    assert codes(r["excluded"]) == ["bar"] and codes(r["preferred"]) == ["pie"]


def test_alternatives_keep_first_name_first():
    r = parse(original="시도별 인구를 막대나 원그래프로 보여줘")
    assert codes(r["preferred"]) == ["bar", "pie"] and r["excluded"] == []
    assert r["stage"]["reason"] is None and r["stage"]["applied"] is True


def test_per_clause_assignment_by_sub_question_topic():
    original = "서울은 막대, 부산은 꺾은선으로 인구를 보여줘"
    assert codes(parse(sub="서울 인구", original=original)["preferred"]) == ["bar"]
    assert codes(parse(sub="부산 인구", original=original)["preferred"]) == ["line"]


def test_ambiguous_scope_when_no_sub_question_matches():
    r = parse(sub="대구 인구", original="서울은 막대, 부산은 꺾은선으로 인구를 보여줘")
    assert r["stage"]["reason"] == "ambiguous_scope" and r["stage"]["applied"] is False
    assert r["preferred"] == []                                  # 첫 이름을 모든 차트에 쓰지 않는다


def test_sub_question_name_wins_over_original():
    r = parse(sub="서울 인구를 원그래프로", original="인구를 막대로 보여줘")
    assert codes(r["preferred"]) == ["pie"]


def test_single_request_in_original_applies_to_sub_question_without_name():
    r = parse(sub="2023년 서울 인구", original="2023년 서울 인구를 원그래프로 보여줘")
    assert codes(r["preferred"]) == ["pie"]


def test_rewritten_is_last_resort():
    r = parse(sub="서울 인구", original="서울 인구", rewritten="서울 인구 원그래프")
    assert codes(r["preferred"]) == ["pie"]


# ── 미지원 이름 ──────────────────────────────────────────────────────────────
def test_unsupported_name_is_recorded_not_dropped():
    r = parse(original="2023년 시도별 인구수를 히스토그램으로 보여줘")
    assert r["preferred"][0]["text"] == "히스토그램"
    assert r["preferred"][0]["code"] is None and r["preferred"][0]["supported"] is False
    assert r["stage"]["reason"] == "unsupported_type"


# ── 오탐 방지 (R-10, T-23) ────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "2023년 운동지도자 수는 몇 명인가요?",
    "서울 지도자 수는?",
    "시도별 막대 수를 알려줘",
    "시도별 인구 분포를 알려줘",                       # T-14: 차트 이름 없음
    "막대기 길이는 얼마인가요?",
])
def test_no_false_request(text):
    assert parse(original=text) is None


# ── 용법이 확인되는 정상 요청 ──────────────────────────────────────────────────
@pytest.mark.parametrize("text, chart", [
    ("시도별 인구를 막대로 보여줘", "bar"),
    ("시도별 인구를 막대그래프로 보여줘", "bar"),
    ("지도로 보여줘", "map"),
    ("지도 위에 시도별 인구를 보여줘", "map"),
    ("인구 피라미드로 보여줘", "pyramid"),
    ("서울 총인구를 인구 피라미드 차트로", "pyramid"),
    ("시도별 인구를 히트맵으로", "heatmap"),
    ("꺾은선으로 추이를 보여줘", "line"),
])
def test_valid_requests(text, chart):
    r = parse(original=text)
    assert r is not None and codes(r["preferred"]) == [chart]


def test_no_request_returns_none():
    assert parse(sub="서울 인구", original="서울 인구는 몇 명인가요?", rewritten="서울 인구") is None


def test_result_shape_matches_schema():
    from backend.schemas.chart import ChartRequestInfo
    r = parse(original="막대 말고 원그래프로 보여줘")
    info = ChartRequestInfo.model_validate(r)
    assert info.preferred[0].supported and info.excluded[0].code == "bar"
