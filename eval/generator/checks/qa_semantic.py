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


# ── [NEW] v2: A0 에서 멈춘 문항의 사용자 안내 정합 ─────────────────
# 멈춘 것 자체(Unanswerable Detection)와 별개로, 안내가 멈춘 이유에 맞는 종류인지 본다. 숫자 정확성이 아니라 안내 종류의 정합이다
GUIDANCE = {
    "empty_view": ("찾지 못", "없어", "없습니다"),
    "unknown_viewset_status": ("형식", "상태", "확인할 수 없"),
    "unresolved_conflict": ("충돌", "선택", "어느", "어떤 자료"),
    "missing_conversation_context": ("알려 주", "알려주", "어떤", "어느", "다시 말"),
    "out_of_scope": ("범위", "통계 수치를 묻는", "통계 자료", "다룹니다"),
}


def a0_guidance(q, run: dict):
    """v2 문항만. 기대 사유(하위 질문 hold_reason, 범위 밖 문항은 out_of_scope)의 안내 어휘가 답변에 있는가"""
    from eval.generator.findings import Finding
    if q.dataset != "v2":
        return []
    reason = "out_of_scope" if q.scope == "out" else next((s.answerable_when[0].hold_reason for s in q.sub_questions
                                                           if s.answerable_when and s.answerable_when[0].hold_reason), None)
    words = GUIDANCE.get(reason or "")
    if not words:
        return []
    text = " ".join([trace.answer_text(run)] + trace.user_caveats(run))
    ok = any(w in text for w in words)
    return [Finding("a0_guidance", "stage2", "QA", ok, f"기대 사유 {reason}: {'안내 일치' if ok else '안내 종류가 다름'}",
                    detail={"reason": reason, "words": list(words)})]
