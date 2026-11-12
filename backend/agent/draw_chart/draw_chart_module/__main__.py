"""
명령줄 실행 (저장소 최상위 폴더 t4core-stat-agent/ 에서)

  python -m backend.agent.draw_chart.draw_chart_module            # 15종 예시 → backend/agent/draw_chart/output/samples/
  python -m backend.agent.draw_chart.draw_chart_module samples    # 위와 같음
"""
import sys

from . import results_table
from .draw_chart_samples import run_samples

# [시나리오] 시나리오 실행 — 주석 처리
# from .draw_chart_run import run_scenario
# python -m backend.agent.draw_chart.draw_chart_module 15d183df   # 시나리오 data/{query_id}/

arg = sys.argv[1] if len(sys.argv) > 1 else "samples"
if arg != "samples":
    sys.exit(f"지원하지 않는 인자: {arg} (samples만 지원. 모듈 2·3 출력은 run_module5로 넘긴다)")
out = run_samples()
# out = run_samples() if arg == "samples" else run_scenario(arg)   # [시나리오]
print(f"query_id: {out['query_id']}")
print(results_table(out["results"]).to_string())
print("HTML:", out["html"])
for k, v in (out.get("load_errors") or {}).items():
    print(f"⚠ {k}: {v}")
