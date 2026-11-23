"""과거 slim trace(profiling/modules36/results/*.jsonl) → RunRecord

slim trace 에는 ViewSet 전체 · 모듈 요청 전체가 없다 (Record 는 모듈에 넘긴 것만, 행 400개까지).
그래서 replay · oracle · A0 지표는 N/A 이고, 하위 질문 연결 · 보류 범위는 어댑터(source=adapter)로 추정한다.

  python -m eval.generator.legacy profiling/modules36/results/full1.jsonl --runs 1,2 --out <EVAL_RUNS_DIR>/legacy/baseline12.jsonl
"""
import argparse
import json
from pathlib import Path

from backend.core.config import EVAL_RUNS_DIR
from eval.generator import trace


def convert(rec: dict) -> dict:
    mods = rec.get("modules") or {}
    return {
        "id": rec["id"], "set": "core34", "run": rec.get("run", 1), "mode": "live",
        "path": "qa" if mods.get("qa") else "modules", "question": rec.get("question"), "ok": rec.get("ok", True),
        "error": rec.get("error"), "source": "legacy", "analysis": rec.get("analysis"), "viewset": None,
        "records": mods.get("records") or [], "modules": mods or None, "requests": None, "result": rec.get("result"),
        "timings": rec.get("timings"), "seconds": rec.get("seconds"), "hcx_calls": rec.get("hcx_calls") or [],
        "expect_text": rec.get("expect"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--runs", default="", help="회차 번호 (쉼표). 비우면 전체")
    ap.add_argument("--renumber", action="store_true", help="고른 회차를 1부터 다시 번호 매김")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    keep = {int(x) for x in a.runs.split(",") if x.strip()}
    recs = [r for r in trace.iter_jsonl(a.trace) if not keep or r.get("run") in keep]
    if a.renumber:
        order = {r: i for i, r in enumerate(sorted({x["run"] for x in recs}), 1)}
        for r in recs:
            r["run"] = order[r["run"]]
    out = Path(a.out or EVAL_RUNS_DIR / "legacy" / (Path(a.trace).stem + (f"_runs{a.runs.replace(',', '')}" if keep else "") + ".jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(convert(r), ensure_ascii=False, default=str) + "\n")
    print("wrote", out, len(recs))


if __name__ == "__main__":
    main()
