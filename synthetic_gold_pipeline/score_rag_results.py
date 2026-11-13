"""기존 RAG 실행 결과(eval/pipeline_review/review_v4.py 의 results.json)를 Synthetic Golden Set 으로 채점한다.

기존 코드는 읽기만 한다 (import 하지 않음, 결과 파일만 읽음). 출력은 synthetic_gold_pipeline/outputs/reports/rag_eval/ 아래.

흐름
  1) 기존 도구로 RAG 실행 (질문 CSV 경로를 그대로 넘기면 같은 폴더의 *_answers_references.csv 를 짝지어 읽음)
       python eval/pipeline_review/review_v4.py run --queries synthetic_gold_pipeline/outputs/datasets/synthetic_gold_queries.csv
       (수치 답변까지 채점하려면 --answer — 문항당 HCX 1회 추가)
  2) 채점
       python -m synthetic_gold_pipeline.score_rag_results \
           --rag-results storage/eval_runs/synthetic_gold_queries__v4/results.json

채점 기준
  - 표 기준 (M3): 필수 근거 그룹마다 '그룹의 허용 표(대체 표 포함)' 가 어느 검색 단위의 top-K 에 있는가
      Table_Any_Hit@K(하나라도) · Table_All_Hit@K(모든 그룹) · Table_Coverage@K · Table_MRR
      조사명 일치는 Hit 로 세지 않는다.
  - 좌표 기준 (M2): RAG View 의 source 좌표(표·항목·시점·분류 코드)가 그룹의 필수 원본 좌표를 모두 포함하는가
      (RAG View ID 와 합성 View ID 는 서로 달라 ID 로 비교하지 않음)
      View_All_Hit(만든 View 전체) · Final_Context_All_Hit(최종 문맥 View)
  - 쿼리 분석 (M1): 시점·지역 조건 추출 일치
  - 답변: results 에 answer 가 있으면 Evaluation Tool 로 수치·단위·중간값 정확도, 답변 불가 정확도
  - 단계별 최초 실패 + 추정 근본 원인, 공식(-O) vs 일상어(-P) 비교 (같은 dataset_id 끼리)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from synthetic_gold_pipeline.schemas.dataset import GoldenRecord
from synthetic_gold_pipeline.tools.evaluation_tool import evaluate_generation, is_abstention
from synthetic_gold_pipeline.utils import (PACKAGE_ROOT, REPO_ROOT, atomic_write_json, display_path, ensure_inside, now_iso,
                                           read_jsonl, resolve_path)

DEFAULT_DATASET = PACKAGE_ROOT / "outputs" / "datasets" / "synthetic_gold_dataset.jsonl"
DEFAULT_OUT = PACKAGE_ROOT / "outputs" / "reports" / "rag_eval"
REGION_SUFFIX = re.compile(r"(특별자치시|특별자치도|특별시|광역시|자치시|자치도)$")


# ── 입력 ────────────────────────────────────────────────────────────
def load_rag_results(path: str | Path) -> dict[str, dict]:
    p = Path(path)
    if p.is_dir():
        p = p / "results.json" if (p / "results.json").exists() else p
    if p.is_dir():                                      # json/<id>.json 폴더
        out = {}
        for f in sorted(p.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out[d["id"]] = d
        return out
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = list(data.values())
    return {d["id"]: d for d in data}


def load_dataset(path: str | Path) -> dict[str, tuple[GoldenRecord, str]]:
    """질문 ID → (레코드, 'original'|'paraphrased')"""
    out = {}
    for d in read_jsonl(path):
        rec = GoldenRecord.model_validate(d)
        for kind, qid in rec.question_ids.items():
            out[qid] = (rec, kind)
    return out


# ── 좌표 포함 판정 ──────────────────────────────────────────────────
def _codes_of(dsel: Any) -> set[str] | None:
    """RAG source.dims 의 한 분류 → 코드 집합 (None = 제한 없음, 'UNKNOWN' 은 깊이로만 지정되어 확인 불가)."""
    if dsel is None:
        return None
    if isinstance(dsel, dict):
        if "codes" in dsel:
            return {str(c) for c in dsel["codes"]}
        return {"__UNKNOWN__"}
    if isinstance(dsel, (list, tuple)):
        return {str(c) for c in dsel}
    return {str(dsel)}


def view_covers(view: dict, coord) -> bool:
    """RAG View(review_v4 _slim_view 형식) 가 원본 좌표 하나를 포함하는가."""
    src = view.get("source") or {}
    tbl = src.get("tbl_id") or view.get("tbl_id")
    if tbl != coord.TBL_ID:
        return False
    itm = src.get("itm_id")
    itms = {str(x) for x in (itm if isinstance(itm, (list, tuple)) else [itm])} if itm else None
    if itms is not None and coord.ITM_ID not in itms:
        return False
    per = src.get("period") or {}
    want = re.sub(r"\D", "", coord.PRD_DE)
    if isinstance(per, dict) and per.get("in"):
        have = {re.sub(r"\D", "", str(x)) for x in per["in"]}
        if want not in have and want[:4] not in have:          # 기존 View 는 월·분기 자료도 연도로 기간을 적음
            return False
    elif isinstance(per, dict) and (per.get("from") or per.get("to")):
        lo, hi = re.sub(r"\D", "", str(per.get("from") or "0")), re.sub(r"\D", "", str(per.get("to") or "9999"))
        if not (lo[:4] <= want[:4] <= hi[:4]):
            return False
    dims = {str(k).upper(): v for k, v in (src.get("dims") or {}).items()}
    for lv, code in coord.dims.items():
        codes = _codes_of(dims.get(lv.upper()))
        if codes is None:
            continue
        if "__UNKNOWN__" in codes or code not in codes:
            return False
    return True


def group_coords(rec: GoldenRecord) -> dict[str, list]:
    by_fact = {f.fact_id: f.coordinate for f in rec.generation_eval.intermediate_facts}
    return {gid: [by_fact[f] for f in g.required_fact_ids if f in by_fact]
            for gid, g in rec.retrieval_eval.required_evidence_groups.items()}


def views_cover_group(views: list[dict], coords: list) -> bool:
    """그룹의 필수 좌표를 (여러 View 에 나눠서라도) 모두 포함하는가."""
    return bool(coords) and all(any(view_covers(v, c) for v in views) for c in coords)


# ── 문항 1개 채점 ────────────────────────────────────────────────────
def _norm_region(x: str) -> str:
    return REGION_SUFFIX.sub("", re.sub(r"\s+", "", str(x)))


def query_check(rec: GoldenRecord, res: dict) -> dict[str, Any]:
    q = (res.get("stages") or {}).get("query") or {}
    slots = q.get("slots") or []
    got_p = {re.sub(r"\D", "", str(s.get("value") or s.get("raw") or ""))[:6] for s in slots if s.get("slot") == "시점"}
    got_r = {_norm_region(s.get("value") or s.get("raw") or "") for s in slots if s.get("slot") == "지역"}
    f = rec.module_eval.M1.expected_filters
    want_p = {re.sub(r"\D", "", str(p))[:4] for p in f.get("periods") or []}
    want_r = {_norm_region(r) for r in f.get("regions") or []}
    if not slots:
        return {"query_checked": False, "query_ok": None, "query_detail": "슬롯 기록 없음"}
    p_ok = not want_p or all(any(g.startswith(w) for g in got_p) for w in want_p)
    r_ok = not want_r or want_r <= got_r
    miss = ([f"시점 {sorted(want_p)}≠{sorted(got_p)}"] if not p_ok else []) + \
        ([f"지역 {sorted(want_r - got_r)} 누락"] if not r_ok else [])
    return {"query_checked": True, "query_ok": p_ok and r_ok, "query_detail": "; ".join(miss)}


def table_hits(rec: GoldenRecord, res: dict, ks: tuple[int, ...]) -> dict[str, Any]:
    groups = rec.retrieval_eval.required_evidence_groups
    gtabs = {gid: {t.split("_", 1)[1] if re.match(r"^\d+_", t) else t for t in g.acceptable_table_ids}
             for gid, g in groups.items()}
    units = res.get("units") or []
    out: dict[str, Any] = {"n_groups": len(groups), "n_units": len(units)}
    best_rank: dict[str, int | None] = {}
    for gid, tabs in gtabs.items():
        ranks = [c["rank"] for u in units for c in u.get("candidates") or [] if c.get("tbl_id") in tabs]
        best_rank[gid] = min(ranks) if ranks else None
    for k in ks:
        sat = [r is not None and r <= k for r in best_rank.values()]
        out[f"Table_Any_Hit@{k}"] = float(any(sat)) if sat else None
        out[f"Table_All_Hit@{k}"] = float(all(sat)) if sat else None
        out[f"Table_Coverage@{k}"] = sum(sat) / len(sat) if sat else None
    firsts = [r for r in best_rank.values() if r is not None]
    out["Table_MRR"] = 1 / min(firsts) if firsts else 0.0
    out["group_best_rank"] = best_rank
    return out


def view_hits(rec: GoldenRecord, res: dict) -> dict[str, Any]:
    gc = group_coords(rec)
    views = [v for u in res.get("units") or [] for v in u.get("views") or []]
    final_ids = set((res.get("final") or {}).get("records") or [])
    final = [v for v in views if v.get("record_id") in final_ids]
    built = {g: views_cover_group(views, c) for g, c in gc.items()}
    ctx = {g: views_cover_group(final, c) for g, c in gc.items()}
    raw_bad = [v for v in views if (v.get("raw") or {}).get("n") and (v.get("raw") or {}).get("ok", 0) < v["raw"]["n"]]
    return {"View_All_Hit": float(all(built.values())) if built else None,
            "View_Coverage": sum(built.values()) / len(built) if built else None,
            "Final_Context_All_Hit": float(all(ctx.values())) if ctx else None,
            "Final_Context_Coverage": sum(ctx.values()) / len(ctx) if ctx else None,
            "group_view_covered": built, "group_context_covered": ctx, "n_views": len(views), "n_final": len(final),
            "raw_value_mismatch_views": len(raw_bad)}


def asked_clarification(res: dict) -> bool:
    return bool((((res.get("stages") or {}).get("query") or {}).get("clarifications") or []))


def abstained(res: dict) -> bool:
    if (res.get("final") or {}).get("status") in ("out_of_scope", "needs_clarification"):
        return True
    a = res.get("answer") or {}
    return bool(a.get("insufficient")) or is_abstention(a.get("answer") or "")


def diagnose(rec: GoldenRecord, res: dict, q: dict, th: dict, vh: dict, gen: dict | None, k: int) -> tuple[str | None, str | None]:
    """관찰된 최초 실패 단계 + 추정 근본 원인."""
    if res.get("error"):
        return "PIPELINE_ERROR", "PIPELINE_ERROR"
    if rec.generation_eval.expected_abstention:
        if rec.answerability_type.value == "AMBIGUOUS" and asked_clarification(res):
            return None, None                            # 되묻기 = 기대 동작
        if gen is None and not abstained(res):
            return "INSUFFICIENT_TRACE", "INSUFFICIENT_TRACE"   # 답변 단계를 돌리지 않아 판정 불가 (--answer 필요)
        return (None, None) if abstained(res) else ("ABSTENTION_ERROR", "ABSTENTION_ERROR")
    q_bad = q.get("query_ok") is False
    stage = None
    if (res.get("final") or {}).get("status") in ("out_of_scope", "needs_clarification") and not res.get("units"):
        stage = "QUERY_CONDITION_ERROR"
    elif th.get(f"Table_Any_Hit@{k}") == 0.0:
        stage = "RETRIEVAL_MISS"
    elif th.get(f"Table_All_Hit@{k}") == 0.0:
        stage = "PARTIAL_RETRIEVAL"
    elif vh.get("raw_value_mismatch_views"):
        stage = "VALUE_MISMATCH"
    elif vh.get("View_All_Hit") == 0.0:
        stage = "VIEW_CONDITION_ERROR"
    elif vh.get("Final_Context_All_Hit") == 0.0:
        stage = "FINAL_CONTEXT_MISS"
    elif gen is None:
        return None, None                                # 답변을 돌리지 않음 — 문맥까지는 정상
    elif gen.get("Numeric_Accuracy") == 0.0:
        stage = "CALCULATION_ERROR" if gen.get("Intermediate_Fact_Accuracy") == 1.0 else "ANSWER_GENERATION_ERROR"
    elif gen.get("Abstention_Accuracy") == 0.0:
        stage = "ABSTENTION_ERROR"
    if stage is None:
        return (("QUERY_CONDITION_ERROR", "QUERY_CONDITION_ERROR") if q_bad else (None, None))
    root = "QUERY_CONDITION_ERROR" if q_bad and stage in ("RETRIEVAL_MISS", "PARTIAL_RETRIEVAL", "VIEW_CONDITION_ERROR") else stage
    if q_bad and stage == "QUERY_CONDITION_ERROR":
        root = stage
    return stage, root


def score_one(qid: str, rec: GoldenRecord, kind: str, res: dict | None, ks: tuple[int, ...], diag_k: int) -> dict[str, Any]:
    row: dict[str, Any] = {"id": qid, "dataset_id": rec.dataset_id, "variant": kind, "reasoning_type": rec.reasoning_type.value,
                           "subtype": rec.subtype, "hop_type": rec.hop_type.value if rec.hop_type else None,
                           "answerability": rec.answerability_type.value,
                           "question": rec.question_original if kind == "original" else rec.question_paraphrased}
    if res is None:
        row.update(ran=False, first_failure="NOT_RUN", root_cause="NOT_RUN")
        return row
    row["ran"] = True
    q = query_check(rec, res) if not rec.generation_eval.expected_abstention else \
        {"query_checked": False, "query_ok": None, "query_detail": "답변 불가 유형 — 조건 추출 채점 안 함"}
    row.update(q)
    gen = None
    if rec.generation_eval.expected_abstention:
        row["retrieval_eligible"] = rec.retrieval_eval.retrieval_eligible
        th, vh = {}, {}
        if res.get("answer") is not None or (res.get("final") or {}).get("status") in ("out_of_scope", "needs_clarification"):
            row["Abstention_Accuracy"] = float(abstained(res))
            gen = {"Abstention_Accuracy": row["Abstention_Accuracy"]}
        if rec.answerability_type.value == "AMBIGUOUS":
            row["Clarification_Asked"] = float(asked_clarification(res))
    else:
        th, vh = table_hits(rec, res, ks), view_hits(rec, res)
        row.update({k: v for k, v in th.items() if k not in ("group_best_rank",)})
        row.update({k: v for k, v in vh.items() if k not in ("group_view_covered", "group_context_covered")})
        row["group_best_rank"] = json.dumps(th["group_best_rank"], ensure_ascii=False)
        if res.get("answer") is not None:
            text = (res.get("answer") or {}).get("answer") or ""
            g = evaluate_generation(rec, text, abstained=abstained(res))
            gen = {k: v for k, v in g.items() if k != "numeric_check" and not isinstance(v, dict)}
            row.update({f"ans_{k}": v for k, v in gen.items()})
            row["answer_text"] = text[:500]
    stage, root = diagnose(rec, res, q, th, vh, gen, diag_k)
    row.update(first_failure=stage, root_cause=root, rag_error=res.get("error"))
    return row


# ── 집계 ────────────────────────────────────────────────────────────
def _mean(xs):
    xs = [float(x) for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return round(sum(xs) / len(xs), 4) if xs else None


def summarize(rows: list[dict], ks: tuple[int, ...]) -> dict[str, Any]:
    df = pd.DataFrame(rows)
    ran = df[df["ran"]] if "ran" in df else df
    metric_cols = [c for c in df.columns if re.match(r"^(Table_|View_|Final_Context_|ans_|Abstention_|Clarification_)", c)
                   or c == "query_ok"]
    def block(d):
        return {"n": int(len(d)), **{c: _mean(d[c].tolist()) for c in metric_cols if c in d}}
    out = {"n_questions": int(len(df)), "n_ran": int(len(ran)), "n_not_run": int(len(df) - len(ran)),
           "overall": block(ran),
           "by_variant": {k: block(g) for k, g in ran.groupby("variant")},
           "by_reasoning_type": {k: block(g) for k, g in ran.groupby("reasoning_type")},
           "by_hop_type": {str(k): block(g) for k, g in ran.groupby(ran["hop_type"].fillna("NONE"))},
           "first_failure": dict(Counter(ran["first_failure"].fillna("NONE"))),
           "root_cause": dict(Counter(ran["root_cause"].fillna("NONE")))}
    return out


def compare_variants(rows: list[dict], key: str) -> tuple[pd.DataFrame, dict]:
    """같은 dataset_id 의 공식(-O) vs 일상어(-P) 결과 → 쿼리 변환 영향 분리."""
    by = defaultdict(dict)
    for r in rows:
        if r.get("ran") and r.get(key) is not None:
            by[r["dataset_id"]][r["variant"]] = r
    out = []
    for did, d in by.items():
        if "original" not in d or "paraphrased" not in d:
            continue
        o, p = d["original"][key] >= 1.0, d["paraphrased"][key] >= 1.0
        cat = ("BOTH_PASS" if o and p else "ORIGINAL_ONLY (쿼리 변환 의심)" if o else
               "PARAPHRASED_ONLY" if p else "BOTH_FAIL (검색·View·답변 쪽)")
        out.append({"dataset_id": did, "metric": key, "original": d["original"][key], "paraphrased": d["paraphrased"][key],
                    "category": cat, "reasoning_type": d["original"]["reasoning_type"],
                    "original_first_failure": d["original"].get("first_failure"),
                    "paraphrased_first_failure": d["paraphrased"].get("first_failure"),
                    "question_original": d["original"]["question"], "question_paraphrased": d["paraphrased"]["question"]})
    df = pd.DataFrame(out)
    return df, (dict(Counter(df["category"])) if len(df) else {})


def run(rag_results: str | Path, dataset: str | Path = DEFAULT_DATASET, out_dir: str | Path | None = None,
        ks: tuple[int, ...] = (1, 3, 5, 10), diag_k: int = 5, variants: str = "all") -> dict[str, Any]:
    res = load_rag_results(rag_results)
    ds = load_dataset(dataset)
    ids = [q for q in ds if variants == "all" or ds[q][1] == variants]
    rows = [score_one(q, ds[q][0], ds[q][1], res.get(q), ks, diag_k) for q in ids]
    unknown = sorted(set(res) - set(ds))
    name = Path(rag_results).resolve().parent.name if Path(rag_results).is_file() else Path(rag_results).resolve().name
    out = Path(out_dir) if out_dir else DEFAULT_OUT / name
    if not out_dir:
        ensure_inside(out, PACKAGE_ROOT / "outputs")
    out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "per_question.csv", index=False, encoding="utf-8-sig")
    summary = summarize(rows, ks)
    cmp_key = f"Table_All_Hit@{diag_k}"
    cmp_df, cmp_sum = compare_variants(rows, cmp_key)
    cmp_df.to_csv(out / "original_vs_paraphrased.csv", index=False, encoding="utf-8-sig")
    ans_key = "ans_Numeric_Accuracy"
    ans_df, ans_sum = compare_variants(rows, ans_key) if ans_key in df else (pd.DataFrame(), {})
    if len(ans_df):
        ans_df.to_csv(out / "original_vs_paraphrased_answer.csv", index=False, encoding="utf-8-sig")
    summary.update({
        "generated_at": now_iso(), "rag_results": display_path(rag_results), "dataset": display_path(dataset), "ks": list(ks),
        "diagnosis_k": diag_k, "original_vs_paraphrased": {"metric": cmp_key, **cmp_sum},
        "original_vs_paraphrased_answer": {"metric": ans_key, **ans_sum} if ans_sum else None,
        "answer_scored": ans_key in df, "unknown_result_ids": unknown[:50],
        "notes": ["표 Hit 는 필수 근거 그룹의 허용 표(대체 표 포함) 기준 — 조사명 일치는 Hit 아님",
                  "View Hit 는 RAG View 의 source 좌표가 필수 원본 좌표를 모두 포함하는지로 판정 (View ID 비교 아님)",
                  "대체 Positive 가 다른 표인 경우 좌표 판정은 원래 근거 표 좌표 기준이라 보수적으로 낮게 나올 수 있음"]})
    atomic_write_json(out / "summary.json", summary)
    summary["output_dir"] = display_path(out)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAG 실행 결과(review_v4 results.json)를 Synthetic Golden Set 으로 채점")
    ap.add_argument("--rag-results", required=True, help="results.json 또는 그 폴더 (예: storage/eval_runs/synthetic_gold_queries__v4)")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET), help="synthetic_gold_dataset.jsonl")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 synthetic_gold_pipeline/outputs/reports/rag_eval/<실행 이름>)")
    ap.add_argument("--k", default="1,3,5,10")
    ap.add_argument("--diag-k", type=int, default=5, help="실패 진단·O/P 비교에 쓸 K")
    ap.add_argument("--variants", choices=["all", "original", "paraphrased"], default="all")
    a = ap.parse_args(argv)
    rr = resolve_path(a.rag_results, REPO_ROOT)
    if not rr or not rr.exists():
        print(f"[중단] RAG 결과 없음: {a.rag_results}", file=sys.stderr)
        return 2
    s = run(rr, resolve_path(a.dataset, REPO_ROOT), resolve_path(a.out) if a.out else None,
            tuple(int(x) for x in a.k.split(",")), a.diag_k, a.variants)
    print(json.dumps({k: s[k] for k in ("n_questions", "n_ran", "overall", "by_variant", "first_failure",
                                        "original_vs_paraphrased", "output_dir")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
