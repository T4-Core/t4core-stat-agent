"""
[NEW] 모듈 6 API — 답변 · 통계 표 생성

  POST /api/v1/answer/compose        질문 + View + 모듈 3 계산 결과 → 답변 문장 · 근거 표 · 주의사항
  POST /api/v1/answer/compose/trace  같은 입력 → 시도별 중간 결과 (HCX 에 보낸 메시지 · 초안 · 검사 문제) — 테스트 화면용

로직은 backend/agent/answer_compose 에 있고, 여기는 HTTP ↔ 함수 연결만 한다.
입력은 /api/v1/chart/calc 응답(calc_results · displays · chart_plan.answer_steps)과 같은 호출의 records · query_bundle 을 이어 붙인 것이다.
"""
from fastapi import APIRouter
from pydantic import ConfigDict

from backend.agent.answer_compose.pipeline import Module6Trace, run_module6, run_module6_trace
from backend.api.deps import guard
from backend.schemas.answer import Module6Output, Module6Request

TAG = "③-2 답변·표 생성 (모듈 6)"      # main.py TAGS 의 이름과 같아야 한다
router = APIRouter(prefix="/api/v1/answer", tags=[TAG])

_VIEW = "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
_YEARS = ["2021", "2022", "2023", "2024", "2025"]
_VALUES = [192507, 191690, 193657, 222412, 240326]
# 모듈 3 의 명세 시나리오 결과 (혼인건수 2021 → 2025 증감률). HCX 를 부르는 예시다
EX_COMPOSE = {
    "query_bundle": {"query_id": "27077dec", "original": "최근 5년 혼인건수 얼마나 변했어?",
                     "sub_questions": ["2021~2025년 전국 혼인건수 추이"]},
    "records": [{
        "id": _VIEW, "lexical_text": "인구동태건수 및 동태율 추이", "parent_id": "table::101_DT_1B8000G",
        "table": {"columns": ["시점", "행정구역별", "항목", "값"],
                  "rows": [[y, "전국", "혼인건수(건)", v] for y, v in zip(_YEARS, _VALUES)]},
        "metadata": {"prd_se": "Y", "view_type": "trend", "unit": "건"}}],
    "calc_results": [{
        "step_id": "a1", "op": "growth_rate", "value": 24.84013568337775, "unit": "%", "display_ref": "d1",
        "inputs": [{"role": "value", "record_id": _VIEW, "item": "혼인건수(건)", "key": {"시점": y}, "value": v, "unit": "건"}
                   for y, v in ((_YEARS[0], _VALUES[0]), (_YEARS[-1], _VALUES[-1]))],
        "record_ids": [_VIEW]}],
    "displays": {"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1}},
    "answer_steps": [],
}


class ComposeRequest(Module6Request):
    """Module6Request 와 같다. Swagger 예시를 붙이려고 이 API 에서만 한 번 감쌌다"""
    model_config = ConfigDict(json_schema_extra={"examples": [EX_COMPOSE]})


@router.post("/compose", response_model=Module6Output, summary="계산 결과 → 답변 문장 + 근거 표")
def answer_compose(body: ComposeRequest):
    """`calc_results` · `displays` · `answer_steps` 는 `/api/v1/chart/calc` 응답에서
    (`answer_steps` 는 `chart_plan.answer_steps`), `records` · `query_bundle` 은 그 호출에 넣었던 것을 그대로 붙인다.

    - `answer` 의 숫자는 HCX 가 쓴 것이 아니라 `calc_results` 값에서 채운 것이다 (`used_step_ids` = 인용한 계산).
    - `method`: `hcx`(첫 시도 통과) · `hcx_retry`(재시도 후 통과) · `template`(규칙 문장) · `none`(계산 결과 없음)
    - `tables`: 계산 요약 → 계산 목록 → 원본 View. `rows` 는 표시 문자열, `raw_rows` 는 원래 값. View 표의 `highlight_rows` 가 계산에 쓴 행이다.
    - `caveats`: View 가 못 맞춘 조건 · 계산하지 못한 이유. `notes` 에는 HCX 실패·재시도 사유가 남는다."""
    with guard("answer: "):
        return run_module6(body)


@router.post("/compose/trace", response_model=Module6Trace, summary="/compose 와 같은 입력 → 시도별 중간 결과 (테스트 화면용)")
def answer_compose_trace(body: ComposeRequest):
    """`output` 은 `/compose` 응답과 같다. `attempts` 에 시도마다 HCX 에 보낸 메시지 · 원 응답 · 초안 · 채운 문장 · 걸린 문제가 있다."""
    with guard("answer: "):
        return run_module6_trace(body)
