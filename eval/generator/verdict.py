"""질문 단위 판정 (criteria.md 3장)

0단계 범위(scope 고정값) → (A0 중단) → 1단계 출력 정확성(상태와 무관하게 출력한 모든 내용) → 2단계 완전성
판정: 1단계 실패 = 미달 / 2단계 미충족 = 보류 / 그 밖 = 통과. 자동 판정이 None 인 항목은 needs_review 태그로 수동 판정에 넘긴다.
회차 병합: 낮은 판정 (미달 < 보류 < 통과), 회차 판정이 다르면 unstable.

  python -m eval.generator.verdict <runs.jsonl> --set core34 [--review review.csv] [--out verdicts.jsonl]
"""
import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.generator import QUESTIONS_DIR, trace
from eval.generator.checks import chart_request, m2, m3, m5, m6, qa_semantic
from eval.generator.findings import Finding, failed, unresolved
from eval.generator.schema import Question, load_set
from eval.generator.status import expectations, question_expect
from eval.generator.subq import match

ORDER = {"미달": 0, "보류": 1, "통과": 2}
FF_ORDER = ["M1+R", "M2", "M3", "M5", "M6", "QA", "data"]
SETS = {"core34": "core34.yaml", "ext-chart-request": "ext_chart_request.yaml"}
# [NEW] pipeline 이 Generator 앞에서 반환하는 상태 → 그 상태가 맞는 v2 보류 사유
PIPELINE_HOLD = {"needs_selection": {"unresolved_conflict"}, "needs_clarification": {"missing_conversation_context"}}


@dataclass
class RunVerdict:
    id: str
    run: int
    verdict: str
    expected: str
    observed: str
    a0_expected: str
    a0_observed: str
    first_failure: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    subs: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    detectors: list[dict] = field(default_factory=list)
    extra_subs: int = 0
    seconds: float | None = None
    method: str | None = None
    hcx_calls: int = 0
    hcx_failed: int = 0
    exception: bool = False
    source: str = "full"
    # [NEW] 집계 키 (dataset, dataset_version, condition, id). 과거 RunRecord 에 없으면 core34 · 1.0 · live
    dataset: str = "core34"
    dataset_version: str = "1.0"
    condition: str = "live"
    input_hash: str | None = None
    group: str = ""

    def key(self) -> tuple[str, str, str, str]:
        return (self.dataset, self.dataset_version, self.condition, self.id)


def load_questions(name_or_path: str):
    p = Path(name_or_path)
    return load_set(p if p.suffix in (".yaml", ".yml") else QUESTIONS_DIR / SETS[name_or_path])


def _observed_state(subres) -> str:
    obs = {s.observed for s in subres}
    if not obs:
        return "none"
    if obs == {"value"}:
        return "answer"
    if "value" in obs:
        return "partial"
    return "hold"


def condition_of(run: dict) -> str:
    """실행 조건. 과거 RunRecord 는 condition 이 없어 mode(live · replay · oracle_*)로 채운다"""
    if run.get("condition"):
        return run["condition"]
    mode = run.get("mode") or "live"
    return "oracle" if str(mode).startswith("oracle") else mode


def judge(q: Question, run: dict, review: dict | None = None) -> RunVerdict:
    base = dict(id=q.id, run=run.get("run", 1), seconds=run.get("seconds"), source=run.get("source", "full"),
                method=trace.m6(run).get("method"), hcx_calls=len(run.get("hcx_calls") or []),
                hcx_failed=sum(1 for c in run.get("hcx_calls") or [] if not c.get("ok", True)),
                dataset=run.get("dataset") or q.dataset, dataset_version=run.get("dataset_version") or q.dataset_version,
                condition=condition_of(run), input_hash=run.get("input_hash"), group=q.group)
    fs: list[Finding] = []
    tags: list[str] = []
    if not run.get("ok", True):
        return _finish(RunVerdict(**base, verdict="미달", expected="?", observed="exception", a0_expected="?",
                                  a0_observed="?", first_failure=["QA"], tags=["exception"], exception=True), review)
    a_status = trace.analysis_status(run)
    # ── 0단계: 범위 ──
    if q.scope == "out":
        # [CHANGED] 이전: analysis 가 out_of_scope 이거나 모듈 출력이 없을 때만 범위 밖 처리.
        # v2 격리 입력은 범위 밖 판단이 ViewSet status 로 들어와 A0 에서 멈춘다 → 수치 없이 멈췄으면 범위 밖 처리로 본다
        stopped = qa_semantic.a0_observed(run).startswith("stop_") and not m6.has_any_value(run)
        stat = "out_of_scope" if a_status == "out_of_scope" or not trace.mods(run) or stopped else "answered"
        if stat == "out_of_scope":
            g = qa_semantic.a0_guidance(q, run)
            v = RunVerdict(**base, verdict="보류" if any(f.ok is False for f in g) else "통과", expected="out_of_scope",
                           observed="out_of_scope", a0_expected="n/a", a0_observed="n/a",
                           tags=["no_viewset"] + (["guidance_mismatch"] if any(f.ok is False for f in g) else []),
                           findings=[f.as_dict() for f in g])
        else:
            v = RunVerdict(**base, verdict="미달", expected="out_of_scope", observed="answered", a0_expected="n/a",
                           a0_observed="n/a", first_failure=["M1+R"], tags=["scope_error:false_in"])
        return _finish(v, review)
    if run.get("pipeline_status") in PIPELINE_HOLD:
        # [NEW] Generator 앞에서 사용자 선택 · 되묻기 상태로 반환 (isolated 의 운영 pipeline 분기). 안내는 API 상태 자체다
        st = run["pipeline_status"]
        reasons = {s.answerable_when[0].hold_reason for s in q.sub_questions if s.answerable_when}
        ok = bool(reasons) and reasons <= PIPELINE_HOLD[st]
        v = RunVerdict(**base, verdict="통과" if ok else "보류", expected="hold", observed=st, a0_expected="n/a",
                       a0_observed="n/a", tags=["skipped:pipeline_status"] + ([] if ok else ["pipeline_status_mismatch"]),
                       findings=[Finding("pipeline_status", "stage2", "QA", ok, f"상태 {st} / 기대 사유 {sorted(r or '' for r in reasons)}").as_dict()])
        return _finish(v, review)
    if a_status in ("out_of_scope", "needs_clarification") or (not trace.mods(run) and not trace.records_of(run)):
        bad = m6.bad_tokens(trace.answer_text(run))
        v = RunVerdict(**base, verdict="미달" if bad else "보류", expected="?", observed=a_status or "no_modules",
                       a0_expected="n/a", a0_observed="n/a", first_failure=["M1+R"],
                       tags=["scope_error:false_out", "skipped:no_viewset"])
        return _finish(v, review)
    a0_exp, sub_exps = expectations(q, run)
    a0_obs = qa_semantic.a0_observed(run)
    exp_by = {e.key: e for e in sub_exps}
    subres, extra = match(q, run)
    res_by = {r.key: r for r in subres}
    if a0_obs.startswith("stop_"):
        tags.append("skipped:qa_a0_stop")
        for r in subres:
            r.observed, r.notified = "hold", bool(trace.answer_text(run))
        fs += qa_semantic.a0_guidance(q, run)          # [NEW] v2: 멈춘 이유에 맞는 안내인가 (2단계)
    # ── 1단계: 출력 정확성 ──
    # [NEW] m3_only: 모듈 3 단독 실행 (최종 답변 · 차트 렌더링 없음) → 모듈 3 항목만 본다
    m3_only = run.get("condition") == "m3_only"
    if not m3_only:
        fs += m6.text_checks(run) + m6.causal_checks(q, run)
    if m3_only and not a0_obs.startswith("stop_"):
        fs += m3.unit_semantic(run) + m3.asked_indicator(q, run)
        for s in q.sub_questions:
            e, r = exp_by[s.key], res_by[s.key]
            fs += m3.check(s, e, r, run)
            if e.expect == "hold" and r.observed == "value":
                fs.append(Finding("hold_but_value", "stage1", "M3", m3.hold_grounded(r, run, s), "", s.key))
    elif not a0_obs.startswith("stop_"):
        fs += m6.display_checks(run) + m6.unit_checks(run) + m3.unit_semantic(run) + m3.asked_indicator(q, run) + m5.check(run) + m6.caveat_checks(q, run)
        fs += chart_request.check(q, run) + chart_request.mode_check(q, run) + m6.format_metrics(run) + m6.visibility_checks(q, run)
        for s in q.sub_questions:
            e, r = exp_by[s.key], res_by[s.key]
            fs += m2.check(s, e, r)
            fs += m3.check(s, e, r, run)
            if e.expect == "answer":
                fs += m6.value_checks(s, r, run)
            elif r.observed == "value":
                # 기대 hold 인데 값을 냄: 근거 없는 값 → 미달. 근거가 있으면(대체 시점 · 일부 기간) 고지했는지는 2단계에서 본다
                grounded = m3.hold_grounded(r, run, s)
                fs.append(Finding("hold_but_value", "stage1", "M3", grounded,
                                  "근거 있는 값 (rule_review)" if grounded else "근거 없는 값", s.key))
                if grounded:
                    tags += ["rule_review", "needs_review"]
    # ── 2단계: 완전성 ──
    sub_rows = []
    for s in q.sub_questions:
        e, r = exp_by[s.key], res_by[s.key]
        row = {"key": s.key, "sid": r.sid, "match": r.status, "expect": e.expect, "hold_reason": e.hold_reason,
               "observed": r.observed, "notified": r.notified, "hold_codes": r.hold_codes, "expect_source": e.source,
               "expect_tags": e.tags, "match_source": r.source}
        if m3_only:
            # 고지는 모듈 6 몫이다. 모듈 3 은 기대대로 값을 냈는가 · 보류했는가만 본다
            row["completeness"] = "met" if (r.observed == "value") == (e.expect == "answer") else "unmet_silent"
        elif e.expect == "answer":
            row["completeness"] = "met" if r.observed == "value" else ("unmet_notified" if r.notified else "unmet_silent")
        else:
            # 기대 hold: 보류 · 누락은 고지했으면 충족. 값을 냈으면(1단계에서 근거 확인) 요청과 다른 범위를 썼다는 고지가 있어야 충족
            row["completeness"] = "met" if r.notified else "unmet_silent"
            if r.observed == "hold" and e.hold_reason and e.source != "a0" and e.hold_reason not in r.hold_codes:
                row["hold_reason_mismatch"] = True
        if r.status == "ambiguous_match":
            tags.append("ambiguous_match")
        if "convertible_unit" in e.tags:
            tags.append("convertible_unit")
        if "status_unresolved" in e.tags or "manual" in e.tags:
            tags.append("status_unresolved")
        sub_rows.append(row)
        owner = "M3" if m3_only or r.observed == "hold" else ("M2" if r.out is None or not (r.out.calcs or r.out.charts) else "M6")
        fs.append(Finding("completeness", "stage2", owner, row["completeness"] == "met", row["completeness"], s.key))
    # ── 판정 ──
    st1 = failed(fs, "stage1")
    expected, observed = question_expect(q, sub_exps), _observed_state(subres)
    if st1:
        verdict = "미달"
    elif any(r["completeness"] != "met" for r in sub_rows):
        verdict = "보류"
        if any(r["completeness"] == "unmet_silent" for r in sub_rows):
            tags.append("silent_omission")
    elif q.strict_final and any(f.code == "final_in_answer" and f.ok is False for f in fs):
        verdict = "보류"                  # [NEW] v2: 계산은 됐는데 기대 claim 이 답변 문장에 없다 (J09 하위 질문 누락 · J03 숫자 없음)
        tags.append("final_missing")
    elif any(f.code == "a0_guidance" and f.ok is False for f in fs):
        verdict = "보류"                  # [NEW] v2: A0 에서 바르게 멈췄지만 안내가 멈춘 이유와 다르다 (B16 선택지 · C19 되묻기)
        tags.append("guidance_mismatch")
    else:
        verdict = "통과"
    if any(f.code.startswith("caveat_") and f.ok is False for f in fs):
        tags.append("failed_to_contain")
    if unresolved([f for f in fs if f.stage == "stage1"]):
        tags.append("needs_review")
    ff = _first_failure(fs, sub_rows, sub_exps, a0_exp, a0_obs)
    detectors = qa_semantic.detector_rows(run, set((review or {}).get("tags", "").split()), bool(st1))
    v = RunVerdict(**base, verdict=verdict, expected=expected, observed=observed, a0_expected=a0_exp, a0_observed=a0_obs,
                   first_failure=ff, tags=sorted(set(tags)), subs=sub_rows, findings=[f.as_dict() for f in fs],
                   detectors=detectors, extra_subs=len(extra))
    return _finish(v, review)


def _first_failure(fs, sub_rows, sub_exps, a0_exp, a0_obs) -> list[str]:
    mods = []
    if a0_exp != a0_obs and "n/a" not in (a0_exp, a0_obs):
        mods.append("QA")
    for r, e in zip(sub_rows, sub_exps):
        if e.expect == "hold" and e.source == "predicate" and r["completeness"] == "met":
            mods.append("M1+R")            # 기대 자체가 '자료 없음' → 앞 단계 원인으로 보류
    for f in failed(fs, "stage1") + failed(fs, "stage2"):
        mods.append(f.module if f.module != "E2E" else "M6")
    return sorted(set(mods), key=FF_ORDER.index) if mods else []


def _finish(v: RunVerdict, review: dict | None) -> RunVerdict:
    if not review:
        return v
    if review.get("verdict"):
        v.tags.append(f"override:{v.verdict}->{review['verdict']}")
        v.verdict = review["verdict"]
    if review.get("first_failure"):
        v.first_failure = review["first_failure"].split()
    for k in ("slot", "faithfulness"):
        if review.get(k) not in (None, ""):
            v.tags.append(f"{k}:{review[k]}")
    v.tags += [t for t in (review.get("tags") or "").split() if t]
    if "needs_review" in v.tags and review.get("verdict"):
        v.tags.remove("needs_review")
    return v


def merge(vs: list[RunVerdict]) -> dict:
    """같은 (dataset, version, condition, id) 의 회차 판정들 → 최종 판정"""
    worst = min(vs, key=lambda v: ORDER[v.verdict])
    hashes = {v.input_hash for v in vs if v.input_hash}
    return {"id": worst.id, "dataset": worst.dataset, "dataset_version": worst.dataset_version, "condition": worst.condition,
            "group": worst.group, "input_hash_changed": len(hashes) > 1, "verdict": worst.verdict, "runs": [v.verdict for v in sorted(vs, key=lambda v: v.run)],
            "unstable": len({v.verdict for v in vs}) > 1, "first_failure": worst.first_failure,
            "tags": sorted({t for v in vs for t in v.tags})}


def load_review(path: str | Path | None) -> dict[tuple[str, int], dict]:
    if not path or not Path(path).exists():
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {(r["id"], int(r["run"])): r for r in csv.DictReader(f)}


def load_questions_for(set_name: str, v2_path: str | None = None) -> dict[str, Question]:
    """질문 세트 이름(core34 · ext-chart-request · YAML 경로) 또는 v2 데이터셋 → {id: Question}"""
    if set_name == "v2":
        from eval.generator import v2
        return v2.questions(v2.load(v2.dataset_dir(v2_path)))
    return load_questions(set_name).by_id()


def judge_file(runs_path, set_name, review_path=None, v2_path: str | None = None) -> list[RunVerdict]:
    qs = load_questions_for(set_name, v2_path)
    review = load_review(review_path)
    out = []
    for run in trace.load(runs_path):
        q = qs.get(run["id"])
        if q is None:
            continue
        out.append(judge(q, run, review.get((run["id"], int(run.get("run", 1))))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--set", default="core34")
    ap.add_argument("--v2", help="v2 데이터셋 경로")
    ap.add_argument("--review")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    vs = judge_file(a.runs, "v2" if a.v2 else a.set, a.review, v2_path=a.v2)
    out = Path(a.out or Path(a.runs).with_suffix(".verdicts.jsonl"))
    out.write_text("\n".join(json.dumps(asdict(v), ensure_ascii=False, default=str) for v in vs) + "\n", encoding="utf-8")
    print("wrote", out, len(vs))


if __name__ == "__main__":
    main()
