"""
[NEW] 모듈 3 API — 질문 계산 + 차트용 계산·내용 구성·검증

  POST /api/v1/chart/calc    Records + QueryBundle + 모듈 2 차트 계획 → ChartPlan · ChartContent[] · CalcResult[] · displays · validation
  POST /api/v1/chart/calc/trace  같은 입력 → 단계별 중간 결과 (HCX 프롬프트·원 응답, 계획, 차트 시도, 표시값) — 테스트 화면용
  POST /api/v1/chart/decide  질문 + View → 차트 계획 (모듈 2 실행 + 어댑터). 응답의 charts 를 /calc 에 넣는다   [NEW]
  GET  /api/v1/chart/specs   차트 15종 표 (필수 역할 · 행 구조 · 기본 requirements)

로직은 backend/agent/chart_calculate 에 있고, 여기는 HTTP ↔ 함수 연결만 한다.
"""
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.chart_calculate.from_module2 import records_of, skipped_sets, to_chart_requests, unknown_view_ids  # [NEW]
from backend.agent.chart_decision import run_chart_decision               # [NEW] 모듈 2 (LangGraph 는 호출할 때 불러온다)
from backend.agent.chart_calculate.pipeline import Module3Trace, run_module3, run_module3_trace
from backend.agent.chart_calculate.planner import Decision
from backend.agent.chart_calculate.specs import SPECS
from backend.api.deps import guard
from backend.schemas.chart import ChartRequest, Module3Output, Module3Request
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record                                  # [NEW]
from backend.schemas.view import ViewResult                                # [NEW]

TAG = "③-1 Chart 계산 (모듈 3)"      # main.py TAGS 의 이름과 같아야 한다
router = APIRouter(prefix="/api/v1/chart", tags=[TAG])

_VIEW = "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
_YEARS = ["2021", "2022", "2023", "2024", "2025"]
# 명세 시나리오 (혼인건수 5년 추이 + 증감률). decision 이 들어 있어 HCX 없이 실행된다
EX_CALC = {
    "query_bundle": {"query_id": "27077dec", "original": "최근 5년 혼인건수 추이와 증감률",
                     "sub_questions": ["2021~2025년 전국 혼인건수 추이"]},
    "records": [{
        "id": _VIEW, "lexical_text": "인구동태건수 및 동태율 추이", "parent_id": "table::101_DT_1B8000G",
        "table": {"columns": ["시점", "행정구역별", "항목", "값"],
                  "rows": [[y, "전국", "혼인건수(건)", v] for y, v in
                           zip(_YEARS, [192507, 191690, 193657, 222412, 240326])]},
        "metadata": {"prd_se": "Y", "view_type": "trend", "unit": "건"}}],
    "charts": [{"chart_id": "c1", "sub_question_ids": ["27077dec-1"], "chart_type": "line", "measure": "raw",
                "requirements": ["time_axis_required", "min_points_3"], "fallback_chart": "bar",
                "view_ids": [_VIEW]}],       # 세트: 질문(27077dec-1) · 차트(line) · View (모듈 2 의 view_ids)
    "decision": {
        "charts": [{"chart_id": "c1", "record_id": _VIEW,
                    "select": {"행정구역별": ["전국"], "항목": ["혼인건수(건)"], "시점": _YEARS}}],
        "answers": [{"sub_question_id": "27077dec-1", "op": "growth_rate", "from": "2021", "to": "2025",
                     "operands": [{"record_id": _VIEW, "item": "혼인건수(건)", "select": {"행정구역별": ["전국"]}}]}]},
}


class CalcRequest(Module3Request):
    """Module3Request + 선택 필드 decision. 이 API 에서만 쓰는 입력이라 schemas/ 가 아니라 여기에 둔다"""
    model_config = ConfigDict(json_schema_extra={"examples": [EX_CALC]})
    decision: Decision | None = Field(None, description="HCX 가 정할 계획 결정을 직접 넣는다. 넣으면 HCX 를 부르지 않는다 "
                                                        "(시험·재실행용). 비우면 HCX 가 정한다")


class DecideRequest(BaseModel):
    """모듈 2 입력: 질문과, 그 질문으로 찾은 View. 모듈 2 가 하위 질문마다 차트 유형·measure 를 정한다"""
    query_bundle: QueryBundle
    view_input: ViewResult = Field(..., description="POST /api/v1/rag/views/detail 응답")
    use_llm: bool = Field(True, description="False 면 모듈 2 가 HCX 를 부르지 않는다 (규칙으로 못 정한 measure 는 raw 로 대체된다)")


class DecideResponse(BaseModel):
    charts: list[ChartRequest] = Field(..., description="어댑터를 거친 값. /calc 의 charts 에 그대로 넣는다")
    errors: list[dict[str, Any]] = Field(default_factory=list, description="모듈 2 가 건너뛴 하위 질문(짝 없음 · 필터 0행 · 입력 문제) "
                                                                         "+ query_id 불일치 경고")
    records: list[Record] = Field(default_factory=list, description="/calc 의 records 에 그대로 넣는다 (unit 마다 rank 1 View 하나씩. "
                                                                    "세트의 view_ids 는 모두 여기 있다)")
    chart_plan: dict[str, Any] | None = Field(None, description="모듈 2 원본 출력 (어댑터가 바꾸기 전). 차이를 눈으로 비교하는 용도")


@router.post("/decide", response_model=DecideResponse, summary="② 모듈 2 — 질문 + View → 차트 계획 (charts · records 를 /calc 에 넣는다)")
def chart_decide(body: DecideRequest):
    """모듈 2(`backend/agent/chart_decision`)를 실행하고, 결과를 모듈 3 입력(`ChartRequest`)으로 바꿔 돌려준다.

    - 바꾸는 것(임시 어댑터): `fallback_charts` 목록 → `fallback_chart` 첫 값, `measure` None → raw, `'범위 밖'` → 차트 없음,
      하위 질문이 없을 때의 `sub_question_ids` `'main'` → `'{query_id}-1'`.
      바꾼 사실은 `reason` 에 남는다. 원래 값은 `chart_plan` 에 그대로 있다.
    - 모듈 2 의 `view_ids` 는 차트마다 그대로 전달된다 (세트 = 질문 · 차트 유형 · View). `records` 에 없는 View 가 있으면 `errors` 에 경고.
    - `chart_plan` 이 비어 있으면(`charts: []`) 이유는 `errors` 에 있다."""
    with guard("chart: "):
        view_input = body.view_input.model_dump(mode="json", by_alias=True)
        out = run_chart_decision(body.query_bundle.model_dump(mode="json", by_alias=True), view_input, use_llm=body.use_llm)
        plan, errors = out["chart_plan"], list(out["errors"])
        if body.query_bundle.query_id != body.view_input.query_id:
            # 모듈 3 은 '{QueryBundle.query_id}-{순번}' 으로 하위 질문을 찾는다 → 다르면 시점·지역 같은 고정 조건이 적용되지 않는다
            errors.append({"reason": f"QueryBundle.query_id({body.query_bundle.query_id}) 와 View 의 query_id"
                                     f"({body.view_input.query_id}) 가 달라 모듈 3 이 하위 질문을 찾지 못할 수 있음"})
        charts = to_chart_requests(plan or {}, body.query_bundle)
        records = records_of(view_input)
        errors += unknown_view_ids(charts, records)        # 세트의 View 가 records 에 있는지 (HCX 부르기 전에)
        charts += skipped_sets(out["errors"], body.query_bundle, charts, view_input)  # 건너뛴 하위 질문 → 차트 없는 세트 (x1, x2 …). 같은 순서의 View 가 있으면 붙인다
        return DecideResponse(charts=charts, errors=errors, records=records, chart_plan=plan)


@router.post("/calc", response_model=Module3Output, summary="계산 계획 → 계산 → 차트 내용 구성·검증")
def chart_calc(body: CalcRequest):
    """`records` 에 `/api/v1/rag/views` 응답(Record 목록), `query_bundle` 에 query-rewrite 응답의 `view_bundle`,
    `charts` 에 모듈 2 의 차트 계획을 넣는다.

    - `chart_contents` 에는 검증을 통과한 차트만 들어 있다. 빠진 차트의 사유는 `validation` 에 있다.
    - `calc_results` 는 차트와 관계없이 계산한다. 값과 `chart_contents.rows` 는 원래 정밀도이고, 표시는 `displays` 로 한다.
    - `chart_plan.notes` 에 HCX 가 고른 값 중 View 에 없는 것, 질문용 연산과 모듈 2 measure 의 차이 등이 남는다."""
    with guard("chart: "):
        return run_module3(body, decision=body.decision)


@router.post("/calc/trace", response_model=Module3Trace, summary="/calc 와 같은 입력 → 단계별 중간 결과 (테스트 화면용)")
def chart_calc_trace(body: CalcRequest):
    """`output` 은 `/calc` 응답과 같다. 그 밖에:
    `decide`(HCX 에 보낸 메시지 · 원 응답 · 버린 항목 · Decision), `charts`(차트별 원래 → 대체 시도의 내용과 검증),
    `calcs`(CalcResult + displays 를 적용한 표시값).
    화면: `http://localhost:8000/lab/chart-lab/`"""
    with guard("chart: "):
        return run_module3_trace(body, decision=body.decision)


@router.get("/specs", summary="차트 15종 표 (필수 역할 · 행 구조 · 기본 requirements)")
def chart_specs():
    return {name: asdict(spec) for name, spec in SPECS.items()}
