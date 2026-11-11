"""Generator 모듈 패키지

2번 차트 유형 판단 모듈 실행:
    from module import run_chart_decision
    out = run_chart_decision(query_bundle, view_input)
"""


def run_chart_decision(query_bundle, view_input, use_llm=True, show_steps=False):
    """2번 모듈 실행. 자세한 설명은 chart_decision/chart_type_run.py"""
    from .chart_decision_module.chart_type_run import run_chart_decision as _run
    return _run(query_bundle, view_input, use_llm=use_llm, show_steps=show_steps)


__all__ = ["run_chart_decision"]
