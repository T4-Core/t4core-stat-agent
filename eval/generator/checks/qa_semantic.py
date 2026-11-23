"""QA 내용 경고 ↔ 수동 판정 태그 대조, Unanswerable Detection

내용 경고는 출력을 바꾸지 않는 detector 다. 정답 라벨은 판정 시트의 태그(review.csv 의 tags 열)에서 온다.
"""
from backend.agent.qa.qa_policy import SEMANTIC_KINDS
from eval.generator import trace

# 내용 경고 → 판정 시트 태그 (정답 라벨). withheld · plan_warning · answer_fallback · note 는 출력 필드를 옮긴 것이라 빈도만 본다
DETECTOR_TAG = {"condition_unused": "condition_not_applied", "ratio_missing": "ratio_not_answered",
                "measure_mismatch": "measure_ignored", "answer_caveat_conflict": "held_value_asserted",
                "chart_answer_mismatch": "chart_without_answer", "too_many_marks": "unreadable_chart",
                "value_list": "long_list"}
FREQ_ONLY = {"withheld", "plan_warning", "answer_fallback", "note"}


def warnings_of(run: dict) -> set[str]:
    return {i.get("kind") for i in trace.qa(run).get("issues") or [] if i.get("severity") == "warning"
            and i.get("kind") in SEMANTIC_KINDS}


def a0_observed(run: dict) -> str:
    qa = trace.qa(run)
    if not qa:
        return "n/a"
    if qa.get("stopped_at") != "A0":
        return "continue"
    kinds = {i.get("kind") for i in qa.get("issues") or []}
    if "indicator_not_found" in kinds:
        return "stop_indicator_not_found"
    if "no_data" in kinds:
        return "stop_no_data"
    return "stop_status"


def detector_rows(run: dict, tags: set[str], stage1_failed: bool) -> list[dict]:
    """종류별 (경고 여부, 정답 라벨 여부) 한 줄. report.py 가 P/R 로 집계한다"""
    warned = warnings_of(run)
    rows = []
    for kind, tag in DETECTOR_TAG.items():
        rows.append({"kind": kind, "warned": kind in warned, "label": tag in tags,
                     "known_but_shipped": kind in warned and stage1_failed})
    for kind in FREQ_ONLY:
        rows.append({"kind": kind, "warned": kind in warned, "label": None, "known_but_shipped": False})
    return rows
