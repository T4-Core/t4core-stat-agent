"""2번 모듈을 함수 하나로 실행하는 입구

    from module import run_chart_decision
    out = run_chart_decision(query_bundle, view_input)      # dict·list 또는 JSON 파일 경로
    out["chart_plan"], out["filtered_views"], out["errors"]

터미널에서:
    python -m module.chart_decision QueryBundle.json Views.json [--no-llm] [--steps] [--out 결과.json]
"""
import argparse
import json
import sys

from .chart_type_graph import build_chart_decision_graph

OUTPUT_KEYS = ["chart_plan", "filtered_views", "errors"]
_GRAPH = None                                   # 처음 부를 때 한 번만 만든다


def _graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_chart_decision_graph()
    return _GRAPH


def run_chart_decision(query_bundle, view_input, use_llm=True, show_steps=False):
    """2번 차트 유형 판단 모듈 실행.

    query_bundle : 질의 변환 결과 (dict, [dict] 리스트, 또는 JSON 파일 경로)
    view_input   : 검색 결과 Views (dict 또는 JSON 파일 경로)
    use_llm      : False면 LLM을 부르지 않는다 (규칙으로 못 정한 measure는 None)
    show_steps   : True면 노드별 바뀐 값을 "steps"에 함께 돌려준다

    반환: {"chart_plan": {"query_id", "charts": [...]}, "filtered_views": [...], "errors": [...]}
          (show_steps=True면 + "steps": [{"node", "update"}, ...])
    """
    inp = {"query_bundle": query_bundle, "view_input": view_input, "use_llm": use_llm}
    if not show_steps:
        out = _graph().invoke(inp)
        return {k: out.get(k) if k != "errors" else (out.get(k) or []) for k in OUTPUT_KEYS}

    steps, last = [], {}
    for mode, chunk in _graph().stream(inp, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node, update in chunk.items():
                steps.append({"node": node, "update": update})
        else:
            last = chunk
    out = {k: last.get(k) if k != "errors" else (last.get(k) or []) for k in OUTPUT_KEYS}
    out["steps"] = steps
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m module.chart_decision", description="2번 차트 유형 판단 모듈 실행")
    ap.add_argument("query_bundle", help="QueryBundle JSON 파일 경로")
    ap.add_argument("view_input", help="Views JSON 파일 경로")
    ap.add_argument("--no-llm", action="store_true", help="LLM을 부르지 않음")
    ap.add_argument("--steps", action="store_true", help="노드 순서와 바뀐 키도 출력")
    ap.add_argument("--out", help="결과(chart_plan, filtered_views, errors)를 저장할 JSON 파일 경로")
    args = ap.parse_args(argv)

    out = run_chart_decision(args.query_bundle, args.view_input, use_llm=not args.no_llm, show_steps=args.steps)
    if args.steps:
        for s in out.pop("steps"):
            print(f"[{s['node']}] 바뀐 키: {list(s['update'])}", file=sys.stderr)
    print(json.dumps(out["chart_plan"], ensure_ascii=False, indent=2))
    if out["errors"]:
        print("errors:", json.dumps(out["errors"], ensure_ascii=False), file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"저장: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
