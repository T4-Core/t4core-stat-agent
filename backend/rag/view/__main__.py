"""[NEW v4] CLI — 질문 → 분석(되묻기) → View 묶음 → 충돌이면 선택 → 최종 Record 요약

  python -m backend.rag.view "작년 대전 인구 수"                       # 되묻기·선택을 터미널에서 물어봄
  python -m backend.rag.view "작년 대전 인구 수" --select first        # 충돌이면 첫 선택지 (묻지 않음)
  python -m backend.rag.view --bundle bundle.json --config hybrid_rrf_hcx --json out.json
  python -m backend.rag.view --token <selection_token> --option opt-2  # 토큰만으로 선택 (다른 실행에서 받은 것)
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


def _print_options(p):
    print(f"\n[선택 필요] 단위 {p['unit_id']} — 같은 교차점의 값이 표마다 다릅니다")
    for i, o in enumerate(p["options"], 1):
        print(f"  {i}) {o['option_id']}  {o['tbl_nm']}  ({', '.join(o['tbl_ids'])})  {o.get('survey_nm') or ''}")
        for v in o["value_preview"][:3]:
            others = ", ".join(f"{x['tbl_id']}={x['value']}{x['unit']}" for x in v["others"])
            print(f"       {v['key_str']}: {v['value']} {v['unit']}   (다른 표: {others})")
        for fn in o["footnotes"][:3]:
            print(f"       ※ [{fn['type']}{' ' + fn['target'] if fn.get('target') else ''}] {fn['text'][:100]}")
        print(f"       기준: {json.dumps({k: v for k, v in o['basis'].items() if v}, ensure_ascii=False)[:160]}")


def _clarify(a, today):
    from backend.rag.query_analyzer.v4 import analyze
    sels = {}
    for c in a.get("clarifications") or []:
        print(f"\n[되묻기] {c['slot']}: {c.get('reason', '')}")
        opts = c.get("options") or []
        for i, o in enumerate(opts[:20], 1):
            print(f"  {i}) {o.get('label') or o['value']}")
        sels[c["slot"]] = [_ask("  번호 또는 값: ", [str(o["value"]) for o in opts[:20]])]
    return analyze(a["question"], today, query_id=a.get("query_id"), previous=a, selections=sels)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--bundle", help="view_bundle JSON 파일 (질문 대신)")
    ap.add_argument("--today")
    ap.add_argument("--config", help="검색 구성 (configs/retrieval/<이름>)")
    ap.add_argument("--n-views", type=int)
    ap.add_argument("--select", choices=["ask", "first", "none"], default="ask")
    ap.add_argument("--json", help="최종 결과를 JSON 파일로")
    ap.add_argument("--token")
    ap.add_argument("--option")
    a = ap.parse_args()

    from backend.rag.view import apply_selections, build_viewset, resolve
    if a.token:
        r = resolve(a.token, a.option)
        print(json.dumps({k: v for k, v in r.items() if k != "records"} | {"record_ids": [x["id"] for x in r["records"]]},
                         ensure_ascii=False, indent=1))
        return
    if a.bundle:
        src = json.loads(open(a.bundle, encoding="utf-8").read())
    else:
        from backend.rag.query_analyzer.v4 import analyze
        src = analyze(a.question, a.today)
        while src["status"] == "needs_clarification" and a.select == "ask":
            src = _clarify(src, a.today)
        print("분석:", src["status"], "| 검색 문장:", src.get("search_text"))
    first = (lambda c: c["options"][0]["option_id"]) if a.select == "first" else None
    vs = build_viewset(src, today=a.today, retrieval_config=a.config, n_views=a.n_views, on_ambiguous=first)
    if vs["status"] == "needs_selection" and a.select == "ask":
        picks = []
        for p in vs["pending"]:
            _print_options(p)
            picks.append({"selection_token": p["selection_token"],
                          "option_id": _ask("  선택 (번호 또는 opt-n): ", [o["option_id"] for o in p["options"]])})
        vs, _ = apply_selections(vs, picks)
    print(f"\n상태: {vs['status']}  ({vs.get('seconds')}초)")
    for u in vs["units"]:
        c = u["conflict"]
        print(f"  [{u['unit_id']}] {u['search_query']} → {c['status']}"
              f"{' 선택 ' + c['selected_option'] if c.get('selected_option') else ''}  {' / '.join(c['notes'])}")
    print("records:")
    for r in vs["records"]:
        print(f"  {r['id']}  ({len(r['table']['rows'])}행)")
    if vs["status"] == "needs_selection":
        for p in vs["pending"]:
            print(f"  선택 대기 {p['unit_id']}: --token {p['selection_token'][:24]}… --option {p['options'][0]['option_id']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(vs, f, ensure_ascii=False, indent=1, default=str)
        print("저장:", a.json)


if __name__ == "__main__":
    main()
