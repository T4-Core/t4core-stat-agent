"""모듈 5 재렌더링 + Chart-Data Fidelity · Spec Lint (계획 2.5, V-5). HCX 호출 없음

저장한 모듈 2 차트 계획(modules.chart_plan)과 모듈 3 출력으로 run_module5 를 다시 돌린다. 같은 입력이면 같은 그림이다.
slim trace 는 figure 를 저장하지 않았으므로 과거 회차의 Fidelity 는 이 도구로만 산출된다.

  python -m eval.generator.render <runs.jsonl[.gz]> [--png] [--out DIR]
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import plotly

from eval.generator import rel, trace
from eval.generator.chart_extract import compare
from eval.generator.checks.m5 import lint


def render_run(run: dict, out_dir: Path | None, png: bool) -> list[dict]:
    from backend.agent.draw_chart import run_module5
    mods = trace.mods(run)
    m3 = mods.get("module3") or {}
    if not m3.get("chart_contents"):
        return []
    d = out_dir / f"{run['id']}_run{run.get('run', 1)}" if out_dir and png else None
    try:
        res = run_module5(chart_plan=mods.get("chart_plan") or {"query_id": m3.get("query_id"), "charts": []},
                          module3_output=m3, out_dir=d, save=bool(png))
    except Exception as e:  # noqa: BLE001  (한 건이 실패해도 나머지를 계속)
        return [{"id": run["id"], "run": run.get("run", 1), "chart_id": None, "status": "exception", "error": f"{type(e).__name__}: {e}"[:200]}]
    contents = {c["chart_id"]: c for c in m3.get("chart_contents") or []}
    displays = m3.get("displays") or {}
    rows = []
    for r in res.get("results") or []:
        fig = json.loads(r.figure.to_json()) if r.figure is not None else None
        drawn = {"chart_id": r.chart_id, "figure": fig, "merged_from": list(r.merged_from)}
        c = contents.get(r.chart_id)
        f = compare(c, displays, drawn) if c else None
        rows.append({"id": run["id"], "run": run.get("run", 1), "chart_id": r.chart_id, "chart_type": r.chart_type,
                     "status": r.status, "fidelity": f.status if f else "no_content",
                     "missing": (f.missing if f else [])[:5], "extra": (f.extra if f else [])[:5], "diff": (f.diff if f else [])[:5],
                     "lint": lint(c, drawn, displays) if c and fig else [], "png": (r.files or {}).get("png")})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--png", action="store_true", help="PNG · HTML 저장 (Visual Defect 수동 검토용, kaleido 필요)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    src = Path(a.runs)
    out = Path(a.out or src.parent / (src.name.split(".")[0] + "_render"))
    out.mkdir(parents=True, exist_ok=True)
    rows = [row for run in trace.load(src) for row in render_run(run, out / "charts", a.png)]
    (out / "render.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + "\n", encoding="utf-8")
    st, fid = Counter(r["status"] for r in rows), Counter(r["fidelity"] for r in rows)
    decided = [r for r in rows if r["fidelity"] in ("ok", "mismatch")]
    drawn = [r for r in rows if r["status"] in ("drawn", "failed", "exception")]
    summary = {"plotly": plotly.__version__, "charts": len(rows), "status": dict(st), "fidelity": dict(fid),
               "render_success": None if not drawn else round(sum(r["status"] == "drawn" for r in drawn) / len(drawn), 4),
               "fidelity_ok": None if not decided else round(sum(r["fidelity"] == "ok" for r in decided) / len(decided), 4),
               "lint_ok": None if not decided else round(sum(not r["lint"] for r in rows if r["fidelity"] in ("ok", "mismatch")) / len(decided), 4)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print("wrote", rel(out))


if __name__ == "__main__":
    main()
