"""시점 규칙 — 해끼리 비교(비교축 연도)인데 시점이 없으면 표의 수록 기간 전체 (clarify.apply_time_rules)"""
from backend.core.settings import Settings
from backend.rag.query_analyzer.clarify import apply_time_rules, missing_required, year_axis

S = Settings()


def test_year_axis_without_time_uses_whole_period():
    # '혼인건수가 가장 적은 해는?' → 비교축 연도 · 의도 순위 · 시점 없음. 재작성 모듈의 최신 연도 추정도 지움
    raw, rules = apply_time_rules({"비교축": ["연도"], "시점": ["2025년"], "지표": ["혼인건수"]},
                                  "혼인건수가 가장 적은 해는?", ["순위"], S)
    assert raw["시점"] == [] and "수록 기간 전체" in rules[0]
    assert S.year_compare_years == 0


def test_year_axis_recent_n_when_configured():
    raw, rules = apply_time_rules({"비교축": ["연도"]}, "혼인건수가 가장 많은 해", ["순위"],
                                  S.model_copy(update={"year_compare_years": 10, "base_year": 2025}))
    assert raw["시점"][0] == "2016년" and raw["시점"][-1] == "2025년" and len(raw["시점"]) == 10 and "최근 10년" in rules[0]


def test_explicit_period_and_trend_unchanged():
    assert apply_time_rules({"비교축": ["연도"], "시점": ["2016년"]}, "최근 10년 혼인건수가 많은 해 순서대로", ["순위"], S)[1] == []
    assert "최근 5년" in apply_time_rules({"비교축": ["연도"]}, "혼인건수 추이", ["추이"], S)[1][0]
    assert apply_time_rules({"비교축": ["시도"]}, "혼인건수가 가장 많은 시도", ["순위"], S) == ({"비교축": ["시도"]}, [])


def test_year_axis_does_not_ask_for_time():
    grounded = {"지역": [{"grounded": True}], "대상": [{"grounded": True, "value": "혼인건수"}]}
    assert year_axis({"비교축": ["연도"]}, S) == "연도"
    assert not [x for x in missing_required(grounded, {"비교축": ["연도"]}, S) if x[0] == "시점"]
    assert [x for x in missing_required(grounded, {"비교축": ["시도"]}, S) if x[0] == "시점"]
