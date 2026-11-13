"""Evaluation Tool (수치 검증 · Ablation · View 판정 · Retriever/Generator 지표 · 실패 진단) + Deduplication Tool."""
from __future__ import annotations

from synthetic_gold_pipeline.schemas.dataset import (EvidenceGroup, ExpectedClaim, GenerationEval, GoldenRecord, M1Eval,
                                                      M2Eval, M3Eval, ModuleEval, Provenance, RetrievalEval,
                                                      VerificationMetrics)
from synthetic_gold_pipeline.schemas.planning import (AnswerabilityType, HopType, Operand, OperationGraph, OperationPlan,
                                                       OperationStep, ReasoningType, SampledCluster)
from synthetic_gold_pipeline.schemas.verification import AblationOutcome, ViewLabel
from synthetic_gold_pipeline.tests.conftest import find_view
from synthetic_gold_pipeline.tools.calculation_tool import TableCalculationEngine
from synthetic_gold_pipeline.tools.deduplication_tool import DedupIndex, entity_signature, fact_signature
from synthetic_gold_pipeline.tools.evaluation_tool import (AblationChecker, NumericAnswerEvaluator, ViewJudge,
                                                            diagnose_failure, evaluate_generation, evaluate_retrieval,
                                                            extract_numbers)

POLICY = {"rounding_digits": [1, 2], "abs_tolerance": 0.05, "rel_tolerance": 0.0, "unit_required": True}
CLAIMS = [ExpectedClaim(claim_id="F", role="FINAL", value=-0.6878939, value_text="-0.7%", unit="%"),
          ExpectedClaim(claim_id="I1", role="INTERMEDIATE", value=2329865, value_text="2,329,865명", unit="명",
                        period="2023년", region="대구광역시"),
          ExpectedClaim(claim_id="I2", role="INTERMEDIATE", value=2313838, value_text="2,313,838명", unit="명",
                        period="2024년", region="대구광역시")]
EV = NumericAnswerEvaluator()
CP = {**POLICY, "rounding_digits": [0], "abs_tolerance": 0.5}


def test_correct_answer_passes():
    t = "대구광역시 총인구수: 2023년 2,329,865명, 2024년 2,313,838명. 증감률은 -0.7%입니다 (감소)."
    assert EV.evaluate(t, CLAIMS, POLICY, "GROWTH_RATE").passed


def test_value_bound_to_wrong_year_is_detected():
    """회귀: 두 원본값이 서로 다른 연도에 잘못 연결된 답변 (실제 생성 중 발견된 버그)."""
    t = "2024년 대구광역시 총인구수는 2,329,865명으로 2023년의 2,313,838명과 비교한 증감률은 -0.7%입니다."
    r = EV.evaluate(t, CLAIMS, POLICY, "GROWTH_RATE")
    assert not r.passed and r.binding_errors


def test_wrong_final_sign_unit_and_unsupported_numbers():
    base = "대구광역시 총인구수: 2023년 2,329,865명, 2024년 2,313,838명. "
    assert EV.evaluate(base + "증감률은 0.7% 증가했습니다.", CLAIMS, POLICY, "GROWTH_RATE").sign_ok is False
    assert EV.evaluate(base + "증감률은 -0.7입니다.", CLAIMS, POLICY, "GROWTH_RATE").unit_ok is False
    assert EV.evaluate(base + "증감률은 -0.9%입니다.", CLAIMS, POLICY, "GROWTH_RATE").final_value_ok is False
    r = EV.evaluate(base + "증감률은 -0.7%이며 약 16,027명 줄었습니다.", CLAIMS, POLICY, "GROWTH_RATE")
    assert "16,027명" in r.unsupported_numbers and not r.passed
    # 크기만 쓰고 '감소'로 방향을 말한 답은 인정
    assert EV.evaluate(base + "0.7% 감소했습니다.", CLAIMS, POLICY, "GROWTH_RATE").final_value_ok


def test_intermediate_swapped_into_final_detected():
    c = [ExpectedClaim(claim_id="F", role="FINAL", value=58.4, value_text="58.4%", unit="%"),
         ExpectedClaim(claim_id="I", role="INTERMEDIATE", value=54.3, value_text="54.3%", unit="%", period="2024년")]
    r = EV.evaluate("2024년 비율은 54.3%입니다.", c, POLICY)
    assert r.swap_detected and not r.passed


def test_rounding_policy():
    c = [ExpectedClaim(claim_id="F", role="FINAL", value=14.285714, value_text="14.3%", unit="%")]
    assert EV.evaluate("14.3%", c, POLICY).final_value_ok
    assert EV.evaluate("14.29%", c, POLICY).final_value_ok
    assert not EV.evaluate("14%", c, POLICY).final_value_ok        # 0자리 반올림은 정책상 불허


def test_number_extraction():
    ns = [n for n in extract_numbers("2024년 3월 서울은 945만 명, 1,234가구, 4.5건/천명, -1.3%p") if not n.is_period_token]
    assert [(float(n.value), n.unit) for n in ns] == [(9450000.0, "명"), (1234.0, "가구"), (4.5, "건/천명"), (-1.3, "%p")]


def test_label_numbers_are_masked():
    c = [ExpectedClaim(claim_id="F", role="FINAL", value=131046, value_text="131,046가구", unit="가구")]
    r = EV.evaluate("1인가구는 131,046가구입니다.", c, CP, mask_labels=["1인가구"])
    assert r.passed, r


# ── Ablation · View 판정 ───────────────────────────────────────────
def _growth_case(demo_env, b_view):
    idx = demo_env["index"]
    a = find_view(idx, "101_DT_DEMO_POP", "T20", "2023")
    ops = [Operand(operand_id="A", view_id=a, itm_id="T20", prd_de="2023", coordinates={"C1": "27"}),
           Operand(operand_id="B", view_id=b_view, itm_id="T20", prd_de="2024", coordinates={"C1": "27"})]
    plan = OperationPlan(plan_id="g", reasoning_type=ReasoningType.TIME_SERIES_COMPARISON, operands=ops,
                         operation=OperationGraph(steps=[OperationStep(step_id="s", op="GROWTH_RATE", inputs=["B", "A"])],
                                                  final_step_id="s"))
    cl = SampledCluster(sample_id="S", attempt_index=0, random_seed=1, reasoning_type=ReasoningType.TIME_SERIES_COMPARISON,
                        subtype="GROWTH_RATE", hop_type=HopType.SINGLE_TABLE_MULTI_VIEW, view_ids=[a, b_view],
                        table_ids=["101_DT_DEMO_POP"])
    eng = TableCalculationEngine(idx, demo_env["cfg"]["calculation"])
    return plan, cl, eng, eng.run(plan, cl.view_ids)


def test_ablation_and_alternative_positive(demo_env):
    idx = demo_env["index"]
    b = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    plan, cl, eng, calc = _growth_case(demo_env, b)
    assert calc.success
    res, alts = AblationChecker(idx, eng).run(plan, calc, cl)
    assert all(r.outcome == AblationOutcome.NECESSARY for r in res)
    alt_tables = {idx.view(v).parent_table_id for v in alts[b]}
    assert "101_DT_DEMO_POP_OLD" in alt_tables                                # 같은 값의 구 표
    assert any(idx.view(v).input_mode.value == "STORED_VIEW" for v in alts[b])   # 저장된 View(대구 포함)
    sv = next(v for v in idx.views.values() if v.input_mode.value == "STORED_VIEW")
    foreign = find_view(idx, "101_DT_DEMO_FOREIGN", "T1", "2024")
    proj = find_view(idx, "101_DT_DEMO_PROJ", "T1", "2024", {"C1": ["1"]})
    judg, groups = ViewJudge(idx).judge(cl, calc, alts, [foreign, proj, find_view(idx, "101_DT_DEMO_POP", "T20", "2022")])
    lab = {j.view_id: j.label for j in judg}
    assert lab[foreign] == ViewLabel.HARD_NEGATIVE and lab[proj] == ViewLabel.HARD_NEGATIVE
    assert lab[find_view(idx, "101_DT_DEMO_POP", "T20", "2022")] == ViewLabel.HARD_NEGATIVE
    assert lab[sv.view_id] == ViewLabel.ALTERNATIVE_POSITIVE
    assert set(groups) == {"R1", "R2"} and b in groups["R2"]["acceptable_view_ids"]


def test_ablation_replaceable_when_same_fact_remains(demo_env):
    """같은 Fact 를 주는 View 두 개(신·구 표)를 Positive 로 쓰면 하나는 필수가 아님."""
    idx = demo_env["index"]
    a = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    b = find_view(idx, "101_DT_DEMO_POP_OLD", "T20", "2024")
    ops = [Operand(operand_id="A", view_id=a, itm_id="T20", prd_de="2024", coordinates={"C1": "11"}),
           Operand(operand_id="B", view_id=b, itm_id="T20", prd_de="2024", coordinates={"C1": "26"})]
    plan = OperationPlan(plan_id="r", reasoning_type=ReasoningType.CROSS_TABLE_RATIO, operands=ops,
                         operation=OperationGraph(steps=[OperationStep(step_id="s", op="DIFFERENCE", inputs=["A", "B"])],
                                                  final_step_id="s"))
    cl = SampledCluster(sample_id="S", attempt_index=0, random_seed=1, reasoning_type=ReasoningType.CROSS_TABLE_RATIO,
                        subtype="X", hop_type=HopType.MULTI_TABLE_MULTI_VIEW, view_ids=[a, b], table_ids=[])
    eng = TableCalculationEngine(idx, {})
    calc = eng.run(plan, [a, b])
    res, _ = AblationChecker(idx, eng).run(plan, calc, cl)
    assert any(r.outcome == AblationOutcome.REPLACEABLE for r in res)


# ── Retriever / Generator 평가 ────────────────────────────────────
def record(expected_abstention=False):
    groups = {"R1": EvidenceGroup(description="2023", acceptable_view_ids=["vA", "vA2"], acceptable_table_ids=["T1", "T1b"]),
              "R2": EvidenceGroup(description="2024", acceptable_view_ids=["vB"], acceptable_table_ids=["T1"])}
    return GoldenRecord(
        dataset_id="X", data_snapshot_id="s", reasoning_type=ReasoningType.TIME_SERIES_COMPARISON,
        answerability_type=AnswerabilityType.ANSWERABLE, difficulty="easy", question_original="q", question_paraphrased="q2",
        random_seed=1,
        retrieval_eval=RetrievalEval(golden_view_ids=["vA", "vB"], golden_table_ids=["T1"], golden_org_table_ids=["101_T1"],
                                     unjudged_view_ids=["vU"], hard_negative_view_ids=["vN"], required_evidence_groups=groups),
        generation_eval=GenerationEval(reference_answer="r", expected_claims=CLAIMS, expected_abstention=expected_abstention,
                                       comparison_policy={"rounding_digits": [1, 2], "abs_tolerance": 0.05}),
        module_eval=ModuleEval(M1=M1Eval(expected_intent="x", expected_filters={"operation": "GROWTH_RATE",
                                                                                 "periods": ["2023", "2024"],
                                                                                 "regions": ["대구광역시"]}),
                               M2=M2Eval(), M3=M3Eval()),
        verification_metrics=VerificationMetrics(),
        provenance=Provenance(sample_id="S", attempt_index=0, created_at="t", pipeline_version="0"))


def test_retrieval_metrics_with_alternatives_and_unjudged():
    r = evaluate_retrieval(record(), ["vN", "vU", "vA2", "vX", "vB"], ["T9", "T1b", "T1"], ks=(1, 2, 3))
    assert r["view_n_unjudged_removed"] if "view_n_unjudged_removed" in r else r["n_unjudged_removed"] == 1
    assert r["view_Hit@1"] == 0.0 and r["view_Hit@2"] == 1.0          # vU 제외 후 vA2 가 2위
    assert r["view_All_Hit@2"] == 0.0 and r["view_All_Hit@3"] == 0.0
    r4 = evaluate_retrieval(record(), ["vN", "vU", "vA2", "vX", "vB"], None, ks=(4,))
    assert r4["view_All_Hit@4"] == 1.0 and r4["view_Requirement_Coverage@4"] == 1.0
    assert abs(r["view_MRR"] - 0.5) < 1e-9
    assert r["table_Hit@2"] == 1.0 and r["table_All_Hit@3"] == 1.0
    assert 0 < r4["view_NDCG@4"] <= 1


def test_generation_metrics_and_abstention():
    g = evaluate_generation(record(), "대구광역시: 2023년 2,329,865명, 2024년 2,313,838명. 증감률 -0.7%.", pred_operation="GROWTH_RATE")
    assert g["Numeric_Accuracy"] == 1.0 and g["Unit_Accuracy"] == 1.0 and g["Intermediate_Fact_Accuracy"] == 1.0
    assert g["Operation_Correctness"] == 1.0 and g["Abstention_Accuracy"] == 1.0
    g = evaluate_generation(record(True), "제공된 자료로는 확인할 수 없습니다.")
    assert g["Abstention_Accuracy"] == 1.0
    g = evaluate_generation(record(True), "답은 3명입니다.")
    assert g["Abstention_Accuracy"] == 0.0


def test_failure_diagnosis():
    rec = record()
    assert diagnose_failure(rec, None)["first_failure"] == "INSUFFICIENT_TRACE"
    d = diagnose_failure(rec, {"query_analysis": {"filters": {"시점": ["2022년"], "지역": ["대구광역시"]}},
                               "retrieval": {"table_ids": ["T9"]}})
    assert d["first_failure"] == "QUERY_CONDITION_ERROR" and d["root_cause"] == "QUERY_CONDITION_ERROR"
    d = diagnose_failure(rec, {"retrieval": {"table_ids": ["T1b"]}, "final_context": {"view_ids": ["vA"]}})
    assert d["first_failure"] in ("PARTIAL_RETRIEVAL", "FINAL_CONTEXT_MISS")
    d = diagnose_failure(rec, {"retrieval": {"table_ids": ["T1"]}, "final_context": {"view_ids": ["vA", "vB"]},
                               "answer": {"text": "증감률 -5.0%"}})
    assert d["first_failure"] in ("ANSWER_GENERATION_ERROR", "CALCULATION_ERROR")
    d = diagnose_failure(record(True), {"answer": {"text": "3명입니다"}})
    assert d["first_failure"] == "ABSTENTION_ERROR"


# ── Dedup ──────────────────────────────────────────────────────────
def test_dedup_rules():
    d = DedupIndex(threshold=0.85)
    fs = fact_signature("GROWTH_RATE", "GROWTH_RATE", [{"TBL_ID": "T", "ITM_ID": "I", "PRD_DE": "2023", "dims": {"C1": "11"}}], "SCALAR")
    es = entity_signature(["서울특별시"], ["2023", "2024"], ["총인구수"], "GROWTH_RATE")
    q = ["2023년 대비 2024년 서울특별시 총인구수 증감률은?", "서울 인구 23년 대비 24년 얼마나 변했어?"]
    assert not d.check("a", q, fs, es).is_duplicate                 # original/paraphrase 쌍은 서로 비교하지 않음
    d.add("a", q, fs, es)
    assert d.check("b", ["표현만 바꾼 질문"], fs, "other").reason == "SAME_FACT_SIGNATURE"
    fs2 = fact_signature("GROWTH_RATE", "GROWTH_RATE", [{"TBL_ID": "T", "ITM_ID": "I", "PRD_DE": "2023", "dims": {"C1": "26"}}], "SCALAR")
    es2 = entity_signature(["부산광역시"], ["2023", "2024"], ["총인구수"], "GROWTH_RATE")
    dec = d.check("c", ["2023년 대비 2024년 부산광역시 총인구수 증감률은?"], fs2, es2)
    assert not dec.is_duplicate and dec.max_score > 0.5              # 비슷하지만 지역이 다름 → 유지
    dec = d.check("e", ["2023년 대비 2024년 서울특별시 총인구수 증감률은?"], fs2, es)
    assert dec.is_duplicate and dec.reason == "NEAR_DUPLICATE_SAME_ENTITIES"
