"""5번 차트 그리기 모듈 패키지

5번 모듈 실행:
    from backend.agent.draw_chart import run_module5, results_table
    out = run_module5(chart_plan=module2_chart_plan, module3_output=module3_output)
    out["results"], out["html"]

자세한 설명은 draw_chart_module/README.md
"""


def run_module5(chart_plan=None, module3_output=None, **kwargs):
    """5번 모듈 실행. 인자 · 반환값은 draw_chart_module/draw_chart_run.py"""
    from .draw_chart_module.draw_chart_run import run_module5 as _run
    return _run(chart_plan, module3_output, **kwargs)


def results_table(results):
    """DrawResult[] → 결과 요약 표 (pandas DataFrame)"""
    from .draw_chart_module.draw_chart_save import results_table as _table
    return _table(results)


def run_samples(out_dir=None, save=True):
    """15종 예시 데이터로 실행 (렌더러 확인용). 자세한 설명은 draw_chart_module/draw_chart_samples.py"""
    from .draw_chart_module.draw_chart_samples import run_samples as _run
    return _run(out_dir=out_dir, save=save)


__all__ = ["run_module5", "results_table", "run_samples"]
