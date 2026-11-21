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
    "M3-in": Rule("차트 계산 입력(모듈 3)", retry=False, drop=(("charts",), ("role_links",))),
    # withheld 를 빼도 같은 사유가 chart_plan.warnings 에 남아 모듈 6 이 질문 전체의 주의사항으로 붙인다
    "M3-out": Rule("차트 계산(모듈 3)", retry=True, drop=(("chart_contents",), ("calc_results",),
                                                     ("chart_plan", "answer_steps"), ("chart_plan", "withheld"))),
    "M5-out": Rule("차트 그리기(모듈 5)", retry=False, drop=(("results",),), on_fail="skip_charts"),
    "M6-in": Rule("답변 작성 입력(모듈 6)", retry=False, on_fail="skip_answer"),
    "M6-out": Rule("답변 작성(모듈 6)", retry=True, on_fail="skip_answer"),
    "A9": Rule("최종 결과", retry=False, on_fail="warn"),
}
MAX_RETRY = 1

# 스키마 다음의 규칙 (qa_rules.py: 허용값 · 빈 값 · id 짝) 위반을 어떻게 볼지. "error" = 지금 대응 그대로 (재시도 → 빼기 → 중단)
# "warning" = 기록만 (진단용: 정상 결과에서 얼마나 걸리는지 볼 때)
RULE_SEVERITY = "error"

# 경고 구분: 이 종류는 '내용 경고' (사람이 결과를 확인해야 함), 나머지 경고는 '형식 경고' (스키마와 어긋나지만 결과는 그대로)
# QA 상태(qa.status)는 내용 경고 기준이다 — 형식 경고만 있으면 'ok'. 건수는 qa.counts 의 semantic · format
SEMANTIC_KINDS = {"note", "withheld", "plan_warning", "answer_fallback",
                  "condition_unused", "ratio_missing", "measure_mismatch", "too_many_marks",
                  "chart_answer_mismatch", "answer_caveat_conflict", "value_list"}

# 내용 검사 기준 (qa_semantic.py, qa 설계.md 17장)
MAX_BAR_MARKS = 100                     # 막대 차트의 막대(행) 수 상한
BAR_CHARTS = ("bar", "stacked_bar")
ANSWER_LIST_MIN = 5                     # 규칙 문장의 '외 N개' 가 이 이상이면 값 나열로 본다
COMPUTED_MEASURES = {"change", "growth_rate", "cagr", "index", "share", "diff", "ratio", "aggregate", "combine"}
RATIO_OPS = {"share", "ratio", "growth_rate", "cagr", "index"}   # 질문의 '비율 · 비중' 에 답할 수 있는 연산
NOT_THRESHOLD_UNITS = {"세", "살", "대", "년", "월", "일"}         # '65세 이상' 처럼 분류 · 기간을 뜻하는 단위는 숫자 조건이 아니다
NO_DATA_MESSAGE = "요청한 지표를 찾지 못했습니다."

# 스키마에 없는 키 중 이미 아는 것 → 경고 대신 info (경로의 목록 번호는 [] 로 쓴다). 처음 보는 키는 계속 경고
KNOWN_EXTRAS: dict[str, set[str]] = {
    "A0": {"viewset.units[].candidates[].years_have",        # 검색 PR #76: 그 표에 있는 요청 연도
           "viewset.units[].candidates[].years_missing",     # 그 표에 없는 요청 연도
           "viewset.units[].candidates[].stitch"},           # 여러 표를 이어 붙이는 계획
}
# 받는 모듈이 읽지 않는 영역 → 없는 키 · 빠진 필드를 기록하지 않는다 (타입 오류 같은 스키마 오류는 그대로 잡는다)
QUIET_PATHS: dict[str, set[str]] = {
    "M2-in": {"view_input.units[].candidates"},              # 모듈 2 는 입력을 받자마자 candidates 를 지운다
}

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


def no_indicator_message(names: list[str]) -> str:
    """사전에도 고른 표에도 없는 지표를 물었을 때 (A0 조기 종료)"""
    return f"요청한 지표({', '.join(names)})를 찾지 못해 답변을 만들지 못했습니다."


def chart_dropped_message(name: str | None = None) -> str:
    """QA 가 M2-out · M3-in 에서 사용자가 지정한 차트를 뺐을 때의 안내"""
    return f"요청한 차트({name})를 만들지 못했습니다." if name else "요청한 차트를 만들지 못했습니다."


def skip_message(point: str) -> str:
    rule = RULES[point]
    if rule.on_fail == "skip_charts":
        return f"{rule.stage} 단계에 문제가 있어 차트 없이 답변만 보여 드립니다."
    if rule.on_fail == "skip_answer":
        return f"{rule.stage} 단계에 문제가 있어 답변 문장 없이 차트만 보여 드립니다."
    return ""
