"""T-1 · T-26: 차트 지정 요청(request)이 모듈 2 출력 → 어댑터 → ChartRequest → 응답까지 보존된다

1판 검토에서 새 필드가 ChartOut 검증과 M2→M3 어댑터에서 사라지는 것이 재현됐다. 그 경로를 단위 테스트로 고정한다.
"""
from backend.agent.chart_calculate.from_module2 import to_chart_request
from backend.agent.chart_decision.chart_decision_module.chart_type_nodes import CHART_KEYS
from backend.agent.chart_decision.chart_decision_module.chart_type_schema import validate_plan
from backend.schemas.chart import ChartRequest, Module3Output

REQ = {"preferred": [{"text": "히스토그램", "code": None, "supported": False}], "excluded": [], "scope": "all",
       "stage": {"reason": "unsupported_type", "selected": "bar", "applied": True}}


def _chart(**kw):
    c = {"chart_id": "c1", "sub_question_ids": ["q-1"], "view_ids": ["v1"], "chart_type": "bar", "requirements": [],
         "fallback_charts": [], "measure": "raw", "reason": "설명 문장", "warnings": ["요청한 히스토그램…"], "request": REQ}
    c.update(kw)
    return c


def test_chart_keys_include_request():
    assert "request" in CHART_KEYS


def test_chart_out_keeps_request():
    plan, errors = validate_plan({"query_id": "q", "charts": [_chart()], "overlays": []})
    assert not errors
    assert plan["charts"][0]["request"] == REQ


def test_chart_out_without_request_is_none():
    c = _chart()
    del c["request"]
    plan, errors = validate_plan({"query_id": "q", "charts": [c], "overlays": []})
    assert not errors and plan["charts"][0]["request"] is None


def test_adapter_keeps_request_and_stage():
    plan, _ = validate_plan({"query_id": "q", "charts": [_chart()], "overlays": []})
    r = to_chart_request(plan["charts"][0])
    assert r.request is not None
    assert r.request.stage.reason == "unsupported_type" and r.request.stage.selected == "bar"
    assert r.request.preferred[0].text == "히스토그램" and r.request.preferred[0].supported is False
    assert r.model_dump(mode="json")["request"]["stage"]["reason"] == "unsupported_type"     # 응답(charts)에 실리는 모양


def test_stage_reason_survives_reason_overwrite():
    """reason(설명 문장)은 reason_node 가 덮어쓴다. 구조화된 사유는 request.stage 에 따로 있으므로 영향이 없다"""
    plan, _ = validate_plan({"query_id": "q", "charts": [_chart(reason="전혀 다른 문장")], "overlays": []})
    assert to_chart_request(plan["charts"][0]).request.stage.reason == "unsupported_type"


def test_adapter_moves_m2_warnings_only_to_diagnostic_field():
    plan, _ = validate_plan({"query_id": "q", "charts": [_chart()], "overlays": []})
    r = to_chart_request(plan["charts"][0])
    assert r.m2_warnings == ["요청한 히스토그램…"]


def test_adapter_without_request():
    c = _chart()
    del c["request"]
    plan, _ = validate_plan({"query_id": "q", "charts": [c], "overlays": []})
    assert to_chart_request(plan["charts"][0]).request is None


def test_module3_output_has_no_request_field():
    """요청은 M2 출력과 응답의 charts 에 보존한다. M3 출력은 바꾸지 않는다 (validation 만 읽는다)"""
    assert "request" not in Module3Output.model_fields
    assert "request" in ChartRequest.model_fields


def test_old_style_chart_dict_still_valid():
    """request 키가 없던 이전 모양의 차트 dict 도 어댑터가 받는다 (회귀)"""
    c = {"chart_id": "c1", "sub_question_ids": ["q-1"], "chart_type": "bar", "measure": "raw", "requirements": [], "view_ids": ["v"]}
    assert to_chart_request(c).request is None
