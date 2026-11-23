"""QA 평가 (계획 2.7, D-20): Fault Injection(형식 검사) · FI-SEM(내용 경고) · FI-CONTRA(의미 정합성 미검사) · Policy Compliance

  python -m eval.generator.faults <runs.jsonl[.gz]> [--policy] [--out DIR]
형식 검사 지표에는 내용 경고(SEMANTIC_KINDS)를 넣지 않는다. FI-CONTRA 는 QA Recall 에 넣지 않고 어느 단계가 잡는지만 기록한다.
Policy Compliance 는 ViewSet 전체가 저장된 실행(source=full)에서만 돈다 (HCX 없이: 모듈 3 · 6 은 저장한 출력을 돌려주는 가짜, 모듈 2 는 규칙만).
"""
import argparse
import copy
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from backend.agent.qa.qa_check import ERROR, INFO, WARNING, check
from backend.agent.qa.qa_policy import MAX_RETRY, RULES, SEMANTIC_KINDS
from eval.generator import rel, trace
from eval.generator.contract import ctx_of, points


@dataclass
class Mutant:
    code: str           # F-MISS · F-TYPE · F-ENUM · F-EMPTY · F-REF · F-NEWREF · F-EXTRA · F-MULTI · CLEAN
    point: str
    path: str
    expect: str         # error · warning · none
    raw: dict


def _get(d, path):
    cur = d
    for p in path:
        if isinstance(cur, list):
            if not isinstance(p, int) or p >= len(cur):
                return None
        elif not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _mut(raw, path, fn):
    out = copy.deepcopy(raw)
    parent = _get(out, path[:-1]) if len(path) > 1 else out
    if parent is None or (isinstance(parent, dict) and path[-1] not in parent) or \
            (isinstance(parent, list) and path[-1] >= len(parent)):
        return None
    fn(parent, path[-1])
    return out


def _del(p, k):
    del p[k]


def _set(v):
    def f(p, k):
        p[k] = v
    return f


# (지점, 코드, 경로, 변이, 기대). 경로가 그 실행에 없으면 그 변이는 만들지 않는다
SPECS = [
    ("M3-out", "F-MISS", ("chart_plan",), _del, "error"),
    ("M3-out", "F-MISS", ("calc_results", 0, "step_id"), _del, "error"),
    ("M3-out", "F-TYPE", ("calc_results", 0, "inputs", 0, "value"), "str_number", "warning"),   # 손실 없는 변환 → 보정 + 경고
    ("M3-out", "F-TYPE", ("calc_results", 0, "inputs", 0, "value"), _set({"x": 1}), "error"),  # 손실 있는 변환
    ("M3-out", "F-ENUM", ("calc_results", 0, "op"), _set("bogus_op"), "error"),
    ("M3-out", "F-EMPTY", ("calc_results", 0, "step_id"), _set(""), "error"),
    ("M3-out", "F-REF", ("calc_results", 0, "record_ids"), _set(["view::없는표::Y::0::x"]), "error"),
    ("M3-out", "F-REF", ("chart_contents", 0, "chart_id"), _set("c_없음"), "error"),
    ("M3-out", "F-NEWREF", ("calc_results", 0, "sub_question_id"), _set("없는질문-9"), "error"),
    ("M3-out", "F-NEWREF", ("chart_plan", "withheld", 0, "sub_question_id"), _set("없는질문-9"), "error"),
    ("M3-out", "F-NEWREF", ("chart_plan", "answer_steps", 0, "sub_question_id"), _set("없는질문-9"), "error"),
    ("M3-out", "F-EXTRA", ("zz_eval_extra",), "add", "warning"),
    ("M6-out", "F-MISS", ("answer",), _del, "error"),
    ("M6-out", "F-ENUM", ("method",), _set("bogus"), "error"),
    ("M6-out", "F-EMPTY", ("answer",), _set(""), "error"),
    ("M6-out", "F-REF", ("used_step_ids",), _set(["a_없음"]), "error"),
    ("M6-out", "F-EXTRA", ("zz_eval_extra",), "add", "warning"),
    ("M2-out", "F-MISS", ("chart_plan", "charts", 0, "chart_id"), _del, "error"),
    ("M2-out", "F-ENUM", ("chart_plan", "charts", 0, "measure"), _set("bogus"), "error"),
    ("M2-out", "F-REF", ("chart_plan", "charts", 0, "view_ids"), _set(["view::없는표::Y::0::x"]), "error"),
    ("A9", "F-EXTRA", ("zz_eval_extra",), "add", "warning"),
]


def mutants(run: dict) -> list[Mutant]:
    pts = points(run)
    out = [Mutant("CLEAN", pt, "", "none", raw) for pt, raw in pts.items() if raw is not None]
    for pt, code, path, fn, exp in SPECS:
        raw = pts.get(pt)
        if raw is None:
            continue
        if fn == "add":
            m = copy.deepcopy(raw)
            m[path[0]] = 1
        elif fn == "str_number":
            v = _get(raw, path)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            m = _mut(raw, path, _set(str(int(v)) if float(v).is_integer() else repr(v)))
        else:
            if _get(raw, path) is None and fn is not _del:
                continue
            m = _mut(raw, path, fn)
        if m is not None:
            out.append(Mutant(code, pt, ".".join(map(str, path)), exp, m))
    a, b = [x for x in out if x.point == "M3-out" and x.code == "F-MISS" and "step_id" in x.path], \
           [x for x in out if x.point == "M3-out" and x.code == "F-ENUM"]
    if a and b:                                        # F-MULTI: 두 변이를 함께
        m = _mut(a[0].raw, ("calc_results", 0, "op"), _set("bogus_op"))
        if m is not None:
            out.append(Mutant("F-MULTI", "M3-out", "calc_results.0.step_id+op", "error", m))
    return out


def classify(issues) -> str:
    fmt = [i for i in issues if i.kind not in SEMANTIC_KINDS]
    if any(i.severity == ERROR for i in fmt):
        return "error"
    if any(i.severity == WARNING for i in fmt):
        return "warning"
    return "none"


def fault_injection(runs: list[dict]) -> dict:
    rows = []
    for r in runs:
        for m in mutants(r):
            try:
                got = classify(check(m.point, m.raw, ctx_of(r, m.point)).issues)
            except Exception as e:  # noqa: BLE001
                got = f"exception:{type(e).__name__}"
            rows.append({"id": r["id"], "run": r.get("run"), "code": m.code, "point": m.point, "path": m.path,
                         "expect": m.expect, "got": got})
    by = defaultdict(lambda: Counter())
    for x in rows:
        c = by[x["code"]]
        c["n"] += 1
        c["detected"] += x["got"] == x["expect"] if x["code"] != "CLEAN" else 0
        c["false_alarm"] += x["code"] == "CLEAN" and x["got"] == "error"
        c["severity_ok"] += x["got"] == x["expect"]
    inj = [x for x in rows if x["code"] != "CLEAN"]
    det = [x for x in inj if x["got"] in ("error", "warning")]
    clean = [x for x in rows if x["code"] == "CLEAN"]
    summary = {
        "mutants": len(inj), "clean": len(clean),
        "detection_recall": round(len(det) / len(inj), 4) if inj else None,
        "severity_correct": round(sum(x["got"] == x["expect"] for x in inj) / len(inj), 4) if inj else None,
        "false_alarm_rate": round(sum(x["got"] == "error" for x in clean) / len(clean), 4) if clean else None,
        "precision": (lambda tp, fp: round(tp / (tp + fp), 4) if tp + fp else None)(
            len(det), sum(x["got"] in ("error", "warning") for x in clean)),
        "per_type": {k: dict(v) for k, v in sorted(by.items())},
        "misses": [x for x in inj if x["got"] != x["expect"]][:50],
    }
    return {"summary": summary, "rows": rows}


# ── FI-SEM · FI-CONTRA ───────────────────────────────────────────
def _models(run):
    from backend.schemas.answer import Module6Output
    from backend.schemas.chart import Module3Output
    from backend.schemas.query import QueryBundle
    m = trace.mods(run)
    try:
        m3 = Module3Output.model_validate(m["module3"])
        m6 = Module6Output.model_validate(m["answer"]) if m.get("answer") else None
        b = trace.bundle(run)
        bundle = QueryBundle.model_validate({**b, "query_id": b.get("query_id") or m3.query_id,
                                             "original": b.get("original") or run.get("question") or ""})
    except Exception:  # noqa: BLE001
        return None
    return m3, m6, bundle, m.get("charts") or [], m.get("drawn") or []


def sem_mutations(run):
    """(내용 경고 종류, 변이 함수(m3, m6, bundle, charts, drawn) → 같은 튜플). 전제가 없으면 만들지 않는다"""
    out = []

    def ratio_missing(m3, m6, b, ch, dr):
        b.original = (b.original or "") + " 비율"
        for c in m3.calc_results:
            c.op, c.unit = "raw", "명"
        return m3, m6, b, ch, dr

    def measure_mismatch(m3, m6, b, ch, dr):
        for c in ch:
            c["measure"] = "growth_rate"
        for c in m3.calc_results:
            c.op = "raw"
        return m3, m6, b, ch, dr

    def chart_answer_mismatch(m3, m6, b, ch, dr):
        m6.insufficient = True
        return m3, m6, b, ch, [{**d, "status": "drawn"} for d in dr] or [{"chart_id": "c1", "status": "drawn"}]

    def value_list(m3, m6, b, ch, dr):
        m6.method, m6.answer = "template", (m6.answer or "") + " 외 6개입니다."
        return m3, m6, b, ch, dr

    def too_many_marks(m3, m6, b, ch, dr):
        for c in m3.chart_contents:
            if c.chart_type in ("bar", "stacked_bar") and c.rows:
                c.rows = (c.rows * (101 // len(c.rows) + 1))[:101]
        return m3, m6, b, ch, dr

    def answer_caveat_conflict(m3, m6, b, ch, dr):
        from backend.schemas.chart import Withheld
        sid = (trace.sub_question_list(run) or [("q-1", "")])[0][0]
        m3.chart_plan.withheld.append(Withheld(sub_question_id=sid, text="분모가 없어 계산하지 못했습니다"))
        cited = set(m6.used_step_ids or [])
        for c in m3.calc_results:              # 11-20 이전 출력에는 sub_question_id 가 없다 → 인용한 계산을 그 하위 질문에 둔다
            if c.step_id in cited:
                c.sub_question_id = sid
        if m6.answer:
            m6.answer = m6.answer.replace("참고로", "")
        return m3, m6, b, ch, dr

    from eval.generator.subq import has_value
    m = trace.mods(run)
    m3 = m.get("module3") or {}
    # 내용 경고 규칙은 수치 답변이 나간 경우에만 적용된다 → 값 있는 계산 + insufficient=false 일 때만 주입한다
    has_calc = any(has_value(c) for c in m3.get("calc_results") or []) and not (m.get("answer") or {}).get("insufficient")
    if has_calc and m.get("answer"):
        out.append(("ratio_missing", ratio_missing))
        out.append(("answer_caveat_conflict", answer_caveat_conflict))
    if has_calc and m.get("charts"):
        out.append(("measure_mismatch", measure_mismatch))
    if m.get("answer"):
        out.append(("chart_answer_mismatch", chart_answer_mismatch))
        out.append(("value_list", value_list))
    if any(c.get("chart_type") in ("bar", "stacked_bar") for c in m3.get("chart_contents") or []):
        out.append(("too_many_marks", too_many_marks))
    return out


def semantic_injection(runs: list[dict]) -> dict:
    from backend.agent.qa.qa_semantic import meaning_issues
    rows = []
    for r in runs:
        base = _models(r)
        if base is None:
            continue
        for kind, fn in sem_mutations(r):
            try:
                args = fn(*copy.deepcopy(base))
                kinds = {i.kind for i in meaning_issues(*args)}
                before = {i.kind for i in meaning_issues(*copy.deepcopy(base))}
                rows.append({"id": r["id"], "run": r.get("run"), "kind": kind, "detected": kind in kinds,
                             "already": kind in before})
            except Exception as e:  # noqa: BLE001
                rows.append({"id": r["id"], "run": r.get("run"), "kind": kind, "detected": None, "error": f"{type(e).__name__}: {e}"[:160]})
    by = defaultdict(Counter)
    for x in rows:
        if x.get("detected") is None or x.get("already"):
            by[x["kind"]]["skipped"] += 1
            continue
        by[x["kind"]]["n"] += 1
        by[x["kind"]]["detected"] += bool(x["detected"])
    return {"summary": {k: {**dict(v), "recall": round(v["detected"] / v["n"], 4) if v["n"] else None} for k, v in sorted(by.items())},
            "rows": rows}


def contra_injection(runs: list[dict]) -> dict:
    """FI-CONTRA: 결과 부호만 반전(입력 그대로) · 비중 > 100% · 순위 중복. QA 형식 검사 · 내용 경고 중 무엇이 잡는지 기록"""
    from backend.agent.qa.qa_semantic import meaning_issues
    rows = []
    for r in runs:
        base = _models(r)
        if base is None:
            continue
        m3 = base[0]
        for c in m3.calc_results:
            kind = {"growth_rate": "sign_flip", "change": "sign_flip", "cagr": "sign_flip", "share": "share_over_100",
                    "rank": "rank_duplicate"}.get(c.op)
            if not kind or c.value is None:
                continue
            args = copy.deepcopy(base)
            cc = next(x for x in args[0].calc_results if x.step_id == c.step_id)
            if kind == "sign_flip" and not isinstance(cc.value, list):
                cc.value = -cc.value
            elif kind == "share_over_100" and not isinstance(cc.value, list):
                cc.value = 140.0
            elif kind == "rank_duplicate" and isinstance(cc.value, list) and len(cc.value) > 1:
                cc.value[1]["rank"] = cc.value[0].get("rank")
            else:
                continue
            fmt = classify(check("M3-out", args[0].model_dump(mode="json"), ctx_of(r, "M3-out")).issues)
            sem = sorted({i.kind for i in meaning_issues(*args)} - {i.kind for i in meaning_issues(*copy.deepcopy(base))})
            rows.append({"id": r["id"], "run": r.get("run"), "kind": kind, "step_id": c.step_id,
                         "qa_format": fmt, "qa_semantic": sem, "detected_by_qa": fmt != "none" or bool(sem)})
    return {"summary": dict(Counter(f"{x['kind']}:{'탐지' if x['detected_by_qa'] else '미탐지'}" for x in rows)), "rows": rows}


# ── Policy Compliance ────────────────────────────────────────────
def policy_compliance(runs: list[dict]) -> dict:
    """저장한 ViewSet 으로 QA 그래프를 돌리되, 모듈 3 · 6 은 저장한 출력(또는 변이)을 돌려주는 가짜로 바꾼다 (HCX 없음)"""
    from backend.agent.qa import run_modules_with_qa
    from backend.schemas.answer import Module6Output
    from backend.schemas.chart import Module3Output
    rows = []
    for r in runs:
        vs, m = r.get("viewset"), trace.mods(r)
        if not vs or vs.get("status") != "ok" or not m.get("module3") or not m.get("answer"):
            continue
        good3, good6 = m["module3"], m["answer"]
        for name, point, bad, always, expect in (
            ("m3_retry_recovers", "M3-out", _mut(good3, ("calc_results", 0, "op"), _set("bogus")) if good3.get("calc_results") else None,
             False, {"retry": True, "stopped": False}),
            ("m3_persistent_drop", "M3-out", _mut(good3, ("calc_results", 0, "op"), _set("bogus")) if good3.get("calc_results") else None,
             True, {"retry": True, "stopped": False, "dropped": True}),
            ("m3_plan_missing_stop", "M3-out", _mut(good3, ("chart_plan",), _del), True, {"retry": True, "stopped": True}),
            ("m6_missing_skip_answer", "M6-out", _mut(good6, ("answer",), _del), True, {"retry": True, "stopped": False, "no_answer": True}),
        ):
            if bad is None:
                continue
            calls = Counter()

            def _as_model(kind, v):
                cls = Module3Output if kind == "m3" else Module6Output
                try:
                    return cls.model_validate(v)
                except Exception:  # noqa: BLE001  (스키마를 깨는 변이는 검증 없이 넘긴다 — QA 가 잡아야 하는 값)
                    return cls.model_construct(**v)

            def fake(kind, good, badv, always=always):
                def f(*a, **kw):
                    calls[kind] += 1
                    return _as_model(kind, badv if (always or calls[kind] == 1) else good)
                return f
            mods = {"module3": fake("m3", good3, bad if point == "M3-out" else good3),
                    "module6": fake("m6", good6, bad if point == "M6-out" else good6)}
            try:
                out = run_modules_with_qa(vs, use_llm_chart=False, draw=False, analysis=r.get("analysis"), mods=mods)
                qa = out.get("qa") or {}
                got = {"retry": any(x.get("point") == point if isinstance(x, dict) else point in str(x) for x in qa.get("retries") or []),
                       "stopped": bool(qa.get("stopped_at")), "dropped": bool(qa.get("dropped")),
                       "no_answer": not out.get("answer"), "retries": len(qa.get("retries") or []),
                       "max_calls": max(calls.values()) if calls else 0}
            except Exception as e:  # noqa: BLE001
                got = {"exception": f"{type(e).__name__}: {e}"[:160]}
            ok = "exception" not in got and all(got.get(k) == v for k, v in expect.items()) and \
                got.get("max_calls", 0) <= 1 + MAX_RETRY
            rows.append({"id": r["id"], "scenario": name, "expect": expect, "got": got, "ok": ok,
                         "rule": {"retry": RULES[point].retry, "on_fail": RULES[point].on_fail}})
    n = len(rows)
    return {"summary": {"scenarios": n, "compliance": round(sum(x["ok"] for x in rows) / n, 4) if n else None,
                        "retry_cap_violations": sum(1 for x in rows if x["got"].get("max_calls", 0) > 1 + MAX_RETRY)},
            "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--policy", action="store_true", help="Policy Compliance (source=full 실행만)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    runs = trace.load(a.runs)
    src = Path(a.runs)
    out = Path(a.out or src.parent / (src.name.split(".")[0] + "_faults"))
    out.mkdir(parents=True, exist_ok=True)
    res = {"fault_injection": fault_injection(runs), "semantic": semantic_injection(runs), "contra": contra_injection(runs)}
    if a.policy:
        res["policy"] = policy_compliance(runs)
    for k, v in res.items():
        (out / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in res.items()}, ensure_ascii=False, indent=1, default=str))
    print("wrote", rel(out))


if __name__ == "__main__":
    main()
