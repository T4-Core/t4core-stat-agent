"""저장한 출력에 현재 QA 스키마 검사(qa_check.check)를 다시 돌린다 (계획 3.2, profiling/modules36/contract_check.py 이전)

지점: M2-out · M3-out · M6-out · A9(run_modules 반환 11개 키). 형식 경고와 내용 경고(SEMANTIC_KINDS)를 나눠 센다.
  python -m eval.generator.contract <runs.jsonl[.gz]>
"""
import argparse
import json
from collections import Counter, defaultdict

from backend.agent.qa.qa_check import check
from backend.agent.qa.qa_policy import SEMANTIC_KINDS
from eval.generator import trace

A9_KEYS = ("charts", "chart_errors", "chart_plan", "records", "module3", "drawn", "answer", "notes",
           "render_status", "request_outcomes", "chart_notices")


def points(run: dict) -> dict:
    m = trace.mods(run)
    if not m:
        return {}
    a9 = {k: m.get(k) for k in A9_KEYS if k in m}
    if run.get("source") == "legacy":
        a9.pop("records", None)            # slim trace 의 Record 는 줄인 모양이라 스키마 오류로 잡힌다 (평가 대상 아님)
    return {"M2-out": {"chart_plan": m.get("chart_plan"), "errors": m.get("chart_errors") or []},
            "M3-out": m.get("module3"), "M6-out": m.get("answer"), "A9": a9}


def ctx_of(run: dict, point: str) -> dict:
    """qa_nodes.ref_ctx 와 같은 참조 목록을 저장한 실행에서 만든다"""
    m = trace.mods(run)
    rids = {r.get("id") for r in trace.records_of(run)}
    sub_ids = {sid for sid, _ in trace.sub_question_list(run)}
    chart_ids = {c.get("chart_id") for c in m.get("charts") or []}
    if point == "M2-out":
        return {"view_ids": rids}
    if point == "M3-out":
        return {"chart_ids": chart_ids, "record_ids": rids, "sub_ids": sub_ids}
    if point == "M6-out":
        m3 = m.get("module3") or {}
        wh = (m3.get("chart_plan") or {}).get("withheld") or []
        return {"record_ids": rids, "step_ids": {c.get("step_id") for c in m3.get("calc_results") or []},
                "withheld_ids": {x for w in wh for x in (w.get("sub_question_id"), w.get("chart_id")) if x}}
    return {}


def run_checks(runs: list[dict]) -> dict:
    n, issues, examples = Counter(), defaultdict(Counter), {}
    for r in runs:
        for pt, raw in points(r).items():
            if raw is None:
                continue
            n[pt] += 1
            try:
                c = check(pt, raw, ctx_of(r, pt))
            except Exception as e:  # noqa: BLE001
                key = f"exception/{type(e).__name__}"
                issues[pt][key] += 1
                examples.setdefault((pt, key), (r["id"], r.get("run"), str(e)[:160]))
                continue
            for i in c.issues:
                group = "semantic" if i.kind in SEMANTIC_KINDS else i.severity
                key = f"{group}/{i.kind} {i.path[:60]}"
                issues[pt][key] += 1
                examples.setdefault((pt, key), (r["id"], r.get("run"), i.message[:120]))
    return {"checked": dict(n), "issues": {pt: dict(c.most_common()) for pt, c in issues.items()},
            "errors": sum(v for c in issues.values() for k, v in c.items() if k.startswith(("error/", "exception/"))),
            "examples": {f"{pt} {k}": v for (pt, k), v in examples.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    a = ap.parse_args(argv)
    print(json.dumps(run_checks(trace.load(a.runs)), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
