"""CLI — 질문 → 분석(되묻기) → 검색·View(충돌이면 선택) → 답변

  python -m backend.agent "작년 대전 인구 수"                 # 되묻기·선택을 터미널에서 물어봄
  python -m backend.agent "작년 대전 인구 수" --select first  # 충돌이면 첫 선택지 (묻지 않음)
  python -m backend.agent "…" --json out.json                 # 전체 응답 저장
"""
import argparse
import json
import sys


def _ask(prompt, choices):
    while True:
        a = input(prompt).strip()
        if a in choices:
            return a
        if a.isdigit() and 1 <= int(a) <= len(choices):
            return choices[int(a) - 1]
        print(f"  다음 중 하나: {', '.join(choices)} (또는 번호)")


def _clarify(analysis):
    sels = {}
    for c in analysis.get("clarifications") or []:
        print(f"\n[되묻기] {c['slot']}: {c.get('reason', '')}")
        opts = (c.get("options") or [])[:20]
        for i, o in enumerate(opts, 1):
            print(f"  {i}) {o.get('label') or o['value']}")
        sels[c["slot"]] = [_ask("  번호 또는 값: ", [str(o["value"]) for o in opts])]
    return sels


def _select(views):
    picks = []
    for p in views["pending"]:
        print(f"\n[선택 필요] 단위 {p['unit_id']} — 같은 교차점의 값이 표마다 다릅니다")
        for i, o in enumerate(p["options"], 1):
            print(f"  {i}) {o['option_id']}  {o['tbl_nm']}  ({', '.join(o['tbl_ids'])})  {o.get('survey_nm') or ''}")
            for v in o["value_preview"][:3]:
                others = ", ".join(f"{x['tbl_id']}={x['value']}{x['unit']}" for x in v["others"])
                print(f"       {v['key_str']}: {v['value']} {v['unit']}   (다른 표: {others})")
            for fn in o["footnotes"][:3]:
                print(f"       ※ [{fn['type']}{' ' + fn['target'] if fn.get('target') else ''}] {fn['text'][:100]}")
        picks.append({"selection_token": p["selection_token"],
                      "option_id": _ask("  선택 (번호 또는 opt-n): ", [o["option_id"] for o in p["options"]])})
    return picks


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.agent")
    ap.add_argument("question")
    ap.add_argument("--today")
    ap.add_argument("--n-views", type=int)
    ap.add_argument("--select", choices=["ask", "first"], default="ask")
    ap.add_argument("--json", help="전체 응답을 JSON 파일로")
    a = ap.parse_args()

    from backend.agent.pipeline import run_chat
    out = run_chat(a.question, a.today, n_views=a.n_views, auto_select=a.select == "first")
    while out["status"] in ("needs_clarification", "needs_selection") and a.select == "ask":
        if out["status"] == "needs_clarification":
            out = run_chat(a.question, a.today, n_views=a.n_views, auto_select=False, previous=out,
                           selections=_clarify(out["analysis"]))
        else:
            out = run_chat(a.question, a.today, n_views=a.n_views, auto_select=False, previous=out,
                           view_selections=_select(out["views"]))

    an = out.get("analysis") or {}
    print(f"\n분석: {an.get('status')} | 검색 문장: {an.get('search_text')}")
    for u in (out.get("views") or {}).get("units") or []:
        c = u["conflict"]
        print(f"  [{u['unit_id']}] {u['search_query']} → {[v['tbl_id'] for v in u['views']]} 충돌 {c['status']}"
              f"{' 선택 ' + c['selected_option'] if c.get('selected_option') else ''}")
    res = out.get("result") or {}
    print(f"\n상태: {out['status']}  ({out['timings'].get('total')}초)\n")
    print(res.get("answer") or "(답변 없음)")
    for s in res.get("sources") or []:
        print("  출처:", s)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=str)
        print("저장:", a.json)


if __name__ == "__main__":
    main()
