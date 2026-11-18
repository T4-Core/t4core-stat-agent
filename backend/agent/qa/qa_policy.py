"""대응 규칙 (qa 설계.md 7장) — 지점마다 단계 이름 · 재시도 여부 · 뺄 수 있는 목록 · 끝내 실패했을 때

  순서: 보정(B안, qa_check) → 재시도(LLM 모듈만, 1회) → 그 항목만 빼기 → 끝내 실패
  끝내 실패 (on_fail)
    stop          전체 중단 — 멈춘 단계를 사용자에게 보여 준다
    skip_charts   차트 없이 답변만 (모듈 5)
    skip_answer   답변 없이 차트만 (모듈 6)
    warn          경고만, 결과는 그대로 돌려준다 (최종 결과)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    stage: str                      # 사용자에게 보여 줄 단계 이름
    retry: bool                     # LLM 을 쓰는 모듈이면 True (1회)
    drop: tuple = ()                # 뺄 수 있는 목록의 경로
    on_fail: str = "stop"


RULES: dict[str, Rule] = {
    "A0": Rule("에이전트 입력", retry=False),
    "M2-in": Rule("차트 유형 판단 입력(모듈 2)", retry=False),
    "M2-out": Rule("차트 유형 판단(모듈 2)", retry=True,
                   drop=(("chart_plan", "charts"), ("chart_plan", "overlays"), ("filtered_views",), ("errors",))),
    "M3-in": Rule("차트 계산 입력(모듈 3)", retry=False, drop=(("charts",),)),
    "M3-out": Rule("차트 계산(모듈 3)", retry=True, drop=(("chart_contents",), ("calc_results",))),
    "M5-out": Rule("차트 그리기(모듈 5)", retry=False, drop=(("results",),), on_fail="skip_charts"),
    "M6-in": Rule("답변 작성 입력(모듈 6)", retry=False, on_fail="skip_answer"),
    "M6-out": Rule("답변 작성(모듈 6)", retry=True, on_fail="skip_answer"),
    "A9": Rule("최종 결과", retry=False, on_fail="warn"),
}
MAX_RETRY = 1

# [형식 밖 예외] 모듈 메모에 이 문구가 있으면 그 모듈을 1번 다시 돌린다 (형식은 맞지만 HCX 편차로 계산을 못 한 경우)
#   M3-out: Module3Output.chart_plan.notes · calc_results[].note 에서 찾는다
#     '열 없음'       HCX 가 표에 없는 열을 조건으로 골라 계산을 포기함 (예: '…-1: 열 없음: 연령')
#     'HCX 호출 실패' 모듈 3 이 HCX 오류를 삼키고 빈 계획을 돌려줌
#   재시도 횟수는 형식 오류 재시도와 합쳐 MAX_RETRY 번. 두 결과 중 메모가 적은 쪽을 쓴다 (같으면 처음 결과)
RETRY_NOTES: dict[str, tuple[str, ...]] = {
    "M3-out": ("열 없음", "HCX 호출 실패"),
}


def stop_message(point: str) -> str:
    return f"{RULES[point].stage} 단계에서 결과 형식이 올바르지 않아 답변을 만들지 못했습니다."


def skip_message(point: str) -> str:
    rule = RULES[point]
    if rule.on_fail == "skip_charts":
        return f"{rule.stage} 단계에 문제가 있어 차트 없이 답변만 보여 드립니다."
    if rule.on_fail == "skip_answer":
        return f"{rule.stage} 단계에 문제가 있어 답변 문장 없이 차트만 보여 드립니다."
    return ""
