"""실행 레코드(RunRecord) 읽기. 새 실행(run.py, source=full)과 과거 slim trace(legacy.py, source=legacy)를 같은 접근자로 읽는다

RunRecord (dict, JSON 한 줄)
  id · set · run · mode(live|replay|oracle) · path(qa|modules) · question · ok · error · source(full|legacy)
  analysis · viewset(full 만) · records(정규화한 Record 목록) · modules(run_modules 반환 11개 키 + qa)
  requests{m3, m6}(full 만, Module3Request · Module6Request 전체) · result(사용자에게 나간 최종 응답)
  timings · seconds · hcx_calls · qa_timing · manifest_id
"""
import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

VALUE_COL = "값"


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def iter_jsonl(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for x in f:
            if x.strip():
                yield json.loads(x)


def table(rec: dict) -> tuple[list[str], list[list[Any]]]:
    """Record(전체 스키마) · slim Record({id, columns, rows}) 모두"""
    if "table" in rec:
        t = rec["table"] or {}
        return list(t.get("columns") or []), list(t.get("rows") or [])
    return list(rec.get("columns") or []), list(rec.get("rows") or [])


def truncated(rec: dict) -> bool:
    """slim trace 는 행을 400개로 잘랐다 (run_modules36._slim)"""
    n = rec.get("n_rows")
    return n is not None and n > len(table(rec)[1])


def value_index(columns: list[str]) -> int:
    return columns.index(VALUE_COL) if VALUE_COL in columns else len(columns) - 1


def records_of(run: dict) -> list[dict]:
    if run.get("records") is not None:
        return run["records"]
    vs = run.get("viewset") or {}
    if vs.get("records") is not None:
        return vs["records"]
    return (run.get("modules") or {}).get("records") or []


def mods(run: dict) -> dict:
    return run.get("modules") or {}


def m3(run: dict) -> dict:
    return mods(run).get("module3") or {}


def m6(run: dict) -> dict:
    return mods(run).get("answer") or {}


def qa(run: dict) -> dict:
    return mods(run).get("qa") or {}


def answer_text(run: dict) -> str:
    return ((run.get("result") or {}).get("answer") or "").strip()


def user_caveats(run: dict) -> list[str]:
    return [c if isinstance(c, str) else (c or {}).get("text", "") for c in (run.get("result") or {}).get("caveats") or []]


def bundle(run: dict) -> dict:
    """QueryBundle 모양 (view_bundle). slim trace 는 analysis 요약만 있다"""
    vs = run.get("viewset") or {}
    if vs.get("view_bundle"):
        return vs["view_bundle"]
    a = run.get("analysis") or {}
    vb = a.get("view_bundle") or {}
    if vb:
        return vb
    return {"query_id": (m3(run) or {}).get("query_id"), "original": run.get("question"),
            "sub_questions": a.get("sub_questions") or [], "filters": a.get("filters"),
            "sub_filters": a.get("sub_filters")}


def sub_question_list(run: dict) -> list[tuple[str, str]]:
    """[(하위 질문 ID, 문장)] — chart_calculate.planner.sub_question_ids 와 같은 규칙 ('{query_id}-{순번}')"""
    b = bundle(run)
    qid = b.get("query_id") or (m3(run) or {}).get("query_id") or "q"
    subs = b.get("sub_questions") or [b.get("original") or run.get("question") or ""]
    return [(f"{qid}-{i}", s) for i, s in enumerate(subs, 1)]


def analysis_status(run: dict) -> str | None:
    return (run.get("analysis") or {}).get("status")
