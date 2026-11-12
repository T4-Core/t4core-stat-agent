"""
모듈 5. 차트 그리기 — ChartPlan(모듈 2) + ChartContent[] · CalcResult[] · displays(모듈 3) → 차트 (Plotly)

  이 파일 하나만 import하면 모듈 5 전체를 실행할 수 있다.

    from backend.agent.draw_chart import run_module5, results_table                     # 짧게 (상위 패키지)
    # from backend.agent.draw_chart.draw_chart_module import run_module5, results_table  # 이 패키지에서 직접

    out = run_module5(chart_plan=module2_chart_plan, module3_output=module3_output)   # 모듈 2·3 출력
    out["results"]  # DrawResult[]   out["html"]  # 질문 HTML 경로

  파일 구성 (draw_chart_이름.py)
    schema     상태 코드 · 15종 · 유형별 약속 · DrawJob · DrawResult · 경로
    load       ① 입력 로드 (모듈 2·3 출력 / 4개 직접)
    prepare    ② DrawJob 만들기
    format     표시 헬퍼 (format_value, 축 이름, 범위 …)
    renderers  렌더러 15종 + RENDERERS
    tool       draw_chart(job) — precheck · 렌더러 · decorate
    save       fan-in 저장 (json · PNG 일괄 · 질문 HTML)
    graph      LangGraph: load → prepare → Send(draw) × N → save
    run        진입점 run_module5
    samples    15종 예시 데이터 + run_samples
"""
import sys
from pathlib import Path

# 모듈 3 코드(backend/…)를 import하려면 저장소 최상위가 import 경로에 있어야 한다
_ROOT = next((p for p in Path(__file__).resolve().parents if (p / "backend").is_dir()), None)
if _ROOT and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .draw_chart_graph import build_module5_graph, graph  # noqa: E402
from .draw_chart_run import run_module5  # noqa: E402
from .draw_chart_save import results_table  # noqa: E402
from .draw_chart_schema import DrawJob, DrawResult, contract_table  # noqa: E402

# [시나리오] 시나리오 실행 함수 — 주석 처리
# from .draw_chart_run import run_scenario

__all__ = ["run_module5", "graph", "build_module5_graph", "results_table", "DrawJob", "DrawResult", "contract_table"]
