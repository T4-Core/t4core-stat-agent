"""검증이 끝난 샘플 → 최종 GoldenRecord (retrieval_eval · generation_eval · module_eval · verification_metrics)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from synthetic_gold_pipeline import __version__
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.schemas.calculation import CalculationResult
from synthetic_gold_pipeline.schemas.dataset import (EvidenceGroup, ExpectedClaim, GenerationEval, GoldenRecord, M1Eval,
                                                      M2Eval, M3Eval, ModuleEval, Provenance, RetrievalEval,
                                                      VerificationMetrics)
from synthetic_gold_pipeline.schemas.metadata import DimensionType
from synthetic_gold_pipeline.schemas.planning import (AnswerabilityType, ComparisonPolicy, HopType, OperationPlan,
                                                       SampledCluster)
from synthetic_gold_pipeline.schemas.verification import (AblationResult, NumericCheck, QualityReview,
                                                           StatisticalValidationReport, VerificationStatus, ViewJudgement,
                                                           ViewLabel)
from synthetic_gold_pipeline.tools.calculation_tool import result_kind
from synthetic_gold_pipeline.tools.deduplication_tool import entity_signature, fact_signature
from synthetic_gold_pipeline.utils import now_iso, stable_hash

OP_INTENT = {"GROWTH_RATE": "두 시점 증감률", "DIFFERENCE": "두 시점 증감량", "PERCENTAGE_POINT_DIFFERENCE": "두 시점 %p 차이",
             "SHARE_RATIO": "두 지표의 비율", "SUM": "조건부 합계", "COUNT": "조건부 개수", "MEAN": "조건부 평균",
             "TOP_K": "순위 상위 K", "MAX": "최댓값 지역", "MIN": "최솟값 지역", "WEIGHTED_MEAN": "가중평균", "LOOKUP": "값 조회"}


def policy_for(unit: str | None, base: ComparisonPolicy, cfg: dict, display_digits: int | None = None) -> ComparisonPolicy:
    """허용 반올림 자릿수 = 설정값 ∪ Tool 이 정한 표시 자릿수 (예: 수량의 평균 28,734.3명 → 0·1자리)."""
    p = base.model_copy()
    kind = result_kind(unit or "").value
    digits = list(cfg.get("accepted_rounding_digits", {}).get(kind, [0] if kind in ("COUNT", "AMOUNT") else [1, 2]))
    if display_digits is not None and display_digits not in digits:
        digits.append(display_digits)
    p.rounding_digits = sorted(digits)
    p.abs_tolerance = 0.5 * 10 ** (-min(digits)) if digits else 0.0
    p.rel_tolerance = float(cfg.get("rel_tolerance", 0.0))
    return p


def final_digits(fin) -> int | None:
    if fin is None:
        return None
    if fin.value is not None:
        return fin.value.display_digits
    if fin.entity is not None:
        return fin.entity.value.display_digits
    return fin.ranking[0].value.display_digits if fin.ranking else None


def region_of(index: MetadataIndex, fact) -> str | None:
    v = index.view(fact.view_id)
    for lv in fact.coordinate.dims:
        d = v.dim(lv)
        if d and d.dim_type == DimensionType.REGION:
            return fact.coordinate.dim_names.get(lv)
    return None


def expected_claims(index: MetadataIndex, calc: CalculationResult, plan: OperationPlan) -> list[ExpectedClaim]:
    out = []
    fin = calc.final
    if fin and fin.kind == "SCALAR":
        out.append(ExpectedClaim(claim_id="C_FINAL", role="FINAL", value=fin.value.raw, value_text=fin.value.display,
                                 unit=fin.unit, accepted_forms=fin.value.formatted_candidates))
    elif fin and fin.kind == "ENTITY":
        out.append(ExpectedClaim(claim_id="C_E1", role="ENTITY", value_text=fin.entity.key_name,
                                 labels={"code": fin.entity.key_code}))
        out.append(ExpectedClaim(claim_id="C_E1_VALUE", role="ENTITY_VALUE", value=fin.entity.value.raw,
                                 value_text=fin.entity.value.display, unit=fin.unit,
                                 accepted_forms=fin.entity.value.formatted_candidates))
    elif fin and fin.kind == "RANKING":
        for e in fin.ranking:
            out.append(ExpectedClaim(claim_id=f"C_E{e.rank}", role="ENTITY", value_text=e.key_name,
                                     labels={"code": e.key_code, "rank": str(e.rank)}))
            out.append(ExpectedClaim(claim_id=f"C_E{e.rank}_VALUE", role="ENTITY_VALUE", value=e.value.raw,
                                     value_text=e.value.display, unit=fin.unit, accepted_forms=e.value.formatted_candidates))
    for f in calc.intermediate_facts:
        if f.kind != "SCALAR":
            continue
        out.append(ExpectedClaim(claim_id=f"C_{f.fact_id}", role="INTERMEDIATE", value=f.value.raw, value_text=f.value.display,
                                 unit=f.unit, period=f.period, region=region_of(index, f), item=f.item_name,
                                 labels=f.coordinate_labels, accepted_forms=f.value.formatted_candidates))
    for fid, nr in calc.resolved_thresholds.items():
        out.append(ExpectedClaim(claim_id=f"C_{fid}", role="THRESHOLD", value=nr.raw, value_text=nr.display, unit=nr.unit))
    flt = [s for s in calc.step_results if s.op == "FILTER"]
    if fin and fin.kind == "SCALAR" and plan.operation.steps[-1].op.value == "COUNT" and flt:
        for e in flt[-1].vector:
            out.append(ExpectedClaim(claim_id=f"C_M_{e.key_code}", role="ENTITY", value_text=e.key_name,
                                     labels={"code": e.key_code}))
    return out


def difficulty_of(cluster: SampledCluster, calc: CalculationResult, plan: OperationPlan) -> str:
    score = len(cluster.view_ids) - 1 + (len(cluster.table_ids) - 1) + len(plan.filters) + len(calc.unit_conversion_trace) \
        + max(0, len(plan.operation.steps) - 1)
    return "easy" if score <= 1 else ("medium" if score <= 3 else "hard")


def verification_status(det_ok: bool, sem_ok: bool | None, warnings: list[str], mock_llm: bool) -> tuple[VerificationStatus, bool]:
    if not det_ok or sem_ok is False:
        return VerificationStatus.REJECTED, True
    if sem_ok is None or mock_llm:
        return VerificationStatus.NEEDS_HUMAN_REVIEW, True
    if warnings:
        return VerificationStatus.VERIFIED_WITH_WARNINGS, True
    return VerificationStatus.VERIFIED, False


def build_answerable_record(*, index: MetadataIndex, cluster: SampledCluster, plan: OperationPlan, calc: CalculationResult,
                            plan_report: StatisticalValidationReport, result_report: StatisticalValidationReport,
                            ablation: list[AblationResult], judgements: list[ViewJudgement], groups: dict[str, dict],
                            question_original: str, question_paraphrased: str, reference_answer: str,
                            evidence_trace: list[dict], numeric_check: NumericCheck, quality: QualityReview | None,
                            mapping: dict[str, dict], snapshot_id: str, cfg: dict, llm_provider: str, llm_model: str,
                            planner_attempts: int) -> GoldenRecord:
    fin = calc.final
    last_op = plan.operation.steps[-1].op.value if plan.operation else ""
    final_op = next((s.op.value for s in plan.operation.steps if s.step_id == plan.operation.final_step_id), last_op)
    facts_coords = [f.coordinate.model_dump() for f in calc.intermediate_facts]
    fsig = fact_signature(cluster.subtype, final_op, facts_coords, fin.kind if fin else "NONE")
    regions = [r for r in (region_of(index, f) for f in calc.intermediate_facts if f.kind == "SCALAR") if r]
    periods = sorted({o.prd_de for o in plan.operands})
    items = sorted({index.view(o.view_id).item(o.itm_id).itm_nm for o in plan.operands if index.view(o.view_id).item(o.itm_id)})
    esig = entity_signature(regions, periods, items, final_op + ":" + cluster.subtype)
    dataset_id = "SG-" + fsig[3:15]
    views = [index.view(v) for v in cluster.view_ids]
    pos = [j for j in judgements if j.label == ViewLabel.POSITIVE]
    alt = [j.view_id for j in judgements if j.label == ViewLabel.ALTERNATIVE_POSITIVE]
    hn = [j.view_id for j in judgements if j.label == ViewLabel.HARD_NEGATIVE]
    unj = [j.view_id for j in judgements if j.label == ViewLabel.UNJUDGED]
    eg = {k: EvidenceGroup(**v) for k, v in groups.items()}
    unit = fin.unit if fin else None
    policy = policy_for(unit, plan.comparison_policy, cfg.get("evaluation", {}), final_digits(fin))
    claims = expected_claims(index, calc, plan)
    join_keys = []
    if plan.join_specification:
        join_keys.append({**plan.join_specification.model_dump(), "common_codes": cluster.common_codes})
    gt = fin.value if fin and fin.kind == "SCALAR" else (fin.entity.value if fin and fin.kind == "ENTITY" else None)
    region_dims = {}
    for f in calc.intermediate_facts:
        for k, v in f.coordinate_labels.items():
            region_dims.setdefault(k, [])
            if v not in region_dims[k]:
                region_dims[k].append(v)
    cond = []
    for fid, nr in calc.resolved_thresholds.items():
        fl = next(x for x in plan.filters if x.filter_id == fid)
        cond.append({"filter_id": fid, "comparator": fl.comparator, "threshold": nr.display, "condition_ref": fl.condition_ref})
    k = next((int(s.params.get("k", 3)) for s in plan.operation.steps if s.op.value == "TOP_K"), None)
    agg_constraints = []
    if any(o.group_by_level for o in plan.operands):
        agg_constraints.append("벡터 집계에서 총계·소계 코드 제외 (exclude_totals)")
    if calc.unit_conversion_trace:
        agg_constraints += [f"단위 변환 {t.from_unit}→{t.to_unit} ×{t.factor}" for t in calc.unit_conversion_trace]
    if final_op in ("SUM", "MEAN"):
        agg_constraints.append("합산 가능한 수량 단위만 합산·평균")
    m1 = M1Eval(expected_intent=f"{cluster.reasoning_type.value}:{cluster.subtype} ({OP_INTENT.get(final_op, final_op)})",
                expected_filters={"periods": periods, "period_labels": sorted({f.period for f in calc.intermediate_facts}),
                                  "regions": sorted(set(regions)), "items": items, "units": sorted({f.unit for f in calc.intermediate_facts}),
                                  "surveys": sorted({v.survey_name for v in views}), "operation": final_op, "conditions": cond, "k": k},
                expected_sub_questions=[g["description"] for g in groups.values()], ambiguity_handling="NONE",
                pass_criteria=["질문의 시점·지역·지표·연산을 모두 추출", f"필수 근거 그룹 {len(groups)}개에 대응하는 하위 질의 생성",
                               "서로 다른 주기·모집단을 같은 조건으로 합치지 않음"])
    m2 = M2Eval(expected_source_coordinates=[f.coordinate for f in calc.intermediate_facts],
                expected_dimensions=region_dims, expected_items=items, expected_periods=periods,
                expected_units=sorted({f.unit for f in calc.intermediate_facts}),
                expected_values=[{"fact_id": f.fact_id, "view_id": f.view_id, "period": f.period, "labels": f.coordinate_labels,
                                  "item": f.item_name, "value": f.value.exact_decimal, "unit": f.unit}
                                 for f in calc.intermediate_facts],
                aggregation_constraints=agg_constraints,
                pass_criteria=["원본 좌표(표·시점·항목·분류 코드)의 값이 정확히 일치", "단위·스케일 일치", "결측 기호를 0 으로 바꾸지 않음"])
    m3 = M3Eval(expected_table_ids=[v.parent_table_id for v in views], expected_view_ids=[v.view_id for v in views],
                required_evidence_groups=eg, expected_final_context=[v.view_id for v in views],
                pass_criteria=["모든 필수 근거 그룹을 최종 문맥에 포함 (그룹 안에서는 대체 View 허용)",
                               "Hard Negative View 를 근거로 쓰지 않음"])
    warnings = [i.message for r in (plan_report, result_report) for i in r.issues if i.severity.value == "WARNING"]
    if any(v.population_scope == "UNSPECIFIED" for v in views):
        warnings.append("모집단(population_scope) 규칙 미일치 — 모집단 호환성은 메타데이터로 확인되지 않음")
    low = [v.view_id for v in views if v.metadata_completeness.score < float(cfg.get("verification", {}).get(
        "min_metadata_completeness", 0.6))]
    if low:
        warnings.append(f"메타데이터 완결성 낮음: {low}")
    mock = llm_provider == "mock"
    if mock:
        warnings.append("Demo Mode: 질문 생성·의미 검수가 Mock LLM 규칙 응답 (실제 LLM 품질 검증 아님)")
    det_ok = plan_report.passed and result_report.passed and numeric_check.passed and all(
        a.outcome.value == "NECESSARY" for a in ablation)
    sem_ok = None if quality is None else bool(quality.semantic_valid and quality.statistical_validity and
                                                quality.question_answer_alignment)
    if quality is not None and not quality.multi_hop_necessity:
        warnings.append("LLM 검수: 멀티홉 불필요로 판단 (View 필요성은 Ablation 으로 확인됨)")
    status, human = verification_status(det_ok, sem_ok, warnings, mock)
    checks = {**{k: v.value for k, v in plan_report.checks.items()}, **{k: v.value for k, v in result_report.checks.items()}}
    vm = VerificationMetrics(
        deterministic_passed=det_ok, numeric_validation_passed=numeric_check.passed, unit_validation_passed=numeric_check.unit_ok,
        statistical_validation_passed=plan_report.passed and result_report.passed,
        ablation_passed=all(a.outcome.value == "NECESSARY" for a in ablation), per_view_ablation_results=ablation,
        semantic_validation_passed=sem_ok, paraphrase_equivalence_passed=quality.paraphrase_equivalence if quality else None,
        validation_errors=[], validation_warnings=warnings, verification_status=status, human_review_required=human,
        quality_review=quality, check_states=checks)
    return GoldenRecord(
        dataset_id=dataset_id, data_snapshot_id=snapshot_id, reasoning_type=cluster.reasoning_type, subtype=cluster.subtype,
        hop_type=hop_from_facts(calc, len(cluster.view_ids), groups),
        survey_names=list(dict.fromkeys(v.survey_name for v in views)), answerability_type=AnswerabilityType.ANSWERABLE,
        difficulty=difficulty_of(cluster, calc, plan), question_original=question_original,
        question_paraphrased=question_paraphrased, question_ids={"original": f"{dataset_id}-O", "paraphrased": f"{dataset_id}-P"},
        random_seed=cluster.random_seed,
        retrieval_eval=RetrievalEval(
            golden_view_ids=[j.view_id for j in pos], golden_table_ids=list(dict.fromkeys(v.tbl_id for v in views)),
            golden_org_table_ids=list(dict.fromkeys(v.parent_table_id for v in views)), alternative_positive_view_ids=alt,
            hard_negative_view_ids=hn, unjudged_view_ids=unj, required_evidence_groups=eg, join_keys=join_keys,
            source_coordinate_references=[f.coordinate for f in calc.intermediate_facts], retrieval_eligible=True,
            view_mapping_status=mapping),
        generation_eval=GenerationEval(
            exact_numeric_ground_truth=gt, final_answer=fin, intermediate_facts=calc.intermediate_facts,
            executed_sql=calc.executed_sql, executed_formula=calc.executed_formula, reference_answer=reference_answer,
            reference_answer_text=reference_answer.split("\n\n[근거]")[0].strip(),
            expected_claims=claims, expected_abstention=False, unit_conversion_trace=calc.unit_conversion_trace,
            comparison_policy=policy, evidence_trace=evidence_trace),
        module_eval=ModuleEval(M1=m1, M2=m2, M3=m3), verification_metrics=vm,
        provenance=Provenance(sample_id=cluster.sample_id, attempt_index=cluster.attempt_index, plan_id=plan.plan_id,
                              planner_attempts=planner_attempts, llm_provider=llm_provider, llm_model=llm_model,
                              created_at=now_iso(), pipeline_version=__version__),
        fact_signature=fsig + "|" + esig)


def hop_from_facts(calc: CalculationResult, n_views: int, groups: dict[str, dict] | None = None) -> HopType:
    """실제 근거 표 수로 판정. View 가 여러 개여도, 또는 대체 Positive 를 포함해 한 표로 모든 필수 근거 그룹을
    채울 수 있으면 SINGLE_TABLE (예: 신 표의 남자인구 ÷ 구 표의 총인구 — 신 표에도 같은 총인구가 있음)."""
    tables = {f.parent_table_id for f in calc.intermediate_facts} | {
        e.query_spec.get("view_id", "").split("::")[1] for e in calc.evidence_files if "::" in e.query_spec.get("view_id", "")}
    if groups:
        common = set.intersection(*[set(g.get("acceptable_table_ids") or []) for g in groups.values()])
        if common:
            return HopType.SINGLE_TABLE_MULTI_VIEW if n_views > 1 else HopType.SINGLE_TABLE_SINGLE_VIEW
    if len(tables) > 1:
        return HopType.MULTI_TABLE_MULTI_VIEW
    return HopType.SINGLE_TABLE_MULTI_VIEW if n_views > 1 else HopType.SINGLE_TABLE_SINGLE_VIEW


def signatures(rec: GoldenRecord) -> tuple[str, str]:
    a, _, b = rec.fact_signature.partition("|")
    return a, b or stable_hash(rec.dataset_id)


def decimal_of(x: Any) -> Decimal:
    return Decimal(str(x))
