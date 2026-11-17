"""2번 차트 유형 판단 모듈

사용 예 (가장 간단):
    from module import run_chart_decision
    out = run_chart_decision(query_bundle, view_input)   # dict 또는 JSON 파일 경로
    out["chart_plan"], out["filtered_views"], out["errors"]
"""
from .chart_type_chart_picker import attach_requirements, check_chart, pick_chart, try_combo
from .chart_type_loader import load_json, slim_query_bundle, slim_view_input
from .chart_type_matcher import match_units
from .chart_type_measure import decide_measure, decide_measure_llm, decide_measure_rule, end_intent
from .chart_type_pipeline import decide_charts
from .chart_type_profiler import profile_data
from .chart_type_reason import make_reason
from .chart_type_view_filter import filter_view



def run_chart_decision(query_bundle, view_input, use_llm=True, show_steps=False):
    """2번 모듈 실행 (LangGraph 서브그래프). 자세한 설명은 chart_type_run.run_chart_decision"""
    from .chart_type_run import run_chart_decision as _run      # 쓸 때 불러옴 (langgraph는 이때 필요)
    return _run(query_bundle, view_input, use_llm=use_llm, show_steps=show_steps)


__all__ = [
    "run_chart_decision", "decide_charts", "load_json", "slim_query_bundle", "slim_view_input",
    "match_units", "filter_view", "decide_measure", "decide_measure_rule", "decide_measure_llm", "end_intent",
    "profile_data", "check_chart", "pick_chart", "try_combo", "attach_requirements", "make_reason",
]
