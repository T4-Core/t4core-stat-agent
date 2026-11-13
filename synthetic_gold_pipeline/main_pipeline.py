"""Synthetic Golden Set 생성 Orchestrator (Reverse Generation).

  RAW/Meta/View → 결합 가능한 View 탐색(Compatibility Graph) → 통계적 연산 가능성 검증 → LLM 연산 계획
  → 독립 Calculation Tool 실행 → 원본 값·계산 결과 확정 → 확정 Fact 기반 질문·답변 역생성
  → 독립 Evaluation Tool 검증 → LLM 의미 검수 → (결정론적) 중복 제거 → Golden Set 저장

실행 (저장소 루트에서)
  python -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline.yaml --mode demo --target-count 10
  python -m synthetic_gold_pipeline.main_pipeline --mode real --data-root storage/kosis_data --target-count 100
  python -m synthetic_gold_pipeline.main_pipeline --mode real --resume

동시성: asyncio 로 샘플을 제한 병렬 처리. DuckDB 연결은 샘플(계산)마다 새로 만들고 닫는다(공유 없음).
재현성: 샘플 seed = f(base_seed, attempt_index). 채택(중복 제거·할당량)은 배치마다 attempt 순서대로 순차 처리.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import logging
import platform
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from synthetic_gold_pipeline import __version__
from synthetic_gold_pipeline.adapters.view_mapping_adapter import ViewMappingAdapter
from synthetic_gold_pipeline.agents.llm_client import (BaseLLMClient, LLMBudgetExceeded, LLMConfigError,
                                                       LLMRateLimitExhausted, LLMResponseError, make_llm_client)
from synthetic_gold_pipeline.agents.planner_agent import PlannerAgent
from synthetic_gold_pipeline.agents.quality_verifier_agent import QualityVerifierAgent, review_payload
from synthetic_gold_pipeline.agents.reverse_qa_agent import (ReverseQAGeneratorAgent, ReverseQAOutput,
                                                             assemble_reference_answer, build_fact_bundle)
from synthetic_gold_pipeline.demo_data import build_demo_dataset
from synthetic_gold_pipeline.record_builder import (build_answerable_record, expected_claims, final_digits, policy_for,
                                                    signatures)
from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.sampler.unanswerable_sampler import UnanswerableBuilder
from synthetic_gold_pipeline.sampler.view_cluster_sampler import SamplerState, ViewClusterSampler
from synthetic_gold_pipeline.schemas.dataset import ANSWER_REF_COLUMNS, QUERY_CSV_COLUMNS, GoldenRecord
from synthetic_gold_pipeline.schemas.planning import HopType, ReasoningType, SampledCluster
from synthetic_gold_pipeline.tools.calculation_tool import TableCalculationEngine
from synthetic_gold_pipeline.tools.deduplication_tool import DedupIndex
from synthetic_gold_pipeline.tools.evaluation_tool import AblationChecker, NumericAnswerEvaluator, ViewJudge
from synthetic_gold_pipeline.tools.plan_repair import repair_plan
from synthetic_gold_pipeline.tools.statistical_validation_tool import StatisticalValidator
from synthetic_gold_pipeline.utils import (PACKAGE_ROOT, append_jsonl, atomic_write_json, atomic_write_text, display_path,
                                           load_config, load_dotenv_if_present, now_iso, read_jsonl,
                                           resolve_path, sha256_file, stable_hash, write_jsonl)

log = logging.getLogger("synthetic_gold")
ANSWERABLE_TYPES = [ReasoningType.SIMPLE_LOOKUP, ReasoningType.TIME_SERIES_COMPARISON, ReasoningType.CROSS_TABLE_RATIO,
                    ReasoningType.CONDITIONAL_AGGREGATION]
DEFAULT_TYPE_RATIO = {ReasoningType.SIMPLE_LOOKUP: 0.0}     # [NEW 11-12] 단순 조회는 설정에 적었을 때만 (기본 0 = 예전과 같음)


@dataclass
class Outcome:
    cluster: SampledCluster
    record: GoldenRecord | None = None
    stage: str = ""
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    planner_attempts: int = 0
    plan: dict | None = None
    flags: dict[str, bool] = field(default_factory=dict)
    budget_exhausted: bool = False
    rate_limited: bool = False            # 429 가 기다려도 계속됨 → 탈락이 아니라 실행 중단 (--resume 으로 이어서)
    repairs: list = field(default_factory=list)    # 계획 자동 보정 기록 (tools/plan_repair.py)
    extra: dict = field(default_factory=dict)      # 진단용: 질문·답변·검수 결과


class Pipeline:
    def __init__(self, cfg: dict, mode: str, output_root: Path, data_root: Path | None, resume: bool = False,
                 rebuild_index: bool = False):
        self.cfg, self.mode, self.resume, self.rebuild_index = cfg, mode, resume, rebuild_index
        self.out = output_root.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.dirs = {k: self.out / k for k in ("metadata_index", "generated_views", "intermediate_facts", "rejected_samples",
                                                "checkpoints", "datasets", "reports")}
        for d in self.dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        self.data_root = data_root
        run = cfg.get("run", {})
        self.seed = int(run.get("seed", 42))
        self.batch_size = int(run.get("batch_size", 8))
        self.concurrency = int(run.get("concurrency", 4))
        self.max_attempts = int(run.get("max_sampling_attempts", 400))
        self.max_planner_retries = int(cfg.get("planner", {}).get("max_self_correction_retries", 2))
        self.max_revisions = int(cfg.get("quality", {}).get("max_question_revisions", 1))
        self.unans_ratio = float(run.get("unanswerable_ratio", 0.12))
        # LLM 검수 항목 중 탈락시키는 것. multi_hop_necessity 는 기본 제외 — View 필요성은 Ablation(결정론적)이 이미 증명하고,
        # 실데이터에서 HCX 가 '같은 표 두 시점' 문제를 일괄 '멀티홉 불필요' 로 판정해 검수 탈락의 89% 를 차지했음 (기록만 남김)
        self.review_required = list(self.cfg.get("quality", {}).get("required_review_checks") or [
            "semantic_valid", "statistical_validity", "question_answer_alignment", "paraphrase_equivalence",
            "natural_question"])
        self.type_ratio = run.get("taxonomy_ratio", {})
        self.counters: Counter = Counter()
        self.failures: Counter = Counter()
        self.accepted: list[GoldenRecord] = []
        self.attempt_index = 0
        self.t0 = time.time()

    # ── 준비 ──────────────────────────────────────────────────────
    def prepare(self, llm: BaseLLMClient | None = None):
        self.llm = llm or make_llm_client(self.mode, self.cfg)        # 키 없음 등 설정 오류는 무거운 인덱싱 전에 확인
        if self.mode == "demo":
            root = (self.data_root or (self.out / "demo_kosis_data")).resolve()
            if not root.is_relative_to(self.out):
                raise PermissionError("Demo 데이터는 출력 폴더 안에만 생성합니다 (--data-root 를 비우세요)")
            if not (root / "catalog.csv").exists() or not self.resume:
                build_demo_dataset(root)
            self.data_root = root
        if not self.data_root or not self.data_root.exists():
            raise FileNotFoundError(f"데이터 폴더 없음: {self.data_root}")
        log.info("메타데이터 인덱스 생성: %s", self.data_root)
        self.index = MetadataIndex.build(self.data_root, self.dirs["generated_views"], self.out, self.cfg,
                                         cache_dir=self.dirs["metadata_index"] / "cache", rebuild=self.rebuild_index)
        c = self.index.build_info.get("cache", {})
        log.info("인덱스: 표 %d · View %d (캐시 사용 %d, 새로 읽음 %d, 무효 %s) %.1fs", self.index.build_info["n_tables"],
                 self.index.build_info["n_views"], c.get("table_hits", 0), c.get("table_misses", 0), c.get("invalid"),
                 self.index.build_info["index_seconds"])
        self.index.save(self.dirs["metadata_index"])
        self.snapshot_id = self.index.snapshot_id()
        self.graph = CompatibilityGraph(self.index, self.cfg.get("compatibility", {}))
        if len(self.index.views) <= int(self.cfg.get("compatibility", {}).get("build_full_graph_max_views", 3000)):
            n = self.graph.build_all()
            self.graph.save(self.dirs["metadata_index"] / "compatibility_edges.jsonl")
            log.info("Compatibility edges: %d", n)
        state = SamplerState()
        if self.resume and (self.dirs["checkpoints"] / "state.json").exists():
            st = json.loads((self.dirs["checkpoints"] / "state.json").read_text(encoding="utf-8"))
            state = SamplerState.from_json(st.get("sampler", {}))
        self.sampler = ViewClusterSampler(self.index, self.graph, self.cfg.get("sampler", {}), self.seed, state)
        self.validator = StatisticalValidator(self.index, self.graph, {**self.cfg.get("statistics", {}),
                                                                      **self.cfg.get("compatibility", {})})
        self.engine = TableCalculationEngine(self.index, self.cfg.get("calculation", {}), self.dirs["intermediate_facts"])
        self.ablation = AblationChecker(self.index, self.engine, self.cfg.get("ablation", {}))
        self.judge = ViewJudge(self.index)
        self.numeric = NumericAnswerEvaluator(self.cfg.get("evaluation", {}).get("region_aliases", {}))
        self.planner = PlannerAgent(self.llm, self.index, self.graph, self.cfg.get("planner", {}))
        self.qa = ReverseQAGeneratorAgent(self.llm, self.index, self.cfg.get("reverse_qa", {}))
        self.verifier = QualityVerifierAgent(self.llm, self.cfg.get("quality", {}))
        dcfg = self.cfg.get("dedup", {})
        self.dedup = DedupIndex(threshold=float(dcfg.get("similarity_threshold", 0.85)),
                                ngram_range=tuple(dcfg.get("char_ngram_range", [2, 4])))
        self.mapper = ViewMappingAdapter(self.cfg.get("existing_rag", {}).get("views_jsonl") or None)
        self.sem = asyncio.Semaphore(self.concurrency)
        self._load_checkpoint()

    # ── 체크포인트 ────────────────────────────────────────────────
    def _ckpt(self, name):
        return self.dirs["checkpoints"] / name

    def _config_hash(self) -> str:
        keep = {k: v for k, v in self.cfg.items() if not k.startswith("_") and k not in ("run",)}
        return stable_hash(keep, 16)

    def _load_checkpoint(self):
        st_path = self._ckpt("state.json")
        if not self.resume:
            if st_path.exists() or self._ckpt("accepted.jsonl").exists():
                arch = self.dirs["checkpoints"] / f"archive_{time.strftime('%Y%m%d_%H%M%S')}"
                arch.mkdir(parents=True, exist_ok=True)
                for f in ("state.json", "accepted.jsonl"):
                    if self._ckpt(f).exists():
                        shutil.move(str(self._ckpt(f)), str(arch / f))
            for p in (self.dirs["rejected_samples"] / "rejected_samples.jsonl", self.dirs["reports"] / "validation_errors.jsonl"):
                if p.exists():
                    p.unlink()
            return
        if not st_path.exists():
            log.warning("--resume 이지만 체크포인트가 없어 새로 시작")
            return
        st = json.loads(st_path.read_text(encoding="utf-8"))
        if st.get("snapshot_id") != self.snapshot_id:
            raise RuntimeError(f"데이터 스냅샷이 바뀌어 이어서 실행할 수 없음 ({st.get('snapshot_id')} → {self.snapshot_id})")
        if st.get("config_hash") != self._config_hash():
            log.warning("설정이 체크포인트와 다름 (config_hash) — 이어서 진행하지만 보고서에 기록")
            self.counters["resume_config_changed"] += 1
        self.attempt_index = int(st.get("attempt_index", 0))
        self.counters.update(st.get("counters", {}))
        self.failures.update(st.get("failures", {}))
        self.llm.usage.load(st.get("llm_usage", {}))
        for d in read_jsonl(self._ckpt("accepted.jsonl")):
            rec = GoldenRecord.model_validate(d)
            self.accepted.append(rec)
            fs, es = signatures(rec)
            self.dedup.add(rec.dataset_id, [rec.question_original, rec.question_paraphrased], fs, es)
        log.info("체크포인트에서 재개: 시도 %d, 채택 %d", self.attempt_index, len(self.accepted))

    def _save_state(self):
        atomic_write_json(self._ckpt("state.json"), {
            "attempt_index": self.attempt_index, "snapshot_id": self.snapshot_id, "config_hash": self._config_hash(),
            "sampler": self.sampler.state.to_json(), "counters": dict(self.counters), "failures": dict(self.failures),
            "llm_usage": self.llm.usage.to_json(), "n_accepted": len(self.accepted), "saved_at": now_iso()})

    def _reject(self, o: Outcome):
        self.failures[f"{o.stage}:{o.codes[0] if o.codes else 'UNKNOWN'}"] += 1
        append_jsonl(self.dirs["rejected_samples"] / "rejected_samples.jsonl", [{
            "sample_id": o.cluster.sample_id, "attempt_index": o.cluster.attempt_index, "reasoning_type": o.cluster.reasoning_type.value,
            "subtype": o.cluster.subtype, "view_ids": o.cluster.view_ids, "stage": o.stage, "codes": o.codes,
            "reasons": o.reasons[:10], "planner_attempts": o.planner_attempts, "plan_repairs": o.repairs[-12:],
            **o.extra, "last_plan": o.plan, "at": now_iso()}])
        append_jsonl(self.dirs["reports"] / "validation_errors.jsonl", [
            {"sample_id": o.cluster.sample_id, "stage": o.stage, "code": c, "message": m}
            for c, m in zip(o.codes or ["UNKNOWN"], (o.reasons or [""]) + [""] * len(o.codes))])

    # ── 샘플 1개 처리 (비동기) ──────────────────────────────────────
    async def process(self, cluster: SampledCluster) -> Outcome:
        async with self.sem:
            try:
                return await self._process(cluster)
            except LLMBudgetExceeded as e:
                return Outcome(cluster, stage="api_budget", codes=["API_BUDGET_EXCEEDED"], reasons=[str(e)],
                               budget_exhausted=True)
            except LLMRateLimitExhausted as e:
                return Outcome(cluster, stage="rate_limited", codes=["RATE_LIMIT_EXHAUSTED"], reasons=[str(e)],
                               rate_limited=True)
            except LLMResponseError as e:
                return Outcome(cluster, stage="llm", codes=["LLM_RESPONSE_ERROR"], reasons=[str(e)])
            except Exception as e:  # noqa: BLE001 — 샘플 1개의 예외로 전체 실행을 멈추지 않음 (원인은 기록)
                log.exception("샘플 처리 중 예외 %s", cluster.sample_id)
                return Outcome(cluster, stage="internal_error", codes=[type(e).__name__],
                               reasons=[traceback.format_exc()[-1500:]])

    def _coverage(self, recs) -> dict:
        """표 범위: 인덱스 전체 표 중 몇 개가 시도·채택됐는가 (조사별)"""
        all_t = Counter()
        survey_of = {}
        for v in self.index.views.values():
            if v.parent_table_id not in survey_of:
                survey_of[v.parent_table_id] = v.survey_name
                all_t[v.survey_name] += 1
        tried = {t for t in self.sampler.state.attempts_by_table if t in survey_of}
        short = {t.split("_", 1)[1] if "_" in t and t.split("_", 1)[0].isdigit() else t: t for t in survey_of}
        used = {short.get(t, t) for r in recs for t in r.retrieval_eval.golden_table_ids} & set(survey_of)   # 정답 표 ID 는 기관 접두어 없음
        tried |= used                     # 답변 불가 레코드는 별도 샘플러가 고르므로 시도 기록에 없음 → 합쳐서 셈
        by = {s: {"tables": n, "tried": sum(survey_of[t] == s for t in tried), "in_dataset": sum(survey_of[t] == s for t in used)}
              for s, n in all_t.most_common()}
        return {"tables_total": len(survey_of), "tables_tried": len(tried), "tables_in_dataset": len(used),
                "share_in_dataset": round(len(used) / max(1, len(survey_of)), 3), "by_survey": by}

    def _drop_unused_views(self, cluster: SampledCluster, plan) -> SampledCluster | None:
        """계획이 쓰지 않은 View 를 묶음에서 뺀 새 묶음. 표 사이 비율은 두 표 이상 남아야 함 (아니면 None)"""
        used = [v for v in cluster.view_ids if v in {op.view_id for op in plan.operands}]
        if not used or len(used) == len(cluster.view_ids):
            return None
        tables = list(dict.fromkeys(self.index.view(v).parent_table_id for v in used))
        if cluster.reasoning_type == ReasoningType.CROSS_TABLE_RATIO and len(tables) < 2:
            return None
        hop = (HopType.SINGLE_TABLE_SINGLE_VIEW if len(used) == 1 else
               HopType.SINGLE_TABLE_MULTI_VIEW if len(tables) == 1 else HopType.MULTI_TABLE_MULTI_VIEW)
        return cluster.model_copy(update={"view_ids": used, "table_ids": tables, "hop_type": hop,
                                          "notes": [*cluster.notes, "계획이 쓰지 않은 View 제외"]})

    async def _process(self, cluster: SampledCluster) -> Outcome:
        o = Outcome(cluster)
        errors: list[str] = []
        plan = calc = rep_p = rep_r = None
        for attempt in range(self.max_planner_retries + 1):
            o.planner_attempts = attempt + 1
            plan, _ = await self.planner.plan(cluster, errors, attempt)
            plan, fixes = repair_plan(plan, self.index)                 # 기계적 빈칸 보정 (기록 남김)
            if fixes:
                o.repairs += [f"[시도 {attempt + 1}] {x}" for x in fixes]
                self.counters["plan_repairs"] += len(fixes)
            o.plan = plan.model_dump(mode="json")
            o.flags["plan_generated"] = plan.plan_status.value == "OK"
            rep_p = self.validator.validate_plan(plan, cluster)
            if not rep_p.passed and {i.code for i in rep_p.errors} == {"UNUSED_VIEW"}:
                shrunk = self._drop_unused_views(cluster, plan)            # 안 쓴 View 만 문제면 묶음에서 빼고 다시 검증
                if shrunk is not None:
                    o.repairs.append(f"[시도 {attempt + 1}] 안 쓴 View 제외 {sorted(set(cluster.view_ids) - set(shrunk.view_ids))}")
                    cluster = o.cluster = shrunk
                    rep_p = self.validator.validate_plan(plan, cluster)
            if not rep_p.passed:
                if rep_p.retryable and attempt < self.max_planner_retries:
                    errors = [f"[{i.code}] {i.message}" for i in rep_p.errors]
                    self.counters["planner_retries"] += 1
                    continue
                o.stage, o.codes, o.reasons = "statistical_validation_plan", [i.code for i in rep_p.errors], [
                    i.message for i in rep_p.errors]
                return o
            o.flags["statistically_compatible"] = True
            calc = await asyncio.to_thread(self.engine.run, plan, cluster.view_ids)
            if not calc.success:
                if calc.retryable and attempt < self.max_planner_retries:
                    errors = [f"[{calc.error_code.value}] {calc.error_message}"]
                    self.counters["planner_retries"] += 1
                    continue
                o.stage, o.codes, o.reasons = "calculation", [calc.error_code.value], [calc.error_message or ""]
                return o
            rep_r = self.validator.validate_result(plan, cluster, calc)
            if not rep_r.passed:
                o.stage, o.codes, o.reasons = "statistical_validation_result", [i.code for i in rep_r.errors], [
                    i.message for i in rep_r.errors]
                return o
            break
        else:  # pragma: no cover
            o.stage, o.codes = "planner", ["RETRY_EXHAUSTED"]
            return o
        o.flags["calculated"] = True
        atomic_write_json(self.dirs["intermediate_facts"] / f"{cluster.sample_id}.json",
                          {"cluster": cluster.model_dump(mode="json"), "plan": plan.model_dump(mode="json"),
                           "calculation": calc.model_dump(mode="json")})
        abl, alts = await asyncio.to_thread(self.ablation.run, plan, calc, cluster)
        bad = [a for a in abl if a.outcome.value != "NECESSARY"]
        if bad:
            o.stage, o.codes = "ablation", [f"VIEW_{a.outcome.value}" for a in bad]
            o.reasons = [f"{a.view_id}: {a.detail}" for a in bad]
            return o
        o.flags["ablation_passed"] = True
        judgements, groups = await asyncio.to_thread(self.judge.judge, cluster, calc, alts, cluster.hard_negative_candidates)
        bundle = build_fact_bundle(cluster, plan, calc, self.index)
        try:
            qa_out, _ = await self.qa.generate(bundle)
        except LLMResponseError as e:
            o.stage, o.codes, o.reasons = "reverse_qa", ["QA_GENERATION_FAILED"], [str(e)]
            o.extra["qa_input"] = {k: bundle["llm_input"].get(k) for k in ("operands", "scalar_facts", "reasoning_type")}
            o.extra["qa_last_output"] = getattr(e, "last_text", None)
            return o
        o.flags["question_generated"] = True
        ref, trace, body = assemble_reference_answer(qa_out, bundle, calc, self.index)
        claims = expected_claims(self.index, calc, plan)
        policy = policy_for(calc.final.unit if calc.final else None, plan.comparison_policy, self.cfg.get("evaluation", {}),
                            final_digits(calc.final))
        final_op = plan.operation.steps[-1].op.value
        # (1) LLM 이 쓴 답변 문장: 최종값·단위·부호·지역/연도 연결·근거 없는 숫자 (중간값은 근거 블록에 있으므로 선택)
        masks = label_texts(bundle)
        chk = self.numeric.evaluate(body, claims, policy.model_dump(), final_op, mask_labels=masks,
                                    allowed_extra=[c.value for c in claims if c.value is not None], require_intermediates=False)
        # (2) 전체 모범 답변: 모든 중간 원본값이 실제 원본과 같은 값으로 들어 있는가
        chk_full = self.numeric.evaluate(ref, [c for c in claims if c.role == "INTERMEDIATE"], policy.model_dump(), None,
                                         mask_labels=masks)
        ent_missing = [c.value_text for c in claims if c.role == "ENTITY" and c.value_text not in body]
        if not chk.passed or ent_missing or chk_full.intermediates_ok is False:
            o.extra["reference_answer"] = ref[:1500]
            o.stage, o.codes = "numeric_self_check", ["REFERENCE_ANSWER_NUMERIC_MISMATCH"]
            o.reasons = chk.details + chk.binding_errors + [f"unsupported {chk.unsupported_numbers}"] + \
                [f"entity missing {ent_missing}"] + chk_full.details
            return o
        o.flags["numeric_validated"] = True
        q1, q2 = self._fill_q(qa_out.question_original, bundle), self._fill_q(qa_out.question_paraphrased, bundle)
        quality = None
        for rev in range(self.max_revisions + 1):
            payload = review_payload(q1, q2, ref, bundle["llm_input"], len(cluster.view_ids), len(cluster.table_ids))
            quality, _ = await self.verifier.review(payload)
            sem_ok = all(getattr(quality, k) for k in self.review_required)
            if sem_ok and not quality.ambiguity_detected:
                break
            if quality.ambiguity_detected and quality.suggested_revision and rev < self.max_revisions:
                cand = ReverseQAOutput(question_original=quality.suggested_revision,
                                       question_paraphrased=qa_out.question_paraphrased,
                                       answer_template=qa_out.answer_template, limitations=qa_out.limitations)
                errs = self.qa.validate(cand, bundle)          # 수정본도 같은 결정론적 검사 (GT 불변)
                if not errs:
                    q1 = self._fill_q(cand.question_original, bundle)
                    self.counters["question_revisions"] += 1
                    continue
            o.stage, o.codes = "semantic_review", ["SEMANTIC_REJECTED"]
            flags = [k for k in self.review_required if not getattr(quality, k)]
            if quality.ambiguity_detected:
                flags.append("ambiguity_detected")
            o.reasons = [f"검수 불합격 항목: {', '.join(flags) or '-'}", *quality.rejection_reasons,
                         *[f"빠진 조건: {m}" for m in quality.missing_conditions]]
            o.extra.update(question_original=q1, question_paraphrased=q2, reference_answer=ref[:1500],
                           review=quality.model_dump(mode="json"))
            return o
        o.flags["semantic_passed"] = True
        mapping = {v: self.mapper.map_view(self.index.view(v)) for v in cluster.view_ids}
        o.record = build_answerable_record(
            index=self.index, cluster=cluster, plan=plan, calc=calc, plan_report=rep_p, result_report=rep_r, ablation=abl,
            judgements=judgements, groups=groups, question_original=q1, question_paraphrased=q2, reference_answer=ref,
            evidence_trace=trace, numeric_check=chk, quality=quality, mapping=mapping, snapshot_id=self.snapshot_id,
            cfg=self.cfg, llm_provider=self.llm.provider, llm_model=self.llm.model, planner_attempts=o.planner_attempts)
        if o.repairs:
            o.record.provenance.plan_repairs = list(o.repairs)
        if o.record.reasoning_type == ReasoningType.CROSS_TABLE_RATIO and o.record.hop_type.value != "MULTI_TABLE_MULTI_VIEW":
            o.stage, o.codes = "hop_type", ["SINGLE_TABLE_ANSWERABLE"]
            o.reasons = ["대체 Positive 를 포함하면 한 표로 모든 필수 근거를 채울 수 있음 → 표 간 비율 문제가 아님"]
            o.record = None
        return o

    @staticmethod
    def _fill_q(q: str, bundle: dict) -> str:
        from synthetic_gold_pipeline.agents.reverse_qa_agent import fill
        return fill(q, {k: v for k, v in bundle["values"].items() if k.startswith("T") or k == "K"})

    # ── 할당량 ──────────────────────────────────────────────────
    def targets(self, n_total: int) -> tuple[dict[ReasoningType, int], int]:
        n_un = round(n_total * self.unans_ratio)
        n_ans = n_total - n_un
        w = {t: float(self.type_ratio.get(t.value, DEFAULT_TYPE_RATIO.get(t, 1.0))) for t in ANSWERABLE_TYPES}
        s = sum(w.values())
        raw = {t: n_ans * w[t] / s for t in ANSWERABLE_TYPES}
        out = {t: int(raw[t]) for t in ANSWERABLE_TYPES}
        for t in sorted(ANSWERABLE_TYPES, key=lambda t: raw[t] - out[t], reverse=True)[: n_ans - sum(out.values())]:
            out[t] += 1
        return out, n_un

    def _count(self, rt: ReasoningType) -> int:
        return sum(1 for r in self.accepted if r.reasoning_type == rt)

    # ── 실행 ────────────────────────────────────────────────────
    async def run(self, target_count: int) -> dict:
        tgt, _ = self.targets(target_count)
        budget_stop, empty_streak = False, 0
        shortfall: list[str] = []
        unavailable: set[ReasoningType] = set()
        while self.attempt_index < self.max_attempts and not budget_stop:
            need = {t: tgt[t] - self._count(t) for t in ANSWERABLE_TYPES if t not in unavailable}
            if all(v <= 0 for v in need.values()):
                break
            batch: list[SampledCluster] = []
            planned = Counter()
            for _ in range(self.batch_size):
                order = sorted((t for t, v in need.items() if v - planned[t] > 0),
                               key=lambda t: (-(need[t] - planned[t]) / max(1, tgt[t]), t.value))
                if not order or self.attempt_index >= self.max_attempts:
                    break
                rt = order[0]
                cl = self.sampler.sample(rt, self.attempt_index)
                self.attempt_index += 1
                self.counters["sampling_attempts"] += 1
                if cl is None:
                    self.counters["sampling_failed"] += 1
                    self.failures[f"sampling:NO_COMPATIBLE_CLUSTER:{rt.value}"] += 1
                    self.counters[f"sampling_failed:{rt.value}"] += 1
                    if self.counters[f"sampling_failed:{rt.value}"] >= int(self.cfg.get("run", {}).get(
                            "max_consecutive_sampling_failures", 30)):
                        unavailable.add(rt)
                        shortfall.append(f"{rt.value}: 호환 가능한 View 클러스터를 더 찾지 못함 (표·조사 상한 포함)")
                    continue
                self.counters[f"sampling_failed:{rt.value}"] = 0
                planned[rt] += 1
                batch.append(cl)
            if not batch:
                empty_streak += 1
                if empty_streak >= 3 or not need:
                    break
                continue
            empty_streak = 0
            outs = await asyncio.gather(*(self.process(c) for c in batch))
            for o in sorted(outs, key=lambda x: x.cluster.attempt_index):
                for k, v in o.flags.items():
                    if v:
                        self.counters[f"ok:{k}"] += 1
                if o.rate_limited:                       # 샘플 잘못이 아님 → 탈락으로 세지 않고 멈춤
                    self.counters["rate_limited_stop"] += 1
                    if not budget_stop:
                        shortfall.append("HCX 호출 한도(429)가 기다려도 계속됨 — llm.rate_limit 를 낮추거나 몇 분 뒤 --resume")
                    budget_stop = True
                    continue
                self.counters["processed_samples"] += 1
                if o.budget_exhausted:
                    budget_stop = True
                    shortfall.append("최대 API 호출 수 도달")
                if o.record is None:
                    self._reject(o)
                    continue
                self._accept(o, tgt)
            self._save_state()
            top = ", ".join(f"{k} {v}" for k, v in self.failures.most_common(3) if not k.startswith("sampling:"))
            log.info("시도 %d · 채택 %d/%d · API %d%s", self.attempt_index, len(self.accepted), sum(tgt.values()),
                     self.llm.usage.calls, f" · 탈락 상위: {top}" if top else "")
            ff = int(self.cfg.get("run", {}).get("fail_fast_after", 0) or 0)
            n_ans = sum(1 for r in self.accepted if r.reasoning_type != ReasoningType.UNANSWERABLE_ABSTENTION)
            if ff and n_ans == 0 and self.counters["processed_samples"] >= ff:
                shortfall.append(f"조기 중단: 처음 {self.counters['processed_samples']}개 샘플이 모두 탈락 "
                                 f"(run.fail_fast_after={ff}) — 탈락 원인: {top}")
                log.warning("처음 %d개 샘플이 모두 탈락해 중단합니다 (API 낭비 방지). 원인 확인: "
                            "python -m synthetic_gold_pipeline.diagnose", self.counters["processed_samples"])
                break
        if self.attempt_index >= self.max_attempts and any(tgt[t] > self._count(t) for t in ANSWERABLE_TYPES):
            shortfall.append(f"최대 샘플링 시도 {self.max_attempts}회 도달")
        # 답변 불가: 최종 채택된 답변 가능 레코드 수 기준 비율
        n_ans = sum(1 for r in self.accepted if r.reasoning_type != ReasoningType.UNANSWERABLE_ABSTENTION)
        have_un = sum(1 for r in self.accepted if r.reasoning_type == ReasoningType.UNANSWERABLE_ABSTENTION)
        n_un_target = round(n_ans * self.unans_ratio / (1 - self.unans_ratio)) if n_ans else 0
        if n_un_target > have_un:
            ub = UnanswerableBuilder(self.index, self.snapshot_id, self.cfg.get("unanswerable", {}),
                                     today=_today(self.cfg), base_seed=self.seed)
            base = [r for r in self.accepted if r.reasoning_type != ReasoningType.UNANSWERABLE_ABSTENTION]
            existing = {r.dataset_id for r in self.accepted}
            for rec in ub.build(n_un_target - have_un, base, start_index=have_un, exclude_ids=existing):
                fs, es = signatures(rec)
                dec = self.dedup.check(rec.dataset_id, [rec.question_original, rec.question_paraphrased], fs, es)
                if dec.is_duplicate and rec.answerability_type.value != "CONTEXT_UNANSWERABLE":
                    self.failures["unanswerable:DUPLICATE"] += 1
                    continue
                if any(r.dataset_id == rec.dataset_id for r in self.accepted):
                    continue
                self._set_sim(rec, dec)
                self.accepted.append(rec)
                if rec.answerability_type.value != "CONTEXT_UNANSWERABLE":
                    self.dedup.add(rec.dataset_id, [rec.question_original, rec.question_paraphrased], fs, es)
                append_jsonl(self._ckpt("accepted.jsonl"), [rec])
            got = sum(1 for r in self.accepted if r.reasoning_type == ReasoningType.UNANSWERABLE_ABSTENTION)
            if got < n_un_target:
                shortfall.append(f"답변 불가 {got}/{n_un_target}: 검증 가능한 후보 부족")
        self._save_state()
        return self.write_outputs(target_count, tgt, n_un_target, shortfall)

    @staticmethod
    def _set_sim(rec: GoldenRecord, dec):
        vm = rec.verification_metrics
        vm.max_jaccard_similarity, vm.max_cosine_similarity, vm.max_similarity_score = (dec.max_jaccard, dec.max_cosine,
                                                                                         dec.max_score)

    def _accept(self, o: Outcome, tgt: dict):
        rec = o.record
        rt = rec.reasoning_type
        if self._count(rt) >= tgt.get(rt, 0):
            self.counters["quota_full_discarded"] += 1
            o.stage, o.codes, o.reasons = "quota", ["QUOTA_FULL"], ["유형별 목표 개수 충족 후 생성된 샘플"]
            self._reject(o)
            return
        fs, es = signatures(rec)
        dec = self.dedup.check(rec.dataset_id, [rec.question_original, rec.question_paraphrased], fs, es)
        if dec.is_duplicate or any(r.dataset_id == rec.dataset_id for r in self.accepted):
            self.counters["dedup_dropped"] += 1
            o.stage, o.codes, o.reasons = "dedup", [dec.reason if dec.is_duplicate else "DUPLICATE_ID"], [
                f"matched={dec.matched_id} score={dec.max_score}"]
            self._reject(o)
            return
        self._set_sim(rec, dec)
        self.dedup.add(rec.dataset_id, [rec.question_original, rec.question_paraphrased], fs, es)
        self.accepted.append(rec)
        regions = rec.module_eval.M1.expected_filters.get("regions", [])
        self.sampler.register_accepted(o.cluster, regions, rec.module_eval.M1.expected_filters.get("periods", []))
        append_jsonl(self._ckpt("accepted.jsonl"), [rec])

    # ── 출력 ────────────────────────────────────────────────────
    def write_outputs(self, target_count: int, tgt: dict, n_un_target: int, shortfall: list[str]) -> dict:
        ds = self.dirs["datasets"]
        recs = sorted(self.accepted, key=lambda r: (r.reasoning_type.value != "UNANSWERABLE_ABSTENTION",
                                                    r.provenance.attempt_index, r.dataset_id), reverse=False)
        recs = sorted(recs, key=lambda r: (r.reasoning_type == ReasoningType.UNANSWERABLE_ABSTENTION, r.provenance.attempt_index))
        write_jsonl(ds / "synthetic_gold_dataset.jsonl", recs)
        qbuf, abuf = io.StringIO(), io.StringIO()
        qw = csv.DictWriter(qbuf, fieldnames=QUERY_CSV_COLUMNS, lineterminator="\n")
        aw = csv.DictWriter(abuf, fieldnames=ANSWER_REF_COLUMNS, lineterminator="\n")
        qw.writeheader()
        aw.writeheader()
        for r in recs:
            for kind, q in (("original", r.question_original), ("paraphrased", r.question_paraphrased)):
                qid = r.question_ids[kind]
                qw.writerow({"id": qid, "survey": "/".join(r.survey_names), "test_type": r.reasoning_type.value,
                             "target_module": "M1/M2/M3", "question": q})
                ge, re_ = r.generation_eval, r.retrieval_eval
                aw.writerow({
                    # 기존 eval/pipeline_review(review_80·review_v4)가 읽는 형식: 쉼표로 나눈 TBL_ID (JSON 목록은 _json 열)
                    "id": qid, "dataset_id": r.dataset_id, "gold_table_ids": ", ".join(re_.golden_table_ids),
                    "gold_table_ids_json": json.dumps(re_.golden_table_ids, ensure_ascii=False),
                    "answerability": "UNANSWERABLE" if ge.expected_abstention else "ANSWERABLE",
                    "question_variant": kind,
                    "gold_org_table_id": json.dumps(re_.golden_org_table_ids, ensure_ascii=False),
                    "gold_view_ids": json.dumps(re_.golden_view_ids, ensure_ascii=False),
                    "required_evidence_groups": json.dumps({k: v.model_dump() for k, v in re_.required_evidence_groups.items()},
                                                           ensure_ascii=False),
                    "gold_answer_text": ge.reference_answer_text or ge.reference_answer.split("\n\n[근거]")[0].strip(),
                    "gold_answer": ge.reference_answer,
                    "numeric_ground_truth": json.dumps(ge.exact_numeric_ground_truth.model_dump() if ge.exact_numeric_ground_truth
                                                       else (ge.final_answer.model_dump() if ge.final_answer else None),
                                                       ensure_ascii=False),
                    "source_url": json.dumps(sorted({self.index.view(v).source_url for v in re_.golden_view_ids
                                                     if v in self.index.views}), ensure_ascii=False),
                    "source_csv_paths": json.dumps(sorted({c.source_path for c in re_.source_coordinate_references}),
                                                   ensure_ascii=False),
                    "source_coordinates": json.dumps([c.model_dump() for c in re_.source_coordinate_references], ensure_ascii=False),
                    "executed_sql": json.dumps(ge.executed_sql, ensure_ascii=False),
                    "executed_formula": ge.executed_formula,
                    "gold_status": r.verification_metrics.verification_status.value,
                    "strict_hit_eligible": bool(re_.retrieval_eligible and re_.golden_view_ids),
                    "module_eval": json.dumps(r.module_eval.model_dump(mode="json"), ensure_ascii=False)})
        atomic_write_text(ds / "synthetic_gold_queries.csv", "﻿" + qbuf.getvalue())
        atomic_write_text(ds / "synthetic_gold_answers_references.csv", "﻿" + abuf.getvalue())
        report = self.report(target_count, tgt, n_un_target, shortfall, recs)
        atomic_write_json(self.dirs["reports"] / "generation_report.json", report)
        if not (self.dirs["rejected_samples"] / "rejected_samples.jsonl").exists():
            atomic_write_text(self.dirs["rejected_samples"] / "rejected_samples.jsonl", "")
        if not (self.dirs["reports"] / "validation_errors.jsonl").exists():
            atomic_write_text(self.dirs["reports"] / "validation_errors.jsonl", "")
        atomic_write_json(self.dirs["reports"] / "run_manifest.json", self.manifest(ds))
        return report

    def report(self, target_count, tgt, n_un_target, shortfall, recs) -> dict:
        c = self.counters
        proc = max(1, c["processed_samples"])
        n_un = sum(1 for r in recs if r.reasoning_type == ReasoningType.UNANSWERABLE_ABSTENTION)

        def rate(k):
            return round(c[f"ok:{k}"] / proc, 4)
        return {
            "pipeline_version": __version__, "mode": self.mode, "generated_at": now_iso(),
            "elapsed_seconds": round(time.time() - self.t0, 2),
            "target_count": target_count, "target_count_unit": self.cfg.get("run", {}).get("target_count_unit", "fact_records"),
            "target_count_note": "N = Fact 레코드 수. 각 레코드는 질문 2개(original·paraphrased)를 질문 CSV 에 별도 ID 로 가진다.",
            "taxonomy_targets": {t.value: v for t, v in tgt.items()} | {"UNANSWERABLE_ABSTENTION": n_un_target},
            "final_dataset_count": len(recs), "final_question_count": 2 * len(recs),
            "unanswerable_ratio_actual": round(n_un / len(recs), 4) if recs else None,
            "total_sampling_attempts": c["sampling_attempts"], "sampling_failed": c["sampling_failed"],
            "processed_samples": c["processed_samples"],
            "rates_over_processed_samples": {
                "plan_generation_success": rate("plan_generated"), "statistical_compatibility_success": rate("statistically_compatible"),
                "calculation_success": rate("calculated"), "ablation_pass": rate("ablation_passed"),
                "question_generation_success": rate("question_generated"), "numeric_validation_pass": rate("numeric_validated"),
                "semantic_review_pass": rate("semantic_passed")},
            "dedup_dropped": c["dedup_dropped"],
            "dedup_drop_rate": round(c["dedup_dropped"] / max(1, c["dedup_dropped"] + len(recs) - n_un), 4),
            "quota_full_discarded": c["quota_full_discarded"], "planner_self_correction_retries": c["planner_retries"],
            "question_revisions": c["question_revisions"],
            "distribution": {
                "by_taxonomy": dict(Counter(r.reasoning_type.value for r in recs)),
                "by_subtype": dict(Counter(r.subtype for r in recs)),
                "by_hop_type": dict(Counter(r.hop_type.value if r.hop_type else "NONE" for r in recs)),
                "by_survey": dict(Counter(s for r in recs for s in r.survey_names)),
                "by_answerability": dict(Counter(r.answerability_type.value for r in recs)),
                "by_verification_status": dict(Counter(r.verification_metrics.verification_status.value for r in recs)),
                "by_difficulty": dict(Counter(r.difficulty for r in recs))},
            "coverage": self._coverage(recs),
            "failure_reasons": dict(self.failures.most_common()),
            "api": self.llm.usage.to_json() | {"provider": self.llm.provider, "model": self.llm.model},
            "shortfall_reasons": shortfall if len(recs) < target_count else [],
            "notes": ["Mock LLM(Demo) 결과는 파이프라인 동작 검증이며 실제 LLM 생성 품질 검증이 아닙니다."] if self.llm.provider == "mock" else [],
            "metadata_index": self.index.build_info,
            "existing_rag_view_mapping": {"views_jsonl_found": self.mapper.available, "n_loaded": self.mapper.n_loaded},
        }

    def manifest(self, ds: Path) -> dict:
        files = {}
        for p in sorted(ds.glob("*")):
            if p.is_file():
                files[display_path(p)] = sha256_file(p)
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
                                    cwd=str(PACKAGE_ROOT)).stdout.strip() or None
        except Exception:  # noqa: BLE001
            commit = None
        cfg = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        return {"pipeline_version": __version__, "mode": self.mode, "seed": self.seed, "data_root": display_path(self.data_root),
                "data_snapshot_id": self.snapshot_id, "config_path": self.cfg.get("_config_path"), "config_hash": self._config_hash(),
                "config": _redact(cfg), "git_commit": commit, "python": sys.version.split()[0], "platform": platform.platform(),
                "llm": {"provider": self.llm.provider, "model": self.llm.model}, "output_files": files,
                "resumed": self.resume, "finished_at": now_iso()}


def label_texts(bundle: dict) -> list[str]:
    li = bundle["llm_input"]
    out = []
    for o in li["operands"]:
        out += [o["item"], o["table"], o["survey"], *o["fixed_labels"].values(), *o.get("split_labels", {}).values()]
    for f in li["scalar_facts"]:
        out += [f["item"], f["table"], *(f.get("labels") or {}).values()]
    for t in li["thresholds"]:
        out += [t.get("condition_item") or "", t.get("condition_table") or ""]
    return [x for x in out if x]


def _redact(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: ("***" if any(s in k.lower() for s in ("key", "secret", "token", "password")) and k != "api_key_env"
                    else _redact(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_redact(v) for v in x]
    return x


def _today(cfg) -> date:
    s = cfg.get("run", {}).get("today")
    return date.fromisoformat(s) if s else date.today()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="KOSIS Multi-View Synthetic Golden Set 생성")
    ap.add_argument("--config", default=str(PACKAGE_ROOT / "configs" / "pipeline.yaml"))
    ap.add_argument("--mode", choices=["demo", "real"], default="demo")
    ap.add_argument("--data-root", default=None, help="real: KOSIS 데이터 폴더 (기본: 설정 paths.kosis_data_root)")
    ap.add_argument("--target-count", type=int, default=None, help="목표 Fact 레코드 수 (질문 수 = 2배)")
    ap.add_argument("--output-root", default=None, help="출력 폴더 (기본: synthetic_gold_pipeline/outputs)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rebuild-index", action="store_true", help="메타데이터 인덱스 캐시를 무시하고 전부 다시 읽기")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--max-attempts", type=int, default=None)
    ap.add_argument("--max-api-calls", type=int, default=None)
    ap.add_argument("--llm-provider", default=None, help="mock | hcx | hcx_repo | openai_compat (모드 기본값 대신)")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def build_from_args(args) -> tuple[Pipeline, int]:
    load_dotenv_if_present()
    over: dict[str, Any] = {"run": {}, "llm": {}}
    if args.seed is not None:
        over["run"]["seed"] = args.seed
    if args.concurrency is not None:
        over["run"]["concurrency"] = args.concurrency
        over["llm"]["max_concurrency"] = args.concurrency
    if args.max_attempts is not None:
        over["run"]["max_sampling_attempts"] = args.max_attempts
    if args.max_api_calls is not None:
        over["llm"]["max_api_calls"] = args.max_api_calls
    if args.llm_provider:
        over["llm"]["provider" if args.mode == "real" else "provider_demo"] = args.llm_provider
    cfg = load_config(args.config, over)
    out = resolve_path(args.output_root) if args.output_root else (resolve_path(cfg.get("paths", {}).get("output_root"),
                                                                                 PACKAGE_ROOT.parent) or PACKAGE_ROOT / "outputs")
    data_root = None
    if args.mode == "real":
        data_root = resolve_path(args.data_root or cfg.get("paths", {}).get("kosis_data_root") or "storage/kosis_data")
    elif args.data_root:
        data_root = resolve_path(args.data_root)
    target = args.target_count or int(cfg.get("run", {}).get("target_count", 10))
    return Pipeline(cfg, args.mode, out, data_root, args.resume, args.rebuild_index), target


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pipe, target = build_from_args(args)
    try:
        pipe.prepare()
    except (LLMConfigError, FileNotFoundError, PermissionError, RuntimeError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    report = asyncio.run(pipe.run(target))
    print(json.dumps({k: report[k] for k in ("final_dataset_count", "final_question_count", "taxonomy_targets",
                                             "shortfall_reasons")} | {"distribution": report["distribution"]["by_taxonomy"],
                                                                      "processed_samples": report["processed_samples"],
                                                                      "table_coverage": {k: report["coverage"][k] for k in (
                                                                          "tables_total", "tables_tried", "tables_in_dataset")},
                                                                      "stage_pass_rates": report["rates_over_processed_samples"],
                                                                      "failure_reasons": dict(list(report["failure_reasons"].items())[:12]),
                                                                      "api_by_task": {k: v.get("calls") for k, v in
                                                                                      (report["api"].get("by_task") or {}).items()},
                                                                      "output": display_path(pipe.dirs["datasets"])},
                     ensure_ascii=False, indent=2))
    if report["final_dataset_count"] == 0 and report["processed_samples"]:
        print("\n채택 0건 — 탈락 원인 자세히: python -m synthetic_gold_pipeline.diagnose", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
