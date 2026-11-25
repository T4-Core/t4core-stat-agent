"""차트 구조 판정 (checks/chart_structure.py): 요구 결과 · 조건(정답 좌표 기준) · 표시 · 좌표 포함, 판정 규칙 버전 분기

fixture: v2 isolated 슬롯 실행 1회차의 차트 필드 발췌 (fixtures/chart_cases.json). HCX 없음
"""
import copy
import json
from pathlib import Path

import pytest

from eval.generator.checks import chart_structure as cs
from eval.generator.schema import Question
from eval.generator.verdict import judge

FX = json.loads((Path(__file__).parent / "fixtures" / "chart_cases.json").read_text(encoding="utf-8"))["cases"]


def _case(cid, rules=2):
    c = FX[cid]
    run = copy.deepcopy(c["run"])
    if rules is None:
        run.pop("judge_rules", None)
    else:
        run["judge_rules"] = rules
    return Question.model_validate(c["question"]), run


def _bad(cid, code=None):
    q, run = _case(cid)
    return [f for f in cs.check(q, run) if f.ok is False and (code is None or f.code == code)]


# ── ② 조건: Generator 형태 검증은 통과했지만 정답 좌표와 대조하면 위반 ──
def test_dumbbell_category_and_pair_swapped():
    """C15: 범주(label)가 시점, 양 끝이 가시 · 다시. 정답은 지역마다 2023 ↔ 2024"""
    f, = _bad("C15", "chart_requirement")
    assert f.stage == "stage1" and f.module == "M3" and "범주(label) 시점" in f.message and "양 끝 시점" in f.message


def test_dumbbell_missing_region_coordinate():
    """C15: M3 가 나시를 빼고 계산 → 차트에 정답 좌표 (나시, 2023) · (나시, 2024) 가 없다"""
    f, = _bad("C15", "chart_covers_final")
    assert f.stage == "stage2" and {m["지역"] for m in f.detail["missing"]} == {"나시"}


@pytest.mark.parametrize("cid", ["C01", "C04", "C08", "C10", "C12", "C14"])
def test_correct_charts_pass_every_requirement(cid):
    """요구 종류를 정확히 그린 대조군: 조건 · 표시 · 좌표 포함 위반이 없다"""
    q, run = _case(cid)
    fs = cs.check(q, run)
    assert not [f for f in fs if f.ok is False]
    assert any(f.code == "chart_requirement" and f.ok for f in fs)


def test_unknown_requirement_is_not_judged():
    q, run = _case("C12")
    q.v2["required_chart"]["requirements"] = ["two_dimensions_required", "new_code_x"]
    rows = [f for f in cs.check(q, run) if f.code == "chart_requirement"]
    assert [f.ok for f in rows] == [True, None] and rows[1].source == "adapter"


# ── ③ 표시 ──
def test_secondary_series_clipped_and_no_y2_axis():
    """C09: line + y2 encoding. 합성 비율(1 · 2 · 3)이 y 축 [5, 35] 밖, 보조축 계열 없음"""
    rows = _bad("C09", "chart_visible")
    assert {f.module for f in rows} == {"M5", "M3"}
    assert any("[5.0, 35.0] 밖" in f.message for f in rows) and any("보조축 계열 없음" in f.message for f in rows)


def test_visible_applies_to_any_set():
    """③ 은 정답 데이터가 필요 없다: core34 문항에도 적용"""
    _, run = _case("C09")
    q = Question.model_validate({"id": "Q99", "question": "q"})
    assert [f.code for f in cs.check(q, run) if f.ok is False] == ["chart_visible", "chart_visible"]


# ── ① 요구 결과 ──
def test_unmet_type_without_notice_is_stage2():
    f, = _bad("C11", "chart_outcome")
    assert f.stage == "stage2" and f.module == "M2" and "고지 없음" in f.message


def test_unmet_type_with_notice_is_metric_and_owner_m3():
    """C03: M2 는 stacked_bar 를 골랐지만 M3 검증(parts_sum_to_total) 실패로 line 대체 + 고지"""
    f, = _bad("C03", "chart_outcome")
    assert f.stage == "metric" and f.module == "M3"


def test_per_subquestion_type():
    """C20: 혼인건수 추이는 line 요구인데 bar"""
    f, = _bad("C20", "chart_outcome")
    assert f.sub_key == "marriage_trend" and f.stage == "stage2"


def test_fallback_requires_notice():
    """C16: 음수가 있어 pie → bar 대체는 맞지만 데이터셋이 요구한 고지가 없다"""
    f, = _bad("C16", "chart_outcome")
    assert "고지 필요" in f.message and f.stage == "stage2"


# ── 판정 규칙 버전: 과거 실행은 다시 판정하지 않는다 ──
@pytest.mark.parametrize("rules", [None, 1])
def test_previous_rule_version_gets_no_chart_findings(rules):
    q, run = _case("C15", rules)
    assert cs.check(q, run) == []


def test_verdict_holds_on_chart_stage2_only_for_new_runs():
    """chart_outcome · chart_covers_final 미충족만 있는 실행: 규칙 2 → 보류(chart_unmet), 규칙 1 → 영향 없음"""
    q, run = _case("C11")
    v2, v1 = judge(q, run), judge(q, _case("C11", None)[1])
    assert v2.judge_rules == 2 and "chart_unmet" in v2.tags and v2.verdict in ("보류", "미달")
    assert v1.judge_rules == 1 and "chart_unmet" not in v1.tags
    assert not [f for f in v1.findings if f["code"] in cs.CODES]


# ── Generator 자체 검증과의 차이 (독립성): 형태 검증은 통과, 의미 검증은 위반 ──
def test_generator_shape_check_passes_c15_but_semantic_check_fails():
    from backend.agent.chart_calculate.validate import check_chart
    from backend.schemas.chart import ChartContent
    q, run = _case("C15")
    content = ChartContent.model_validate(run["modules"]["module3"]["chart_contents"][0])
    assert check_chart(content, ["two_points_per_category"]).passed
    assert _bad("C15", "chart_requirement")


# ── ⑤ 차트-답변 일관성 · 차트 금지 (judge_rules >= 3) ──
from types import SimpleNamespace  # noqa: E402

ANSWER, HOLD = [SimpleNamespace(expect="answer")], [SimpleNamespace(expect="hold")]


def _with_answer(cid, rules=3, **answer):
    q, run = _case(cid, rules)
    run["modules"]["answer"] = {"answer": "x", "insufficient": False, "method": "hcx", **answer}
    return q, run


def test_chart_drawn_but_answer_has_no_result_is_stage1():
    """C01: line 차트가 그려졌는데 답변은 '계산된 결과가 없어…' (method=none, insufficient)"""
    q, run = _with_answer("C01", insufficient=True, method="none")
    f, = [x for x in cs.consistency(q, run, ANSWER) if x.code == "chart_answer_consistent"]
    assert f.ok is False and f.stage == "stage1" and f.module == "M3"


def test_chart_with_numeric_answer_is_consistent():
    q, run = _with_answer("C15")
    f, = [x for x in cs.consistency(q, run, ANSWER) if x.code == "chart_answer_consistent"]
    assert f.ok is True


def test_answer_consistency_needs_an_expected_answer_and_a_drawn_chart():
    q, run = _with_answer("C01", insufficient=True, method="none")
    assert not cs.consistency(q, run, HOLD)                         # 기대 hold 문항은 ⑤a 대상이 아니다
    run["modules"]["drawn"] = [{"chart_id": "c1", "status": "skipped"}]
    assert not cs.consistency(q, run, ANSWER)                       # 차트가 없으면(표만) 모순이 아니다


def test_forbidden_chart_drawn_is_stage2_and_not_a_wrong_value():
    q, run = _with_answer("C01", insufficient=True, method="template")
    q = Question.model_validate({**q.model_dump(), "chart_mode": "forbidden", "chart_types": [None]})
    f, = [x for x in cs.consistency(q, run, HOLD) if x.code == "chart_forbidden_drawn"]
    assert f.ok is False and f.stage == "stage2" and f.code in cs.STAGE2
    run["modules"]["drawn"] = []
    f, = [x for x in cs.consistency(q, run, HOLD) if x.code == "chart_forbidden_drawn"]
    assert f.ok is True


def test_consistency_rules_apply_only_from_version_3():
    for rules in (None, 1, 2):
        q, run = _with_answer("C01", rules, insufficient=True, method="none")
        assert cs.consistency(q, run, ANSWER) == []


def test_verdict_misses_on_chart_answer_mismatch_only_for_new_runs():
    q, run = _with_answer("C01", insufficient=True, method="none")
    v3, v2 = judge(q, run), judge(q, _with_answer("C01", 2, insufficient=True, method="none")[1])
    assert v3.verdict == "미달" and "chart_inconsistent" in v3.tags and "M3" in v3.first_failure
    assert "chart_inconsistent" not in v2.tags and v2.verdict == "보류"          # 규칙 2: 답변 누락 보류만
