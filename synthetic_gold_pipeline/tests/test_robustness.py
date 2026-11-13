"""실제 LLM(HCX) 응답에서 생기는 모양 처리 · 진단 도구"""
from __future__ import annotations

import json

import pytest

from synthetic_gold_pipeline.diagnose import main as diagnose_main
from synthetic_gold_pipeline.schemas.calculation import CalcErrorCode, RETRYABLE_CODES
from synthetic_gold_pipeline.schemas.planning import Operand, OperationStep
from synthetic_gold_pipeline.tests.conftest import find_view
from synthetic_gold_pipeline.tests.test_calculation import _plan
from synthetic_gold_pipeline.tools.calculation_tool import TableCalculationEngine


def test_empty_strings_in_optional_fields_become_none():
    o = Operand.model_validate({"operand_id": "A", "view_id": "v", "itm_id": "T1", "prd_de": "2024",
                                "group_by_level": "", "depth": "null", "include_codes": "", "label": ""})
    assert o.group_by_level is None and o.depth is None and o.include_codes is None
    assert o.label == ""                                   # None 을 허용하지 않는 칸은 그대로


def test_unknown_group_by_level_is_retryable_not_crash(demo_env):
    eng = TableCalculationEngine(demo_env["index"], demo_env["cfg"]["calculation"])
    v = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    plan = _plan([Operand(operand_id="A", view_id=v, itm_id="T20", prd_de="2024", group_by_level="C9")],
                 [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s")
    r = eng.run(plan, [v])
    assert not r.success and r.error_code == CalcErrorCode.UNKNOWN_LEVEL and r.error_code in RETRYABLE_CODES
    assert "C9" in r.error_message


def test_diagnose_summarizes_rejections(tmp_path, capsys):
    (tmp_path / "reports").mkdir()
    (tmp_path / "rejected_samples").mkdir()
    (tmp_path / "reports" / "generation_report.json").write_text(json.dumps({
        "final_dataset_count": 0, "processed_samples": 3, "rates_over_processed_samples": {"plan_generation_success": 1.0},
        "api": {"calls": 18, "by_task": {"planner": {"calls": 15, "latency_ms": 30000, "failures": 0}}}}), encoding="utf-8")
    rows = [{"sample_id": f"S{i}", "reasoning_type": "CROSS_TABLE_RATIO", "subtype": "SHARE", "stage": "calculation",
             "codes": ["CARDINALITY_ERROR"], "reasons": [f"A{i}: 스칼라인데 {i + 2}행"], "planner_attempts": 3,
             "last_plan": {"operands": [{"operand_id": "A", "view_id": "v", "coordinates": {}}]}} for i in range(3)]
    (tmp_path / "rejected_samples" / "rejected_samples.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    assert diagnose_main(["--output-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "calculation / CARDINALITY_ERROR: 3건" in out and "3× AN: 스칼라인데 N행" in out and "operand A" in out


def _isolated(demo_env, blank):
    """공용 index·graph 를 건드리지 않게 복사본 (graph 는 간선을 캐시하므로 새로 만듦)"""
    import copy
    from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph
    idx = copy.copy(demo_env["index"])
    idx.views = dict(idx.views)
    for vid in blank(idx.views):
        idx.views[vid] = idx.views[vid].model_copy(update={"units": []})
    return idx, CompatibilityGraph(idx, demo_env["cfg"]["compatibility"])


def test_view_without_unit_is_rejected_not_crash(demo_env):
    """원본 UNIT_NM 이 빈 표 (실데이터 S000043 의 IndexError) → 계획 검증이 UNIT_UNKNOWN 으로 거절"""
    from synthetic_gold_pipeline.schemas.planning import OperationGraph, OperationPlan, ReasoningType
    from synthetic_gold_pipeline.tests.test_statistical_validation import cluster, scalar
    from synthetic_gold_pipeline.tools.statistical_validation_tool import StatisticalValidator
    cfg = demo_env["cfg"]
    e, p = (find_view(demo_env["index"], "101_DT_DEMO_ECON", "T1", "2024"),
            find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024"))
    idx, graph = _isolated(demo_env, lambda views: [p])
    sv = StatisticalValidator(idx, graph, {**cfg["statistics"], **cfg["compatibility"]})
    pl = OperationPlan(plan_id="p", reasoning_type=ReasoningType.CROSS_TABLE_RATIO,
                       operands=[scalar("A", e, "T1", "2024"), scalar("B", p, "T20", "2024")],
                       operation=OperationGraph(steps=[OperationStep(step_id="s", op="SHARE_RATIO", inputs=["A", "B"])],
                                                final_step_id="s"))
    rep = sv.validate_plan(pl, cluster([e, p]))
    assert not rep.passed and "UNIT_UNKNOWN" in {i.code for i in rep.errors}


def test_sampler_never_returns_unitless_views(demo_env):
    from synthetic_gold_pipeline.sampler.view_cluster_sampler import ViewClusterSampler
    from synthetic_gold_pipeline.schemas.planning import ReasoningType
    idx, graph = _isolated(demo_env, lambda views: [v for v in views if "DT_DEMO_POP::" in v])   # 한 표의 단위를 전부 비움
    s = ViewClusterSampler(idx, graph, demo_env["cfg"]["sampler"], base_seed=7)
    for i in range(40):
        for rt in (ReasoningType.CROSS_TABLE_RATIO, ReasoningType.TIME_SERIES_COMPARISON, ReasoningType.CONDITIONAL_AGGREGATION):
            cl = s.sample(rt, i)
            if cl:
                assert all(len(idx.view(v).units) == 1 for v in cl.view_ids)


# ── 계획 자동 보정 (실데이터 HCX 진단: 탈락 33% 가 '고정 안 된 분류') ──────────────────────
class _FrameIndex:
    """실제 View 메타 + 여러 View 를 합친 프레임 → 고정 안 된 분류가 남는 상황 재현"""

    def __init__(self, idx, vid, extra_vids):
        import pandas as pd
        self.idx, self.vid = idx, vid
        vids = [vid, *extra_vids]
        self.frame = pd.concat([idx.load_frame(v) for v in vids], ignore_index=True)
        base = idx.view(vid)
        codes = {lv: list({c.code: c for v in vids for c in idx.view(v).dimension_codes.get(lv, [])}.values())
                 for lv in base.dimension_codes}
        self.vm = base.model_copy(update={"dimension_codes": codes})     # 실제 View 처럼 자유 분류의 코드(총계 포함)를 가짐

    def view(self, v):
        return self.vm if v == self.vid else self.idx.view(v)

    def load_frame(self, v):
        return self.frame if v == self.vid else self.idx.load_frame(v)


def _hh(demo_env, sex):
    return next(v for v in demo_env["index"].views if "DT_DEMO_HH::T2::Y2020::" in v and f"C2={sex}::" in v)


def test_repair_fixes_free_level_to_total(demo_env):
    from synthetic_gold_pipeline.tools.plan_repair import repair_plan
    vid = _hh(demo_env, 2)
    fi = _FrameIndex(demo_env["index"], vid, [_hh(demo_env, 0), _hh(demo_env, 1)])
    pl = _plan([Operand(operand_id="A", view_id=vid, itm_id="T2", prd_de="2020", group_by_level="C1",
                        coordinates={"C1": "11"})],                                     # ② 그룹 레벨이 coordinates 에도
               [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s")
    new, notes = repair_plan(pl, fi)
    op = new.operands[0]
    assert op.coordinates == {"C2": "0"}                       # ① 고정 안 된 '가구주의 성별' → 총계 '0'
    assert any("총계" in n for n in notes) and any("coordinates 에서 뺌" in n for n in notes)


def test_repair_maps_wrong_codes(demo_env):
    from synthetic_gold_pipeline.tools.plan_repair import match_code
    cm = demo_env["index"].view(_hh(demo_env, 2)).code_map("C1")
    seoul = next(c for c, d in cm.items() if d.name.startswith("서울"))
    assert match_code("000", cm) == "00"                       # 0 채움 차이 (실데이터 S000003: C1=000)
    assert match_code("전국", cm) == "00" and match_code(cm[seoul].name, cm) == seoul
    assert match_code("없는코드", cm) is None


def test_repair_leaves_valid_plan_untouched(demo_env):
    from synthetic_gold_pipeline.tools.plan_repair import repair_plan
    v = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    pl = _plan([Operand(operand_id="A", view_id=v, itm_id="T20", prd_de="2024", coordinates={"C1": "11"})],
               [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s")
    new, notes = repair_plan(pl, demo_env["index"])
    assert notes == [] and new is pl


def test_condition_label_words():
    from synthetic_gold_pipeline.agents.reverse_qa_agent import dim_label, label_present
    assert dim_label("특성별") == "특성" and dim_label("가구주의 성별") == "가구주" and dim_label("기업규모별") == "기업규모"
    assert label_present("기업규모 대기업·중견기업", "대기업과중견기업의종사자수는?")
    assert label_present("가구주 남자", "남성가구주가구수") and not label_present("특성 미혼", "기혼여성의수")


def test_drop_unused_views(tmp_path):
    from synthetic_gold_pipeline.tests.test_pipeline import run_pipeline
    pipe, _ = run_pipeline(tmp_path / "o", 1)
    from synthetic_gold_pipeline.schemas.planning import HopType, ReasoningType, SampledCluster
    idx = pipe.index
    a, b = _hh_ids(idx)
    cl = SampledCluster(sample_id="S", attempt_index=0, random_seed=1, reasoning_type=ReasoningType.CONDITIONAL_AGGREGATION,
                        subtype="X", hop_type=HopType.SINGLE_TABLE_MULTI_VIEW, view_ids=[a, b], table_ids=[])
    pl = _plan([Operand(operand_id="A", view_id=a, itm_id="T2", prd_de="2020", group_by_level="C1")],
               [OperationStep(step_id="s", op="SUM", inputs=["A"])], "s")
    new = pipe._drop_unused_views(cl, pl)
    assert new.view_ids == [a] and new.hop_type == HopType.SINGLE_TABLE_SINGLE_VIEW
    cr = cl.model_copy(update={"reasoning_type": ReasoningType.CROSS_TABLE_RATIO})
    assert pipe._drop_unused_views(cr, pl) is None              # 표 사이 비율은 표 하나로 줄이지 않음


def _hh_ids(idx):
    vs = [v for v in idx.views if "DT_DEMO_HH::T2::Y2020::" in v]
    return vs[0], vs[1]


def test_table_balance_gives_each_table_equal_anchor_weight(demo_env):
    """View 가 많은 표가 더 자주 뽑히지 않게: 표별 View 가중치 합이 모두 같음"""
    from collections import defaultdict
    from synthetic_gold_pipeline.sampler.view_cluster_sampler import ViewClusterSampler
    idx = demo_env["index"]
    s = ViewClusterSampler(idx, demo_env["graph"], demo_env["cfg"]["sampler"])
    per = defaultdict(float)
    for v in idx.views.values():
        per[v.parent_table_id] += s._w(v)
    assert max(per.values()) - min(per.values()) < 1e-9 and len(per) > 3
    s2 = ViewClusterSampler(idx, demo_env["graph"], {**demo_env["cfg"]["sampler"], "table_balance": False})
    per2 = defaultdict(float)
    for v in idx.views.values():
        per2[v.parent_table_id] += s2._w(v)
    assert max(per2.values()) > 2 * min(per2.values())        # 균형을 끄면 View 수만큼 쏠림 (예전 동작)


def test_report_has_table_coverage(tmp_path):
    from synthetic_gold_pipeline.tests.test_pipeline import run_pipeline
    _, rep = run_pipeline(tmp_path / "o", 6)
    cov = rep["coverage"]
    assert cov["tables_total"] == 13 and 0 < cov["tables_in_dataset"] <= cov["tables_tried"] <= 13
    assert sum(x["tables"] for x in cov["by_survey"].values()) == 13


# ── 실데이터 2차 진단 반영 ───────────────────────────────────────────
def test_oversized_prompt_fails_fast_without_waiting():
    """읍면동 공통 코드 수천 개 → 요청 하나가 분당 토큰 한도 초과 → 429 를 기다리지 말고 그 샘플만 실패"""
    import asyncio

    from synthetic_gold_pipeline.agents.llm_client import BaseLLMClient, LLMResponseError

    class C(BaseLLMClient):
        async def _raw(self, *a):                                     # 호출되면 안 됨
            raise AssertionError("보내지 말아야 함")

    c = C({"rate_limit": {"tokens_per_minute": 60000}})
    with pytest.raises(LLMResponseError, match="프롬프트가 너무 큼"):
        asyncio.run(c._call("planner", "s", "가" * 200000, None, None))


def test_planner_caps_common_join_codes(demo_env):
    from synthetic_gold_pipeline.agents.llm_client import MockLLMClient
    from synthetic_gold_pipeline.agents.planner_agent import PlannerAgent
    from synthetic_gold_pipeline.schemas.planning import HopType, ReasoningType, SampledCluster
    v = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    cl = SampledCluster(sample_id="S", attempt_index=0, random_seed=1, reasoning_type=ReasoningType.CROSS_TABLE_RATIO,
                        subtype="SHARE", hop_type=HopType.MULTI_TABLE_MULTI_VIEW, view_ids=[v], table_ids=[],
                        join_levels={v: "C1"}, common_codes=[f"{i:05d}" for i in range(3766)])
    pa = PlannerAgent(MockLLMClient(), demo_env["index"], demo_env["graph"], {"max_codes_in_card": 40})
    ctx = pa.build_context(cl)
    assert len(ctx.common_join_codes) == 41 and "3766" in ctx.common_join_codes[-1]["name"]


def test_count_without_filter_is_rejected(demo_env):
    from synthetic_gold_pipeline.tools.statistical_validation_tool import StatisticalValidator
    from synthetic_gold_pipeline.tests.test_statistical_validation import cluster
    a, b = _hh_ids(demo_env["index"])
    pl = _plan([Operand(operand_id="A", view_id=a, itm_id="T2", prd_de="2020", group_by_level="C1", exclude_totals=True),
                Operand(operand_id="B", view_id=b, itm_id="T2", prd_de="2020", group_by_level="C1", exclude_totals=True)],
               [OperationStep(step_id="d", op="DIFFERENCE", inputs=["A", "B"]),
                OperationStep(step_id="c", op="COUNT", inputs=["d"])], "c")
    cfg = demo_env["cfg"]
    rep = StatisticalValidator(demo_env["index"], demo_env["graph"], {**cfg["statistics"], **cfg["compatibility"]}
                               ).validate_plan(pl, cluster([a, b]))
    assert "COUNT_WITHOUT_FILTER" in {i.code for i in rep.errors} and rep.retryable


def test_depths_aligned_across_joined_operands():
    """시군구(깊이1 261개) operand 와 읍면동(깊이2 3,766개) operand 를 각자 다수 깊이로 고르지 않고 공통 깊이로"""
    from types import SimpleNamespace as NS

    from synthetic_gold_pipeline.tools.plan_repair import _align_depths

    def vm(counts):
        codes = [NS(depth=d, is_total=False, has_children=False, name=f"c{d}{i}") for d, n in counts.items() for i in range(n)]
        return NS(dimension_definitions=[NS(level="C1")], dimension_codes={"C1": codes})
    idx = NS(view=lambda v: {"a": vm({1: 261, 0: 1}), "b": vm({2: 3766, 1: 9})}[v])
    ops = [Operand(operand_id="o1", view_id="a", itm_id="T", prd_de="2022", group_by_level="C1"),
           Operand(operand_id="o2", view_id="b", itm_id="T", prd_de="2022", group_by_level="C1")]
    notes = []
    out = _align_depths(ops, idx, notes)
    assert [o.depth for o in out] == [1, 1]


def test_unknown_label_views_are_skipped():
    from types import SimpleNamespace as NS

    from synthetic_gold_pipeline.sampler.view_cluster_sampler import has_unknown_label
    v = NS(indicator_definitions=[NS(itm_nm="미상")], source_coordinates=NS(dim_filters={}), code_map=lambda lv: {})
    w = NS(indicator_definitions=[NS(itm_nm="인구")], source_coordinates=NS(dim_filters={"C2": ["9"]}),
           code_map=lambda lv: {"9": NS(name="기타")})
    ok = NS(indicator_definitions=[NS(itm_nm="1인가구")], source_coordinates=NS(dim_filters={"C2": ["1"]}),
            code_map=lambda lv: {"1": NS(name="남자")})
    assert has_unknown_label(v) and has_unknown_label(w) and not has_unknown_label(ok)


def test_question_intent_for_class_diff_count(tmp_path):
    """실데이터 S000000: '남녀 차이는 몇 개' 로 잘못 쓴 질문 → 의도 문장이 '…보다 많은 곳의 개수' 를 명시"""
    from synthetic_gold_pipeline.tests.test_pipeline import run_pipeline
    pipe, _ = run_pipeline(tmp_path / "o", 12)
    import json as _j
    intents = []
    for p in (tmp_path / "o" / "intermediate_facts").glob("*.json"):
        d = _j.loads(p.read_text(encoding="utf-8"))
        if d["cluster"]["subtype"] == "CLASS_DIFF_COUNT":
            from synthetic_gold_pipeline.agents.reverse_qa_agent import build_fact_bundle
            from synthetic_gold_pipeline.schemas.calculation import CalculationResult
            from synthetic_gold_pipeline.schemas.planning import OperationPlan, SampledCluster
            b = build_fact_bundle(SampledCluster(**d["cluster"]), OperationPlan(**d["plan"]),
                                  CalculationResult(**d["calculation"]), pipe.index)
            intents.append(b["llm_input"]["question_intent"])
    for t in intents:
        assert "몇 곳" in t and "보다" in t


# ── 결과 검토 반영: 억지 조합·복잡도 · 규칙 계획기 ─────────────────────────
def test_average_and_ratio_items_are_not_additive():
    from types import SimpleNamespace as NS

    from synthetic_gold_pipeline.sampler.view_cluster_sampler import view_kind
    from synthetic_gold_pipeline.schemas.metadata import ValueKind
    from synthetic_gold_pipeline.tools.units import name_is_additive
    assert not name_is_additive("평균 가구원수") and not name_is_additive("고령인구비율") and not name_is_additive("경제활동참가율")
    assert name_is_additive("1인가구") and name_is_additive("총인구수") and name_is_additive("혼인건수")
    avg = NS(units=["명"], indicator_definitions=[NS(itm_nm="평균 가구원수")])
    cnt = NS(units=["명"], indicator_definitions=[NS(itm_nm="총인구수")])
    assert view_kind(avg) == ValueKind.MEAN and view_kind(cnt) == ValueKind.COUNT


def test_rate_per_denominator_must_be_population_base(demo_env):
    from types import SimpleNamespace as NS

    from synthetic_gold_pipeline.sampler.view_cluster_sampler import ViewClusterSampler
    s = ViewClusterSampler(demo_env["index"], demo_env["graph"], demo_env["cfg"]["sampler"])
    den = lambda nm: NS(units=["명"], indicator_definitions=[NS(itm_nm=nm)])  # noqa: E731
    assert s._denominator_ok(den("총인구수"), same_family=False)
    assert not s._denominator_ok(den("외국인 입국자"), same_family=False)    # 실데이터: 혼인건수 ÷ 외국인 입국자
    assert not s._denominator_ok(den("계"), same_family=False)


def test_time_series_needs_same_split(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    vs = {v: v for v in idx.views if "DT_DEMO_HH::T2::" in v}
    a = next(v for v in vs if "Y2015::C2=1::" in v)
    same = next(v for v in vs if "Y2020::C2=1::" in v)
    other = next(v for v in vs if "Y2020::C2=2::" in v)
    assert g.edge(a, same).allowed["TIME_SERIES"]
    assert not g.edge(a, other).allowed["TIME_SERIES"]                    # 남자 2015 vs 여자 2020 은 시계열 아님


def test_complex_views_are_skipped(demo_env):
    from types import SimpleNamespace as NS

    from synthetic_gold_pipeline.sampler.view_cluster_sampler import ViewClusterSampler
    s = ViewClusterSampler(demo_env["index"], demo_env["graph"], demo_env["cfg"]["sampler"])
    panel = NS(indicator_definitions=[NS(itm_nm="혼인·출산 변화 비율 t+3년")], dimension_definitions=[],
               source_coordinates=NS(dim_filters={}), code_map=lambda lv: {})
    assert s._too_complex(panel)
    v = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    assert not s._too_complex(demo_env["index"].view(v))


def test_paraphrase_length_limit(demo_env):
    from synthetic_gold_pipeline.agents.llm_client import MockLLMClient
    from synthetic_gold_pipeline.agents.reverse_qa_agent import ReverseQAGeneratorAgent
    from synthetic_gold_pipeline.agents.reverse_qa_agent import ReverseQAOutput
    qa = ReverseQAGeneratorAgent(MockLLMClient(), demo_env["index"], {"max_question_paraphrased_chars": 20})
    bundle = {"llm_input": {"operands": [], "scalar_facts": [], "thresholds": [], "entities": [], "k": None},
              "values": {"FINAL": "1"}}
    errs = qa.validate(ReverseQAOutput(question_original="짧은 질문?", question_paraphrased="가" * 40,
                                       answer_template="{FINAL}", limitations=[]), bundle)
    assert any("20자 이내" in e for e in errs)


def test_rule_planner_runs_without_llm(tmp_path, monkeypatch):
    """규칙 계획기로 전체 파이프라인: 계획 단계에 LLM 호출이 없어야 하고 데모 레코드가 채택돼야 함"""
    from synthetic_gold_pipeline.agents import planner_agent as P
    from synthetic_gold_pipeline.tests.test_pipeline import run_pipeline

    async def rule_only(self, cluster, previous_errors=None, attempt=0):
        return self.rule_plan(cluster, attempt), {"mode": "rule"}
    monkeypatch.setattr(P.PlannerAgent, "plan", rule_only)
    pipe, rep = run_pipeline(tmp_path / "o", 12)
    assert rep["final_dataset_count"] >= 10
    assert "planner" not in (rep["api"].get("by_task") or {})


def test_fill_removes_duplicated_units():
    """실데이터 '13.9%%', '306개개', '638.9건/천명 건/천명' — 표시값에 단위가 이미 있음"""
    from synthetic_gold_pipeline.agents.reverse_qa_agent import fill
    v = {"FINAL": "13.9%", "C": "306개", "R": "638.9건/천명", "V1": "58,678가구"}
    assert fill("증감률은 {FINAL}%입니다.", v) == "증감률은 13.9%입니다."
    assert fill("모두 {C}개입니다.", v) == "모두 306개입니다."
    assert fill("{R} 건/천명입니다.", v) == "638.9건/천명입니다."
    assert fill("{V1}가구주", v) == "58,678가구가구주"                      # 단위 뒤에 글자가 이어지면 건드리지 않음


def test_formula_answer_template_is_rejected(demo_env):
    from synthetic_gold_pipeline.agents.llm_client import MockLLMClient
    from synthetic_gold_pipeline.agents.reverse_qa_agent import ReverseQAGeneratorAgent, ReverseQAOutput
    qa = ReverseQAGeneratorAgent(MockLLMClient(), demo_env["index"])
    bundle = {"llm_input": {"operands": [], "scalar_facts": [], "thresholds": [], "entities": [], "k": None},
              "values": {"FINAL": "1명", "V1": "2명", "V2": "1명"}}
    bad = qa.validate(ReverseQAOutput(question_original="차이는?", question_paraphrased="차이는?",
                                      answer_template="{FINAL} = {V1} - {V2}", limitations=[]), bundle)
    ok = qa.validate(ReverseQAOutput(question_original="차이는?", question_paraphrased="차이는?",
                                     answer_template="두 값의 차이는 {FINAL}입니다.", limitations=[]), bundle)
    assert any("문장으로" in e for e in bad) and not any("문장으로" in e for e in ok)
