"""
생성 실패 진단 — 왜 채택되지 않았는가를 한 화면으로

읽는 것 (쓰기 없음)
  <output_root>/reports/generation_report.json        단계별 통과율 · 탈락 원인 수 · 작업별 API 호출
  <output_root>/rejected_samples/rejected_samples.jsonl  샘플마다 탈락 단계 · 코드 · 이유 · 마지막 계획

출력
  1) 단계 깔때기: 계획 생성 → 통계 호환 → 계산 → Ablation → 질문 생성 → 수치 검증 → 의미 검수
  2) 탈락 단계·코드별 수, 코드마다 자주 나온 이유 문장 (숫자·ID 는 묶어서 셈) + 예시 샘플
  3) 계획(LLM) 재시도 분포 · 작업별 API 호출 → 어디서 호출을 많이 썼는지
  4) 가장 많은 탈락 코드의 마지막 계획 한 개 (operands 요약)

실행  python -m synthetic_gold_pipeline.diagnose [--output-root synthetic_gold_pipeline/outputs] [--examples 3]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from synthetic_gold_pipeline.utils import load_config, read_jsonl, resolve_path

FUNNEL = [("plan_generation_success", "계획 생성"), ("statistical_compatibility_success", "통계 호환(계획 검증)"),
          ("calculation_success", "결정론적 계산"), ("ablation_pass", "Ablation(View 필요성)"),
          ("question_generation_success", "역방향 질문 생성"), ("numeric_validation_pass", "답변 수치 검증"),
          ("semantic_review_pass", "LLM 의미 검수")]
HINTS = {
    "llm:LLM_RESPONSE_ERROR": "LLM 응답 오류. 이유가 'HTTP 429' 면 호출 한도 초과 → llm.rate_limit(QPM·TPM) 설정. "
                              "그 외는 스키마(JSON) 불일치 → max_tokens 부족(잘림)·구조화 출력 확인",
    "statistical_validation_plan": "계획이 통계 규칙(주기·모집단·단위·분모)에 어긋남 → 이유 문장 확인",
    "calculation": "계획의 좌표(레벨·코드·항목·시점)가 View 와 맞지 않음 → UNKNOWN_*/CARDINALITY 이면 계획 품질 문제",
    "ablation": "고른 View 중 답에 필요 없는 View 가 있음 (멀티뷰 조건 미충족)",
    "numeric_self_check": "LLM 이 쓴 답변 문장의 숫자·단위·지역/연도 연결이 계산값과 다름",
    "semantic_review": "LLM 검수가 질문을 거부 (조건 누락·모호·멀티홉 불필요 등)",
    "reverse_qa": "질문 생성 응답이 결정론적 검사(자리표시자·조건 라벨)를 통과하지 못함",
    "internal_error": "코드 예외 — 로그의 Traceback 확인 (버그)",
}


def _norm(msg: str) -> str:
    m = re.sub(r"sgv::\S+", "<view>", str(msg))
    m = re.sub(r"\b(S\d+_\d+|P_\S+|DT_\w+|\d{3}_DT_\w+)\b", "<id>", m)
    m = re.sub(r"\d+(\.\d+)?", "N", m)
    return m[:160]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m synthetic_gold_pipeline.diagnose")
    ap.add_argument("--config", default="synthetic_gold_pipeline/configs/pipeline.yaml")
    ap.add_argument("--output-root", default=None)
    ap.add_argument("--examples", type=int, default=2)
    a = ap.parse_args(argv)
    root = resolve_path(a.output_root or load_config(a.config).get("paths", {}).get("output_root")
                        or "synthetic_gold_pipeline/outputs")
    rep_p = root / "reports" / "generation_report.json"
    rej_p = root / "rejected_samples" / "rejected_samples.jsonl"
    rep = json.loads(rep_p.read_text(encoding="utf-8")) if rep_p.exists() else {}
    rej = list(read_jsonl(rej_p)) if rej_p.exists() else []
    print(f"출력 폴더: {root}")
    if rep:
        print(f"채택 {rep.get('final_dataset_count')} · 처리 샘플 {rep.get('processed_samples')} · "
              f"샘플링 시도 {rep.get('total_sampling_attempts')} (실패 {rep.get('sampling_failed')}) · "
              f"LLM {rep.get('api', {}).get('provider')}/{rep.get('api', {}).get('model')}")
        rates = rep.get("rates_over_processed_samples") or {}
        print("\n[1] 단계 깔때기 (처리 샘플 중 통과 비율)")
        for k, label in FUNNEL:
            v = rates.get(k)
            bar = "█" * int(round((v or 0) * 30))
            print(f"  {label:22s} {('-' if v is None else f'{v * 100:5.1f}%'):>7s} {bar}")
        api = rep.get("api") or {}
        print(f"\n[3] API 호출 {api.get('calls')} (구조화 재요청 {api.get('structured_retries')}, 일시 오류 재시도 "
              f"{api.get('transient_retries')}, 실패 {api.get('failed_calls')}, 한도 초과 429 {api.get('rate_limited', '-')}"
              f" · 한도 대기 {api.get('rate_limit_wait_seconds', 0):.0f}초) · 계획 자기수정 "
              f"{rep.get('planner_self_correction_retries')}")
        for task, v in (api.get("by_task") or {}).items():
            print(f"  {task:22s} 호출 {v.get('calls'):>5} · 실패 {v.get('failures', 0):>4} · "
                  f"평균 {v.get('latency_ms', 0) / max(1, v.get('calls', 1)) / 1000:.1f}초")
    if not rej:
        print("\n탈락 기록 없음:", rej_p)
        return 0
    by = Counter((r["stage"], (r.get("codes") or ["UNKNOWN"])[0]) for r in rej)
    print(f"\n[2] 탈락 {len(rej)}건 — 단계·코드별")
    msgs = defaultdict(Counter)
    ex = defaultdict(list)
    for r in rej:
        key = (r["stage"], (r.get("codes") or ["UNKNOWN"])[0])
        for m in (r.get("reasons") or [""])[:3]:
            msgs[key][_norm(m)] += 1
        if len(ex[key]) < a.examples:
            ex[key].append(r)
    for (stage, code), n in by.most_common():
        hint = HINTS.get(f"{stage}:{code}") or HINTS.get(stage, "")
        print(f"\n  ■ {stage} / {code}: {n}건 ({n / len(rej) * 100:.0f}%)" + (f"\n    → {hint}" if hint else ""))
        for m, c in msgs[(stage, code)].most_common(4):
            print(f"    {c:>4}× {m}")
        for r in ex[(stage, code)]:
            first = str((r.get("reasons") or [""])[0])
            if stage == "internal_error":                 # Traceback 은 끝부분(예외가 난 줄)이 중요
                tail = "\n      ".join(first.strip().splitlines()[-8:])
                print(f"    예) {r['sample_id']} {r['reasoning_type']}/{r['subtype']}\n      {tail}")
                continue
            print(f"    예) {r['sample_id']} {r['reasoning_type']}/{r['subtype']} · 계획 시도 {r.get('planner_attempts')} · "
                  f"이유: {first[:220]}")
            if r.get("qa_last_output"):
                print(f"        LLM 마지막 응답: {str(r['qa_last_output'])[:300]}")
            if r.get("question_original"):
                print(f"        질문(O): {r['question_original'][:200]}\n        질문(P): {str(r.get('question_paraphrased'))[:200]}")
            if r.get("plan_repairs"):
                print(f"        자동 보정: {'; '.join(r['plan_repairs'][-3:])[:260]}")
    n_rep = sum(bool(r.get("plan_repairs")) for r in rej)
    kinds = Counter(re.sub(r"^\[시도 \d+\] \S+: ", "", x).split(" ")[0] for r in rej for x in r.get("plan_repairs") or [])
    print(f"\n  계획 자동 보정이 들어간 탈락 샘플 {n_rep}/{len(rej)} · 보정 종류 {dict(kinds.most_common(6))}")
    pa = Counter(r.get("planner_attempts") for r in rej)
    print(f"\n  계획 시도 횟수 분포: {dict(sorted(pa.items(), key=lambda x: (x[0] is None, x[0])))}")
    (stage, code), _ = by.most_common(1)[0]
    r = next((x for x in rej if x["stage"] == stage and (x.get("codes") or ["UNKNOWN"])[0] == code and x.get("last_plan")),
             None)
    if r:
        lp = r["last_plan"]
        print(f"\n[4] 가장 많은 탈락({stage}/{code})의 마지막 계획 예 — {r['sample_id']}")
        print(f"  plan_status={lp.get('plan_status')} reject_reason={lp.get('reject_reason')}")
        for o in (lp.get("operands") or [])[:4]:
            print(f"  operand {o.get('operand_id')}: view={str(o.get('view_id'))[:60]} itm={o.get('itm_id')} "
                  f"prd={o.get('prd_de')} coords={o.get('coordinates')} group_by={o.get('group_by_level')!r}")
        steps = ((lp.get("operation") or {}).get("steps") or [])[:4]
        for s in steps:
            print(f"  step {s.get('step_id')}: {s.get('op')} {s.get('inputs')} {s.get('params')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
