"""질문 파일 일괄 실행 — 질문마다 run_chat → results.json (synthetic_gold_pipeline.score_rag_results 가 읽는 형식)

  python -m backend.agent.batch --queries synthetic_gold_pipeline/outputs/datasets/synthetic_gold_queries.csv
  python -m backend.agent.batch --queries q.csv --no-answer --limit 20 --workers 3
  python -m synthetic_gold_pipeline.score_rag_results --rag-results <출력 폴더>

입력  .csv (id, question 열) 또는 .jsonl ({"id", "question"})
출력  RUNS_DIR/batch/<파일 이름>/results.json — 문항마다
        {id, question, status, error, stages.query{slots, clarifications}, units[{unit_id, candidates, views}],
         final{status, records}, answer}
      다시 실행하면 이미 끝난 문항은 건너뜀 (--force 로 다시)
"""
import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path


def load_questions(path):
    p = Path(path)
    if p.suffix == ".jsonl":
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    else:
        with p.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    return [{"id": str(r.get("id") or f"Q{i:03d}"), "question": r["question"]} for i, r in enumerate(rows, 1)
            if (r.get("question") or "").strip()]


def to_result(item, out):
    """ChatResponse(dict) → 채점 형식"""
    an = out.get("analysis") or {}
    slots = [{"slot": k, "value": sv.get("value"), "raw": sv.get("raw")}
             for k, svs in (an.get("slots") or {}).items() for sv in svs]
    vs = out.get("views") or {}
    units = [{"unit_id": u["unit_id"], "query": u.get("query"),
              "candidates": [{"rank": c["rank"], "tbl_id": c["tbl_id"], "survey_nm": c.get("survey_nm", "")}
                             for c in u.get("candidates") or []],
              "views": [{"record_id": v["record"]["id"], "tbl_id": v["tbl_id"], "source": v["record"].get("source") or {},
                         "notes": v.get("notes") or []} for v in u.get("views") or []]}
             for u in vs.get("units") or []]
    return {"id": item["id"], "question": item["question"], "status": out["status"], "error": None,
            "stages": {"query": {"status": an.get("status"), "slots": slots,
                                 "clarifications": an.get("clarifications") or []}},
            "units": units, "final": {"status": out["status"], "records": [r["id"] for r in out.get("records") or []]},
            "answer": out.get("result"), "timings": out.get("timings")}


def run_one(item, today, answer):
    from backend.agent.pipeline import run_chat
    t0 = time.time()
    try:
        if answer:
            out = run_chat(item["question"], today)
        else:
            from backend.rag.query_analyzer.analyze import analyze
            from backend.rag.view.viewset import build_viewset
            an = analyze(item["question"], today)
            vs = build_viewset(an, on_ambiguous=lambda c: c["options"][0]["option_id"]) if an["status"] == "ok" else None
            out = {"status": (vs or an)["status"], "analysis": an, "views": vs, "records": (vs or {}).get("records") or [],
                   "result": None, "timings": {"total": round(time.time() - t0, 2)}}
        return to_result(item, out)
    except Exception as e:  # noqa: BLE001  (문항 하나 실패해도 계속)
        return {"id": item["id"], "question": item["question"], "status": "error",
                "error": f"{e.__class__.__name__}: {str(e)[:300]}", "units": [], "final": {"status": "error"}}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.agent.batch")
    ap.add_argument("--queries", required=True, help=".csv (id, question) 또는 .jsonl")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 RUNS_DIR/batch/<파일 이름>)")
    ap.add_argument("--today", default=str(date.today()))
    ap.add_argument("--no-answer", action="store_true", help="답변(HCX) 없이 분석·검색·View 까지만")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=1, help="동시 실행 문항 수 (HCX 429 가 잦으면 줄임)")
    ap.add_argument("--force", action="store_true", help="이미 끝난 문항도 다시")
    a = ap.parse_args(argv)

    from backend.core.config import RUNS_DIR
    items = load_questions(a.queries)[:a.limit] if a.limit else load_questions(a.queries)
    out_dir = Path(a.out) if a.out else Path(RUNS_DIR) / "batch" / Path(a.queries).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.json"
    done = {} if a.force or not path.exists() else {r["id"]: r for r in json.loads(path.read_text(encoding="utf-8"))
                                                    if r.get("status") != "error"}
    todo = [it for it in items if it["id"] not in done]
    print(f"[batch] {len(items)}문항 · 이미 끝남 {len(items) - len(todo)} · 실행 {len(todo)} → {path}", flush=True)

    def job(it):
        r = run_one(it, a.today, not a.no_answer)
        print(f"  {it['id']}: {r['status']}" + (f"  {r['error']}" if r.get("error") else ""), flush=True)
        return r

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for r in ex.map(job, todo):
            done[r["id"]] = r
            path.write_text(json.dumps([done[i["id"]] for i in items if i["id"] in done], ensure_ascii=False,
                                       indent=1, default=str), encoding="utf-8")
    print(f"완료 → {path}")
    return path


if __name__ == "__main__":
    main()
