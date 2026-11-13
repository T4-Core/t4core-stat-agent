"""[NEW 11-12] 쉬운 평가셋 (configs/pipeline_easy.yaml) — Demo Mode · Mock LLM
설정 상속(extends) · 단순 조회 유형 · View 거르기(min_year·표 이름) · 기본 설정은 예전과 같음"""
from __future__ import annotations

import asyncio
import random

from synthetic_gold_pipeline.agents.planner_agent import _lookup_code, mock_plan_response
from synthetic_gold_pipeline.main_pipeline import Pipeline
from synthetic_gold_pipeline.schemas.dataset import GoldenRecord
from synthetic_gold_pipeline.schemas.planning import ReasoningType
from synthetic_gold_pipeline.utils import PACKAGE_ROOT, load_config, read_jsonl

EASY = PACKAGE_ROOT / "configs" / "pipeline_easy.yaml"


def test_easy_config_extends_base():
    base, easy = load_config(), load_config(EASY)
    assert easy["run"]["taxonomy_ratio"]["CONDITIONAL_AGGREGATION"] == 0.0
    assert easy["sampler"]["min_year"] == 2015 and easy["sampler"]["max_conditions_per_view"] == 1
    assert easy["calculation"] == base["calculation"]                 # 적지 않은 값은 기본 설정 그대로
    assert "extends" not in easy and base["run"]["taxonomy_ratio"]["SIMPLE_LOOKUP"] == 0.0


def test_default_targets_unchanged(tmp_path):
    p = Pipeline(load_config(), "demo", tmp_path, None)
    tgt, _ = p.targets(30)
    assert tgt[ReasoningType.SIMPLE_LOOKUP] == 0                      # 기본 설정은 단순 조회를 만들지 않음
    e = Pipeline(load_config(EASY), "demo", tmp_path, None)
    et, n_un = e.targets(21)
    assert et[ReasoningType.CONDITIONAL_AGGREGATION] == 0 and n_un == 0 and et[ReasoningType.SIMPLE_LOOKUP] >= 9


def test_lookup_code_prefers_sido_and_skips_ambiguous():
    card = {"dimensions": [{"dim_type": "REGION", "level": "C1", "n_codes": 4, "codes": [
        {"code": "00", "name": "전국", "is_total": True}, {"code": "11", "name": "서울특별시", "is_total": False},
        {"code": "11010", "name": "중구", "is_total": False}, {"code": "21010", "name": "중구", "is_total": False}]}]}
    got = {_lookup_code(card, random.Random(s)) for s in range(40)}
    assert got <= {"00", "11"} and got == {"00", "11"}
    sgg = {"dimensions": [{"dim_type": "REGION", "level": "C1", "n_codes": 3, "codes": [
        {"code": "11010", "name": "중구", "is_total": False}, {"code": "21010", "name": "중구", "is_total": False},
        {"code": "11110", "name": "종로구", "is_total": False}]}]}
    assert {_lookup_code(sgg, random.Random(s)) for s in range(20)} == {"11110"}   # 이름이 겹치는 '중구' 는 안 고름
    plan = mock_plan_response({"subtype": "LOOKUP", "reasoning_type": "SIMPLE_LOOKUP", "random_seed": 1, "views": [
        {"view_id": "v1", "items": [{"itm_id": "T1"}], "periods": ["2024"], **card}]})
    assert [s["op"] for s in plan["operation"]["steps"]] == ["LOOKUP"] and len(plan["operands"]) == 1


def test_easy_demo_run(tmp_path):
    p = Pipeline(load_config(EASY), "demo", tmp_path, None)
    p.prepare()
    rep = asyncio.run(p.run(12))
    recs = [GoldenRecord.model_validate(d) for d in read_jsonl(tmp_path / "datasets" / "synthetic_gold_dataset.jsonl")]
    dist = rep["distribution"]["by_taxonomy"]
    assert dist.get("SIMPLE_LOOKUP", 0) >= 4 and "CONDITIONAL_AGGREGATION" not in dist
    for r in recs:
        tables = r.retrieval_eval.golden_table_ids
        assert 1 <= len(tables) <= 2                                   # CSV 1개 또는 2개
        assert all(int(f.coordinate.PRD_DE[:4]) >= 2015 for f in r.generation_eval.intermediate_facts)
        if r.reasoning_type == ReasoningType.SIMPLE_LOOKUP:
            assert r.hop_type.value == "SINGLE_TABLE_SINGLE_VIEW" and r.difficulty == "easy"
            assert len(r.generation_eval.intermediate_facts) == 1
            assert "중구" not in r.question_paraphrased
