"""
서브쿼리 분리만 확인 — VS Code 에서 바로 실행 (Swagger 없이)

  python check_subquery.py "2021~2025년 혼인건수와 출생아수 그리고 사망자수 추이"
      → v4 분석 전체 (HCX 1회): 재작성(v3) 슬롯 · HCX 하위 질문 · 접지 결과 · 1-5 분리 판단을 단계별로 출력
  python check_subquery.py --no-hcx --slots '{"시점":["2021년"],"지표":["혼인건수","출생아수","사망자수"]}'
      → HCX 없이 1-5 분리 규칙만 (슬롯을 직접 줘서 '이 지표 조합이면 나뉘는가' 확인)
  --policy always | no_common_table   분리 정책을 이번 실행만 바꿔 보기

저장소 루트에 두고 실행. backend 코드는 읽기만 함.
"""
import argparse
import json
import sys


def show(title, obj):
    print(f"\n── {title}")
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str)[:3000])


def run_full(question, today, overrides=None):
    from backend.rag.query_analyzer.v4 import analyze
    a = analyze(question, today=today, overrides=overrides)
    st = a.get("state") or {}
    print(f"상태: {a['status']}")
    show("① 재작성(v3) 메인 슬롯 — HCX 가 어느 칸에 넣었나", st.get("raw_slots"))
    show("② 재작성(v3) 하위 질문 슬롯 (HCX 가 나눈 것, 검증 후)", st.get("sub_slots"))
    show("③ 접지 결과 (CSV 값 사전으로 확인한 지표·대상·지역)",
         {k: [(v["raw"], v["value"] if not isinstance(v["value"], dict) else str(v["value"]), v["source"], v["n_tables"])
              for v in vs] for k, vs in (a.get("slots") or {}).items()})
    print(f"\n── ④ 1-5 서브쿼리 분리 판단\n  {a.get('decompose_reason') or '(분리 단계 전에 멈춤: ' + a['status'] + ')'}")
    for s in a.get("sub_queries") or []:
        print(f"  {s['id']}: {s['text']}  ← {s['reason']}  (후보 표 {len(s.get('candidate_tables') or [])}개)")
    if a.get("clarifications"):
        show("되묻기 (필수 슬롯 부족)", [{"slot": c["slot"], "reason": c["reason"]} for c in a["clarifications"]])
    print("\n── 메모")
    for n in a.get("notes") or []:
        print("  -", n)
    step = next((t for t in a.get("trace") or [] if str(t.get("step", "")).startswith("1-5")), None)
    if step:
        show("1-5 단계 기록 (trace)", step)
    fix = next((t for t in a.get("trace") or [] if str(t.get("step", "")).startswith("1-2 지역 칸")), None)
    if fix and fix.get("output"):
        show("1-2 지역 칸 바로잡기 (지역 칸 → 지표로 옮긴 값)", fix["output"])
    if a["status"] == "needs_clarification" and st.get("raw_slots"):
        print("\n── (참고) 되묻기를 무시하고 같은 슬롯으로 1-5 분리만 돌리면:")
        run_rule_only(st["raw_slots"], st.get("intents") or [], quiet=True, overrides=overrides)


def run_rule_only(slots, intents, quiet=False, overrides=None):
    from backend.core.settings_v4 import with_overrides
    from backend.rag.query_analyzer.v4.decompose import decompose
    from backend.rag.query_analyzer.v4.grounding import ground_slots
    from backend.rag.query_analyzer.v4.lexicon import get_lexicon
    from backend.rag.query_analyzer.v4.pipeline import fix_region_slots
    s = with_overrides(overrides)
    lex = get_lexicon(settings=s)
    slots, moved = fix_region_slots(slots, lex)
    if moved:
        print(f"\n── 지역 칸 → 지표로 옮김: {moved}")
    print(f"── 분리 정책: {s.split_policy} (최대 {s.max_sub_queries}개)")
    g, notes = ground_slots(slots, lex)
    if not quiet:
        show("접지 결과", {k: [(v["raw"], v["value"] if not isinstance(v["value"], dict) else str(v["value"]), v["source"],
                            v["n_tables"]) for v in vs] for k, vs in g.items()})
    subs, reason = decompose(g, slots, [], intents, [], lex, s)
    print(f"\n── 1-5 서브쿼리 분리 판단\n  {reason}")
    for x in subs:
        print(f"  {x['id']}: {x['text']}  ← {x['reason']}")
    for n in notes:
        print("  -", n)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="2021~2025년 혼인건수와 출생아수 그리고 사망자수 추이")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (비우면 오늘)")
    ap.add_argument("--no-hcx", action="store_true", help="HCX 없이 1-5 분리 규칙만 (--slots 필요)")
    ap.add_argument("--slots", default='{"지표": ["혼인건수", "출생아수", "사망자수"]}')
    ap.add_argument("--intents", nargs="*", default=["추이"])
    ap.add_argument("--policy", choices=["always", "no_common_table"], default=None,
                    help="1-5 분리 정책 (비우면 configs/query_v4.yaml 의 split_policy)")
    a = ap.parse_args()
    ov = {"split_policy": a.policy} if a.policy else None
    if a.no_hcx:
        run_rule_only(json.loads(a.slots), a.intents, overrides=ov)
    else:
        run_full(a.question, a.today, ov)
