"""Generator 실행기 (criteria.md 1장)

  live   : 질문 → analyze → build_viewset → run_modules_with_qa(vs, analysis, mods=기록 래퍼) → 최종 result 조립 (run_chat 과 같은 순서)
  replay : 저장한 ViewSet + analysis → run_modules_with_qa (--no-qa 면 직렬 run_modules, QA on/off 비교 전용)
  oracle : 저장한 Module6Request 에서 M3 유래 5개 필드만 검증된 M3 출력으로 바꿔 run_module6 (Pipeline · Oracle 짝 실행)
  [NEW] isolated : v2 inputs/<ID>.json 의 격리 ViewSet + query_bundle → run_modules_with_qa (질의 분석 · 검색 없음)
  [NEW] m3_only  : v2 oracle_m3_inputs/<ID>.json 의 Module3Request → run_module3 만 (모듈 3 단독 계산 · 보류 정확도)

  python -m eval.generator.run --mode live --set core34 [--only Q05,Q11] [--runs 2] [--tag 이름] [--no-draw]
  python -m eval.generator.run --mode replay --from <EVAL_RUNS_DIR>/<tag>/runs.jsonl.gz [--no-qa] [--tag 이름]
  python -m eval.generator.run --mode oracle --from <runs.jsonl.gz> --only Q05 [--runs 2]
  python -m eval.generator.run --mode isolated --v2 <데이터셋 경로> [--only R01,B01] [--runs 2]
  python -m eval.generator.run --mode m3_only  --v2 <데이터셋 경로> [--only R01] [--runs 2]

결과: EVAL_RUNS_DIR/<tag>/runs.jsonl.gz (질문 · 회차마다 RunRecord 한 줄, trace.py) · manifest.json · run.log
HCX 키와 .env 는 읽지 않는다 (core.llm 이 스스로 읽는다). 질문은 하나씩 차례로 (HCX 동시 호출 제한).
"""
import argparse
import copy
import gzip
import hashlib
import json
import subprocess
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import backend.core.llm as llm
from backend.core.config import EVAL_RUNS_DIR, ROOT
from eval.generator import JUDGE_RULES, ORACLE_DIR, QUESTIONS_DIR, rel, trace
from eval.generator.verdict import SETS, load_questions

M3_FIELDS_FOR_M6 = ("calc_results", "displays", "answer_steps", "plan_warnings", "withheld")   # Module6Request 의 M3 유래 필드


def _dump(x):
    return x.model_dump(mode="json", by_alias=True) if hasattr(x, "model_dump") else x


# ── 기록 ─────────────────────────────────────────────────────────
class Recorder:
    """HCX 호출 · 모듈 요청/출력 · QA 검사 시간을 한 실행 동안 모은다"""

    def __init__(self):
        self.calls: list[dict] = []
        self.requests: dict[str, Any] = {}
        self.attempts: dict[str, int] = {}
        self.qa_timing: dict[str, float] = {"check": 0.0, "meaning_issues": 0.0, "unanswerable": 0.0}
        self.module_seconds: dict[str, float] = {}
        self.m6_shown_tokens: list[str] | None = None      # [NEW] M6 프롬프트에 실린 자리표시자 (근거 가시성 검사)

    def chat(self, real):
        def wrapped(messages, schema=None, **kw):
            t0 = time.time()
            rec = {"messages": messages, "ok": False}
            try:
                out = real(messages, schema=schema, **kw)
                rec.update(raw=out, ok=True)
                return out
            except BaseException as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                raise
            finally:
                rec["seconds"] = round(time.time() - t0, 2)
                self.calls.append(rec)
        return wrapped

    def module(self, name, fn, req_arg: str | None):
        def wrapped(*a, **kw):
            self.attempts[name] = self.attempts.get(name, 0) + 1
            if req_arg is not None:
                req = a[0] if a else kw.get(req_arg)
                self.requests[name] = _dump(req)
                if name == "m6":
                    self.m6_shown_tokens = shown_tokens_of(req)
            t0 = time.time()
            try:
                return fn(*a, **kw)
            finally:
                self.module_seconds[name] = round(self.module_seconds.get(name, 0) + time.time() - t0, 2)
        return wrapped

    def mods(self):
        from backend.agent.qa.qa_nodes import mods_of
        base = mods_of(None)
        return {"chart_decision": self.module("m2", base["chart_decision"], None),
                "module3": self.module("m3", base["module3"], "request"),
                "module5": self.module("m5", base["module5"], None),
                "module6": self.module("m6", base["module6"], "request")}


def shown_tokens_of(req) -> list[str] | None:
    """모듈 6 코드를 바꾸지 않고, 같은 Facts 로 프롬프트 결과 줄의 자리표시자를 다시 계산한다"""
    try:
        from backend.agent.answer_compose.facts import Facts
        from backend.agent.answer_compose.write import shown_tokens
        from backend.schemas.answer import Module6Request
        r = req if isinstance(req, Module6Request) else Module6Request.model_validate(req)
        return sorted(shown_tokens(Facts(r)))
    except Exception:  # noqa: BLE001  (기록 실패가 실행을 멈추지 않는다. 검사는 메시지 추출로 대신한다)
        return None


@contextmanager
def patched(rec: Recorder):
    """HCX chat 과 QA 검사 함수를 기록용으로 바꾼다. QA 코드는 수정하지 않는다 (qa_nodes 는 check 를 모듈 이름 공간에서 부른다)"""
    from backend.agent.qa import qa_nodes
    saved = {"chat": llm.chat, **{k: getattr(qa_nodes, k) for k in rec.qa_timing}}

    def timer(name, fn):
        def wrapped(*a, **kw):
            t0 = time.time()
            try:
                return fn(*a, **kw)
            finally:
                rec.qa_timing[name] += time.time() - t0
        return wrapped
    llm.chat = rec.chat(saved["chat"])
    for k in rec.qa_timing:
        setattr(qa_nodes, k, timer(k, saved[k]))
    try:
        yield
    finally:
        llm.chat = saved["chat"]
        for k in rec.qa_timing:
            setattr(qa_nodes, k, saved[k])


def assemble_result(mods: dict, vs: dict) -> dict:
    """pipeline.run_chat(answer_mode='modules') 의 최종 result 조립과 같은 순서 (pipeline.py 99-107)"""
    from backend.agent.modules import as_answer_result
    from backend.agent.pipeline import OUT_OF_SCOPE_RESULT, _missing_notes
    qa = mods.get("qa") or {}
    if mods.get("answer"):
        result = as_answer_result(mods)
        if qa.get("message"):
            result["caveats"] = list(result["caveats"]) + [qa["message"]]
    else:
        result = {**OUT_OF_SCOPE_RESULT, "answer": qa.get("message") or "답변을 만들지 못했습니다.", "caveats": []}
    if missing := _missing_notes(vs):
        result["caveats"] = list(dict.fromkeys(missing + result["caveats"]))
    return result


# ── 실행 ─────────────────────────────────────────────────────────
def run_generator(vs: dict, analysis: dict | None, *, qa: bool, draw: bool, max_rows: int, rec: Recorder) -> dict:
    with patched(rec):
        if qa:
            from backend.agent.qa import run_modules_with_qa
            return run_modules_with_qa(vs, analysis=analysis, draw=draw, max_rows=max_rows, mods=rec.mods())
        from backend.agent import modules as M
        from backend.agent.answer_compose import pipeline as p6
        from backend.agent.chart_calculate import pipeline as p3
        s3, s6 = p3.run_module3, p6.run_module6
        p3.run_module3, p6.run_module6 = rec.module("m3", s3, "request"), rec.module("m6", s6, "request")
        try:
            return M.run_modules(vs, draw=draw, max_rows=max_rows)
        finally:
            p3.run_module3, p6.run_module6 = s3, s6


def record(base: dict, rec: Recorder, t0: float, **kw) -> dict:
    out = {**base, **kw, "seconds": round(time.time() - t0, 1), "hcx_calls": rec.calls,
           "qa_timing": {k: round(v, 3) for k, v in rec.qa_timing.items()}, "module_seconds": rec.module_seconds,
           "module_attempts": rec.attempts, "requests": rec.requests or None, "source": "full",
           "m6_shown_tokens": rec.m6_shown_tokens,
           "judge_rules": JUDGE_RULES}           # [NEW] 이 실행을 판정할 규칙 버전 (새 규칙은 이후 실행에만 적용)
    mods = out.get("modules")
    if mods and out.get("viewset") is not None:
        out["records"] = out["viewset"].get("records") or []
    return out


def live_one(q, run_no: int, *, draw: bool, qa: bool, max_rows: int, today: str | None) -> dict:
    from backend.agent.pipeline import OUT_OF_SCOPE_RESULT, _first_option
    from backend.rag.query_analyzer.analyze import analyze
    from backend.rag.view.viewset import build_viewset
    rec, t0 = Recorder(), time.time()
    base = {"id": q.id, "set": None, "run": run_no, "mode": "live", "path": "qa" if qa else "modules", "question": q.question}
    try:
        with patched(rec):
            analysis = analyze(q.question, today)
        if analysis["status"] != "ok":
            result = dict(OUT_OF_SCOPE_RESULT) if analysis["status"] == "out_of_scope" else None
            return record(base, rec, t0, ok=True, analysis=analysis, viewset=None, modules=None, result=result)
        with patched(rec):
            vs = build_viewset(analysis, on_ambiguous=_first_option)
        if vs["status"] != "ok":
            return record(base, rec, t0, ok=True, analysis=analysis, viewset=vs, modules=None, result=None)
        mods = run_generator(vs, analysis, qa=qa, draw=draw, max_rows=max_rows, rec=rec)
        return record(base, rec, t0, ok=True, analysis=analysis, viewset=vs, modules=mods, result=assemble_result(mods, vs))
    except BaseException as e:  # noqa: BLE001  (한 문항 실패해도 다음 문항으로)
        return record(base, rec, t0, ok=False, error=f"{type(e).__name__}: {str(e)[:500]}", traceback=traceback.format_exc()[-2500:])


def replay_one(src: dict, run_no: int, *, draw: bool, qa: bool, max_rows: int) -> dict | None:
    if src.get("viewset") is None or (src.get("viewset") or {}).get("status") != "ok":
        return None                                    # ViewSet 없음 (범위 밖 · 되묻기) → replay 대상 아님
    rec, t0 = Recorder(), time.time()
    base = {"id": src["id"], "set": src.get("set"), "run": run_no, "mode": "replay", "path": "qa" if qa else "modules",
            "question": src.get("question"), "replay_of": src.get("manifest_id")}
    vs, analysis = src["viewset"], src.get("analysis")
    try:
        mods = run_generator(vs, analysis, qa=qa, draw=draw, max_rows=max_rows, rec=rec)
        return record(base, rec, t0, ok=True, analysis=analysis, viewset=vs, modules=mods, result=assemble_result(mods, vs))
    except BaseException as e:  # noqa: BLE001
        return record(base, rec, t0, ok=False, analysis=analysis, viewset=vs, error=f"{type(e).__name__}: {str(e)[:500]}")


def oracle_request(m6_req: dict, verified_m3: dict) -> dict:
    """저장한 Module6Request 에서 M3 유래 필드만 검증된 M3 출력으로 바꾼다. 값은 M3 스키마 표현 그대로 (평가 정규형을 넣지 않는다)"""
    from backend.schemas.chart import Step
    out = copy.deepcopy(m6_req)
    plan = verified_m3.get("chart_plan") or {}
    out["calc_results"] = copy.deepcopy(verified_m3.get("calc_results") or [])
    out["displays"] = copy.deepcopy(verified_m3.get("displays") or {})
    # Module3Output dump 는 별칭 없이(from_), Module6Request 기록은 별칭으로(from) 저장된다 → 같은 표현으로 맞춘다
    out["answer_steps"] = [Step.model_validate(s).model_dump(mode="json", by_alias=True) for s in plan.get("answer_steps") or []]
    out["plan_warnings"] = copy.deepcopy(plan.get("warnings") or [])
    out["withheld"] = copy.deepcopy(plan.get("withheld") or [])
    return out


def oracle_one(src: dict, condition: str, run_no: int) -> dict | None:
    from backend.agent.answer_compose.pipeline import run_module6
    from backend.schemas.answer import Module6Request
    m6_req = (src.get("requests") or {}).get("m6")
    if not m6_req:
        return None                                    # no_full_request (과거 slim trace)
    verified = _load_oracle(src["id"]) if condition == "oracle" else None
    if condition == "oracle" and verified is None:
        return None
    req = oracle_request(m6_req, verified) if verified else copy.deepcopy(m6_req)
    rec, t0 = Recorder(), time.time()
    base = {"id": src["id"], "set": src.get("set"), "run": run_no, "mode": "oracle", "condition": condition,
            "path": "m6", "question": src.get("question"), "oracle_of": src.get("manifest_id")}
    try:
        with patched(rec):
            out = run_module6(Module6Request.model_validate(req), chat=llm.chat).model_dump(mode="json")
        mods = {**(src.get("modules") or {}), "module3": verified or (src.get("modules") or {}).get("module3"), "answer": out}
        result = {"answer": out.get("answer"), "caveats": [c.get("text") for c in out.get("caveats") or []]}
        r = record(base, rec, t0, ok=True, analysis=src.get("analysis"), viewset=src.get("viewset"), modules=mods, result=result)
        r["requests"] = {"m6": req}
        return r
    except BaseException as e:  # noqa: BLE001
        return record(base, rec, t0, ok=False, error=f"{type(e).__name__}: {str(e)[:500]}")


# [NEW] 운영 pipeline(backend/agent/pipeline.py)이 Generator 앞에서 상태로 반환하는 ViewSet 상태.
# 계약 밖 값(v2 B14 unknown_status)은 여기 없으므로 Generator A0 계약 검사로 간다
PIPELINE_STATUSES = ("needs_selection", "needs_clarification", "out_of_scope")


def isolated_one(case_id: str, question: str, inp: dict, run_no: int, *, input_hash: str, version: str,
                 draw: bool, max_rows: int) -> dict:
    """v2 격리 입력. analysis 는 입력의 query_bundle 로 만든다 (메모 없음 → A0 의 사전 밖 지표 검사는 건너뛴다)"""
    rec, t0 = Recorder(), time.time()
    vs = inp["viewset"]
    qb = inp["query_bundle"]
    analysis = {"status": "ok", "notes": [], "view_bundle": qb, "sub_questions": qb.get("sub_questions") or [],
                "filters": qb.get("filters"), "sub_filters": qb.get("sub_filters")}
    base = {"id": case_id, "set": "v2", "run": run_no, "mode": "isolated", "condition": "isolated", "path": "qa",
            "question": question, "dataset": "v2", "dataset_version": version, "input_hash": input_hash,
            "m6_visible_record_ids": inp.get("m6_visible_record_ids")}
    if vs.get("status") in PIPELINE_STATUSES:
        # [CHANGED] 이전: 상태와 관계없이 Generator 에 넣어 QA A0 가 enum 위반으로 멈췄다 (B16 · C19 · M04, 서비스에 없는 경로)
        from backend.agent.pipeline import OUT_OF_SCOPE_RESULT
        st = vs["status"]
        if st == "out_of_scope":
            analysis["status"] = "out_of_scope"
        return record(base, rec, t0, ok=True, analysis=analysis, viewset=vs, pipeline_status=st,
                      result=dict(OUT_OF_SCOPE_RESULT) if st == "out_of_scope" else None)
    try:
        mods = run_generator(vs, analysis, qa=True, draw=draw, max_rows=max_rows, rec=rec)
        return record(base, rec, t0, ok=True, analysis=analysis, viewset=vs, modules=mods, result=assemble_result(mods, vs))
    except BaseException as e:  # noqa: BLE001
        return record(base, rec, t0, ok=False, analysis=analysis, viewset=vs, error=f"{type(e).__name__}: {str(e)[:500]}",
                      traceback=traceback.format_exc()[-2500:])


def m3_only_one(case_id: str, question: str, req: dict, run_no: int, *, input_hash: str, version: str) -> dict:
    """v2 Module3Request → run_module3. 판정은 모듈 3 항목(연산 · 계산 · 보류)만 본다 (verdict: condition=m3_only)"""
    from backend.agent.chart_calculate.pipeline import run_module3
    from backend.schemas.chart import Module3Request
    rec, t0 = Recorder(), time.time()
    base = {"id": case_id, "set": "v2", "run": run_no, "mode": "m3_only", "condition": "m3_only", "path": "m3",
            "question": question, "dataset": "v2", "dataset_version": version, "input_hash": input_hash}
    qb = req["query_bundle"]
    vs = {"status": "ok", "query_id": qb.get("query_id"), "original": qb.get("original"), "records": req["records"],
          "units": [], "view_bundle": qb}
    try:
        with patched(rec):
            out = run_module3(Module3Request.model_validate(req), chat=llm.chat).model_dump(mode="json", by_alias=True)
        rec.requests["m3"] = req
        mods = {"charts": req.get("charts") or [], "chart_plan": out.get("chart_plan") or {}, "module3": out, "answer": {},
                "drawn": [], "notes": [], "qa": {}, "render_status": {}, "request_outcomes": [], "chart_notices": []}
        return record(base, rec, t0, ok=True, analysis={"status": "ok", "notes": [], "view_bundle": qb}, viewset=vs,
                      modules=mods, result={"answer": "", "caveats": []})
    except BaseException as e:  # noqa: BLE001
        return record(base, rec, t0, ok=False, viewset=vs, error=f"{type(e).__name__}: {str(e)[:500]}",
                      traceback=traceback.format_exc()[-2500:])


def _load_oracle(qid: str) -> dict | None:
    p = ORACLE_DIR / "m3" / f"{qid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ── manifest ─────────────────────────────────────────────────────
def _sha(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def manifest(args, set_path: Path | None) -> dict:
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
    agent = ROOT / "backend" / "agent"
    return {"tag": args.tag, "mode": args.mode, "set": "v2" if args.v2 else args.set, "runs": args.runs, "qa": not args.no_qa,
            "draw": not args.no_draw, "dataset": getattr(args, "dataset_meta", None),
            "git_sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
            "model": llm.CHAT_MODEL, "prompts": _sha([agent / "prompts.py"]),
            "m2_code": _sha(list((agent / "chart_decision" / "chart_decision_module").glob("*.py"))),
            "set_hash": _sha([set_path]) if set_path else None, "from": args.from_ and rel(args.from_),
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "judge_rules": JUDGE_RULES}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["live", "replay", "oracle", "isolated", "m3_only"], default="live")
    ap.add_argument("--v2", help="v2 데이터셋 경로 (isolated · m3_only). 없으면 EVAL_V2_DIR")
    ap.add_argument("--slots", type=Path, help="[NEW] isolated 입력 슬롯 overlay (eval/generator/questions/v2_slots.json)")
    ap.add_argument("--set", default="core34", choices=list(SETS))
    ap.add_argument("--only", default="")
    ap.add_argument("--only-file", type=Path, help="[NEW] 줄 단위 문항 ID 목록 (--only 와 교집합)")
    ap.add_argument("--shard", help="[NEW] I/N: 문항을 sha1(id) %% N 으로 나눠 I번째 몫만 실행 (isolated · m3_only)")
    ap.add_argument("--resume", action="store_true", help="[NEW] 같은 --tag 의 기록에 있는 (id, run) 은 건너뛴다 (isolated · m3_only)")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--tag", default=time.strftime("%m%d_%H%M"))
    ap.add_argument("--from", dest="from_", type=Path)
    ap.add_argument("--no-draw", action="store_true")
    ap.add_argument("--no-qa", action="store_true", help="직렬 run_modules (QA on/off 비교 전용)")
    ap.add_argument("--max-rows", type=int, default=40)
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    ds, slots, shard, only_file = None, None, None, None
    if a.shard or a.resume or a.only_file:
        if a.mode not in ("isolated", "m3_only"):
            raise SystemExit("[shard · resume · only-file] isolated · m3_only 전용")
    if a.mode in ("isolated", "m3_only"):
        from eval.generator import v2 as V2
        try:
            root = V2.dataset_dir(a.v2)
            ds = V2.load(root)                        # 해시가 manifest 와 다르면 실행하지 않는다
        except (V2.DatasetError, OSError) as e:
            raise SystemExit(f"[{a.mode}] 데이터셋 오류: {e}")
        a.v2 = str(root)
        try:
            shard = V2.parse_shard(a.shard)
        except V2.DatasetError as e:
            raise SystemExit(f"[{a.mode}] {e}")
        if a.only_file:
            only_file = V2.read_ids(a.only_file)
            if unknown := only_file - {c.id for c in ds["cases"]}:
                raise SystemExit(f"[only-file] 데이터셋에 없는 ID {sorted(unknown)[:5]} 외 {max(len(unknown) - 5, 0)}건")
        a.dataset_meta = {"name": ds["name"], "version": ds["version"], "path": rel(root),
                          "cases_sha256": V2.sha256(root / "cases.json")}
        if a.slots:
            if a.mode != "isolated":
                raise SystemExit("[slots] isolated 전용")
            sl = V2.load_slots(a.slots)
            if errs := V2.slot_errors(root, sl["slots"], {c.id for c in ds["cases"]}):
                raise SystemExit(f"[slots] 슬롯 오류: {errs[:5]}")
            slots = sl["slots"]
            # 입력이 달라지므로 별도 데이터셋 버전으로 기록한다 (compare 가 원래 isolated 와 섞지 않는다)
            ds["version"] = ds["version"] + "+slots"
            a.dataset_meta.update(version=ds["version"], slots={"path": rel(sl["path"]), "sha256": sl["sha256"], "cases": len(slots)})
    out_dir = EVAL_RUNS_DIR / a.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    done: set[tuple[str, int]] = set()
    if a.resume:
        kept = V2.salvage(out_dir / "runs.jsonl.gz")           # 끝나지 않은 gzip 을 온전한 줄로 다시 쓴다
        done = V2.done_keys(out_dir / "runs.jsonl.gz")
        print(f"[resume] {a.tag}: 기존 기록 {kept}줄 · 완료 (id, run) {len(done)}개", flush=True)
    set_path = None if ds else QUESTIONS_DIR / SETS[a.set]
    man = manifest(a, set_path)
    man.update(shard=a.shard, only_file=a.only_file and rel(a.only_file), resume=a.resume)
    man_id = f"{a.tag}@{(man['git_sha'] or '')[:7]}"
    (out_dir / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    log = (out_dir / "run.log").open("a", encoding="utf-8")
    sink = gzip.open(out_dir / "runs.jsonl.gz", "at", encoding="utf-8")

    def emit(r):
        if r is None:
            return
        r["set"], r["manifest_id"] = r.get("set") or a.set, man_id
        sink.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        sink.flush()
        ans = ((r.get("result") or {}).get("answer") or r.get("error") or "")[:80].replace("\n", " ")
        line = f"[{time.strftime('%H:%M:%S')}] {r['mode']} run{r['run']} {r['id']} {r['seconds']:>6}s ok={r['ok']} :: {ans}"
        log.write(line + "\n")
        log.flush()
        print(line, flush=True)

    try:
        if ds is not None:
            for run_no in range(1, a.runs + 1):
                skipped = 0
                for c in ds["cases"]:
                    if only and c.id not in only:
                        continue
                    if only_file is not None and c.id not in only_file:
                        continue
                    if shard and V2.shard_of(c.id, shard[1]) != shard[0]:
                        continue
                    if (c.id, run_no) in done:
                        skipped += 1
                        continue
                    path = V2.input_path(root, c.id, a.mode)
                    if not path.exists():
                        log.write(f"skip {c.id}: {a.mode} 입력 없음\n")    # m3_only 는 A0 에서 멈추는 5문항의 입력이 없다
                        continue
                    inp, h = json.loads(path.read_text(encoding="utf-8")), V2.sha256(path)
                    if a.mode == "isolated" and slots:
                        slot = slots.get(c.id)
                        inp, h = V2.apply_slots(inp, slot), V2.slot_hash(h, slot)
                    if a.mode == "isolated":
                        emit(isolated_one(c.id, c.question, inp, run_no, input_hash=h, version=ds["version"],
                                          draw=not a.no_draw, max_rows=a.max_rows))
                    else:
                        emit(m3_only_one(c.id, c.question, inp, run_no, input_hash=h, version=ds["version"]))
                if skipped:
                    msg = f"[resume] run{run_no}: 완료된 {skipped}문항 건너뜀"
                    log.write(msg + "\n")
                    print(msg, flush=True)
        elif a.mode == "live":
            qs = [q for q in load_questions(a.set).questions if not only or q.id in only]
            for run_no in range(1, a.runs + 1):
                for q in qs:
                    emit(live_one(q, run_no, draw=not a.no_draw, qa=not a.no_qa, max_rows=a.max_rows, today=a.today))
        else:
            if not a.from_:
                ap.error("--from 이 필요하다")
            srcs = [s for s in trace.load(a.from_) if (not only or s["id"] in only) and s.get("run", 1) == 1]
            for run_no in range(1, a.runs + 1):
                for s in srcs:
                    if a.mode == "replay":
                        r = replay_one(s, run_no, draw=not a.no_draw, qa=not a.no_qa, max_rows=a.max_rows)
                        if r is None:
                            log.write(f"skip {s['id']}: no_viewset\n")
                        emit(r)
                    else:
                        for cond in ("pipeline", "oracle"):
                            r = oracle_one(s, cond, run_no)
                            if r is None:
                                log.write(f"skip {s['id']} {cond}: no_full_request · no_oracle\n")
                            emit(r)
    finally:
        sink.close()
        log.close()
    print("DONE", rel(out_dir / "runs.jsonl.gz"))


if __name__ == "__main__":
    main()
