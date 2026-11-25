"""지표 집계 → summary.json · report.md, 두 실행 비교 (criteria.md 5 · 6장)

  python -m eval.generator.report <runs.jsonl> --set core34 [--review review.csv] [--out DIR]
  python -m eval.generator.report <runs.jsonl> --v2 <데이터셋 경로>                  # isolated · m3_only 실행
  python -m eval.generator.report --compare A.verdicts.jsonl B.verdicts.jsonl      # 질문 단위 쌍 비교
분모가 0 인 지표는 N/A (0% 로 쓰지 않는다). source=adapter 로 추정한 지표는 따로 표시한다.
집계 키는 (dataset, dataset_version, condition, id). 한 파일에 조건이 섞여 있으면 조건별로 따로 보고한다.
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from eval.generator import trace
from eval.generator.verdict import ORDER, RunVerdict, condition_of, judge_file, load_questions_for, merge


def rate(ok: int, n: int):
    return None if n == 0 else round(ok / n, 4)


def fmt(x) -> str:
    return "N/A" if x is None else (f"{x * 100:.1f}%" if isinstance(x, float) else str(x))


def _metric(vs: list[RunVerdict], code: str, module: str | None = None, source: str | None = None):
    rows = [f for v in vs for f in v.findings if f["code"] == code and (module is None or f["module"] == module)
            and (source is None or f.get("source") == source)]
    decided = [f for f in rows if f["ok"] is not None]
    return {"ok": sum(1 for f in decided if f["ok"]), "n": len(decided), "unresolved": len(rows) - len(decided),
            "rate": rate(sum(1 for f in decided if f["ok"]), len(decided)),
            "adapter": sum(1 for f in rows if f.get("source") == "adapter")}


def split_by_condition(vs: list[RunVerdict]) -> dict[tuple[str, str, str], list[RunVerdict]]:
    out = defaultdict(list)
    for v in vs:
        out[(v.dataset, v.dataset_version, v.condition)].append(v)
    return dict(out)


def summarize(vs: list[RunVerdict], runs: list[dict] | None = None) -> dict:
    by = defaultdict(list)
    for v in vs:
        by[v.key()].append(v)               # [CHANGED] 이전: by[v.id] — 데이터셋 · 조건이 다른 같은 id 를 한 문항으로 합쳤다
    merged = [merge(x) for x in by.values()]
    n = len(merged)
    cnt = Counter(m["verdict"] for m in merged)
    ff = Counter(f for m in merged if m["verdict"] == "미달" for f in (m["first_failure"] or ["?"]))
    gen = {"M2", "M3", "M5", "M6", "QA"}
    tag_n = lambda t: sum(1 for m in merged if any(x.startswith(t) for x in m["tags"]))  # noqa: E731
    hold_runs = [v for v in vs if v.observed in ("hold", "partial") or any(s["observed"] != "value" for s in v.subs)]
    honest = [v for v in hold_runs if all(s["notified"] for s in v.subs if s["observed"] != "value")]
    secs = [v.seconds for v in vs if v.seconds is not None]
    sub_rows = [(v, s) for v in vs for s in v.subs]
    exp_hold = [s for _, s in sub_rows if s["expect"] == "hold" and s["expect_source"] != "a0"]
    exp_ans = [s for _, s in sub_rows if s["expect"] == "answer"]
    held_codes = [s for s in exp_hold if s["observed"] == "hold"]
    a0 = [v for v in vs if v.a0_expected not in ("n/a", "out_of_scope") and v.a0_observed != "n/a"]
    a0_tp = sum(1 for v in a0 if v.a0_expected.startswith("stop_") and v.a0_observed.startswith("stop_"))
    a0_fp = [v.id for v in a0 if v.a0_expected == "continue" and v.a0_observed.startswith("stop_")]
    a0_pos = sum(1 for v in a0 if v.a0_expected.startswith("stop_"))
    a0_stop = sum(1 for v in a0 if v.a0_observed.startswith("stop_"))
    det = defaultdict(lambda: Counter())
    for v in vs:
        for d in v.detectors:
            c = det[d["kind"]]
            c["warned"] += d["warned"]
            c["known_but_shipped"] += d["known_but_shipped"]
            if d["label"] is not None:
                c["tp"] += d["warned"] and d["label"]
                c["fp"] += d["warned"] and not d["label"]
                c["fn"] += (not d["warned"]) and d["label"]
    groups = defaultdict(Counter)
    for m_ in merged:
        groups[m_["group"] or "-"][m_["verdict"]] += 1
    out = {
        "questions": n, "runs": len(vs), "sources": dict(Counter(v.source for v in vs)),
        "conditions": sorted({"/".join(k[:3]) for k in by}),
        "input_hash_changed": [m_["id"] for m_ in merged if m_.get("input_hash_changed")],
        "by_group": {g: dict(c) for g, c in sorted(groups.items())},
        "e2e": {
            "pass": cnt["통과"], "hold": cnt["보류"], "fail": cnt["미달"],
            "pass_rate": rate(cnt["통과"], n), "hold_rate": rate(cnt["보류"], n), "fail_rate": rate(cnt["미달"], n),
            "fail_by_first_failure": dict(ff),
            "generator_fail": sum(1 for m in merged if m["verdict"] == "미달" and set(m["first_failure"]) & gen),
            "failed_to_contain": tag_n("failed_to_contain"), "silent_omission": tag_n("silent_omission"),
            "scope_error": tag_n("scope_error"), "needs_review": tag_n("needs_review"),
            "unstable": sum(1 for m in merged if m["unstable"]),
            "stability": rate(sum(1 for m in merged if not m["unstable"]), n) if any(len(x) > 1 for x in by.values()) else None,
            "answered_rate": rate(sum(1 for v in vs if v.observed in ("answer", "partial")), len(vs)),
            "honest_failure": rate(len(honest), len(hold_runs)),
            "method": dict(Counter(v.method for v in vs if v.method)),
            "latency": {"mean": round(statistics.mean(secs), 1) if secs else None,
                        "median": round(statistics.median(secs), 1) if secs else None, "max": max(secs) if secs else None},
            "hcx_calls": sum(v.hcx_calls for v in vs), "hcx_failed": sum(v.hcx_failed for v in vs),
            "exceptions": sum(v.exception for v in vs),
            "numeric_vs_semantic_gap": sum(1 for v in vs for f in v.findings if f["code"] == "binding" and f["ok"] is False),
        },
        "m2": {"chart_type": _metric(vs, "chart_type"), "measure": _metric(vs, "measure"),
               "coverage": {"ok": sum(1 for s in exp_ans if s["match"] == "matched"), "n": len(exp_ans),
                            "rate": rate(sum(1 for s in exp_ans if s["match"] == "matched"), len(exp_ans))},
               "extra_subs": sum(v.extra_subs for v in vs),
               "request_parse": _metric(vs, "request_parse"), "request_misparse": _metric(vs, "request_misparse")},
        "m3": {"plan_valid": _metric(vs, "plan_valid"), "operation": _metric(vs, "operation"),
               "operand": _metric(vs, "operand"), "execution": _metric(vs, "execution"),
               "hold_recall": {"ok": sum(1 for s in exp_hold if s["observed"] != "value" and s["completeness"] == "met"),
                               "n": len(exp_hold),
                               "rate": rate(sum(1 for s in exp_hold if s["observed"] != "value" and s["completeness"] == "met"), len(exp_hold))},
               "false_hold": {"bad": sum(1 for s in exp_ans if s["observed"] == "hold"), "n": len(exp_ans),
                              "rate": rate(sum(1 for s in exp_ans if s["observed"] == "hold"), len(exp_ans))},
               "hold_reason": {"ok": sum(1 for s in held_codes if not s.get("hold_reason_mismatch") and s["hold_codes"]
                                         and "unclassified" not in s["hold_codes"]),
                               "n": sum(1 for s in held_codes if s["hold_codes"] and "unclassified" not in s["hold_codes"]),
                               "unclassified": sum(1 for s in held_codes if not s["hold_codes"] or "unclassified" in s["hold_codes"])},
               "convertible_unit": tag_n("convertible_unit"),
               # [NEW] 입력 1행에 다시 집계한 계획 수 (판정은 raw 와 같게 통과, 계획 품질 지표)
               "degenerate_aggregate": sum(1 for v in vs for f in v.findings if f["code"] == "degenerate_aggregate")},
        "m5": {"render": _metric(vs, "render"), "fidelity": _metric(vs, "fidelity"), "spec_lint": _metric(vs, "spec_lint"),
               "fallback_rate": (lambda m: None if m["n"] == 0 else round(1 - m["rate"], 4))(_metric(vs, "fallback")),
               "render_skipped": _metric(vs, "render_skipped")["unresolved"]},
        "m6": {"first_pass": _metric(vs, "method"), "unresolved_placeholder": _metric(vs, "unresolved_placeholder"),
               "unsupported_number": _metric(vs, "unsupported_number"), "direction": _metric(vs, "direction"),
               "binding": _metric(vs, "binding"), "display_round": _metric(vs, "display_round"),
               "result_unit": _metric(vs, "result_unit"),
               "claim_unit": _metric(vs, "claim_unit"), "claim_sign": _metric(vs, "claim_sign"),
               "required_digits": _metric(vs, "required_digits"), "invisible_citation": _metric(vs, "invisible_citation"),
               "unsupported_causal": _metric(vs, "unsupported_causal"), "table_complete": _metric(vs, "table_complete"),
               "final_in_answer": _metric(vs, "final_in_answer"), "caveat": {
                   "projection": _metric(vs, "caveat_projection"), "missing_period": _metric(vs, "caveat_missing_period")},
               "chart_claim": _metric(vs, "m6_chart_claim")},
        "chart_request": {"outcome": _metric(vs, "request_outcome"), "combo": _metric(vs, "outcome_combo"),
                          "notice": _metric(vs, "notice"), "chart_mode": _metric(vs, "chart_mode"),
                          "share_denominator": _metric(vs, "share_denominator")},
        "qa": {"a0": {"positives": a0_pos, "stopped": a0_stop, "tp": a0_tp,
                      "precision": rate(a0_tp, a0_stop), "recall": rate(a0_tp, a0_pos), "blocked_answerable": a0_fp,
                      "n": len(a0)},
               "semantic": {k: {**dict(c), "precision": rate(c["tp"], c["tp"] + c["fp"]) if c["tp"] + c["fp"] >= 3 else None,
                                "recall": rate(c["tp"], c["tp"] + c["fn"]) if c["tp"] + c["fn"] >= 3 else None}
                            for k, c in det.items()}},
        "per_question": merged,
    }
    if runs:
        qa_status = Counter((trace.qa(r) or {}).get("status") or "n/a" for r in runs)
        out["qa"]["status"] = dict(qa_status)
        retries = [r for r in runs if (trace.qa(r) or {}).get("retries")]
        out["qa"]["retry_rate"] = rate(len(retries), len(runs))
        out["qa"]["stop_by_stage"] = dict(Counter((trace.qa(r) or {}).get("stopped_stage") for r in runs
                                                  if (trace.qa(r) or {}).get("stopped_at")))
    return out


def markdown(s: dict, title: str) -> str:
    e = s["e2e"]
    m = lambda d: f"{fmt(d['rate'])} ({d['ok']}/{d['n']}" + (f", 수동 {d['unresolved']}" if d.get("unresolved") else "") + \
        (f", 어댑터 {d['adapter']}" if d.get("adapter") else "") + ")"  # noqa: E731
    lines = [f"# {title}", "", f"- 질문 {s['questions']}개 · 실행 {s['runs']}회 · 출처 {s['sources']} · 조건 {s.get('conditions')}"]
    if s.get("input_hash_changed"):
        lines.append(f"- 경고: 회차마다 입력 해시가 다른 문항 {s['input_hash_changed']}")
    lines += ["",
             "## E2E", "", "| 지표 | 값 |", "|---|---|",
             f"| 통과 · 보류 · 미달 | {e['pass']} · {e['hold']} · {e['fail']} ({fmt(e['pass_rate'])} · {fmt(e['hold_rate'])} · {fmt(e['fail_rate'])}) |",
             f"| 미달의 First Failure | {e['fail_by_first_failure']} |",
             f"| Generator 귀책 미달 | {e['generator_fail']} |",
             f"| failed_to_contain · silent_omission · scope_error | {e['failed_to_contain']} · {e['silent_omission']} · {e['scope_error']} |",
             f"| 수동 판정 필요(needs_review) | {e['needs_review']} |",
             f"| 판정 안정성 · 불안정 | {fmt(e['stability'])} · {e['unstable']} |",
             f"| 응답률(값을 낸 회차) | {fmt(e['answered_rate'])} |",
             f"| 정직한 실패 | {fmt(e['honest_failure'])} |",
             f"| 답변 방식 | {e['method']} |",
             f"| 지연 평균 · 중앙 · 최대(초) | {e['latency']['mean']} · {e['latency']['median']} · {e['latency']['max']} |",
             f"| HCX 호출 · 실패 · 예외 | {e['hcx_calls']} · {e['hcx_failed']} · {e['exceptions']} |",
             f"| numeric_match=1 ∧ semantic_ok=0 | {e['numeric_vs_semantic_gap']} |", "",
             "## 모듈별", "", "| 모듈 | 지표 | 값 |", "|---|---|---|"]
    for mod, keys in (("m2", ["chart_type", "measure", "coverage", "request_parse", "request_misparse"]),
                      ("m3", ["plan_valid", "operation", "operand", "execution", "hold_recall"]),
                      ("m5", ["render", "fidelity", "spec_lint"]),
                      ("m6", ["first_pass", "final_in_answer", "binding", "claim_unit", "claim_sign", "required_digits",
                              "invisible_citation", "unsupported_causal", "table_complete", "display_round", "result_unit",
                              "direction", "unresolved_placeholder", "unsupported_number", "chart_claim"]),
                      ("chart_request", ["outcome", "combo", "notice", "chart_mode", "share_denominator"])):
        for k in keys:
            d = s[mod][k]
            if "rate" in d and "ok" in d:
                if k == "binding" and d["n"] == 0:
                    # 기대값에 좌표(binding)가 없으면 검증하지 않은 것이다. 100% 로 쓰지 않는다
                    lines.append(f"| {mod.upper()} | {k} | N/A (binding 기대 없음 · numeric_match 만 확인) |")
                elif d["n"] or d.get("unresolved"):
                    lines.append(f"| {mod.upper()} | {k} | {m(d)} |")
    m3 = s["m3"]
    lines += [f"| M3 | false_hold | {fmt(m3['false_hold']['rate'])} ({m3['false_hold']['bad']}/{m3['false_hold']['n']}) |",
              f"| M3 | hold_reason | {fmt(rate(m3['hold_reason']['ok'], m3['hold_reason']['n']))} "
              f"({m3['hold_reason']['ok']}/{m3['hold_reason']['n']}, 미분류 {m3['hold_reason']['unclassified']}) |",
              f"| M3 | convertible_unit (개선 후보) | {m3['convertible_unit']} |",
              f"| M3 | degenerate_aggregate (입력 1행 집계, 지표) | {m3.get('degenerate_aggregate', 0)} |",
              f"| M5 | fallback_rate | {fmt(s['m5']['fallback_rate'])} |", "",
              "## QA", "", f"- A0: {s['qa']['a0']}"]
    if "status" in s["qa"]:
        lines += [f"- 상태 분포(품질 지표 아님): {s['qa']['status']}", f"- 재시도율: {fmt(s['qa']['retry_rate'])}",
                  f"- 중단 단계: {s['qa']['stop_by_stage']}"]
    lines += ["", "| 내용 경고 | 경고 | 정밀도 | 재현율 | 알았지만 나감 |", "|---|---|---|---|---|"]
    for k, c in sorted(s["qa"]["semantic"].items()):
        lines.append(f"| {k} | {c.get('warned', 0)} | {fmt(c.get('precision'))} | {fmt(c.get('recall'))} | {c.get('known_but_shipped', 0)} |")
    if len(s.get("by_group") or {}) > 1:
        lines += ["", "## 묶음별 (전체 micro 평균은 내지 않는다)", "", "| 묶음 | 통과 | 보류 | 미달 |", "|---|---|---|---|"]
        for g, c in s["by_group"].items():
            lines.append(f"| {g} | {c.get('통과', 0)} | {c.get('보류', 0)} | {c.get('미달', 0)} |")
    if s.get("pairs"):
        lines += ["", "## 짝 문항", "", "| 짝 | 변형 · 문항 · 판정 |", "|---|---|"]
        for pid, rows in sorted(s["pairs"].items()):
            lines.append(f"| {pid} | {' / '.join(f'{r[0]} {r[1]} {r[2]}' for r in rows)} |")
    lines += ["", "## 질문별", "", "| 질문 | 묶음 | 판정 | 회차 | First Failure | 태그 |", "|---|---|---|---|---|---|"]
    for q in s["per_question"]:
        tags = ", ".join(t for t in q["tags"] if t not in ("no_viewset",))
        lines.append(f"| {q['id']} | {q.get('group') or ''} | {q['verdict']} | {' · '.join(q['runs'])} | {' '.join(q['first_failure'])} | {tags} |")
    return "\n".join(lines) + "\n"


def pair_table(s: dict, questions: dict) -> dict:
    """v2 짝 문항(P-denominator 등): 같은 짝의 변형별 판정"""
    verdict = {q["id"]: q["verdict"] for q in s["per_question"]}
    pairs = defaultdict(list)
    for qid, q in questions.items():
        pr = (q.v2 or {}).get("pair") if hasattr(q, "v2") else None
        if pr and qid in verdict:
            pairs[pr["id"]].append((pr.get("variant"), qid, verdict[qid]))
    return {k: sorted(v) for k, v in pairs.items()}


def compare(a_path, b_path) -> str:
    """질문 단위 쌍 비교. 회귀 = 이전 통과가 모든 회차 미달 / Generator 귀책 미달 증가 (criteria.md 6장)"""
    def load(p):
        by = defaultdict(list)
        for x in trace.load(p):
            v = RunVerdict(**x)
            by[v.key()].append(v)
        conds = {k[:3] for k in by}
        return {k[3]: merge(v) for k, v in by.items()}, conds
    (a, ca), (b, cb) = load(a_path), load(b_path)
    if ca != cb or len(ca) != 1:
        # [NEW] 조건이 다른 실행(live ↔ isolated, core34 ↔ v2)은 같은 문항이라도 입력이 달라 쌍 비교가 성립하지 않는다
        raise SystemExit(f"[compare] 조건이 다르거나 섞여 있어 비교하지 않는다: {sorted(ca)} ↔ {sorted(cb)}")
    hash_warn = [k for k in a if k in b and (a[k].get("input_hash_changed") or b[k].get("input_hash_changed"))]
    better = [k for k in a if k in b and ORDER[b[k]["verdict"]] > ORDER[a[k]["verdict"]]]
    worse = [k for k in a if k in b and ORDER[b[k]["verdict"]] < ORDER[a[k]["verdict"]]]
    regress = [k for k in a if k in b and a[k]["verdict"] == "통과" and all(r == "미달" for r in b[k]["runs"])]
    gen = {"M2", "M3", "M5", "M6", "QA"}
    gf = lambda d: sum(1 for v in d.values() if v["verdict"] == "미달" and set(v["first_failure"]) & gen)  # noqa: E731
    lines = ["| 구분 | 질문 |", "|---|---|", f"| 개선 | {' '.join(better) or '-'} |", f"| 악화 | {' '.join(worse) or '-'} |",
             f"| 회귀(통과 → 모든 회차 미달) | {' '.join(regress) or '-'} |",
             f"| Generator 귀책 미달 | {gf(a)} → {gf(b)} |",
             f"| 판정 | **{'회귀' if regress or gf(b) > gf(a) else '회귀 없음'}** |"]
    if hash_warn:
        lines.append(f"\n경고: 같은 조건 안에서 회차마다 입력 해시가 다른 문항 {' '.join(hash_warn)}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="?")
    ap.add_argument("--set", default="core34")
    ap.add_argument("--review")
    ap.add_argument("--out")
    ap.add_argument("--title")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--v2", help="v2 데이터셋 경로 (isolated · m3_only 실행 판정). 없으면 EVAL_V2_DIR")
    a = ap.parse_args(argv)
    if a.compare:
        print(compare(*a.compare))
        return
    vs = judge_file(a.runs, "v2" if a.v2 else a.set, a.review, v2_path=a.v2)
    qs = load_questions_for("v2" if a.v2 else a.set, a.v2)
    runs = trace.load(a.runs)
    base = Path(a.out or Path(a.runs).parent / (Path(a.runs).name.split(".")[0] + "_report"))
    groups = split_by_condition(vs)
    for cond, cvs in groups.items():
        out = base if len(groups) == 1 else base / "_".join(cond)
        out.mkdir(parents=True, exist_ok=True)
        crun = [r for r in runs if condition_of(r) == cond[2]]
        s = summarize(cvs, crun)
        s["pairs"] = pair_table(s, qs)
        (out / "verdicts.jsonl").write_text("\n".join(json.dumps(asdict(v), ensure_ascii=False, default=str) for v in cvs) + "\n",
                                            encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / "report.md").write_text(markdown(s, (a.title or Path(a.runs).stem) + ("" if len(groups) == 1 else f" — {'/'.join(cond)}")),
                                       encoding="utf-8")
        _review_sheet(cvs, out / "review.csv")
        print("wrote", out)


def _review_sheet(vs: list[RunVerdict], path: Path):
    """수동 판정 시트 (method.md 3.2). 자동 결과를 채워 두고 사람은 verdict · first_failure · slot · faithfulness · tags · note 만 쓴다"""
    import csv
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "run", "auto_verdict", "auto_first_failure", "needs_review", "auto_issues",
                    "verdict", "first_failure", "slot", "faithfulness", "tags", "note"])
        for v in vs:
            issues = "; ".join(f"{x['code']}:{x['message'][:60]}" for x in v.findings
                               if x["stage"] in ("stage1", "stage2") and x["ok"] is not True)
            w.writerow([v.id, v.run, v.verdict, " ".join(v.first_failure), "needs_review" in v.tags, issues, "", "", "", "", "", ""])


if __name__ == "__main__":
    main()
