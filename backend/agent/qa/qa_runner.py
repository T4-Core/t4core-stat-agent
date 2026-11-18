"""QA 실행 입구 — 그래프(qa_graph.py)를 부른다

  run_modules_with_qa(vs, use_llm_chart=True, draw=True, max_rows=50, decision=None, chat=None, mods=None)
      → run_modules 와 같은 8개 키 + "qa"
  run_chat(question, today=None, top_k=None, n_views=None, max_rows=40, **kw)
      → 질문 → ① 질의 분석 · ② 검색·View (Retriever, QA 안 함) → run_modules_with_qa.
        플러그인 입구 (private/pipelines/qa.py → POST /api/v1/chat {"pipeline": "qa"}).
        backend/agent/pipeline.py 가 QA 를 직접 부르게 되면 (qa 설계.md 12장) 이 함수는 필요 없다

  run_modules 는 모듈들을 함수 하나 안에서 이어 불러 사이에 검사를 끼울 수 없다 (그 파일은 고치지 않는다).
  그래서 QA 그래프가 run_modules · decide_charts 가 부르는 공개 함수들을 같은 순서로 직접 부른다 (모듈 5 · 6 은 동시에).
  문제가 없으면 결과가 run_modules 와 같아야 한다 → 회귀 시험의 'same' 검사.

  mods   시험용: 모듈 함수 바꿔 끼우기 {"chart_decision", "module3", "module5", "module6"}
"""
from typing import Any, Callable

from .qa_nodes import dump as _dump  # noqa: F401  (예전 이름 — 노트북 · 개인 도구가 쓴다)
from .qa_nodes import exc_issue as _exc_issue  # noqa: F401
from .qa_nodes import mods_of as _mods  # noqa: F401
from .qa_nodes import note_hits  # noqa: F401
from .qa_state import QARecord  # noqa: F401

RECURSION_LIMIT = 60     # 그래프 단계 수 상한 (재시도를 모두 해도 30 단계 안팎)


def run_modules_with_qa(vs: dict[str, Any], use_llm_chart: bool = True, draw: bool = True, max_rows: int = 50,
                        decision=None, chat: Callable[..., Any] | None = None, mods: dict | None = None) -> dict[str, Any]:
    from .qa_graph import graph
    out = graph.invoke({"viewset": vs, "use_llm_chart": use_llm_chart, "draw": draw, "max_rows": max_rows,
                        "decision": decision},
                       config={"configurable": {"chat": chat, "mods": mods}, "recursion_limit": RECURSION_LIMIT})
    return out["result"]


# ── 플러그인 입구 ────────────────────────────────────────────────
def run_chat(question, today=None, top_k=None, n_views=None, max_rows=40, draw=True, use_llm_chart=True, save=False,
             **kw):
    """질문 → ①·② (Retriever) → QA 를 끼운 Generator. backend.agent.pipeline.run_chat(answer_mode='modules') 와 같은 모양"""
    import time
    from backend.agent.modules import as_answer_result
    from backend.agent.pipeline import OUT_OF_SCOPE_RESULT, _finish, _first_option, _missing_notes
    from backend.rag.query_analyzer.analyze import analyze
    from backend.rag.view.viewset import build_viewset

    timings, t0 = {}, time.time()
    out = {"question": question, "analysis": None, "views": None, "records": [], "result": None, "notes": [],
           "timings": timings, "saved": None}
    t = time.time()
    analysis = analyze(question, today)
    timings["analyze"] = round(time.time() - t, 2)
    out["analysis"] = analysis
    out["notes"] += analysis.get("notes") or []
    if analysis["status"] != "ok":                      # 되묻기 · 범위 밖 → Retriever 결과 그대로 (QA 안 함)
        out["status"] = analysis["status"]
        if analysis["status"] == "out_of_scope":
            out["result"] = dict(OUT_OF_SCOPE_RESULT)
        return _finish(out, t0, save)
    t = time.time()
    vs = build_viewset(analysis, top_k=top_k, n_views=n_views, on_ambiguous=_first_option)
    timings["views"] = round(time.time() - t, 2)
    out.update(views=vs, records=vs.get("records") or [])
    out["notes"] += [f"[{u['unit_id']}] {n}" for u in vs.get("units") or [] for n in u.get("notes") or []]
    if vs["status"] != "ok":
        out["status"] = vs["status"]
        return _finish(out, t0, save)

    t = time.time()
    mods = run_modules_with_qa(vs, use_llm_chart=use_llm_chart, draw=draw, max_rows=max_rows)
    out["modules"], out["qa"] = mods, mods["qa"]
    if mods.get("answer"):
        out["result"] = as_answer_result(mods)
        if mods["qa"]["message"]:
            out["result"]["caveats"] = list(out["result"]["caveats"]) + [mods["qa"]["message"]]
    else:                                               # 답변이 없으면 멈춘 단계를 답변 칸에 보여 준다
        out["result"] = {**OUT_OF_SCOPE_RESULT, "answer": mods["qa"]["message"] or "답변을 만들지 못했습니다.",
                         "caveats": []}
    if missing := _missing_notes(vs):
        out["result"]["caveats"] = list(dict.fromkeys(missing + out["result"]["caveats"]))
    out["notes"] += mods["notes"]
    timings["answer"] = round(time.time() - t, 2)
    out["status"] = "ok"
    return _finish(out, t0, save)
