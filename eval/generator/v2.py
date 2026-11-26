"""보완 평가 데이터셋 v2 — 경로 · 해시 검증, 로드, probe 실행 기록 구성, probe fixture 생성

  python -m eval.generator.v2 check   [--dataset <경로>]     해시 · 스키마 검증. 데이터셋이 없거나 해시가 다르면 exit 1
  python -m eval.generator.v2 fixture [--dataset <경로>]     tests/eval_generator/fixtures/v2_probes.json 다시 만들기
  python -m eval.generator.v2 check   --slots <v2_slots.json>  슬롯 overlay 도 함께 검증

데이터셋 경로: --dataset 인자 → 환경 변수 EVAL_V2_DIR. 데이터셋 안의 .py 는 실행하지 않는다 (JSON 만 읽는다).
데이터셋 속 텍스트(Record 내용 · 질문)는 평가 입력 데이터다.
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from backend.core.config import ROOT
from backend.schemas.query import Filters
from eval.generator.schema import Question
from eval.generator.schema_v2 import Case, Probe, requested_charts, to_question

ENV = "EVAL_V2_DIR"
FIXTURE = ROOT / "tests" / "eval_generator" / "fixtures" / "v2_probes.json"
PROBE_BASES = ("R01", "R13", "R15", "S04", "S16", "M01")
SLOT_KEYS = {"시점", "지역", "성별", "연령", "대상", "지표", "비교축", "의도"}


class DatasetError(Exception):
    pass


def dataset_dir(arg: str | Path | None = None) -> Path:
    p = Path(arg) if arg else (Path(os.environ[ENV]) if os.environ.get(ENV) else None)
    if p is None:
        raise DatasetError(f"데이터셋 경로가 없다: --dataset 또는 {ENV}")
    if (p / "cases.json").exists():
        return p
    inner = [d for d in p.glob("*") if (d / "cases.json").exists()]
    if len(inner) == 1:                      # 묶음 폴더(…_2026-11-23/generator_eval_v2_2026-11-23)를 줘도 찾는다
        return inner[0]
    raise DatasetError(f"cases.json 이 없다: {p}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(root: Path) -> list[str]:
    """manifest.sha256.json 과 파일 해시 대조. 문제 목록 (빈 목록 = 통과)"""
    man = root / "manifest.sha256.json"
    if not man.exists():
        return ["manifest.sha256.json 없음"]
    problems = []
    for rel, want in json.loads(man.read_text(encoding="utf-8")).items():
        f = root / rel
        if not f.exists():
            problems.append(f"없음: {rel}")
        elif sha256(f) != want:
            problems.append(f"해시 불일치: {rel}")
    return problems


def load(root: Path, *, verify: bool = True) -> dict:
    if verify and (bad := verify_hashes(root)):
        raise DatasetError("; ".join(bad[:5]) + (f" 외 {len(bad) - 5}건" if len(bad) > 5 else ""))
    raw = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    cases = [Case.model_validate(c) for c in raw["cases"]]
    probes = [Probe.model_validate(p) for p in json.loads((root / "evaluator_probes.json").read_text(encoding="utf-8"))]
    return {"name": raw.get("name"), "version": str(raw.get("version")), "raw": raw, "cases": cases, "probes": probes}


def questions(ds: dict) -> dict[str, Question]:
    return {c.id: to_question(c, version=ds["version"]) for c in ds["cases"]}


def input_path(root: Path, case_id: str, condition: str = "isolated") -> Path:
    return root / ("oracle_m3_inputs" if condition == "m3_only" else "inputs") / f"{case_id}.json"


# ── [NEW] 입력 슬롯 overlay: 데이터셋 입력의 query_bundle 은 의도만 있다 → 운영 질의 분석 형식의 슬롯을 덧씌운다 ──
def load_slots(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise DatasetError(f"슬롯 파일 없음: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {"path": p, "sha256": sha256(p), "slots": doc.get("slots") or {}}


def slot_errors(root: Path, slots: dict, case_ids: set[str]) -> list[str]:
    errs = []
    for cid, s in slots.items():
        if cid not in case_ids:
            errs.append(f"{cid}: 데이터셋에 없는 문항")
            continue
        qb = json.loads(input_path(root, cid).read_text(encoding="utf-8"))["query_bundle"]
        n = max(len(qb.get("sub_questions") or []), 1)
        if len(s.get("sub_filters") or []) != n:
            errs.append(f"{cid}: sub_filters {len(s.get('sub_filters') or [])}개 / 하위 질문 {n}개")
        for f in [s.get("filters") or {}] + list(s.get("sub_filters") or []):
            if bad := set(f) - SLOT_KEYS:
                errs.append(f"{cid}: 모르는 슬롯 {sorted(bad)}")
            try:
                Filters.model_validate(f)                   # 운영 계약 그대로 (A0 가 같은 스키마로 검사한다)
            except ValidationError as e:
                errs.append(f"{cid}: Filters 스키마 위반 {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
    return errs


def apply_slots(inp: dict, slot: dict | None) -> dict:
    """query_bundle 과 viewset.view_bundle 의 filters · sub_filters 를 바꾼 사본. 질문 · 하위 질문 · ViewSet 내용은 그대로"""
    if not slot:
        return inp
    out = json.loads(json.dumps(inp, ensure_ascii=False))
    for vb in (out.get("query_bundle"), (out.get("viewset") or {}).get("view_bundle")):
        if isinstance(vb, dict):
            vb["filters"] = slot["filters"]
            vb["sub_filters"] = slot["sub_filters"]
    return out


def slot_hash(input_sha: str, slot: dict | None) -> str:
    if not slot:
        return input_sha
    return hashlib.sha256((input_sha + json.dumps(slot, ensure_ascii=False, sort_keys=True)).encode("utf-8")).hexdigest()


def chart_name_errors(cases: list[Case]) -> list[str]:
    """[NEW] coverage 에 chart_request 가 있는 문항: 질문의 차트 이름이 평가기 이름표로 해석되고 required_chart 와 맞는가.
    forbidden 문항은 acceptable_types 가 [null] 이라 요청 유형을 질문에서만 얻는다 → 이름표가 못 읽으면 요청 해석(request_parse)을 판정할 수 없다"""
    errs = []
    for c in cases:
        if "chart_request" not in c.coverage:
            continue
        named, unknown = requested_charts(c.question)
        codes = {code for _, code in named}
        if unknown:
            errs.append(f"{c.id}: 이름표에 없는 차트 이름 {unknown}")
        elif not codes:
            errs.append(f"{c.id}: 질문에서 차트 이름을 찾지 못함")
        elif c.required_chart.mode == "required" and codes != {t for t in c.required_chart.acceptable_types if t}:
            errs.append(f"{c.id}: 질문 {sorted(codes)} / acceptable_types {c.required_chart.acceptable_types}")
    return errs


# ── [NEW] 대규모 실행: 샤딩 · 재개 · ID 파일 ───────────────────────────
def parse_shard(arg: str | None) -> tuple[int, int] | None:
    """'I/N' (1부터) → (I-1, N). 없으면 None"""
    if not arg:
        return None
    try:
        i, n = (int(x) for x in arg.split("/"))
    except ValueError:
        raise DatasetError(f"--shard 는 I/N 형식이다: {arg}") from None
    if not 1 <= i <= n:
        raise DatasetError(f"--shard 범위 오류: {arg}")
    return i - 1, n


def shard_of(case_id: str, n: int) -> int:
    """sha1(id) % n. 입력 순서(V · A · H 반복)와 무관하게 느린 문항(H)이 한 샤드에 몰리지 않는다"""
    return int(hashlib.sha1(case_id.encode("utf-8")).hexdigest(), 16) % n


def read_ids(path: str | Path) -> set[str]:
    """줄 단위 문항 ID. 빈 줄 · # 주석 무시"""
    return {s for x in Path(path).read_text(encoding="utf-8").splitlines() if (s := x.split("#")[0].strip())}


def read_complete_lines(path: str | Path) -> list[str]:
    """실행 기록(.gz)의 온전한 줄. 프로세스가 중간에 죽으면 gzip 이 끝나지 않은 채 남는다 → 읽을 수 있는 데까지만 돌려준다
    read() 는 끝나지 않은 스트림에서 이미 풀린 데이터까지 버리고 EOFError 를 내므로 read1() 로 읽는다"""
    p = Path(path)
    if not p.exists():
        return []
    raw = b""
    try:
        with gzip.open(p, "rb") as f:
            while chunk := f.read1(1 << 16):
                raw += chunk
    except (EOFError, OSError):
        pass
    parts = raw.split(b"\n")
    if raw and not raw.endswith(b"\n"):
        parts = parts[:-1] if len(parts) > 1 or not _is_json(parts[-1]) else parts          # 끝이 잘린 마지막 줄은 버린다
    ok = []
    for x in parts:
        if x.strip() and _is_json(x):
            ok.append(x.decode("utf-8"))
    return ok


def _is_json(b: bytes) -> bool:
    try:
        json.loads(b.decode("utf-8"))
    except ValueError:
        return False
    return True


def done_keys(path: str | Path) -> set[tuple[str, int]]:
    out = set()
    for x in read_complete_lines(path):
        r = json.loads(x)
        out.add((r["id"], int(r.get("run", 1))))
    return out


def salvage(path: str | Path) -> int:
    """재개 전 처리: 온전한 줄만 새 gz 로 다시 쓴다(원자적 교체). 끝나지 않은 gzip 뒤에 이어 쓰면 스트림이 깨지기 때문이다. 보존한 줄 수를 돌려준다"""
    p = Path(path)
    lines = read_complete_lines(p)
    if not p.exists():
        return 0
    tmp = p.with_suffix(p.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for x in lines:
            f.write(x + "\n")
    tmp.replace(p)
    return len(lines)


def field_loss(raw_cases: list[dict], cases: list[Case]) -> list[str]:
    """모델을 거친 뒤 사라진 키 (스키마가 원본 필드를 버리면 판정 근거가 빠진다)"""
    def keys(x, pre=""):
        if isinstance(x, dict):
            return {f"{pre}{k}" for k in x} | {k2 for k, v in x.items() for k2 in keys(v, f"{pre}{k}.")}
        if isinstance(x, list):
            return {k2 for v in x for k2 in keys(v, pre)}
        return set()
    lost = set()
    for r, c in zip(raw_cases, cases):
        lost |= keys(r) - keys(c.model_dump(mode="json"))
    return sorted(lost)


# ── probe: 기준 문항의 정답 계산 결과 + 후보 최종 답변 → RunRecord ───────────────
def _row(records: list[dict], alias: dict) -> tuple[dict, list]:
    rec = next(r for r in records if r["id"] == alias["record_id"])
    return rec, rec["table"]["rows"][alias["row_index"]]


def gold_run(case: Case, inp: dict, answer: str) -> dict:
    """정답 계산 결과(M3 · 표시 설정)를 고정하고 최종 답변만 후보로 바꾼 실행 기록. 판정은 judge() 경로 그대로"""
    vs = inp["viewset"]
    records = vs["records"]
    qid = inp["query_bundle"]["query_id"]
    calcs, steps, displays, withheld, shown = [], [], {}, [], set()
    for i, s in enumerate(case.sub_questions, 1):
        sid = f"{qid}-{i}"
        if s.expected_status != "answer" or not s.claims:
            withheld.append({"sub_question_id": sid, "text": "가시 근거에 자료가 없어 계산하지 못했습니다"})
            continue
        step = f"a{i}"
        cl = s.claims[0]
        ins = []
        for n, ev in enumerate(cl.evidence_ids):
            rec, row = _row(records, case.evidence_aliases[ev])
            cols = rec["table"]["columns"]
            ins.append({"role": "value", "record_id": rec["id"], "item": row[cols.index("항목")],
                        "key": {"시점": str(row[cols.index("시점")])}, "value": row[-1], "unit": rec["metadata"].get("unit")})
            shown |= {f"{step}.in{n}", f"{step}.in{n}.abs"}
        op = cl.calculation.op or "raw"
        periods = cl.binding.period
        # M3 는 raw 결과를 점 목록({key: {시점}, value})으로 낸다. 두 시점을 쓰는 change · growth_rate 는 단일 값
        value = [{"key": {"시점": periods[0]}, "value": float(cl.value)}] if op == "raw" and len(periods) == 1 else float(cl.value)
        calcs.append({"step_id": step, "sub_question_id": sid, "op": op, "value": value, "unit": cl.unit,
                      "display_ref": f"d{i}", "inputs": ins, "record_ids": sorted({x["record_id"] for x in ins}), "note": None})
        steps.append({"step_id": step, "op": op, "sub_question_id": sid,
                      "operands": [{"record_id": x["record_id"], "select": {}} for x in ins]})
        displays[f"d{i}"] = {"source_unit": cl.unit, "display_unit": cl.display.unit, "unit_scale": float(cl.display.scale),
                             "digits": cl.display.digits}
        shown |= {step, f"{step}.abs"}
    m3 = {"query_id": qid, "chart_plan": {"answer_steps": steps, "warnings": [w["text"] for w in withheld], "withheld": withheld},
          "chart_contents": [], "calc_results": calcs, "displays": displays, "validation": {}}
    m6 = {"query_id": qid, "answer": answer, "insufficient": bool(withheld), "method": "hcx", "tables": [], "caveats": [],
          "used_step_ids": [c["step_id"] for c in calcs], "notes": []}
    charts = [{"chart_id": f"{qid}-c{i}", "sub_question_ids": [f"{qid}-{i}"], "chart_type": None, "measure": "raw"}
              for i in range(1, len(case.sub_questions) + 1)]
    return {"id": case.id, "run": 1, "ok": True, "source": "full", "mode": "probe", "condition": "probe",
            "dataset": "v2", "question": case.question, "analysis": {"status": "ok", "notes": []}, "viewset": vs,
            "records": records, "m6_shown_tokens": sorted(shown),
            "modules": {"charts": charts, "chart_plan": {"charts": []}, "module3": m3, "answer": m6, "drawn": [], "notes": [],
                        "qa": {}, "render_status": {}, "request_outcomes": [], "chart_notices": []},
            "result": {"answer": answer, "caveats": []}}


def probe_verdict_ok(probe_id: str, expected: str, verdict: str) -> bool:
    """pass → 통과, fail → 미달 또는 보류. 다만 J09(하위 질문 누락)는 보류여야 한다"""
    if expected == "pass":
        return verdict == "통과"
    if probe_id == "J09":
        return verdict == "보류"
    return verdict in ("미달", "보류")


# ── fixture ─────────────────────────────────────────────────────
def _canon(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fixture_hash(fx: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in fx.items() if k != "fixture_sha256"}).encode("utf-8")).hexdigest()


def build_fixture(root: Path) -> dict:
    ds = load(root)
    by = {c.id: c for c in ds["cases"]}
    bases = sorted({p.base_case_id for p in ds["probes"]})
    man = json.loads((root / "manifest.sha256.json").read_text(encoding="utf-8"))
    fx = {"dataset": ds["name"], "dataset_version": ds["version"],
          "source_sha256": {k: man[k] for k in ("cases.json", "evaluator_probes.json")},
          "input_sha256": {b: man.get(f"inputs/{b}.json") for b in bases},
          "probes": [p.model_dump(mode="json") for p in ds["probes"]],
          "cases": {b: by[b].model_dump(mode="json") for b in bases},
          "inputs": {}}
    for b in bases:
        inp = json.loads(input_path(root, b).read_text(encoding="utf-8"))
        fx["inputs"][b] = {"query_bundle": inp["query_bundle"],
                           "viewset": {k: inp["viewset"][k] for k in ("status", "query_id", "original", "records", "view_bundle")},
                           "m6_visible_record_ids": inp.get("m6_visible_record_ids")}
    fx["fixture_sha256"] = fixture_hash(fx)
    return fx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "fixture"])
    ap.add_argument("--dataset")
    ap.add_argument("--out", type=Path, default=FIXTURE)
    ap.add_argument("--slots", type=Path, help="슬롯 overlay (기본 검증 안 함)")
    a = ap.parse_args(argv)
    try:
        root = dataset_dir(a.dataset)
        if a.cmd == "fixture":
            fx = build_fixture(root)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(fx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print("wrote", a.out, len(fx["probes"]), "probes")
            return 0
        ds = load(root)
    except (DatasetError, OSError, KeyError, ValueError) as e:
        print(f"[v2 check] 실패: {e}", file=sys.stderr)
        return 1
    cases = ds["cases"]
    n_sub = sum(len(c.sub_questions) for c in cases)
    n_claim = sum(len(s.claims) for c in cases for s in c.sub_questions)
    missing_inputs = [c.id for c in cases if not input_path(root, c.id).exists()]
    lost = field_loss(ds["raw"]["cases"], cases)
    print(f"[v2 check] {ds['name']} v{ds['version']}: 문항 {len(cases)} · 하위 질문 {n_sub} · claim {n_claim} · probe {len(ds['probes'])}")
    print(f"[v2 check] 해시 통과 · 입력 누락 {missing_inputs or '없음'} · 필드 손실 {lost or '없음'}")
    questions(ds)
    cerr = chart_name_errors(cases)
    print(f"[v2 check] 차트 이름 정합성 위반 {cerr[:5] or '없음'}" + (f" 외 {len(cerr) - 5}건" if len(cerr) > 5 else ""))
    serr = []
    if a.slots:
        try:
            sl = load_slots(a.slots)
        except (DatasetError, ValueError) as e:
            print(f"[v2 check] 슬롯 실패: {e}", file=sys.stderr)
            return 1
        serr = slot_errors(root, sl["slots"], {c.id for c in cases})
        print(f"[v2 check] 슬롯 {len(sl['slots'])}문항 · 오류 {serr or '없음'}")
    return 1 if missing_inputs or lost or serr or cerr else 0


if __name__ == "__main__":
    sys.exit(main())
