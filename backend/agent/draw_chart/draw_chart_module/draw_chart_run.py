"""
모듈 5 진입점 — 이 파일(또는 패키지 draw_chart_module) 하나만 import하면 모듈 5 전체를 실행한다

  from backend.agent.draw_chart import run_module5          # 짧게 (상위 패키지)
  # from backend.agent.draw_chart.draw_chart_module.draw_chart_run import run_module5

  # 1) 모듈 2·3 출력으로 (기본)
  out = run_module5(chart_plan=module2_chart_plan, module3_output=module3_output)
      #  module2_chart_plan : 모듈 2 출력 {"query_id", "charts"} (모듈 2 그래프 state 전체도 된다)
      #  module3_output     : Module3Output · 그 dict · Module3Trace · 모듈 3 그래프 결과 {"output", "trace"}
  # 2) 입력 4개를 직접
  out = run_module5(chart_plan=plan, chart_contents=contents, calc_results=calcs, displays=displays)

  out = {"query_id", "results": DrawResult[], "html": 질문 HTML 경로, "load_errors"}

  명령줄: (저장소 최상위에서) python -m backend.agent.draw_chart.draw_chart_module samples   ← __main__.py
"""
from pathlib import Path

from .draw_chart_graph import graph

# [시나리오] 시나리오 데이터 경로 — 주석 처리
# from .draw_chart_schema import DATA_DIR


def run_module5(chart_plan=None, module3_output=None, *, chart_contents=None, calc_results=None, displays=None,
                validation=None, out_dir: str | Path | None = None, save: bool = True) -> dict:
    """모듈 5 전체 실행 (LangGraph): load → prepare → draw × N(병렬) → save"""
    state = {"chart_plan": chart_plan, "module3_output": module3_output, "chart_contents": chart_contents,
             "calc_results": calc_results, "displays": displays, "validation": validation,
             "out_dir": out_dir, "save": save}
    return graph.invoke({k: v for k, v in state.items() if v is not None})


# [시나리오] 시나리오 데이터(data/{query_id}/)로 실행 — 모듈 2·3 연결에서는 쓰지 않아 주석 처리
#            (시나리오로 시험할 때는 JSON을 직접 읽어 run_module5에 모듈 2·3 출력 모양으로 넘긴다)
# def run_scenario(query_id: str = "15d183df", **kwargs) -> dict:
#     """시나리오 데이터(data/{query_id}/)로 실행"""
#     return run_module5(scenario_dir=DATA_DIR / query_id, **kwargs)
