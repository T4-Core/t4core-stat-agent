"""T-9 · T-10 · T-16 ~ T-18 · T-21 · T-22: 차트 지정 요청의 최종 결과와 안내 (agent/chart_notice.py)

원칙: 안내는 최종 상태(모듈 3 최종 유형 + 모듈 5 렌더링 결과) 기준이다.
호출자가 의도한 생략(draw=False)과 QA 중단은 안내하지 않고, 요청을 충족하지 못해 내용이 없는 경우는 사유를 안내한다.
"""
import pytest

from backend.agent.chart_notice import finalize_chart_request
from backend.schemas.chart import OUTCOME_REASONS, ChartContent, ChartRequest, Module3Output, ChartPlan


def req(preferred=(), excluded=(), reason=None, selected=None, applied=True):
    def n(x):
        return {"text": x[0], "code": x[1], "supported": x[1] is not None}
    return {"preferred": [n(x) for x in preferred], "excluded": [n(x) for x in excluded], "scope": "all",
            "stage": {"reason": reason, "selected": selected, "applied": applied}}


def chart(cid="c1", request=None, chart_type="bar"):
    return ChartRequest(chart_id=cid, sub_question_ids=["q-1"], chart_type=chart_type, request=request)


def m3(*contents):
    cc = [ChartContent(chart_id=cid, chart_type=t, measure="raw", title=title or cid, encoding={}, columns=[], rows=[])
          for cid, t, title in contents]
    return Module3Output(chart_plan=ChartPlan(), chart_contents=cc)


def drawn(*items):
    return [{"chart_id": cid, "status": status, "reason": None, "merged_from": []} for cid, status in items]


def run(charts, mod3, dr, **kw):
    out = finalize_chart_request(charts, mod3, dr, **kw)
    for o in out["request_outcomes"]:
        assert o["reason"] in OUTCOME_REASONS[o["outcome"]], o
    return out


def only(out):
    assert len(out["request_outcomes"]) == 1
    return out["request_outcomes"][0]


# ── 요청대로 / 대체 ───────────────────────────────────────────────────────────
def test_honored_has_no_notice():
    c = chart(request=req([("막대", "bar")], selected="bar"))
    out = run([c], m3(("c1", "bar", None)), drawn(("c1", "drawn")))
    assert only(out)["outcome"] == "honored" and only(out)["reason"] is None and out["chart_notices"] == []


def test_unsupported_name_substituted_with_notice_in_final_terms():
    c = chart(request=req([("히스토그램", None)], reason="unsupported_type", selected="bar"))
    out = run([c], m3(("c1", "bar", None)), drawn(("c1", "drawn")))
    o = only(out)
    assert (o["outcome"], o["reason"], o["final_chart"]) == ("substituted", "unsupported_type", "bar")
    assert out["chart_notices"] == ["히스토그램은 지원하지 않는 차트라 막대 그래프로 보여 드립니다."]


def test_m3_revalidation_changes_chart_notice_follows_final_type():
    """T-9: 모듈 2 는 원그래프를 수락했지만 모듈 3 재검증에서 막대로 바뀌었다 → 안내는 최종(막대) 기준"""
    c = chart(request=req([("원그래프", "pie")], selected="pie"), chart_type="pie")
    out = run([c], m3(("c1", "bar", None)), drawn(("c1", "drawn")))
    o = only(out)
    assert (o["outcome"], o["reason"], o["final_chart"]) == ("substituted", "validation_fallback", "bar")
    assert "막대 그래프" in out["chart_notices"][0] and "원그래프로" not in out["chart_notices"][0].split("검증")[-1]


def test_only_exclusion_respected_is_honored_without_notice():
    c = chart(request=req(excluded=[("막대", "bar")], selected="line"), chart_type="line")
    out = run([c], m3(("c1", "line", None)), drawn(("c1", "drawn")))
    assert only(out)["outcome"] == "honored" and out["chart_notices"] == []


def test_ambiguous_scope_notice():
    c = chart(request=req(reason="ambiguous_scope", applied=False, selected="bar"))
    out = run([c], m3(("c1", "bar", None)), drawn(("c1", "drawn")))
    assert only(out)["outcome"] == "substituted" and only(out)["reason"] == "ambiguous_scope"
    assert "어느 질문에 적용할지" in out["chart_notices"][0]


# ── 차트 내용이 없는 경우: 요청을 충족하지 못한 것이므로 사유를 안내한다 (T-17a) ───────────────
@pytest.mark.parametrize("reason, text", [
    ("data_mismatch", "그릴 수 없어 차트 없이 표로"),
    ("view_blocked", "맞는 자료 구성이 아니라"),
    ("unsupported_type", "지원하지 않는 차트라 차트 없이 표로"),
    ("no_candidate", "만족하는 차트가 없어"),
])
def test_no_chart_content_with_request_gives_reason(reason, text):
    c = chart(request=req([("인구 피라미드", "pyramid")], reason=reason), chart_type=None)
    out = run([c], m3(), [], draw=True)
    o = only(out)
    assert (o["outcome"], o["reason"]) == ("table_only", reason)
    assert any(text in s for s in out["chart_notices"])
    assert out["render_status"]["c1"] == {"state": "skipped", "reason": "no_chart_content", "error": None}


def test_no_chart_content_without_stage_reason_means_validation_failed():
    c = chart(request=req([("원그래프", "pie")], selected="pie"), chart_type="pie")
    out = run([c], m3(), [])
    assert (only(out)["outcome"], only(out)["reason"]) == ("table_only", "validation_failed")
    assert "계산이 보류되었거나" in out["chart_notices"][0]


def test_no_chart_content_without_request_has_no_outcome_or_notice():
    """T-17b"""
    out = run([chart(request=None, chart_type=None)], m3(), [])
    assert out["request_outcomes"] == [] and out["chart_notices"] == []


# ── 렌더링 상태: 생략과 실패를 구분한다 ──────────────────────────────────────────
def test_draw_disabled_is_not_a_failure_and_has_no_notice():
    """T-16"""
    c = chart(request=req([("막대", "bar")], selected="bar"))
    out = run([c], m3(("c1", "bar", None)), [], draw=False)
    assert out["render_status"]["c1"] == {"state": "skipped", "reason": "draw_disabled", "error": None}
    assert (only(out)["outcome"], only(out)["reason"]) == ("not_rendered", "draw_disabled")
    assert out["chart_notices"] == []


def test_qa_stopped_has_no_chart_notice():
    """T-17c: QA 중단 메시지가 이미 나간다"""
    c = chart(request=req([("막대", "bar")], selected="bar"))
    out = run([c], None, [], stopped=True)
    assert out["render_status"]["c1"]["reason"] == "qa_stopped"
    assert (only(out)["outcome"], only(out)["reason"]) == ("not_rendered", "qa_stopped") and out["chart_notices"] == []


def test_renderer_exception_marks_failed_and_notice_has_no_success_phrase():
    """T-10"""
    c = chart(request=req([("막대", "bar")], selected="bar"))
    out = run([c], m3(("c1", "bar", None)), [], error="ValueError: x")
    assert out["render_status"]["c1"]["state"] == "failed" and out["render_status"]["c1"]["reason"] == "exception"
    assert only(out)["outcome"] == "render_failed"
    assert "보여 드립니다" not in out["chart_notices"][0] and "표시하지 못했습니다" in out["chart_notices"][0]


def test_qa_rejected_output_is_a_render_failure():
    """T-18"""
    c = chart(request=req([("막대", "bar")], selected="bar"))
    out = run([c], m3(("c1", "bar", None)), [], rejected=True)
    assert out["render_status"]["c1"]["reason"] == "render_error" and only(out)["outcome"] == "render_failed"


# ── 부분 실패: 실패한 차트에만 안내한다 ──────────────────────────────────────────
def _two(c1_status, c2_status):
    charts = [chart("c1", req([("막대", "bar")], selected="bar")), chart("c2", req([("막대", "bar")], selected="bar"))]
    return run(charts, m3(("c1", "bar", "혼인건수"), ("c2", "bar", "출생아수")), drawn(("c1", c1_status), ("c2", c2_status)))


def test_partial_failure_c2_only():
    """T-21"""
    out = _two("drawn", "failed")
    st = {o["chart_id"]: o["outcome"] for o in out["request_outcomes"]}
    assert st == {"c1": "honored", "c2": "render_failed"}
    assert len(out["chart_notices"]) == 1 and out["chart_notices"][0].startswith("[출생아수]")


def test_partial_failure_c1_only():
    """T-22: 반대 방향"""
    out = _two("failed", "drawn")
    st = {o["chart_id"]: o["outcome"] for o in out["request_outcomes"]}
    assert st == {"c1": "render_failed", "c2": "honored"}
    assert len(out["chart_notices"]) == 1 and out["chart_notices"][0].startswith("[혼인건수]")


def test_merged_overlay_result_counts_for_both_charts():
    charts = [chart("c1", req([("막대", "bar")], selected="bar")), chart("c2", req([("막대", "bar")], selected="bar"))]
    dr = [{"chart_id": "c1+c2", "status": "drawn", "reason": None, "merged_from": ["c1", "c2"]}]
    out = run(charts, m3(("c1", "bar", None), ("c2", "bar", None)), dr)
    assert {o["outcome"] for o in out["request_outcomes"]} == {"honored"}
