"""모듈 2 → 모듈 3 임시 어댑터 시험 — HCX 없이 돈다

module2_sample/ 은 모듈 2(decide_charts, LLM 없이)를 실제로 돌려 얻은 chart_plan 과 그 입력 View 다.
query_bundle 은 baseline/request.json 의 것을 쓴다 (모듈 2 예시의 옛 형식 번들은 v3 스키마에 맞지 않는다).
"""
import copy
import json
from pathlib import Path

import pytest

from backend.agent.chart_calculate.from_module2 import to_chart_request, to_module3_request, unknown_view_ids
from backend.agent.chart_calculate.pipeline import run_module3
from backend.agent.chart_calculate.planner import Decision, fixed_conditions
from backend.schemas.chart import ChartRequest, Module3Request

HERE = Path(__file__).parent


def _load(rel):
    return json.loads((HERE / rel).read_text(encoding="utf-8"))


def _dump(model):
    return json.loads(json.dumps(model.model_dump(mode="json", by_alias=True), ensure_ascii=False))


@pytest.fixture()
def plan():
    return _load("module2_sample/chart_plan.json")


@pytest.fixture()
def views():
    return _load("module2_sample/view_input.json")


@pytest.fixture()
def bundle():
    return _load("baseline/request.json")["query_bundle"]


def test_real_module2_output_gives_baseline_result(plan, views, bundle):
    """모듈 2 의 실제 출력 → 어댑터 → 모듈 3 이, 0단계 기준값과 같은 결과를 낸다"""
    req = to_module3_request(plan, views, bundle)
    decision = Decision.model_validate(_load("baseline/decision.json"))
    assert _dump(run_module3(req, decision)) == _load("baseline/output.json")


def test_charts_are_converted(plan, views, bundle):
    req = to_module3_request(plan, views, bundle)
    base = Module3Request.model_validate(_load("baseline/request.json"))
    assert [r.id for r in req.records] == [r.id for r in base.records]
    c1 = req.charts[0]
    assert (c1.chart_id, c1.chart_type, c1.measure) == ("c1", "line", "raw")
    assert c1.sub_question_ids == ["27077dec-1"]
    assert c1.requirements == ["time_axis_required", "min_points_3"]
    assert c1.fallback_chart == "bar"          # fallback_charts[0]. 안 바꾸면 조용히 사라진다


def test_extra_fallbacks_are_recorded_not_lost_silently():
    c = to_chart_request({"chart_id": "c1", "chart_type": "pie", "measure": "share",
                          "fallback_charts": ["bar", "donut"], "reason": "구성비"})
    assert c.fallback_chart == "bar"
    assert "donut" in c.reason


def test_measure_none_becomes_raw_and_says_so():
    c = to_chart_request({"chart_id": "c1", "chart_type": "bar", "measure": None, "reason": "비교"})
    assert (c.chart_type, c.measure) == ("bar", "raw")
    assert "measure" in c.reason and "비교" in c.reason


def test_out_of_scope_means_no_chart():
    c = to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "범위 밖", "requirements": ["x"]})
    assert (c.chart_type, c.measure) == (None, "raw")
    assert "범위 밖" in c.reason


def test_unknown_measure_still_fails_loudly():
    """모르는 값은 숨기지 않는다 (임시 처리 대상은 None · '범위 밖' 뿐)"""
    with pytest.raises(ValueError):
        to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "없는값"})


def test_inputs_are_not_modified(plan, views, bundle):
    before = copy.deepcopy((plan, views, bundle))
    to_module3_request(plan, views, bundle)
    assert (plan, views, bundle) == before


def test_best_rank_view_is_used(plan, views, bundle):
    unit = views["units"][1]
    worse = copy.deepcopy(unit["views"][0])
    worse["rank"] = 2
    worse["record"]["id"] = "view::다른표::Y::27077dec-1-2::trend"
    unit["views"].insert(0, worse)                    # rank 2 가 앞에 와도 rank 1 을 고른다
    ids = [r.id for r in to_module3_request(plan, views, bundle).records]
    assert "view::다른표::Y::27077dec-1-2::trend" not in ids


# ── sub_question_ids 'main' → '{query_id}-1' ─────────────────────────────
def test_main_becomes_first_sub_question_id_and_says_so():
    c = to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "raw", "reason": "추이",
                          "sub_question_ids": ["main"]}, main_id="27077dec-1")
    assert c.sub_question_ids == ["27077dec-1"]
    assert "main" in c.reason and "27077dec-1" in c.reason and "추이" in c.reason


def test_main_is_left_alone_without_main_id():
    c = to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "raw", "sub_question_ids": ["main"]})
    assert c.sub_question_ids == ["main"]


def test_other_ids_are_not_touched():
    c = to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "raw", "sub_question_ids": ["27077dec-2"]},
                         main_id="27077dec-1")
    assert c.sub_question_ids == ["27077dec-2"] and c.reason is None


def test_main_is_mapped_only_when_bundle_has_no_sub_questions(plan, views, bundle):
    one = copy.deepcopy(plan)
    one["charts"] = one["charts"][:1]
    one["charts"][0]["sub_question_ids"] = ["main"]

    no_subs = copy.deepcopy(bundle)
    no_subs["sub_questions"], no_subs["sub_filters"] = [], []
    assert to_module3_request(one, views, no_subs).charts[0].sub_question_ids == [f"{bundle['query_id']}-1"]
    assert to_module3_request(one, views, bundle).charts[0].sub_question_ids == ["main"]     # 하위 질문이 있으면 그대로


def test_mapped_id_is_one_module3_can_find_its_fixed_conditions_for(plan, views, bundle):
    """이 변환의 목적: 변환한 ID 로 모듈 3 이 시점·지역 같은 고정 조건을 찾는다 ('main' 으로는 못 찾는다)"""
    one = copy.deepcopy(plan)
    one["charts"] = one["charts"][:1]
    one["charts"][0]["sub_question_ids"] = ["main"]
    no_subs = copy.deepcopy(bundle)
    no_subs["sub_questions"], no_subs["sub_filters"] = [], []

    req = to_module3_request(one, views, no_subs)
    fixed = fixed_conditions(req.query_bundle)
    assert req.charts[0].sub_question_ids[0] in fixed
    assert "main" not in fixed


# ── view_ids: 세트 = 질문 · 차트 유형 · View ─────────────────────────────
def test_view_ids_are_copied_as_the_set(plan, views, bundle):
    req = to_module3_request(plan, views, bundle)
    assert [c.view_ids for c in req.charts] == [["view::101_DT_1B8000G::Y::27077dec-1-1::trend"],
                                                ["view::101_DT_1B8000G::Y::27077dec-2-1::trend"]]
    assert {v for c in req.charts for v in c.view_ids} <= {r.id for r in req.records}     # 세트의 View 는 records 에 있다


def test_view_ids_keep_every_id_in_order_for_combo():
    """combo 는 View 가 여러 개일 수 있다 (개수 제한 없음). 순서는 모듈 2 그대로"""
    c = to_chart_request({"chart_id": "c1", "chart_type": "combo", "measure": "raw", "view_ids": ["v::A", "v::B", "v::C"]})
    assert c.view_ids == ["v::A", "v::B", "v::C"]


def test_view_ids_survive_a_question_without_a_chart():
    """차트 없음(chart_type null)인 하위 질문도 질문용 계산이 쓸 View 를 담는다"""
    c = to_chart_request({"chart_id": "c3", "chart_type": None, "measure": "raw", "view_ids": ["v::C"]})
    assert c.chart_type is None and c.view_ids == ["v::C"]


def test_missing_view_ids_default_to_empty_so_old_inputs_keep_working():
    assert ChartRequest(chart_id="c1").view_ids == []
    assert to_chart_request({"chart_id": "c1", "chart_type": "line", "measure": "raw"}).view_ids == []


def test_unknown_view_ids_are_reported_before_hcx_is_called(plan, views, bundle):
    req = to_module3_request(plan, views, bundle)
    assert unknown_view_ids(req.charts, req.records) == []
    broken = [req.charts[0].model_copy(update={"view_ids": [*req.charts[0].view_ids, "view::없음"]}), req.charts[1]]
    assert unknown_view_ids(broken, req.records) == [
        {"chart_id": "c1", "reason": "view_ids 의 View 가 records 에 없음: ['view::없음']"}]
