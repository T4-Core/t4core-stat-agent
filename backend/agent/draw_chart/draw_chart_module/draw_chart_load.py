"""
모듈 5 ① 입력 로드 — 모듈 2 · 모듈 3 출력 → 모듈 3 스키마로 파싱

  입력
    모듈 2  chart_plan      {"query_id", "charts": [...]} (dict)
                            모듈 2 그래프 state 전체를 줘도 된다 → chart_plan 키를 꺼낸다
    모듈 3  module3_output  아래 어느 모양이든 된다
                              - Module3Output (run_module3)          - Module3Output의 dict
                              - Module3Trace (run_module3_trace)     - 모듈 3 그래프 결과 {"output", "trace"}
                            → chart_contents · calc_results · displays
                              (+ validation: 차트가 없을 때 그 이유를 찾는 데만 쓴다)
    또는 입력 4개를 직접: chart_plan · chart_contents · calc_results · displays

  ChartPlan은 맞는 백엔드 스키마가 없어 dict 그대로 쓴다.
  나머지는 모듈 3 pydantic 스키마로 파싱하고, 원소 하나가 틀려도 멈추지 않고 load_errors에 남긴다
  (틀린 ChartContent는 prepare에서 그 차트를 failed로 처리한다).
"""
from pydantic import BaseModel, ValidationError

from backend.schemas.chart import CalcResult, ChartContent, Display

# [시나리오] 시나리오 데이터(data/{query_id}/*.json)를 읽는 코드 — 모듈 2·3 연결에서는 쓰지 않아 주석 처리
#            (시나리오로 시험할 때는 JSON을 직접 읽어 모듈 2·3 출력 모양으로 run_module5에 넘긴다)
# import json
# from pathlib import Path
#
# INPUT_FILES = ["chart_plan", "chart_contents", "calc_results", "displays"]
#
#
# def read_scenario(folder) -> dict:
#     """data/{query_id}/ 의 JSON 4개를 읽는다"""
#     folder = Path(folder)
#     return {name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8")) for name in INPUT_FILES}


def _dump(obj):
    """pydantic 객체 → dict (명세와 같은 키를 쓰도록 by_alias). dict는 그대로"""
    return obj.model_dump(by_alias=True) if isinstance(obj, BaseModel) else obj


def chart_plan_of(module2) -> dict:
    """모듈 2 출력 → ChartPlan dict {"query_id", "charts": [...]}
    chart_plan 자체 / 모듈 2 그래프 state(chart_plan 키) / pydantic 객체 / None(→ 빈 계획) 모두 받는다"""
    m2 = _dump(module2) or {}
    if "charts" not in m2 and isinstance(m2.get("chart_plan"), (dict, BaseModel)):
        m2 = _dump(m2["chart_plan"]) or {}
    return m2


def module3_output_of(module3) -> dict:
    """모듈 3 출력 → Module3Output dict
    Module3Output / 그 dict / Module3Trace(.output) / 모듈 3 그래프 결과 {"output", "trace"} 모두 받는다"""
    if isinstance(module3, BaseModel) and not hasattr(module3, "chart_contents") and hasattr(module3, "output"):
        module3 = module3.output                                 # Module3Trace
    m3 = _dump(module3) or {}
    if "chart_contents" not in m3 and m3.get("output") is not None:
        m3 = _dump(m3["output"]) or {}                           # 모듈 3 그래프 결과
    return m3


def from_upstream(module2_chart_plan, module3_output) -> dict:
    """모듈 2·3 출력 → 원자료 (chart_plan · chart_contents · calc_results · displays · validation · query_id)"""
    m3 = module3_output_of(module3_output)
    return {"chart_plan": chart_plan_of(module2_chart_plan), "chart_contents": m3.get("chart_contents") or [],
            "calc_results": m3.get("calc_results") or [], "displays": m3.get("displays") or {},
            "validation": {k: _dump(v) for k, v in (m3.get("validation") or {}).items()},
            "query_id": m3.get("query_id")}


def _key(obj, name, default):
    """dict든 pydantic 객체든 필드 하나 꺼내기 (오류 메시지의 키 이름용)"""
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def parse_inputs(raw: dict):
    """→ (chart_plan, {chart_id: ChartContent | None}, CalcResult[], {ref: Display}, load_errors)
    원소는 dict여도 되고 이미 모듈 3 객체여도 된다. ChartPlan에 query_id가 없으면 모듈 3 출력의 query_id를 쓴다"""
    errors = {}

    def parse(model, obj, key):
        try:
            return model.model_validate(obj)
        except ValidationError as e:
            errors[key] = f"{model.__name__} 스키마 오류: {e.error_count()}건 — {e.errors()[0]['loc']} {e.errors()[0]['msg']}"
            return None

    plan = chart_plan_of(raw.get("chart_plan"))
    if not plan.get("query_id") and raw.get("query_id"):
        plan = {**plan, "query_id": raw["query_id"]}
    contents = {}
    for i, c in enumerate(raw.get("chart_contents") or []):
        cid = _key(c, "chart_id", f"#{i}")
        contents[cid] = parse(ChartContent, c, f"chart_contents.{cid}")
    calcs = [r for i, c in enumerate(raw.get("calc_results") or [])
             if (r := parse(CalcResult, c, f"calc_results.{_key(c, 'step_id', i)}"))]
    displays = {k: d for k, v in (raw.get("displays") or {}).items() if (d := parse(Display, v, f"displays.{k}"))}
    return plan, contents, calcs, displays, errors


def resolve_inputs(state: dict) -> dict:
    """그래프 입력 → 원자료. module3_output이 있으면 모듈 2·3 출력으로, 없으면 입력 4개를 직접 받은 것으로 본다"""
    # [시나리오] 시나리오 폴더 입력 — 주석 처리
    # if state.get("scenario_dir"):
    #     return read_scenario(state["scenario_dir"])
    if state.get("module3_output") is not None:
        return from_upstream(state.get("chart_plan"), state["module3_output"])
    return {"chart_plan": state.get("chart_plan"), "chart_contents": state.get("chart_contents") or [],
            "calc_results": state.get("calc_results") or [], "displays": state.get("displays") or {},
            "validation": state.get("validation") or {}}
