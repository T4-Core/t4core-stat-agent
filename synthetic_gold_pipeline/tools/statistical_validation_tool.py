"""독립 Statistical Validation Tool — 연산 계획의 통계적 적합성을 결정론적으로 검사한다 (LLM 불필요).

계산 도구가 실행됐다고 정답이 통계적으로 옳다는 보장은 없다. 그래서 계산 전(plan)과 계산 후(result)에
데이터 정의 · 집계 기준 · 단위 · 주기 · 모집단 · 실측/추계 · 총계 중복 · 행 증폭 등을 따로 검사한다.

오류 분류
  retryable=True  : 계획의 구조적 오류 (없는 코드·항목, 쓰지 않은 View, 총계 포함 합산 등) → PlannerAgent 재시도
  retryable=False : 데이터 부족·통계적 비호환·없는 필수 시점·복구 불가 결측·분모 0 → 즉시 폐기
"""
from __future__ import annotations

import re
from decimal import Decimal

from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex, norm_item_name
from synthetic_gold_pipeline.schemas.calculation import CalculationResult
from synthetic_gold_pipeline.schemas.metadata import ValueKind
from synthetic_gold_pipeline.schemas.planning import AtomicOp, OperationPlan, SampledCluster
from synthetic_gold_pipeline.schemas.verification import (CheckState, Severity, StatisticalValidationReport,
                                                           ValidationIssue)
from synthetic_gold_pipeline.tools.plan_repair import leaf_depths
from synthetic_gold_pipeline.tools.units import unit_info


class StatisticalValidator:
    def __init__(self, index: MetadataIndex, graph: CompatibilityGraph, cfg: dict | None = None):
        cfg = cfg or {}
        self.index, self.graph = index, graph
        self.weighted_pairs = [(norm_item_name(p["value_item"]), norm_item_name(p["weight_item"]))
                               for p in cfg.get("weighted_mean_pairs", [])]
        self.share_den_include = [re.compile(p) for p in cfg.get("share_denominator_include_patterns", [])]
        self.share_den_exclude = [re.compile(p) for p in cfg.get("share_denominator_exclude_patterns", [])]
        self.max_abs_growth = float(cfg.get("max_abs_growth_rate_pct", 1000))
        self.incompatible_scopes = {frozenset(p) for p in cfg.get("incompatible_population_scopes", [])}

    # ── 도우미 ──
    @staticmethod
    def _issue(rep, code, msg, retryable=False, sev=Severity.ERROR, refs=None, stage="plan"):
        rep.issues.append(ValidationIssue(code=code, severity=sev, stage=stage, message=msg, retryable=retryable,
                                          refs=refs or []))

    @staticmethod
    def _roots(plan: OperationPlan, ref: str, seen=()) -> set[str]:
        ops = {o.operand_id for o in plan.operands}
        if ref in ops:
            return {ref}
        if ref in seen:
            return set()
        f = next((x for x in plan.filters if x.filter_id == ref), None)
        if f:
            return StatisticalValidator._roots(plan, f.target_ref, seen + (ref,)) | \
                StatisticalValidator._roots(plan, f.condition_ref, seen + (ref,))
        s = next((x for x in (plan.operation.steps if plan.operation else []) if x.step_id == ref), None)
        if s:
            out = set()
            for r in s.inputs:
                out |= StatisticalValidator._roots(plan, r, seen + (ref,))
            return out
        return set()

    @staticmethod
    def _value_roots(plan: OperationPlan, ref: str, seen=()) -> set[str]:
        """값이 흘러오는 operand (filter 는 target 만 따라감 — 조건 View 의 단위는 집계 대상이 아님)."""
        ops = {o.operand_id for o in plan.operands}
        if ref in ops:
            return {ref}
        if ref in seen:
            return set()
        f = next((x for x in plan.filters if x.filter_id == ref), None)
        if f:
            return StatisticalValidator._value_roots(plan, f.target_ref, seen + (ref,))
        s = next((x for x in (plan.operation.steps if plan.operation else []) if x.step_id == ref), None)
        out = set()
        for r in (s.inputs if s else []):
            out |= StatisticalValidator._value_roots(plan, r, seen + (ref,))
        return out

    # ── 계산 전 ──
    def validate_plan(self, plan: OperationPlan, cluster: SampledCluster) -> StatisticalValidationReport:
        rep = StatisticalValidationReport(passed=False)
        ck = rep.checks
        if plan.plan_status.value != "OK":
            self._issue(rep, "PLAN_REJECTED", f"Planner 가 계획을 거부: {plan.reject_reason}")
            ck["plan_status"] = CheckState.FAIL
            return self._finish(rep)
        ck["plan_status"] = CheckState.PASS
        if plan.reasoning_type != cluster.reasoning_type:
            self._issue(rep, "TAXONOMY_MISMATCH", f"사전 할당 유형 {cluster.reasoning_type.value} ≠ {plan.reasoning_type.value}",
                        retryable=True)
        ops = {o.operand_id: o for o in plan.operands}
        used_views = {o.view_id for o in plan.operands}
        unknown = used_views - set(cluster.view_ids)
        if unknown:
            self._issue(rep, "UNKNOWN_VIEW", f"샘플에 없는 View 사용: {sorted(unknown)}", retryable=True)
        unused = set(cluster.view_ids) - used_views
        ck["all_positive_views_used"] = CheckState.FAIL if unused else CheckState.PASS
        if unused:
            self._issue(rep, "UNUSED_VIEW", f"연산에 기여하지 않는 Positive View: {sorted(unused)}", retryable=True)
        if set(plan.required_view_ids) and set(plan.required_view_ids) != used_views:
            self._issue(rep, "REQUIRED_VIEWS_INCONSISTENT", "required_view_ids 와 operand 의 View 가 다름 (operand 기준으로 보정)",
                        sev=Severity.WARNING)
        # 존재 검사
        exist_ok = True
        for o in plan.operands:
            if o.view_id not in self.index.views:
                exist_ok = False
                continue
            v = self.index.view(o.view_id)
            if o.itm_id not in v.source_coordinates.itm_ids:
                self._issue(rep, "UNKNOWN_ITEM", f"{o.operand_id}: 항목 {o.itm_id} 없음 (가능: {v.source_coordinates.itm_ids})",
                            retryable=True, refs=[o.operand_id])
                exist_ok = False
            if o.prd_de not in v.available_periods:
                self._issue(rep, "MISSING_PERIOD", f"{o.operand_id}: 필수 시점 {o.prd_de} 이 View 에 없음", refs=[o.operand_id])
                exist_ok = False
            levels = {d.level for d in v.dimension_definitions}
            for lv, code in o.coordinates.items():
                if lv not in levels or code not in v.code_map(lv):
                    self._issue(rep, "UNKNOWN_CODE", f"{o.operand_id}: {lv}={code} 없음", retryable=True, refs=[o.operand_id])
                    exist_ok = False
            if o.group_by_level and o.group_by_level not in levels:
                self._issue(rep, "UNKNOWN_LEVEL", f"{o.operand_id}: {o.group_by_level} 없음", retryable=True)
                exist_ok = False
            exp = plan.expected_cardinality.get(o.operand_id)
            want = "MANY" if o.group_by_level else "ONE"
            if exp and exp != want:
                self._issue(rep, "CARDINALITY_DECLARATION", f"{o.operand_id}: expected_cardinality={exp} 이지만 {want}",
                            sev=Severity.WARNING)
        ck["codes_items_periods_exist"] = CheckState.PASS if exist_ok else CheckState.FAIL
        if not plan.operation:
            self._issue(rep, "NO_OPERATION", "operation 없음", retryable=True)
            return self._finish(rep)
        refs = plan.refs()
        for s in plan.operation.steps:
            for r in s.inputs:
                if r not in refs:
                    self._issue(rep, "UNKNOWN_REF", f"{s.step_id}: 참조 {r} 없음", retryable=True)
        for f in plan.filters:
            for r in (f.target_ref, f.condition_ref):
                if r not in refs:
                    self._issue(rep, "UNKNOWN_REF", f"{f.filter_id}: 참조 {r} 없음", retryable=True)
        if not exist_ok or any(i.code == "UNKNOWN_REF" for i in rep.issues):
            return self._finish(rep)
        views = {o.operand_id: self.index.view(o.view_id) for o in plan.operands}
        # 전체 operand 공통 조건: 실측/추계, 시나리오, 주기
        obs = {v.observed_or_projected.value for v in views.values()}
        ck["observed_projected_not_mixed"] = CheckState.PASS if len(obs) == 1 else CheckState.FAIL
        if len(obs) > 1:
            self._issue(rep, "OBSERVED_PROJECTED_MIXED", f"실측치와 추계치 혼합 {sorted(obs)}")
        scen = {v.scenario for v in views.values()}
        if len(scen) > 1:
            self._issue(rep, "SCENARIO_MIXED", f"시나리오 혼합 {sorted(map(str, scen))}")
        freqs = {v.period_frequency for v in views.values()}
        ck["same_frequency"] = CheckState.PASS if len(freqs) == 1 else CheckState.FAIL
        if len(freqs) > 1:
            self._issue(rep, "FREQUENCY_MISMATCH", f"서로 다른 주기 {sorted(freqs)} 를 같은 기간으로 간주하지 않음")
        # 연산별 검사
        steps = {s.step_id: s for s in plan.operation.steps}
        ck.setdefault("time_series_compatible", CheckState.NOT_APPLICABLE)
        ck.setdefault("ratio_compatible", CheckState.NOT_APPLICABLE)
        ck.setdefault("aggregation_valid", CheckState.NOT_APPLICABLE)
        filter_ids = {f.filter_id for f in plan.filters}
        for s in plan.operation.steps:
            if s.op == AtomicOp.COUNT and s.inputs and s.inputs[0] not in filter_ids:
                # 거르지 않은 벡터의 개수 = 그냥 지역 수 → 정답이 의미 없음 (실데이터: DIFFERENCE→COUNT 로 '차이가 몇 개' 질문)
                self._issue(rep, "COUNT_WITHOUT_FILTER", f"{s.step_id}: COUNT 의 입력 {s.inputs[0]} 가 FILTER 결과가 아님 — "
                            "조건(예: 차이 > 0)을 filters 에 정의하고 그 filter_id 를 세세요", retryable=True)
                ck["aggregation_valid"] = CheckState.FAIL
            roots = [self._roots(plan, r) for r in s.inputs]
            if s.op in (AtomicOp.GROWTH_RATE, AtomicOp.DIFFERENCE, AtomicOp.PERCENTAGE_POINT_DIFFERENCE, AtomicOp.SHARE_RATIO):
                if len(roots) != 2:
                    continue
                for a in roots[0]:
                    for b in roots[1]:
                        self._pair_check(rep, s.op, ops[a], ops[b], views[a], views[b], plan)
            if s.op in (AtomicOp.SUM, AtomicOp.MEAN):
                ck["aggregation_valid"] = CheckState.PASS
                for r in (self._value_roots(plan, s.inputs[0]) if s.inputs else ()):
                    o, v = ops[r], views[r]
                    if o.group_by_level and not o.exclude_totals:
                        self._issue(rep, "TOTAL_DOUBLE_COUNT", f"{s.step_id}: {r} 벡터가 총계·소계를 포함한 채 합산/평균",
                                    retryable=True)
                        ck["aggregation_valid"] = CheckState.FAIL
                    if o.group_by_level:
                        depths = set(leaf_depths(v, o.group_by_level))
                        if len(depths) > 1 and o.depth is None:
                            self._issue(rep, "MIXED_HIERARCHY_DEPTH", f"{s.step_id}: {r} 의 코드 깊이가 섞임 {sorted(depths)} → depth 지정",
                                        retryable=True)
                            ck["aggregation_valid"] = CheckState.FAIL
                    kind = unit_info(v.units[0]).kind if v.units else ValueKind.UNKNOWN
                    direct = s.inputs[0] in ops or any(f.filter_id == s.inputs[0] for f in plan.filters)
                    if direct and kind not in (ValueKind.COUNT, ValueKind.AMOUNT):
                        self._issue(rep, "NON_ADDITIVE_AGGREGATION", f"{s.step_id}: {v.units} 단위는 단순 {s.op.value} 금지")
                        ck["aggregation_valid"] = CheckState.FAIL
            if s.op == AtomicOp.WEIGHTED_MEAN:
                ck["aggregation_valid"] = CheckState.PASS
                if len(roots) == 2 and roots[0] and roots[1]:
                    vi = {norm_item_name(views[r].indicator_definitions[0].itm_nm) for r in roots[0]}
                    wi = {norm_item_name(views[r].indicator_definitions[0].itm_nm) for r in roots[1]}
                    if not any((a, b) in self.weighted_pairs for a in vi for b in wi):
                        self._issue(rep, "UNJUSTIFIED_WEIGHT", f"{s.step_id}: 통계적으로 정당화된 가중치 쌍이 설정에 없음 ({vi} / {wi})")
                        ck["aggregation_valid"] = CheckState.FAIL
        for f in plan.filters:
            rt, rc = self._roots(plan, f.target_ref), self._roots(plan, f.condition_ref)
            pt = {ops[r].prd_de for r in rt}
            pc = {ops[r].prd_de for r in rc}
            if rt and rc and not (pt & pc) and f.target_ref in ops:
                self._issue(rep, "FILTER_PERIOD_MISMATCH", f"{f.filter_id}: 조건 시점 {pc} ≠ 지표 시점 {pt}", sev=Severity.WARNING)
        if plan.aggregation_specification and plan.aggregation_specification.function not in {
                steps[plan.operation.final_step_id].op} | {s.op for s in plan.operation.steps}:
            self._issue(rep, "AGGREGATION_SPEC_MISMATCH", "aggregation_specification 함수가 steps 에 없음", retryable=True)
        return self._finish(rep)

    def _pair_check(self, rep, op, oa, ob, va, vb, plan):
        ck = rep.checks
        if va.view_id == vb.view_id and oa.prd_de == ob.prd_de and oa.itm_id == ob.itm_id and oa.coordinates == ob.coordinates \
                and not (oa.group_by_level or ob.group_by_level):
            self._issue(rep, "SELF_COMPARISON", f"{op.value}: 같은 값을 자기 자신과 비교", retryable=True)
            return
        diff_period = oa.prd_de != ob.prd_de
        e = self.graph.edge(va.view_id, vb.view_id) if va.view_id != vb.view_id else None
        if op in (AtomicOp.GROWTH_RATE, AtomicOp.DIFFERENCE, AtomicOp.PERCENTAGE_POINT_DIFFERENCE) and diff_period:
            ok = (e is None and oa.itm_id == ob.itm_id) or (e is not None and e.allowed.get("TIME_SERIES"))
            if oa.itm_id != ob.itm_id:
                ok = False
            ck["time_series_compatible"] = CheckState.PASS if ok else CheckState.FAIL
            if not ok:
                why = e.reasons.get("TIME_SERIES") if e else ["항목이 다름"]
                self._issue(rep, "TIME_SERIES_INCOMPATIBLE", f"{op.value}: 서로 다른 시점 비교 불가 — {why}")
            if oa.coordinates != ob.coordinates or oa.group_by_level != ob.group_by_level:
                self._issue(rep, "TIME_SERIES_COORDINATE_MISMATCH", f"{op.value}: 두 시점의 분류 조건이 다름", retryable=True)
            if op == AtomicOp.GROWTH_RATE and plan.reasoning_type.value == "TIME_SERIES_COMPARISON":
                pass
        elif op == AtomicOp.SHARE_RATIO or (op == AtomicOp.DIFFERENCE and not diff_period):
            if len(va.units) != 1 or len(vb.units) != 1:      # 원본 UNIT_NM 이 비었거나 여러 개 → 단위 호환을 확인할 수 없음
                self._issue(rep, "UNIT_UNKNOWN", f"{op.value}: 단위를 확인할 수 없는 View "
                            f"({va.view_id}: {va.units}, {vb.view_id}: {vb.units})")
                ck["ratio_compatible"] = CheckState.FAIL
                return
            if diff_period:
                self._issue(rep, "RATIO_PERIOD_MISMATCH", f"{op.value}: 분자({oa.prd_de})와 분모({ob.prd_de}) 시점이 다름")
                ck["ratio_compatible"] = CheckState.FAIL
                return
            fam = "RATIO" if op == AtomicOp.SHARE_RATIO else "SIDE_BY_SIDE"
            ok = e is None or e.allowed.get(fam)
            if e is not None and op == AtomicOp.DIFFERENCE:
                ok = ok and unit_info(va.units[0]).family == unit_info(vb.units[0]).family
            ck["ratio_compatible"] = CheckState.PASS if ok else CheckState.FAIL
            if not ok:
                self._issue(rep, "RATIO_INCOMPATIBLE", f"{op.value}: {e.reasons.get(fam) if e else ''}")
            if frozenset({va.population_scope, vb.population_scope}) in self.incompatible_scopes:
                self._issue(rep, "POPULATION_SCOPE_INCOMPATIBLE", f"{op.value}: 모집단 {va.population_scope} vs {vb.population_scope}")
                ck["ratio_compatible"] = CheckState.FAIL
            if op == AtomicOp.SHARE_RATIO:
                bad = narrower_denominator(oa, ob, va, vb)
                if bad:
                    self._issue(rep, "DENOMINATOR_NARROWER_THAN_NUMERATOR",
                                f"분모의 분류 조건 {bad} 이 분자와 달라 분모가 분자를 포함하지 않음 — 분모를 분자와 같은 조건"
                                f"이나 그 조건을 포함하는 총계 코드로 고정하세요", retryable=True)
                    ck["ratio_compatible"] = CheckState.FAIL
                ua, ub = unit_info(va.units[0]), unit_info(vb.units[0])
                den = vb.indicator_definitions[0].itm_nm if vb.indicator_definitions else ""
                if ua.family == ub.family and self.share_den_include:
                    if not any(p.search(den) for p in self.share_den_include) or any(p.search(den) for p in self.share_den_exclude):
                        self._issue(rep, "SHARE_DENOMINATOR_NOT_TOTAL",
                                    f"구성비의 분모 '{den}' 가 분자를 포함하는 전체 모집단으로 확인되지 않음")
                        ck["ratio_compatible"] = CheckState.FAIL

    # ── 계산 후 ──
    def validate_result(self, plan: OperationPlan, cluster: SampledCluster, calc: CalculationResult) -> StatisticalValidationReport:
        rep = StatisticalValidationReport(passed=False)
        ck = rep.checks
        if not calc.success:
            self._issue(rep, calc.error_code.value if calc.error_code else "CALC_FAILED", calc.error_message or "",
                        retryable=calc.retryable, stage="calculation")
            ck["calculation"] = CheckState.FAIL
            return self._finish(rep)
        ck["calculation"] = CheckState.PASS
        ck["finite_result"] = CheckState.PASS
        amp = [d for d in calc.join_diagnostics if d.amplified]
        ck["join_cardinality"] = CheckState.FAIL if amp else (CheckState.PASS if calc.join_diagnostics else CheckState.NOT_APPLICABLE)
        if amp:
            self._issue(rep, "JOIN_AMPLIFICATION", f"Join 행 증폭 {len(amp)}건", stage="calculation")
        fact_views = {f.view_id for f in calc.intermediate_facts} | {e.query_spec.get("view_id") for e in calc.evidence_files}
        missing = set(cluster.view_ids) - fact_views
        ck["every_view_has_evidence"] = CheckState.FAIL if missing else CheckState.PASS
        if missing:
            self._issue(rep, "VIEW_WITHOUT_EVIDENCE", f"원본 근거가 없는 View: {sorted(missing)}", stage="calculation")
        fin = calc.final
        if fin and fin.kind == "SCALAR" and fin.value:
            v = Decimal(fin.value.exact_decimal)
            last = next((s for s in plan.operation.steps if s.step_id == plan.operation.final_step_id), None)
            if last and last.op == AtomicOp.SHARE_RATIO and fin.unit == "%" and v > 100:
                self._issue(rep, "SHARE_EXCEEDS_100", f"구성비가 100% 초과 ({fin.value.display}) — 분자가 분모에 포함되지 않음",
                            stage="calculation")
            if last and last.op == AtomicOp.GROWTH_RATE and abs(float(v)) > self.max_abs_growth:
                self._issue(rep, "EXTREME_GROWTH", f"증감률 {fin.value.display} 이 비정상적으로 큼", sev=Severity.WARNING,
                            stage="calculation")
        tables = {f.parent_table_id for f in calc.intermediate_facts}
        if cluster.hop_type.value == "MULTI_TABLE_MULTI_VIEW" and len(tables) < 2:
            self._issue(rep, "HOP_TYPE_MISMATCH", "Multi-Table 로 샘플됐지만 근거가 한 표에서만 나옴", sev=Severity.WARNING,
                        stage="calculation")
        return self._finish(rep)

    @staticmethod
    def _finish(rep: StatisticalValidationReport) -> StatisticalValidationReport:
        rep.passed = not rep.errors
        return rep


def selected_codes(o, v) -> dict[str, str]:
    """operand 가 실제로 고정한 분류 코드 (coordinates + View 분할 조건), 지역 레벨 제외."""
    out = dict(o.coordinates)
    for lv, cs in v.source_coordinates.dim_filters.items():
        if cs and lv not in out:
            out[lv] = cs[0]
    return out


def narrower_denominator(oa, ob, va, vb) -> list[str]:
    """비율 분모가 분자보다 좁은 분류(예: 분자=여자, 분모=남자)인지. 같은 dim_type 의 분류끼리 비교.
    분모 코드가 총계면 OK, 분자와 같은 코드면 OK, 그 외(다른 비총계 코드)는 분모가 분자를 포함하지 않음."""
    from synthetic_gold_pipeline.schemas.metadata import DimensionType
    sa, sb = selected_codes(oa, va), selected_codes(ob, vb)
    bad = []
    for lvb, cb in sb.items():
        db = vb.dim(lvb)
        if not db or db.dim_type == DimensionType.REGION:
            continue
        code_b = vb.code_map(lvb).get(cb)
        if code_b is None or code_b.is_total:
            continue
        match = [lva for lva in sa if va.dim(lva) and va.dim(lva).dim_type == db.dim_type]
        if not match:
            bad.append(f"{db.obj_nm}={code_b.name}")      # 분자에는 없는 제한이 분모에만 있음
            continue
        ca = va.code_map(match[0]).get(sa[match[0]])
        if ca is None or ca.name.replace(" ", "") != code_b.name.replace(" ", ""):
            bad.append(f"{db.obj_nm}={code_b.name}")
    return bad
