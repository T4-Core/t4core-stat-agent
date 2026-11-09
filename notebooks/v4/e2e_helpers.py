"""[NEW v4] pipeline_v4_e2e.ipynb 화면 출력용 함수 — 계산은 모두 backend 함수 (API·CLI 와 같음)

  r = run_one("2025년 대전 인구 수", CFG)     # ①~④ 결과를 dict 하나에
  show(r)                                    # 단계별 표
  summary_table(R)                           # 질문 여러 개 요약
  choose(R, 질문, "opt-2")                    # 충돌 선택 반영 → 최종 View

CFG = {"today", "query_overrides", "retrieval_configs", "view_config", "n_views", "clarify", "select", "max_view_rows"}
  clarify: "first" | "ask" | {질문: {슬롯: [값]}} | None
  select : "first" | "ask" | {질문: "opt-n"} | None
"""
import json
import time

import pandas as pd
from IPython.display import Markdown, display

from backend.core.settings_v4 import with_overrides
from backend.core.tracking import Tracer
from backend.rag.ingestion.resolve import search_query
from backend.rag.ingestion.views import units_of
from backend.rag.query_analyzer.v4 import analyze
from backend.rag.retrieval.factory import get_pipeline, load_config, missing_requirements
from backend.rag.view import apply_selections, build_viewset

DEFAULT = {"today": None, "query_overrides": {}, "retrieval_configs": ["baseline", "bm25_only"], "view_config": None,
           "n_views": 3, "clarify": "first", "select": None, "max_view_rows": 15}


def _cfg(cfg):
    return {**DEFAULT, **(cfg or {})}


def _h(t):
    display(Markdown(t))


def _short(x, n=90):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + " …"


def ok_configs(names):
    out = []
    for n in names:
        miss = missing_requirements(load_config(n))
        if miss:
            print(f"  (검색 구성 {n} 건너뜀: 설치 필요 {miss})")
        else:
            out.append(n)
    return out


# ── 되묻기·선택 방식 ────────────────────────────────────────────
def _clarify_choice(q, a, mode):
    if isinstance(mode, dict):
        return mode.get(q)
    if mode == "first":
        return {c["slot"]: [c["options"][0]["value"]] for c in a["clarifications"] if c.get("options")}
    if mode == "ask":
        sel = {}
        for c in a["clarifications"]:
            print(f"[되묻기] {q} — {c['slot']}: {c.get('reason', '')}")
            for i, o in enumerate(c["options"][:15], 1):
                print(f"  {i}) {o.get('label') or o['value']}")
            sel[c["slot"]] = [c["options"][int(input("번호: ").strip()) - 1]["value"]]
        return sel
    return None


def _select_choice(q, conflict, mode):
    if isinstance(mode, dict):
        return mode.get(q)
    if mode == "first":
        return conflict["options"][0]["option_id"]
    if mode == "ask":
        show_options(conflict)
        return input(f"[선택] {q} — option_id: ").strip()
    return None


# ── 실행 ────────────────────────────────────────────────────────
def run_one(q, cfg=None):
    cfg = _cfg(cfg)
    over = cfg["query_overrides"] or None
    r = {"question": q}
    t0 = time.time()
    tr = Tracer(run_name="nb_e2e")
    # ① 쿼리 분석 (+ 되묻기 응답 → 다시 분석, HCX 다시 안 부름)
    a = analyze(q, cfg["today"], overrides=over, tracer=tr)
    r["analysis_rounds"] = [a]
    while a["status"] == "needs_clarification":
        sel = _clarify_choice(q, a, cfg["clarify"])
        if not sel:
            break
        r.setdefault("clarify_selections", []).append(sel)
        a = analyze(q, cfg["today"], query_id=a.get("query_id"), overrides=over, previous=a, selections=sel, tracer=tr)
        r["analysis_rounds"].append(a)
    r["analysis"] = a
    if a["status"] != "ok":
        r.update(stop=f"① 에서 멈춤: {a['status']}", trace=tr.as_list(), seconds=round(time.time() - t0, 2))
        return r
    # ② 검색: View 묶음과 같은 검색 단위·검색 문장으로 구성별 후보
    vb = a["view_bundle"]
    units = units_of(vb)
    if len(units) > 1 and not with_overrides(over).view_main_with_subs:
        units = [u for u in units if u[0] != "main"]
    r["retrieval"] = []
    for uid, text, f in units:
        sq = search_query(text, f)
        res = {}
        for name in ok_configs(cfg["retrieval_configs"]):
            try:
                res[name] = get_pipeline(name).search(sq, f, 10)
            except Exception as e:  # noqa: BLE001
                res[name] = {"error": f"{e.__class__.__name__}: {e}", "hits": []}
        r["retrieval"].append({"unit_id": uid, "text": text, "search_query": sq, "filters": f, "results": res})
    # ③ View 묶음 + ④ 충돌 (+ 선택)
    r["viewset"] = build_viewset(a, retrieval_config=cfg["view_config"], n_views=cfg["n_views"], overrides=over,
                                 on_ambiguous=lambda c: _select_choice(q, c, cfg["select"]), tracer=tr)
    r.update(trace=tr.as_list(), seconds=round(time.time() - t0, 2))
    return r


def choose(R, q, option_id, cfg=None):
    """선택 대기인 질문에 option_id 를 반영 → 최종 View 표시"""
    vs = R[q]["viewset"]
    picks = [{"selection_token": p["selection_token"], "option_id": option_id} for p in vs["pending"]]
    if not picks:
        print("선택 대기 없음")
        return
    R[q]["viewset"], applied = apply_selections(vs, picks)
    print("반영:", [(a["unit_id"], a["option_id"], "뺀 View", a["dropped_ids"]) for a in applied])
    show_records(R[q]["viewset"]["records"], _cfg(cfg)["max_view_rows"])


# ── 화면 ────────────────────────────────────────────────────────
def show_trace(trace, prefix=None):
    rows = [{"단계": t["step"], "파라미터": _short(t.get("params"), 70), "출력": _short(t.get("output"), 160),
             "메모": _short(t.get("notes"), 80) if t.get("notes") else "", "초": t.get("seconds")}
            for t in trace if prefix is None or t["step"].startswith(prefix)]
    if rows:
        display(pd.DataFrame(rows))


def show_analysis(a):
    _h(f"**상태** `{a['status']}` · 검색 문장 `{a.get('search_text')}` · 서브쿼리: {a.get('decompose_reason') or '-'}")
    if a.get("applied_rules"):
        _h("**적용 규칙**: " + " / ".join(a["applied_rules"]))
    rows = [{"슬롯": slot, "원래 표현": v.get("raw"), "표준 값": _short(v.get("value"), 40), "출처": v.get("source"),
             "일치": v.get("match"), "CSV 접지": v.get("grounded"), "가진 표 수": v.get("n_tables"), "메모": v.get("note") or ""}
            for slot, vals in (a.get("slots") or {}).items() for v in vals]
    if rows:
        _h("**1-2·1-3 슬롯 → CSV 값 (동의어·접지)**")
        display(pd.DataFrame(rows))
    for c in a.get("clarifications") or []:
        _h(f"**1-4 되묻기** `{c['slot']}` — {c.get('reason', '')}  · 후보: "
           + ", ".join(str(o.get("label") or o["value"]) for o in c["options"][:12]))
    if a.get("sub_queries"):
        _h("**1-5 서브쿼리**")
        display(pd.DataFrame([{"id": s["id"], "문장": s["text"], "근거": s.get("reason", ""),
                               "후보 표": ", ".join(s.get("candidate_tables", [])[:5])} for s in a["sub_queries"]]))
    vb = a.get("view_bundle")
    if vb:
        _h("**View 입력 (view_bundle)** — 기존 `POST /api/v1/rag/views` 와 같은 모양")
        rows = [{"단위": "본 질의", "검색 문장": vb.get("search_text"), "슬롯": _short(vb.get("filters"), 150)}]
        rows += [{"단위": f"하위 {i}", "검색 문장": t, "슬롯": _short(f, 150)}
                 for i, (t, f) in enumerate(zip(vb.get("sub_questions") or [], vb.get("sub_filters") or []), 1)]
        display(pd.DataFrame(rows))


def show_retrieval(units, top=5):
    for u in units:
        _h(f"**단위 `{u['unit_id']}`** — 검색 문장 `{u['search_query']}` · 슬롯 `{_short(u['filters'], 120)}`")
        cols = {}
        for name, res in u["results"].items():
            if res.get("error"):
                cols[name] = [res["error"][:60]] + [""] * (top - 1)
                continue
            cell = [f"{h['tbl_nm'][:24]} ({h['tbl_id']})" + (f" ✗{len(h['unmet'])}" if h.get("unmet") else "")
                    for h in res["hits"][:top]]
            cols[name] = cell + [""] * (top - len(cell))
        display(pd.DataFrame(cols, index=range(1, top + 1)))
    print("✗n = 표 메타 기준 못 맞춘 조건 수. 단계별 순위: r['retrieval'][i]['results'][구성]['hits'][j]['stages']")


def show_options(c):
    for o in c.get("options") or []:
        _h(f"**{o['option_id']}** {o['tbl_nm']} `{', '.join(o['tbl_ids'])}` · {o.get('survey_nm') or ''}")
        for v in o["value_preview"][:4]:
            print(f"    {v['key_str']}: {v['value']} {v['unit']}   다른 표: "
                  + ", ".join(f"{x['tbl_id']}={x['value']}{x['unit']}" for x in v["others"]))
        for fn in o["footnotes"]:
            print(f"    ※ [{fn['type']}{' ' + fn['target'] if fn.get('target') else ''}] {fn['text']}")
        print("    기준:", {k: v for k, v in o["basis"].items() if v})


def show_viewset(vs):
    _h(f"**상태** `{vs['status']}` · 검색 구성 `{vs.get('retrieval_config') or '기존(baseline)'}` · {vs.get('seconds')}초")
    for u in vs["units"]:
        c = u["conflict"]
        _h(f"**단위 `{u['unit_id']}`** — `{u['search_query']}` → 충돌 판정 `{c['status']}`"
           + (f" · 선택 `{c['selected_option']}`" if c.get("selected_option") else "") + "  \n" + " / ".join(c["notes"]))
        if c["views"]:
            display(pd.DataFrame([{"순위": v["rank"], "표": v["tbl_id"], "비교에 넣음": v["usable"],
                                   "필수 메타 사용": " ".join(f"{k}{'○' if ok else '✗'}" for k, ok in v["used"].items()),
                                   "값 칸 수": v["n_points"], "메모": "; ".join(v["notes"])} for v in c["views"]]))
        if c["differing_points"]:
            _h("같은 교차점에서 값이 다른 곳")
            display(pd.DataFrame([{"교차점": d["key_str"], **{x["tbl_id"]: f"{x['value']} {x['unit']}" for x in d["values"]}}
                                  for d in c["differing_points"][:10]]))
        if c["status"] == "ambiguous" and not c.get("selected_option"):
            _h("선택지 (값이 같은 표끼리 한 묶음)")
            show_options(c)


def show_records(records, max_rows=15):
    if not records:
        _h("_(넘길 View 없음 — 선택 대기이거나 검색 결과 없음)_")
        return
    for rec in records:
        m, s = rec.get("metadata") or {}, rec.get("source") or {}
        notes = [n.get("text") if isinstance(n, dict) else str(n) for n in rec.get("notes") or []]
        _h(f"**`{rec['id']}`**  \n{m.get('survey_nm')} · 단위 {m.get('unit')} · 기간 {m.get('prd_from')}~{m.get('prd_to')} · "
           f"{m.get('view_type')} · 값 {m.get('n_points')}칸 · [KOSIS]({s.get('kosis_url')})"
           + ("  \n⚠ " + " / ".join(notes) if notes else ""))
        df = pd.DataFrame(rec["table"]["rows"], columns=rec["table"]["columns"])
        display(df.head(max_rows))
        if len(df) > max_rows:
            print(f"  … {len(df)}행 중 {max_rows}행")


def show(r, cfg=None):
    cfg = _cfg(cfg)
    _h(f"# {r['question']}  ({r.get('seconds')}초)")
    _h("## ① 쿼리 분석 (Step 2)")
    if len(r["analysis_rounds"]) > 1:
        a0 = r["analysis_rounds"][0]
        _h(f"처음 분석 `{a0['status']}` → 되묻기 응답 `{r.get('clarify_selections')}` 로 다시 분석 (HCX 다시 안 부름)")
        for c in a0.get("clarifications") or []:
            _h(f"- 되묻기 `{c['slot']}`: {c.get('reason', '')} · 후보 "
               + ", ".join(str(o.get("label") or o["value"]) for o in c["options"][:10]))
    show_analysis(r["analysis"])
    _h("단계별 기록 (trace)")
    show_trace(r.get("trace") or [], "1-")
    if r.get("stop"):
        _h(f"**{r['stop']}**")
        return
    _h("## ② 검색 — 구성별 후보 표 (Step 3)")
    show_retrieval(r["retrieval"])
    _h("## ③·④ View 묶음 · 충돌 판정 (Step 4)")
    show_viewset(r["viewset"])
    show_trace(r["trace"], "2-")
    _h("## ⑤ 최종 View — 답변 모듈로 넘길 Record")
    show_records(r["viewset"]["records"], cfg["max_view_rows"])
    if r["viewset"]["pending"]:
        _h(f"**선택 대기** — `choose(R, \"{r['question']}\", \"opt-n\")`")


def summary_table(R):
    rows = []
    for q, r in R.items():
        a, vs = r["analysis"], r.get("viewset") or {}
        rows.append({"질문": q, "① 분석": a["status"] + (" (되묻기 응답)" if r.get("clarify_selections") else ""),
                     "검색 문장": a.get("search_text") or "", "단위 수": len(vs.get("units") or []),
                     "② baseline 1위": " / ".join(((x["results"].get("baseline") or {}).get("hits") or [{}])[0].get("tbl_id", "-")
                                              for x in r.get("retrieval") or []),
                     "④ 충돌": " / ".join(u["conflict"]["status"]
                                         + (f"→{u['conflict']['selected_option']}" if u["conflict"].get("selected_option") else "")
                                         for u in vs.get("units") or []),
                     "최종 상태": vs.get("status") or r.get("stop", ""), "최종 View 수": len(vs.get("records") or []),
                     "초": r.get("seconds")})
    return pd.DataFrame(rows)
