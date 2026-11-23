"""Metamorphic Test

  MT-1  ViewSet 안 View 순서 섞기 → 차트 · op · 결과 값이 같아야 한다 (replay, 실제 HCX)
  MT-2  -O / -P 질문 쌍(synth) → E2E 판정 · 수치가 같아야 한다 (두 실행 결과 비교, HCX 없음)
  MT-3a 증감 연산의 처음 · 끝 입력을 맞바꾸고 결과 · displays · 원본 Record 행을 함께 다시 만든 정합 사례
        → 방향 단어 반전 + 재계산 값 일치 (oracle 입력 위에서 run_module6, 실제 HCX)
  결과만 바꾼 모순 입력은 FI-CONTRA(faults.py)로 분리했다.

  python -m eval.generator.metamorphic mt3a <runs.jsonl.gz> [--only Q02] [--runs 2]
  python -m eval.generator.metamorphic mt1  <runs.jsonl.gz> [--only ...] [--seed 7]
  python -m eval.generator.metamorphic mt2  <A.verdicts.jsonl> --pairs pairs.csv
"""
import argparse
import copy
import json
import random
from pathlib import Path

from eval.generator import rel, resolve as R, trace
from eval.generator.display_ref import from_display

DIRECTIONAL = {"growth_rate", "change", "cagr"}


def recompute(op: str, first: float, last: float, years: int | None = None) -> float | None:
    """M3 와 같은 식 (calculate.py 15행 머리말: growth_rate (b−a)/a×100, change b−a, cagr ((b/a)^(1/n)−1)×100)"""
    if op == "change":
        return last - first
    if first == 0:
        return None
    if op == "growth_rate":
        return (last - first) / first * 100
    if op == "cagr" and years:
        if first <= 0 or last < 0:
            return None
        return ((last / first) ** (1 / years) - 1) * 100
    return None


def _years(inputs: list[dict]) -> int | None:
    try:
        a, b = int(str(inputs[0]["key"].get("시점"))[:4]), int(str(inputs[-1]["key"].get("시점"))[:4])
        return b - a
    except (KeyError, ValueError, TypeError, IndexError):
        return None


def mt3a_request(m6_req: dict) -> tuple[dict | None, str]:
    """변형 전용 요청. 원본 요청은 바꾸지 않는다(깊은 복사). 원본 행을 하나로 특정하지 못하면 (None, 사유)"""
    req = copy.deepcopy(m6_req)
    steps = req.get("answer_steps") or []
    targets = [c for c in req.get("calc_results") or [] if c.get("op") in DIRECTIONAL
               and not isinstance(c.get("value"), list) and c.get("value") is not None and len(c.get("inputs") or []) >= 2]
    if not targets:
        return None, "no_scalar_directional"
    records = req.get("records") or []
    for c in targets:
        a, b = c["inputs"][0], c["inputs"][-1]
        ra, _ = R.resolve_input(records, a, R.select_of(steps, c["step_id"], a.get("record_id")))
        rb, _ = R.resolve_input(records, b, R.select_of(steps, c["step_id"], b.get("record_id")))
        if ra is None or rb is None or ra.cols == rb.cols:
            return None, "unresolved_row"
        new = recompute(c["op"], b["value"], a["value"], _years(c["inputs"]))
        if new is None:
            return None, "not_recomputable"
        a["value"], b["value"] = b["value"], a["value"]
        _set_row_value(records, ra, a["value"])
        _set_row_value(records, rb, b["value"])
        c["value"] = new
    return req, "ok"


def _set_row_value(records: list[dict], row: R.Row, value) -> None:
    rec = next(r for r in records if r.get("id") == row.record_id)
    cols, rows = trace.table(rec)
    vi = trace.value_index(cols)
    for r in rows:
        if {c: r[i] for i, c in enumerate(cols) if i != vi} == row.cols:
            r[vi] = value
            return


def consistency(req: dict) -> list[str]:
    """변형 요청의 정합성: 모든 CalcInput 값 == 원본 행 값, 결과 == 재계산"""
    problems = []
    records, steps = req.get("records") or [], req.get("answer_steps") or []
    for c in req.get("calc_results") or []:
        for inp in c.get("inputs") or []:
            row, _ = R.resolve_input(records, {**inp, "value": None}, R.select_of(steps, c["step_id"], inp.get("record_id")))
            if row is None:
                row, _ = R.resolve_input(records, inp, R.select_of(steps, c["step_id"], inp.get("record_id")))
            if row is None or not R.is_number(row.value) or abs(float(row.value) - float(inp["value"])) > 1e-9:
                problems.append(f"{c['step_id']}: 입력 {inp.get('key')} 값이 원본 행과 다름")
        if c.get("op") in DIRECTIONAL and not isinstance(c.get("value"), list) and len(c.get("inputs") or []) >= 2:
            want = recompute(c["op"], c["inputs"][0]["value"], c["inputs"][-1]["value"], _years(c["inputs"]))
            if want is None or abs(want - c["value"]) > 1e-9 * max(1, abs(want)):
                problems.append(f"{c['step_id']}: 결과가 재계산과 다름")
    return problems


def expected_display(req: dict) -> dict[str, str]:
    return {c["step_id"]: from_display(c["value"], (req.get("displays") or {}).get(c.get("display_ref")))
            for c in req.get("calc_results") or [] if c.get("op") in DIRECTIONAL and not isinstance(c.get("value"), list)}


def run_mt3a(src_path, only: set[str], runs: int) -> list[dict]:
    import backend.core.llm as llm
    from backend.agent.answer_compose.pipeline import run_module6
    from backend.schemas.answer import Module6Request
    from synthetic_gold_pipeline.tools.evaluation_tool import DECREASE, INCREASE
    rows = []
    for src in trace.load(src_path):
        if (only and src["id"] not in only) or src.get("run", 1) != 1:
            continue
        m6_req = (src.get("requests") or {}).get("m6")
        if not m6_req:
            rows.append({"id": src["id"], "status": "mt_skipped", "why": "no_full_request"})
            continue
        var, why = mt3a_request(m6_req)
        if var is None:
            rows.append({"id": src["id"], "status": "mt_skipped", "why": why})
            continue
        probs = consistency(var)
        orig_dir = {c["step_id"]: c["value"] > 0 for c in m6_req["calc_results"] if c.get("op") in DIRECTIONAL
                    and isinstance(c.get("value"), (int, float))}
        for run_no in range(1, runs + 1):
            out = run_module6(Module6Request.model_validate(var), chat=llm.chat).model_dump(mode="json")
            text = out.get("answer") or ""
            new_up = not all(orig_dir.values())          # 원래 감소였으면 변형은 증가
            dir_ok = bool(INCREASE.search(text)) if new_up else bool(DECREASE.search(text))
            disp = expected_display(var)
            val_ok = all(d is None or d.lstrip("-") in text for d in disp.values())
            rows.append({"id": src["id"], "run": run_no, "status": "ok" if dir_ok and val_ok and not probs else "fail",
                         "direction_ok": dir_ok, "value_ok": val_ok, "consistency": probs, "answer": text[:200],
                         "expected_display": disp})
    return rows


def run_mt1(src_path, only: set[str], seed: int) -> list[dict]:
    """View 순서만 섞어 replay. 기대: 차트 유형 · op · 결과 값 동일"""
    from eval.generator.run import Recorder, run_generator
    rng = random.Random(seed)
    rows = []
    for src in trace.load(src_path):
        if (only and src["id"] not in only) or src.get("run", 1) != 1 or not src.get("viewset"):
            continue
        vs = copy.deepcopy(src["viewset"])
        for u in vs.get("units") or []:
            views = u.get("views") or []
            rank1 = [v for v in views if v.get("rank") == min((x.get("rank") or 99) for x in views)] if views else []
            rest = [v for v in views if v not in rank1]
            rng.shuffle(rest)
            u["views"] = rank1 + rest                    # 1순위는 그대로 (모듈 2 · 3 은 단위마다 1순위 View 를 쓴다)
        rng.shuffle(vs.get("records") or [])
        mods = run_generator(vs, src.get("analysis"), qa=True, draw=False, max_rows=40, rec=Recorder())
        def sig(m):
            m3 = (m or {}).get("module3") or {}
            return {"charts": sorted(str(c.get("chart_type")) for c in m.get("charts") or []),
                    "calcs": sorted((c.get("op"), json.dumps(c.get("value"), sort_keys=True, default=str)) for c in m3.get("calc_results") or [])}
        a, b = sig(src.get("modules") or {}), sig(mods)
        rows.append({"id": src["id"], "same_charts": a["charts"] == b["charts"], "same_calcs": a["calcs"] == b["calcs"]})
    return rows


def run_mt2(verdicts_path, pairs_csv) -> list[dict]:
    import csv
    v = {}
    for x in trace.load(verdicts_path):
        v.setdefault(x["id"], []).append(x)
    rows = []
    with open(pairs_csv, encoding="utf-8-sig") as f:
        for p in csv.DictReader(f):
            a, b = v.get(p["original"]), v.get(p["paraphrased"])
            if not a or not b:
                continue
            rows.append({"pair": p.get("dataset_id") or p["original"], "same_verdict": a[0]["verdict"] == b[0]["verdict"],
                         "verdicts": [a[0]["verdict"], b[0]["verdict"]]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("test", choices=["mt1", "mt2", "mt3a"])
    ap.add_argument("src")
    ap.add_argument("--only", default="")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--pairs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    rows = run_mt3a(a.src, only, a.runs) if a.test == "mt3a" else run_mt1(a.src, only, a.seed) if a.test == "mt1" \
        else run_mt2(a.src, a.pairs)
    out = Path(a.out or Path(a.src).parent / f"{a.test}.jsonl")
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + "\n", encoding="utf-8")
    print(json.dumps(rows[:20], ensure_ascii=False, indent=1, default=str))
    print("wrote", rel(out))


if __name__ == "__main__":
    main()
