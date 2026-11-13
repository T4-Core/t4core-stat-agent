"""E2E (Demo Mode, Mock LLM) + LLM Client 단위 테스트.

Mock LLM 통과는 파이프라인 동작(데이터 처리·계산·역생성 인터페이스·검증·저장) 검증이며 실제 LLM 생성 품질 검증이 아니다.
"""
from __future__ import annotations

import asyncio
import csv
import json
import re
from pathlib import Path

import pandas as pd
import pytest
from pydantic import BaseModel

from synthetic_gold_pipeline.agents.llm_client import (BaseLLMClient, HCXClient, LLMBudgetExceeded, LLMConfigError,
                                                       LLMResponseError, LLMTransientError, MockLLMClient, extract_json)
from synthetic_gold_pipeline.main_pipeline import Pipeline
from synthetic_gold_pipeline.schemas.dataset import QUERY_CSV_COLUMNS, GoldenRecord
from synthetic_gold_pipeline.schemas.planning import OperationPlan
from synthetic_gold_pipeline.tools.calculation_tool import TableCalculationEngine
from synthetic_gold_pipeline.utils import REPO_ROOT, load_config, read_jsonl


def run_pipeline(out: Path, n: int, resume=False, **run_over) -> tuple[Pipeline, dict]:
    cfg = load_config(overrides={"run": run_over} if run_over else None)
    p = Pipeline(cfg, "demo", out, None, resume=resume)
    p.prepare()
    return p, asyncio.run(p.run(n))


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    out = tmp_path_factory.mktemp("e2e")
    p, rep = run_pipeline(out, 20)
    recs = [GoldenRecord.model_validate(d) for d in read_jsonl(out / "datasets" / "synthetic_gold_dataset.jsonl")]
    return {"out": out, "pipe": p, "report": rep, "recs": recs}


def test_outputs_exist_and_counts(e2e):
    out, rep, recs = e2e["out"], e2e["report"], e2e["recs"]
    for f in ["datasets/synthetic_gold_dataset.jsonl", "datasets/synthetic_gold_queries.csv",
              "datasets/synthetic_gold_answers_references.csv", "reports/generation_report.json",
              "rejected_samples/rejected_samples.jsonl", "reports/validation_errors.jsonl", "reports/run_manifest.json",
              "metadata_index/views.jsonl", "metadata_index/compatibility_edges.jsonl", "checkpoints/state.json"]:
        assert (out / f).exists(), f
    assert rep["final_dataset_count"] == len(recs) == 20
    assert len({r.dataset_id for r in recs}) == 20
    n_un = sum(r.reasoning_type.value == "UNANSWERABLE_ABSTENTION" for r in recs)
    assert 0.10 <= n_un / len(recs) <= 0.15
    assert {r.hop_type.value for r in recs if r.hop_type} >= {"SINGLE_TABLE_MULTI_VIEW", "MULTI_TABLE_MULTI_VIEW"}
    assert rep["target_count_unit"] == "fact_records" and rep["final_question_count"] == 40
    assert rep["planner_self_correction_retries"] > 0            # 주입된 구조 오류 → 재시도 경로 실제 통과
    assert rep["api"]["calls"] > 0 and rep["notes"]


def test_query_csv_has_only_five_columns_and_no_leakage(e2e):
    out, recs = e2e["out"], e2e["recs"]
    with open(out / "datasets" / "synthetic_gold_queries.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == QUERY_CSV_COLUMNS
    assert len(rows) == 40 and len({r["id"] for r in rows}) == 40
    gt = {}
    for r in recs:
        fa = r.generation_eval.final_answer
        if fa and fa.value:
            gt[r.question_ids["original"]] = gt[r.question_ids["paraphrased"]] = fa.value
    for row in rows:
        q = row["question"]
        assert "kosis.kr" not in q and not re.search(r"\b101_", q) and "sgv::" not in q
        if row["id"] in gt:
            v = gt[row["id"]]
            assert v.display not in q and v.display.replace(",", "") not in q
    with open(out / "datasets" / "synthetic_gold_answers_references.csv", encoding="utf-8-sig") as f:
        refs = list(csv.DictReader(f))
    assert {r["id"] for r in refs} == {r["id"] for r in rows}


def _raw_value(path: str, row_number: int) -> str:
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    if p.suffix == ".parquet":
        return str(pd.read_parquet(p).iloc[row_number - 1]["value_raw"])
    df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return df.iloc[row_number - 1]["DT"]


def test_every_source_coordinate_matches_original_raw_row(e2e):
    n = 0
    for r in e2e["recs"]:
        for c in r.retrieval_eval.source_coordinate_references:
            assert _raw_value(c.source_path, c.row_number) == c.raw_value
            n += 1
    assert n > 20


def test_ground_truth_is_reproducible_from_saved_plan(e2e):
    pipe = e2e["pipe"]
    eng = TableCalculationEngine(pipe.index, pipe.cfg["calculation"])
    checked = 0
    for r in e2e["recs"]:
        if r.reasoning_type.value == "UNANSWERABLE_ABSTENTION":
            continue
        saved = json.loads((e2e["out"] / "intermediate_facts" / f"{r.provenance.sample_id}.json").read_text(encoding="utf-8"))
        plan = OperationPlan.model_validate(saved["plan"])
        res = eng.run(plan, saved["cluster"]["view_ids"])
        assert res.success and res.final.model_dump() == r.generation_eval.final_answer.model_dump()
        checked += 1
    assert checked >= 15


def test_answerable_records_verified_and_honest_status(e2e):
    for r in e2e["recs"]:
        vm = r.verification_metrics
        if r.reasoning_type.value == "UNANSWERABLE_ABSTENTION":
            assert r.generation_eval.expected_abstention and r.generation_eval.exact_numeric_ground_truth is None
            continue
        assert vm.deterministic_passed and vm.numeric_validation_passed and vm.statistical_validation_passed
        assert vm.ablation_passed and all(a.outcome.value == "NECESSARY" for a in vm.per_view_ablation_results)
        assert vm.human_review_required and vm.verification_status.value == "NEEDS_HUMAN_REVIEW"   # Mock 검수
        assert len(r.retrieval_eval.required_evidence_groups) == len(r.retrieval_eval.golden_view_ids) >= 2
        assert not set(r.retrieval_eval.hard_negative_view_ids) & set(r.retrieval_eval.golden_view_ids)
        assert r.module_eval.M2.expected_source_coordinates and r.generation_eval.executed_sql
        assert all(v["status"] in ("UNMAPPED", "MAPPED_EXACT", "MAPPED_CONTAINING")
                   for v in r.retrieval_eval.view_mapping_status.values())
        groups = list(r.retrieval_eval.required_evidence_groups.values())
        one_table = bool(set.intersection(*[set(g.acceptable_table_ids) for g in groups]))
        assert (not one_table) == (r.hop_type.value == "MULTI_TABLE_MULTI_VIEW")   # 한 표로 다 채울 수 있으면 SINGLE


def test_generated_files_stay_inside_output_root(e2e):
    for v in e2e["pipe"].index.views.values():
        if v.input_mode.value == "GENERATED_FROM_RAW":
            p = Path(v.view_file) if Path(v.view_file).is_absolute() else REPO_ROOT / v.view_file
            assert e2e["out"] in p.resolve().parents


def test_resume_continues_without_duplicates(tmp_path):
    run_pipeline(tmp_path, 6)
    _, rep = run_pipeline(tmp_path, 12, resume=True)
    recs = list(read_jsonl(tmp_path / "datasets" / "synthetic_gold_dataset.jsonl"))
    assert rep["final_dataset_count"] == 12 == len(recs) == len({r["dataset_id"] for r in recs})


def test_deterministic_across_concurrency(tmp_path):
    _, _ = run_pipeline(tmp_path / "a", 8, concurrency=4)
    _, _ = run_pipeline(tmp_path / "b", 8, concurrency=1, batch_size=8)
    a = [d["question_original"] for d in read_jsonl(tmp_path / "a" / "datasets" / "synthetic_gold_dataset.jsonl")]
    b = [d["question_original"] for d in read_jsonl(tmp_path / "b" / "datasets" / "synthetic_gold_dataset.jsonl")]
    assert a == b


def test_shortfall_reported_not_infinite_loop(tmp_path):
    _, rep = run_pipeline(tmp_path, 200, max_sampling_attempts=12)
    assert rep["final_dataset_count"] < 200 and rep["shortfall_reasons"]


# ── LLM Client ─────────────────────────────────────────────────────
class _Out(BaseModel):
    a: int


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('설명입니다 {"a": {"b": "}"}} 끝') == {"a": {"b": "}"}}
    with pytest.raises(LLMResponseError):
        extract_json("no json")


def test_structured_retry_and_budget():
    c = MockLLMClient({"structured_retries": 2, "max_api_calls": 10})
    c.register("t", lambda ctx: {"a": "x"} if ctx["_attempt"] == 0 else {"a": 3})
    obj, meta = asyncio.run(c.generate_structured("t", "s", "u", _Out, context={}))
    assert obj.a == 3 and meta["attempts"] == 2 and c.usage.structured_retries == 1
    c2 = MockLLMClient({"max_api_calls": 1, "structured_retries": 3})
    c2.register("t", lambda ctx: {"a": "bad"})
    with pytest.raises(LLMBudgetExceeded):
        asyncio.run(c2.generate_structured("t", "s", "u", _Out, context={}))


def test_transient_errors_are_retried(monkeypatch):
    class Flaky(BaseLLMClient):
        n = 0

        async def _raw(self, task, system, user, schema, context):
            Flaky.n += 1
            if Flaky.n < 3:
                raise LLMTransientError("HTTP 429")
            return '{"a": 5}', {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}

    async def nosleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", nosleep)
    c = Flaky({"transient_retries": 4})
    obj, _ = asyncio.run(c.generate_structured("t", "s", "u", _Out, context={}))
    assert obj.a == 5 and c.usage.transient_retries == 2 and c.usage.total_tokens == 5 and c.usage.tokens_reported


def test_real_client_requires_key(monkeypatch):
    monkeypatch.delenv("HCX_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        HCXClient({})


# ── RAG 결과 채점 (review_v4 results.json 형식) ─────────────────────
def _fake_rag(recs, *, drop_group=None, drop_code=False, fail_paraphrase=False, answer=True):
    """Golden Set 으로 review_v4 형식의 가짜 RAG 결과를 만든다 (정상 + 의도된 실패)."""
    out = []
    for r in recs:
        for kind, qid in r.question_ids.items():
            units, final = [], []
            groups = r.retrieval_eval.required_evidence_groups
            by_fact = {f.fact_id: f.coordinate for f in r.generation_eval.intermediate_facts}
            for gi, (gid, g) in enumerate(groups.items()):
                drop_i = len(groups) - 1 if drop_group == "last" else drop_group
                if drop_i is not None and gi == drop_i or (fail_paraphrase and kind == "paraphrased"):
                    continue
                coords = [by_fact[f] for f in g.required_fact_ids if f in by_fact]
                if not coords:
                    continue
                c0 = coords[0]
                dims = {}
                for lv in c0.dims:
                    codes = sorted({c.dims[lv] for c in coords})
                    if drop_code and gi == 0:
                        codes = codes[:-1] or ["ZZ"]
                    dims[lv.lower()] = {"codes": codes}
                vid = f"view::{c0.ORG_ID}_{c0.TBL_ID}::Y::{gi}::value"
                v = {"record_id": vid, "tbl_id": c0.TBL_ID, "source": {"tbl_id": c0.TBL_ID, "itm_id": [c0.ITM_ID],
                                                                       "dims": dims, "period": {"in": [c0.PRD_DE]}}}
                units.append({"unit_id": gid, "candidates": [{"rank": 1, "tbl_id": c0.TBL_ID, "survey_nm": ""}], "views": [v]})
                final.append(vid)
            res = {"id": qid, "question": "", "units": units, "final": {"status": "ok", "records": final},
                   "stages": {"query": {"slots": [{"slot": "시점", "value": p} for p in r.module_eval.M1.expected_filters.get("periods", [])]
                                        + [{"slot": "지역", "value": g} for g in r.module_eval.M1.expected_filters.get("regions", [])],
                                        "clarifications": [{"slot": "지역"}] if r.answerability_type.value == "AMBIGUOUS" else []}}}
            if answer:
                res["answer"] = {"answer": ("제공된 자료로는 확인할 수 없습니다." if r.generation_eval.expected_abstention
                                            else r.generation_eval.reference_answer), "insufficient": False}
            out.append(res)
    return out


def test_score_rag_results_perfect_and_failures(e2e, tmp_path):
    from synthetic_gold_pipeline.score_rag_results import run as score
    ds = e2e["out"] / "datasets" / "synthetic_gold_dataset.jsonl"
    recs = e2e["recs"]
    p = tmp_path / "ok" / "results.json"
    p.parent.mkdir()
    p.write_text(json.dumps(_fake_rag(recs), ensure_ascii=False), encoding="utf-8")
    s = score(p, ds, tmp_path / "s_ok")
    ov = s["overall"]
    assert ov["Table_All_Hit@1"] == 1.0 and ov["View_All_Hit"] == 1.0 and ov["Final_Context_All_Hit"] == 1.0
    assert ov["ans_Numeric_Accuracy"] == 1.0 and ov["query_ok"] == 1.0
    assert set(s["first_failure"]) == {"NONE"}
    assert s["original_vs_paraphrased"]["BOTH_PASS"] == sum(r.reasoning_type.value != "UNANSWERABLE_ABSTENTION" for r in recs)
    assert (tmp_path / "s_ok" / "per_question.csv").exists() and (tmp_path / "s_ok" / "original_vs_paraphrased.csv").exists()
    # 마지막 필수 근거 그룹(다른 표 질문이면 두 번째 표)을 못 찾음 → All-Hit 0, Any-Hit 1, 진단 PARTIAL_RETRIEVAL
    p2 = tmp_path / "miss" / "results.json"
    p2.parent.mkdir()
    p2.write_text(json.dumps(_fake_rag(recs, drop_group="last", answer=False), ensure_ascii=False), encoding="utf-8")
    s2 = score(p2, ds, tmp_path / "s_miss")
    assert s2["overall"]["Table_Any_Hit@5"] == 1.0 and s2["overall"]["View_All_Hit"] == 0.0
    pq = pd.read_csv(tmp_path / "s_miss" / "per_question.csv", encoding="utf-8-sig")
    by_id = {r.dataset_id: r for r in recs}
    for _, row in pq[pq["answerability"] == "ANSWERABLE"].iterrows():
        g = list(by_id[row["dataset_id"]].retrieval_eval.required_evidence_groups.values())
        # 뺀 그룹의 허용 표가 다른 그룹의 표에도 있으면(같은 표·대체 표) 표 기준으로는 여전히 Hit 가 맞다
        still = bool(set(g[-1].acceptable_table_ids) & set().union(*[set(x.acceptable_table_ids) for x in g[:-1]]))
        assert row["Table_All_Hit@5"] == float(still), row["id"]
        assert row["View_All_Hit"] == 0.0                                 # 좌표 기준으로는 항상 못 찾음
    assert s2["first_failure"].get("PARTIAL_RETRIEVAL", 0) > 0
    # 표는 맞는데 View 조건(분류 코드)이 빠짐 → VIEW_CONDITION_ERROR
    p3 = tmp_path / "cond" / "results.json"
    p3.parent.mkdir()
    p3.write_text(json.dumps(_fake_rag(recs, drop_code=True, answer=False), ensure_ascii=False), encoding="utf-8")
    assert score(p3, ds, tmp_path / "s_cond")["first_failure"].get("VIEW_CONDITION_ERROR", 0) > 0
    # 일상어 질문만 실패 → 쿼리 변환 의심으로 분리
    p4 = tmp_path / "para" / "results.json"
    p4.parent.mkdir()
    p4.write_text(json.dumps(_fake_rag(recs, fail_paraphrase=True, answer=False), ensure_ascii=False), encoding="utf-8")
    s4 = score(p4, ds, tmp_path / "s_para")
    assert s4["original_vs_paraphrased"].get("ORIGINAL_ONLY (쿼리 변환 의심)", 0) > 0
    assert s4["by_variant"]["original"]["Table_All_Hit@5"] == 1.0 and s4["by_variant"]["paraphrased"]["Table_All_Hit@5"] == 0.0


def test_answers_csv_is_readable_by_existing_review_tools(e2e):
    """기존 eval/pipeline_review/review_80.expected_tables 와 같은 규칙으로 정답 표를 읽을 수 있어야 한다."""
    tbl_col = re.compile(r"tbl|table_?ids?|표_?id|정답_?표", re.I)
    tbl_id = re.compile(r"^[A-Z]{2,4}_[A-Za-z0-9_]+$")
    with open(e2e["out"] / "datasets" / "synthetic_gold_answers_references.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    recs = {r.question_ids["original"]: r for r in e2e["recs"]}
    for row in rows:
        got = set()
        for k, v in row.items():
            if tbl_col.search(k):
                got |= {x for x in re.split(r"[\s,;|/]+", str(v)) if tbl_id.match(x)}
        if row["id"] in recs and recs[row["id"]].retrieval_eval.golden_table_ids:
            assert got == set(recs[row["id"]].retrieval_eval.golden_table_ids)
        assert row["answerability"] in ("ANSWERABLE", "UNANSWERABLE")
