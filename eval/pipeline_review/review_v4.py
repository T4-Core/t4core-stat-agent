"""
[NEW v4] v4 파이프라인 단계별 검수 카드 — 질문마다 ①쿼리 분석 ②검색 ③View ④충돌 (⑤답변) 의 근거를 카드 한 장에

review_80.py (v3 경로 run_chat, 답변 지표 중심) 와 같은 입력·카드(HTML/PNG) 방식을 쓰되, **단계마다 근거와 자동 진단**을 보여
어느 단계가 문제인지 사람이 고를 수 있게 한다.

  카드 한 장 = 질문 1개
    ① 쿼리 분석  재작성 문장 · 슬롯 → CSV 값 접지(출처·근거 표·CSV 값) · 시점 규칙 · 되묻기(자동 응답) · 서브쿼리 · 검색 문장
    ② 검색      검색 단위마다 후보 표 (순위·점수·BM25 순위·못 맞춘 조건·View 생성 여부·KOSIS 링크)
    ③ View      단위마다 View: 필수 메타 사용(판단 모듈 근거) · 못 맞춘 조건 · 잘라 낸 표 · **원본 CSV 같은 조건 행과 값 대조**
                · KOSIS 통계표 링크 · 원본 CSV · View CSV 경로
    ④ 충돌      같은 교차점 값이 다른 표 · 선택지(주석·산출 기준) · 자동 선택
    ⑤ 답변      (선택) HCX 답변 · 검증 안 된 숫자
  단계마다 자동 진단(PASS/PARTIAL/FAIL/CHECK + 사유 코드) → 사람 판정(단계별 · 첫 실패 단계 · 코멘트)

입력  review_80 과 같은 테스트 세트 탐색 (config.TEST_DATA_DIR: storage/test_data → ./test_data …)
      **질문 문장만 사용** (id 가 없으면 Q001…). 정답 참고 열은 쓰지 않음
출력  config.EVAL_RUNS_DIR / <질문 파일 이름>__v4 /
        results.json · json/Q001.json · cards/Q001.html (+ .png) · review.csv · run_meta.json

CLI (저장소 루트에서)
  python eval/pipeline_review/review_v4.py list
  python eval/pipeline_review/review_v4.py run --queries 80 --n 5           # 앞 5문항 (이어서 실행)
  python eval/pipeline_review/review_v4.py run --queries 80                 # 전체
  python eval/pipeline_review/review_v4.py run --queries 80 --ids Q003 --force --answer
  python eval/pipeline_review/review_v4.py cards --queries 80 --png
  python eval/pipeline_review/review_v4.py summary --queries 80             # 단계별 문제 유형 집계
  python eval/pipeline_review/review_v4.py hits --queries 80                # 정답 표 기준 hit@1·3·5·10 · MRR
"""
import argparse
import html
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import review_80 as r80  # noqa: E402  (테스트 세트 탐색 · PNG 변환 재사용)
from backend.core.config import KOSIS_DATA_DIR, VIEW_OUT_DIR  # noqa: E402

STAGES = {"query": "① 쿼리 분석", "search": "② 검색", "view": "③ View", "conflict": "④ 충돌·선택", "answer": "⑤ 답변"}
GRADES = ("PASS", "PARTIAL", "FAIL", "CHECK")
RANK = {"PASS": 0, "CHECK": 1, "PARTIAL": 2, "FAIL": 3}
MARK = {"PASS": "○", "PARTIAL": "△", "FAIL": "✗", "CHECK": "?"}
COLORS = {"PASS": ("#d4edda", "#155724"), "PARTIAL": ("#fff3cd", "#856404"), "FAIL": ("#f8d7da", "#721c24"),
          "CHECK": ("#dbeafe", "#1e3a8a"), "-": ("#e2e8f0", "#334155")}
# 사유 코드 (summary 에서 단계별 문제 유형으로 집계)
REASONS = {
    "q.error": "쿼리 분석 오류", "q.out_of_scope": "범위 밖 판정 (맞는지 확인)", "q.clarify": "필수 슬롯 없음 → 되묻기 (자동 응답)",
    "q.clarify_stop": "되묻기에서 멈춤", "q.ungrounded": "슬롯 값이 CSV 에 없음", "q.time_no_table": "요청 연도 자료가 있는 표 없음",
    "q.no_target": "대상·지표 없음", "s.none_ok": "후보 표 모두 조건 못 맞춤", "s.top1_unmet": "1위 표가 조건 못 맞춤",
    "s.no_cand": "후보 없음", "v.none": "View 없음", "v.error": "View 생성 실패", "v.empty": "값 없는 View",
    "v.unusable": "필수 메타를 못 쓴 View", "v.raw_mismatch": "원본 CSV 와 값 다름", "v.raw_missing": "원본 CSV 없음",
    "c.ambiguous": "같은 교차점 값이 다른 표 → 선택", "c.partial": "다 맞은 View 없음 (비교 안 함)", "c.empty": "비교할 View 없음",
    "a.insufficient": "답변: 자료 부족", "a.unverified": "답변: 근거에 없는 숫자", "a.error": "답변 오류", "x.error": "실행 오류",
}


# ═════════════════════════════ 경로 · 입력 ═════════════════════════════
def run_for(queries=None, test_dir=None):
    ts = r80.resolve_test_set(queries, test_dir)
    return r80.RunPaths(f"{ts['name']}__v4"), ts


def load_questions(queries=None, test_dir=None):
    """질문 문장만 [{id, question}] (정답 참고 열은 쓰지 않음)"""
    return [{"id": x["id"], "question": x["question"]} for x in r80.load_questions(queries, test_dir)]


def list_sets(test_dir=None, log=print):
    for i, t in enumerate(r80.find_test_sets(test_dir), 1):
        if "error" in t:
            log(f"  [-] {t['path'].name}: {t['error']}")
            continue
        run = r80.RunPaths(f"{t['name']}__v4")
        done = len(load_results(run))
        log(f"  [{i}] {t['path'].name}  {t['n']}문항  → {run.dir}  (완료 {done})")


# ═════════════════════════════ 정답 기준 · hit 지표 ═════════════════════════════
# 파이프라인에는 질문 문장만 넣고, 정답 참고는 점수 계산·카드 ★ 표시에만 쓴다.
# 정답 기준 우선순위: 사람이 카드에서 고른 정답 표 > 정답 참고 파일의 표 ID 열(이름에 'tbl') > 조사명(약한 기준)
HIT_KS = (1, 3, 5, 10)


def _nospace(x):
    return re.sub(r"\s+", "", str(x or ""))


def references(queries=None, test_dir=None):
    """id → {survey, tables} (질문 파일의 남는 열 + 이름이 짝인 정답 참고 파일, review_80 과 같은 규칙)"""
    out = {}
    alias = {r80._key(a) for a in r80.COLUMN_ALIASES["survey"]}
    for it in r80.load_questions(queries, test_dir):
        ref = it.get("reference") or {}
        survey = it.get("survey") or next((str(v) for k, v in ref.items() if r80._key(k) in alias and v), "")
        out[it["id"]] = {"survey": survey, "tables": sorted(r80.expected_tables(ref))}
    return out


def gold_of(rec, ref=None):
    """→ {basis: 사람|정답표|조사명|None, tables: [...], survey: str}"""
    human = (rec.get("human") or {}).get("relevant_tables") or []
    if human:
        return {"basis": "사람", "tables": list(human), "survey": ""}
    ref = ref or rec.get("gold_ref") or {}
    if ref.get("tables"):
        return {"basis": "정답표", "tables": list(ref["tables"]), "survey": ""}
    if ref.get("survey"):
        return {"basis": "조사명", "tables": [], "survey": ref["survey"]}
    return {"basis": None, "tables": [], "survey": ""}


def is_gold(gold, tbl_id, survey_nm=""):
    if gold["tables"]:
        return tbl_id in gold["tables"]
    if gold["survey"] and "교차" not in gold["survey"]:
        return _nospace(gold["survey"]) in _nospace(survey_nm)
    return False


def hit_of(rec, ref=None):
    """문항 하나 → 검색 후보 순위 기준 hit@k·MRR + View·최종 Record 에 정답 표가 있는가"""
    g = gold_of(rec, ref)
    row = {"id": rec["id"], "question": rec["question"], "기준": g["basis"] or "-",
           "정답": ", ".join(g["tables"]) or g["survey"] or ""}
    if not g["basis"] or not rec.get("units"):
        return {**row, "첫_정답_순위": None, **{f"hit@{k}": None for k in HIT_KS}, "MRR": None, "View_hit": None,
                "최종_hit": None}
    ranks = [c["rank"] for u in rec["units"] for c in u["candidates"] if is_gold(g, c["tbl_id"], c.get("survey_nm"))]
    first = min(ranks) if ranks else None
    views = [v for u in rec["units"] for v in u["views"]]
    final = set((rec.get("final") or {}).get("records") or [])
    return {**row, "첫_정답_순위": first, **{f"hit@{k}": bool(first and first <= k) for k in HIT_KS},
            "MRR": round(1 / first, 3) if first else 0.0,
            "View_hit": any(is_gold(g, v["tbl_id"], v.get("survey_nm")) for v in views),
            "최종_hit": any(is_gold(g, v["tbl_id"], v.get("survey_nm")) for v in views if v["record_id"] in final)}


def hit_table(data, refs=None):
    """문항별 hit 표 + 기준별 요약 → (문항 표, 요약 표)"""
    refs = refs or {}
    df = pd.DataFrame([hit_of(data[k], refs.get(k)) for k in sorted(data)])
    cols = [f"hit@{k}" for k in HIT_KS] + ["MRR", "View_hit", "최종_hit"]
    scored = df[df["기준"] != "-"]
    summ = []
    for basis, g in [("전체", scored)] + list(scored.groupby("기준")):
        if len(g):
            summ.append({"기준": basis, "문항 수": len(g),
                         **{c: round(pd.to_numeric(g[c].astype(float), errors="coerce").mean(), 3) for c in cols}})
    return df, pd.DataFrame(summ)


# ═════════════════════════════ 원본 CSV 대조 ═════════════════════════════
def raw_csv_of(rec):
    """Record → 원본 CSV 경로 (CSV 값 사전 → 카테고리 폴더 규칙 순)"""
    src, md = rec.get("source") or {}, rec.get("metadata") or {}
    try:
        from backend.rag.csv_index import load_index
        t = load_index().table(src.get("tbl_id"))
        if t and t.get("raw_path"):
            return Path(t["raw_path"])
    except FileNotFoundError:
        pass
    from backend.core.utils import safe
    p = KOSIS_DATA_DIR / "raw" / safe(md.get("category") or "") / f"{src.get('table_key')}.csv"
    if p.exists():
        return p
    hit = list((KOSIS_DATA_DIR / "raw").glob(f"*/{src.get('table_key')}.csv"))
    return hit[0] if hit else p


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def raw_check(rec, max_rows=40, con=None):
    """View 의 값이 원본 CSV 의 같은 좌표(항목·분류 코드·연도) 행에 있는가
    → {path, exists, n(값 있는 View 칸), ok(원본에 같은 값), bad[…], raw_rows[…], n_raw}"""
    from backend.core.utils import sql_str
    path = raw_csv_of(rec)
    out = {"path": str(path), "exists": path.exists(), "n": 0, "ok": 0, "bad": [], "raw_rows": [], "n_raw": 0}
    t = rec.get("table") or {}
    cols, rows = t.get("columns") or [], t.get("rows") or []
    if not path.exists() or "값" not in cols:
        return out
    src = rec.get("source") or {}
    vi = cols.index("값")
    years = [str(y) for y in (src.get("period") or {}).get("in") or []]
    if not years and "시점" in cols:
        years = sorted({str(r[cols.index("시점")])[:4] for r in rows if r[cols.index("시점")] is not None})
    import duckdb
    own = con is None
    con = con or duckdb.connect()
    try:
        rel = f"read_csv({sql_str(path.as_posix())}, all_varchar=true, header=true)"
        have = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()]
        where = []
        if src.get("itm_id") and "ITM_ID" in have:
            where.append(f"ITM_ID IN ({', '.join(sql_str(i) for i in src['itm_id'])})")
        for k, v in (src.get("dims") or {}).items():
            col = k.upper()
            if v.get("codes") and col in have:
                where.append(f"{col} IN ({', '.join(sql_str(c) for c in v['codes'])})")
        if years and "PRD_DE" in have:
            where.append(f"substr(PRD_DE, 1, 4) IN ({', '.join(sql_str(y) for y in years)})")
        show = [c for c in ["PRD_DE"] + [f"C{i}_NM" for i in range(1, 9)] + ["ITM_NM", "UNIT_NM", "DT"] if c in have]
        q = f"SELECT {', '.join(show)} FROM {rel}" + (f" WHERE {' AND '.join(where)}" if where else "")
        df = con.execute(q).df()
    finally:
        if own:
            con.close()
    out["n_raw"] = len(df)
    out["raw_rows"] = df.head(max_rows).to_dict(orient="records")
    vals = [v for v in (_num(x) for x in df.get("DT", [])) if v is not None]
    for r in rows:
        v = _num(r[vi])
        if v is None:
            continue
        out["n"] += 1
        if any(abs(v - w) <= max(1e-6, 1e-9 * abs(w)) for w in vals):
            out["ok"] += 1
        elif len(out["bad"]) < 5:
            out["bad"].append(" | ".join(str(x) for x in r[:vi]) + f" = {r[vi]} (원본에 같은 값 없음)")
    return out


# ═════════════════════════════ 실행 ═════════════════════════════
def _reason(code, text=""):
    return {"code": code, "text": text or REASONS.get(code, code)}


def _grade(reasons, base="PASS"):
    g = base
    for r in reasons:
        g2 = r.get("grade", "PARTIAL")
        g = g2 if RANK[g2] > RANK[g] else g
    return g


def _slot_rows(a):
    rows = []
    for slot, vals in (a.get("slots") or {}).items():
        for v in vals:
            ev = "; ".join(f"{c.get('tbl_id')}:{c.get('name')}({c.get('kind')})" for c in (v.get("csv") or [])[:3])
            rows.append({"slot": slot, "raw": v.get("raw"), "value": v.get("value"), "source": v.get("source"),
                         "match": v.get("match"), "grounded": v.get("grounded"), "n_tables": v.get("n_tables"),
                         "tables": (v.get("tables") or [])[:5], "csv": ev, "note": v.get("note") or ""})
    return rows


def _query_stage(rounds, clarify_sel):
    a = rounds[-1]
    first = rounds[0]
    st = {"status": a["status"], "rewritten": (a.get("bundle") or {}).get("rewritten"),
          "raw_slots": (a.get("state") or {}).get("raw_slots"), "applied_rules": a.get("applied_rules") or [],
          "notes": a.get("notes") or [], "slots": _slot_rows(a),
          "clarifications": [{"slot": c["slot"], "reason": c.get("reason"),
                              "options": [o.get("label") or o["value"] for o in c.get("options", [])[:12]]}
                             for c in first.get("clarifications") or []],
          "clarify_answer": clarify_sel, "sub_queries": [{"id": s["id"], "text": s["text"], "reason": s.get("reason"),
                                                         "tables": (s.get("candidate_tables") or [])[:6]}
                                                        for s in a.get("sub_queries") or []],
          "decompose_reason": a.get("decompose_reason"), "search_text": a.get("search_text"),
          "view_bundle": {k: (a.get("view_bundle") or {}).get(k) for k in ("search_text", "filters", "sub_questions", "sub_filters")},
          "trace": [{"step": t["step"], "params": t.get("params"), "output": t.get("output"), "seconds": t.get("seconds")}
                    for t in a.get("trace") or []]}
    rs = []
    if first["status"] == "needs_clarification":
        if a["status"] == "ok":
            rs.append({**_reason("q.clarify", "되묻기 " + ", ".join(c["slot"] for c in first["clarifications"])
                                 + f" → 자동 응답 {clarify_sel}"), "grade": "PARTIAL"})
        else:
            rs.append({**_reason("q.clarify_stop"), "grade": "FAIL"})
    if a["status"] == "out_of_scope":
        rs.append({**_reason("q.out_of_scope"), "grade": "CHECK"})
    for r in st["slots"]:
        if r["grounded"]:
            continue
        if r["slot"] == "시점":
            rs.append({**_reason("q.time_no_table", f"시점 {r['value']}: {r['note'] or '자료 있는 표 없음'} (최신 자료로 대체 예정)"),
                       "grade": "PASS"})
        elif r["slot"] in ("지역", "지표", "대상", "성별", "연령"):
            rs.append({**_reason("q.ungrounded", f"{r['slot']} '{r['raw']}' → '{r['value']}' CSV 에 없음 ({r['source']})"),
                       "grade": "PARTIAL"})
    f = (a.get("view_bundle") or {}).get("filters") or {}
    if a["status"] == "ok" and not (f.get("지표") or f.get("대상")):
        rs.append({**_reason("q.no_target"), "grade": "PARTIAL"})
    return st, rs


def _slim_view(v, cand_by_tbl, conf_view, raw):
    rec = v["record"]
    md, src = rec.get("metadata") or {}, rec.get("source") or {}
    c = cand_by_tbl.get(v["tbl_id"]) or {}
    vcsv = VIEW_OUT_DIR / "views" / (re.sub(r"[^\w\-]+", "_", rec["id"]) + ".csv")
    t = rec.get("table") or {}
    return {"record_id": rec["id"], "tbl_id": v["tbl_id"], "tbl_nm": c.get("tbl_nm", ""), "survey_nm": md.get("survey_nm"),
            "rank": v.get("rank"), "kosis_url": src.get("kosis_url"), "view_csv": str(vcsv),
            "unit": md.get("unit"), "prd_se": md.get("prd_se"), "period": f"{md.get('prd_from')}~{md.get('prd_to')}",
            "view_type": md.get("view_type"), "n_points": md.get("n_points"), "n_rows": len(t.get("rows") or []),
            "source": {k: src.get(k) for k in ("tbl_id", "itm_id", "dims", "period", "prd_se")},
            "notes": [n.get("text") if isinstance(n, dict) else str(n) for n in rec.get("notes") or []],
            "columns": t.get("columns") or [], "rows": (t.get("rows") or [])[:30],
            "usable": (conf_view or {}).get("usable"), "used": (conf_view or {}).get("used"),
            "checks": (conf_view or {}).get("checks"), "raw": raw}


def run_one(item, today=r80.DEFAULT_TODAY, clarify="first", select="first", n_views=3, top_k=10, answer=False,
            raw=True, retrieval_config=None, overrides=None):
    """질문 하나 → 단계별 근거 레코드"""
    from backend.core.tracking import Tracer
    from backend.rag.query_analyzer.v4 import analyze
    from backend.rag.view import build_viewset
    t0 = time.time()
    rec = {"id": item["id"], "question": item["question"], "stages": {}, "auto": {}, "units": [], "final": {},
           "settings": {"today": today, "clarify": clarify, "select": select, "n_views": n_views, "top_k": top_k,
                        "retrieval_config": retrieval_config, "overrides": overrides or {}}}
    try:
        tr = Tracer(run_name="review_v4")
        a = analyze(item["question"], today, overrides=overrides, tracer=tr)
        rounds, sel = [a], None
        if a["status"] == "needs_clarification" and clarify == "first":
            sel = {c["slot"]: [c["options"][0]["value"]] for c in a["clarifications"] if c.get("options")}
            a = analyze(item["question"], today, query_id=a.get("query_id"), overrides=overrides, previous=a,
                        selections=sel, tracer=tr)
            rounds.append(a)
        qst, qrs = _query_stage(rounds, sel)
        rec["stages"]["query"] = qst
        rec["auto"]["query"] = {"grade": _grade(qrs), "reasons": qrs}
        if a["status"] != "ok":
            for k in ("search", "view", "conflict"):
                rec["auto"][k] = {"grade": "-", "reasons": []}
            rec["final"] = {"status": a["status"], "records": []}
            return _done(rec, t0)
        first = (lambda c: c["options"][0]["option_id"]) if select == "first" else None
        vs = build_viewset(a, retrieval_config=retrieval_config, top_k=top_k, n_views=n_views, overrides=overrides,
                           on_ambiguous=first, tracer=tr)
        srs, vrs, crs = [], [], []
        import duckdb
        con = duckdb.connect()
        try:
            for u in vs["units"]:
                cands = [{"rank": c["rank"], "tbl_id": c["tbl_id"], "tbl_nm": c.get("tbl_nm"), "survey_nm": c.get("survey_nm"),
                          "score": c.get("score"), "bm25_rank": c.get("bm25_rank"), "cost": c.get("cost"),
                          "unmet": [x.get("text") for x in c.get("unmet") or []], "has_view": c.get("has_view"),
                          "kosis_url": _kosis(c["tbl_id"])}
                         for c in u["candidates"]]
                by_tbl = {c["tbl_id"]: c for c in cands}
                conf = u["conflict"]
                cv = {x["record_id"]: x for x in conf["views"]}
                views = []
                for v in u["views"]:
                    rc = None
                    if raw:
                        try:
                            rc = raw_check(v["record"], con=con)
                        except Exception as e:  # noqa: BLE001
                            rc = {"error": f"{e.__class__.__name__}: {str(e)[:200]}", "exists": None}
                    views.append(_slim_view(v, by_tbl, cv.get(v["record"]["id"]), rc))
                uid = u["unit_id"]
                # ② 검색 진단
                n = len(cands)
                ok_ranks = [c["rank"] for c in cands if not c["unmet"]]
                if not n:
                    srs.append({**_reason("s.no_cand", f"[{uid}] 후보 없음"), "grade": "FAIL"})
                elif not ok_ranks:
                    srs.append({**_reason("s.none_ok", f"[{uid}] 상위 {n}개 모두 조건 못 맞춤 — 1위: "
                                          + "; ".join(cands[0]["unmet"])), "grade": "FAIL"})
                elif ok_ranks[0] != 1:
                    srs.append({**_reason("s.top1_unmet", f"[{uid}] 1위 '{cands[0]['tbl_nm']}' 못 맞춤: "
                                          + "; ".join(cands[0]["unmet"]) + f" (다 맞은 첫 표 {ok_ranks[0]}위)"), "grade": "PARTIAL"})
                # ③ View 진단
                if not views:
                    vrs.append({**_reason("v.none", f"[{uid}] View 없음 " + "; ".join(u.get("notes") or [])), "grade": "FAIL"})
                for x in u.get("notes") or []:
                    if "실패" in x:
                        vrs.append({**_reason("v.error", f"[{uid}] {x[:160]}"), "grade": "PARTIAL"})
                for v in views:
                    if not v["n_points"]:
                        vrs.append({**_reason("v.empty", f"[{uid}] {v['tbl_id']} 값 없음"), "grade": "PARTIAL"})
                    elif v["usable"] is False:
                        miss = [k for k, ok in (v["used"] or {}).items() if not ok]
                        vrs.append({**_reason("v.unusable", f"[{uid}] {v['tbl_id']} 못 쓴 조건 {miss}"), "grade": "PARTIAL"})
                    rcx = v.get("raw") or {}
                    if rcx.get("exists") is False:
                        vrs.append({**_reason("v.raw_missing", f"[{uid}] {v['tbl_id']} 원본 CSV 없음"), "grade": "CHECK"})
                    elif rcx.get("n") and rcx.get("ok", 0) < rcx["n"]:
                        vrs.append({**_reason("v.raw_mismatch", f"[{uid}] {v['tbl_id']} 원본 대조 {rcx['ok']}/{rcx['n']}"),
                                    "grade": "FAIL"})
                if views and not any(v["usable"] for v in views):
                    vrs.append({"code": "v.unusable", "text": f"[{uid}] 다 맞은 View 가 하나도 없음", "grade": "FAIL"})
                # ④ 충돌 진단
                if conf["status"] == "ambiguous":
                    crs.append({**_reason("c.ambiguous", f"[{uid}] 교차점 {len(conf['differing_points'])}곳 값 다름 · 선택지 "
                                          f"{len(conf['options'])}개" + (f" → 자동 {conf.get('selected_option')}"
                                                                       if conf.get("selected_option") else " (선택 대기)")),
                                "grade": "PARTIAL"})
                elif conf["status"] == "partial":
                    crs.append({**_reason("c.partial", f"[{uid}] {_reason('c.partial')['text']}"), "grade": "PARTIAL"})
                elif conf["status"] == "empty":
                    crs.append({**_reason("c.empty", f"[{uid}] 비교할 View 없음"), "grade": "FAIL"})
                rec["units"].append({
                    "unit_id": uid, "query": u["query"], "search_query": u["search_query"], "filters": u["filters"],
                    "candidates": cands, "views": views,
                    "conflict": {"status": conf["status"], "notes": conf["notes"], "n_compared_keys": conf["n_compared_keys"],
                                 "differing_points": [{"key_str": d["key_str"],
                                                       "values": [{"tbl_id": x["tbl_id"], "value": x["value"], "unit": x["unit"]}
                                                                  for x in d["values"]]} for d in conf["differing_points"][:8]],
                                 "options": [{k: o.get(k) for k in ("option_id", "tbl_ids", "tbl_nm", "survey_nm", "value_preview",
                                                                     "footnotes", "description", "basis", "kosis_url")}
                                             for o in conf.get("options") or []],
                                 "selected_option": conf.get("selected_option")}})
        finally:
            con.close()
        rec["auto"]["search"] = {"grade": _grade(srs), "reasons": srs}
        rec["auto"]["view"] = {"grade": _grade(vrs), "reasons": vrs}
        rec["auto"]["conflict"] = {"grade": _grade(crs), "reasons": crs}
        rec["final"] = {"status": vs["status"], "records": [r["id"] for r in vs["records"]],
                        "pending": [p["unit_id"] for p in vs["pending"]]}
        rec["trace_view"] = [{"step": t["step"], "params": t.get("params"), "output": t.get("output"), "seconds": t.get("seconds")}
                             for t in tr.as_list() if t["step"].startswith("2-")]
        if answer:
            ars = []
            try:
                from backend.agent.light_agent import answer_from_records
                res = answer_from_records(item["question"], vs["records"]) if vs["records"] else \
                    {"answer": "(넘길 View 없음)", "insufficient": True, "unverified_numbers": []}
                rec["answer"] = {k: res.get(k) for k in ("answer", "summary", "key_points", "insufficient",
                                                         "unverified_numbers", "used_ids")}
                if res.get("insufficient"):
                    ars.append({**_reason("a.insufficient"), "grade": "PARTIAL"})
                if res.get("unverified_numbers"):
                    ars.append({**_reason("a.unverified", f"근거에 없는 숫자 {res['unverified_numbers']}"), "grade": "PARTIAL"})
            except Exception as e:  # noqa: BLE001
                ars.append({**_reason("a.error", f"{e.__class__.__name__}: {str(e)[:200]}"), "grade": "FAIL"})
            rec["auto"]["answer"] = {"grade": _grade(ars), "reasons": ars}
    except Exception as e:  # noqa: BLE001  (한 문항 실패로 전체를 멈추지 않음)
        rec["error"] = f"{e.__class__.__name__}: {str(e)[:400]}"
        for k in ("query", "search", "view", "conflict"):
            rec["auto"].setdefault(k, {"grade": "FAIL", "reasons": [{**_reason("x.error", rec["error"]), "grade": "FAIL"}]})
    return _done(rec, t0)


def _kosis(tbl_id):
    """후보 표 → KOSIS 통계표 링크 (기관 id 는 메타 프로필에서)"""
    from backend.rag.ingestion.build_view import KOSIS_URL
    from backend.rag.ingestion.resolve import profile
    p = profile(tbl_id) or {}
    org = p.get("org_id") or str(p.get("table_key") or "101_").split("_")[0] or "101"
    return KOSIS_URL.format(org=org, tbl=tbl_id)


def _done(rec, t0):
    order = [k for k in STAGES if k in rec["auto"]]
    worst = max((rec["auto"][k]["grade"] for k in order if rec["auto"][k]["grade"] in RANK), key=RANK.get, default="PASS")
    first = next((k for k in order if rec["auto"][k]["grade"] == "FAIL"), None) or \
        next((k for k in order if rec["auto"][k]["grade"] == "PARTIAL"), None)
    rec["auto_overall"] = {"grade": worst, "first_issue": first}
    rec.setdefault("human", {**{k: None for k in STAGES}, "first_fail": None, "comment": "", "reviewed": False})
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec


# ═════════════════════════════ 저장 ═════════════════════════════
def load_results(run):
    p = run.dir / "results.json"
    return {r["id"]: r for r in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else {}


def save_results(run, data):
    run.dir.mkdir(parents=True, exist_ok=True)
    run.json_dir.mkdir(exist_ok=True)
    ordered = [data[k] for k in sorted(data)]
    (run.dir / "results.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for r in ordered:
        (run.json_dir / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    review_df(data).to_csv(run.dir / "review.csv", index=False, encoding="utf-8-sig")


def review_df(data):
    rows = []
    for k in sorted(data):
        r = data[k]
        h, a = r["human"], r["auto"]
        u0 = (r.get("units") or [{}])[0]
        v0 = (u0.get("views") or [{}])[0]
        rows.append({"id": r["id"], "question": r["question"],
                     "검색_문장": (r["stages"].get("query") or {}).get("search_text", ""),
                     "분석_상태": (r["stages"].get("query") or {}).get("status", ""),
                     **{f"자동_{STAGES[s]}": (a.get(s) or {}).get("grade", "") for s in STAGES},
                     **{f"사람_{STAGES[s]}": h.get(s) or "" for s in STAGES},
                     "자동_첫_문제_단계": STAGES.get((r.get("auto_overall") or {}).get("first_issue"), ""),
                     "사람_첫_실패_단계": STAGES.get(h.get("first_fail"), h.get("first_fail") or ""), "코멘트": h.get("comment", ""),
                     "자동_사유": " / ".join(x["text"] for s in STAGES for x in (a.get(s) or {}).get("reasons", [])),
                     "1위_View_표": f"{v0.get('tbl_nm', '')} ({v0.get('tbl_id', '')})" if v0 else "",
                     "KOSIS": v0.get("kosis_url", ""), "최종_상태": (r.get("final") or {}).get("status", ""),
                     "검수": "Y" if h.get("reviewed") else "", "초": r.get("elapsed_s"),
                     **{k: v for k, v in hit_of(r).items() if k in ("기준", "정답", "첫_정답_순위", "hit@1", "hit@5", "MRR")}})
    return pd.DataFrame(rows)


def run_batch(queries=None, ids=None, n=None, force=False, png=True, test_dir=None, log=print, **kw):
    run, ts = run_for(queries, test_dir)
    items = load_questions(queries, test_dir)
    if ids:
        items = [x for x in items if x["id"] in set(ids)]
    if n:
        items = items[:n]
    data = load_results(run)
    refs = references(queries, test_dir)                         # 점수·★ 표시용 (파이프라인 입력에는 안 씀)
    run.dir.mkdir(parents=True, exist_ok=True)
    (run.dir / "run_meta.json").write_text(json.dumps({"test_set": str(ts["path"]), "n_questions": len(items),
                                                       "settings": kw, "started": time.strftime("%Y-%m-%d %H:%M:%S")},
                                                      ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    todo = [x for x in items if force or x["id"] not in data or data[x["id"]].get("error")]
    log(f"{ts['path'].name}: {len(items)}문항 중 {len(todo)}개 실행 → {run.dir}")
    t0 = time.time()
    for i, it in enumerate(todo, 1):
        old = data.get(it["id"])
        r = run_one(it, **kw)
        r["gold_ref"] = refs.get(it["id"]) or {}
        if old and old.get("human", {}).get("reviewed"):
            r["human"] = old["human"]                            # 다시 실행해도 사람 판정 유지
        data[it["id"]] = r
        save_results(run, data)
        write_card(run, r, png=False)                             # HTML 은 바로, PNG 는 끝에 한 번에
        g = " ".join(f"{STAGES[s][:1]}{MARK.get((r['auto'].get(s) or {}).get('grade'), '-')}" for s in STAGES if s in r["auto"])
        log(f"  [{i}/{len(todo)}] {it['id']} {r['elapsed_s']}초  {g}  {it['question'][:40]}"
            + (f"  ✗ {r['error'][:80]}" if r.get("error") else ""))
    if png and todo:
        log(f"카드 PNG {len(todo)}장 만드는 중 …")
        write_cards(run, ids=[x["id"] for x in todo], png=True, log=log)
    log(f"끝 ({time.time() - t0:.0f}초). 카드 {run.card_dir}")
    return run, data


def set_review(run, qid, first_fail=None, comment=None, png=True, relevant=None, **stage_grades):
    """사람 판정: set_review(run, "Q001", query="PASS", search="FAIL", first_fail="search", comment="…",
                            relevant=["DT_1JC1516"])   ← 정답 표 (hit 지표의 기준이 됨, 정답 참고 파일보다 우선)"""
    data = load_results(run)
    h = data[qid]["human"]
    if relevant is not None:
        h["relevant_tables"] = list(relevant)
    for s, g in stage_grades.items():
        if s in STAGES and g in GRADES + (None,):
            h[s] = g
    if first_fail is not None:
        h["first_fail"] = first_fail
    if comment is not None:
        h["comment"] = comment
    h["reviewed"] = True
    save_results(run, data)
    write_card(run, data[qid], png)
    return data[qid]


def stage_summary(data, who="auto"):
    """단계별 판정 분포 + 사유 코드 집계 → (판정 표, 사유 표)"""
    g = {STAGES[s]: Counter() for s in STAGES}
    reasons = Counter()
    for r in data.values():
        for s in STAGES:
            v = (r["auto"].get(s) or {}).get("grade") if who == "auto" else r["human"].get(s)
            if v:
                g[STAGES[s]][v] += 1
            for x in (r["auto"].get(s) or {}).get("reasons", []):
                reasons[(STAGES[s], x["code"], REASONS.get(x["code"], x["code"]))] += 1
    gt = pd.DataFrame(g).T.reindex(columns=[c for c in ("PASS", "PARTIAL", "FAIL", "CHECK", "-")]).fillna(0).astype(int)
    gt = gt[gt.sum(axis=1) > 0]                                   # 돌리지 않은 단계(⑤ 답변 등)는 뺌
    rt = pd.DataFrame([{"단계": a, "사유 코드": b, "사유": c, "문항 수": n} for (a, b, c), n in reasons.most_common()])
    return gt, rt


def questions_with(data, code):
    """사유 코드가 붙은 문항 id 목록 (예: 'v.raw_mismatch')"""
    return [k for k in sorted(data) if any(x["code"] == code for s in STAGES for x in (data[k]["auto"].get(s) or {}).get("reasons", []))]


# ═════════════════════════════ 카드 (HTML / PNG) ═════════════════════════════
def _e(x):
    return html.escape("" if x is None else str(x))


def _badge(v):
    v = v or "-"
    bg, fg = COLORS.get(v, COLORS["-"])
    return f'<span class="bd" style="background:{bg};color:{fg}">{_e(v)}</span>'


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.0f}" if v.is_integer() else f"{v:,.3f}".rstrip("0").rstrip(".")
    return v


def _tbl(cols, rows, limit=12, hl=None):
    if not rows:
        return "<div class='g'>(없음)</div>"
    th = "".join(f"<th>{_e(c)}</th>" for c in cols)
    body = ""
    for i, r in enumerate(rows[:limit]):
        vals = r if isinstance(r, (list, tuple)) else [r.get(c) for c in cols]
        style = " class='hl'" if hl and hl(i, vals) else ""
        body += f"<tr{style}>" + "".join(f"<td>{_e(_fmt(v))}</td>" for v in vals) + "</tr>"
    more = f"<div class='g'>… 외 {len(rows) - limit}행</div>" if len(rows) > limit else ""
    return f"<table class='t'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>{more}"


def _link(url, text=None):
    return f"<a href='{_e(url)}'>{_e(text or url)}</a>" if url else ""


def _file_link(path, text):
    p = Path(path)
    return f"<a href='{_e(p.as_uri())}'>{_e(text)}</a> <span class='g'>{_e(path)}</span>" if p.is_absolute() else _e(path)


def _stage_head(rec, key):
    a = rec["auto"].get(key) or {}
    h = rec["human"].get(key)
    rs = "".join(f"<li>{_badge(x.get('grade'))} <code>{_e(x['code'])}</code> {_e(x['text'])}</li>" for x in a.get("reasons", []))
    return (f"<div class='sh'><b>{STAGES[key]}</b> 자동 {_badge(a.get('grade'))} · 사람 {_badge(h)}</div>"
            + (f"<ul class='rs'>{rs}</ul>" if rs else ""))


def card_html(rec):
    q = rec["stages"].get("query") or {}
    ao, h = rec.get("auto_overall") or {}, rec["human"]
    chips = " ".join(f"{STAGES[s]} {_badge((rec['auto'].get(s) or {}).get('grade'))}" for s in STAGES if s in rec["auto"])
    parts = [f"<h2>[{_e(rec['id'])}] {_e(rec['question'])}</h2>",
             f"<div class='g'>{chips} · 자동 첫 문제 단계 <b>{_e(STAGES.get(ao.get('first_issue'), '-'))}</b> · "
             f"{_e(rec.get('elapsed_s'))}초 · {'✅ 검수완료' if h.get('reviewed') else '⏳ 자동 초안'}</div>"]
    g = gold_of(rec)
    if g["basis"] and rec.get("units"):
        hr = hit_of(rec)
        parts.append(f"<div class='box hm'><b>정답 기준</b> {_e(g['basis'])}: {_e(', '.join(g['tables']) or g['survey'])} · "
                     f"첫 정답 순위 <b>{_e(hr['첫_정답_순위'] or '없음')}</b> · "
                     + " ".join(f"hit@{k} {'○' if hr[f'hit@{k}'] else '✗'}" for k in HIT_KS)
                     + f" · View {'○' if hr['View_hit'] else '✗'} · 최종 {'○' if hr['최종_hit'] else '✗'} (★ = 정답)</div>")
    if h.get("reviewed") or h.get("comment"):
        parts.append(f"<div class='box hm'><b>사람 판정</b> 첫 실패 단계 <b>{_e(STAGES.get(h.get('first_fail'), h.get('first_fail') or '-'))}</b>"
                     f" · {_e(h.get('comment'))}</div>")
    if rec.get("error"):
        parts.append(f"<div class='box w'><b>실행 오류</b> {_e(rec['error'])}</div>")
    # ① 쿼리 분석
    b = [_stage_head(rec, "query"),
         f"<div>재작성(v3) <b>{_e(q.get('rewritten'))}</b> · 상태 <code>{_e(q.get('status'))}</code></div>",
         f"<div class='g'>HCX 슬롯 <code>{_e(json.dumps(q.get('raw_slots'), ensure_ascii=False))}</code></div>"]
    if q.get("applied_rules"):
        b.append(f"<div>시점 규칙: {_e(' / '.join(q['applied_rules']))}</div>")
    for c in q.get("clarifications") or []:
        b.append(f"<div class='w'>되묻기 <b>{_e(c['slot'])}</b>: {_e(c['reason'])} · 후보 {_e(', '.join(map(str, c['options'])))}"
                 f"{' → 자동 응답 ' + _e(q.get('clarify_answer')) if q.get('clarify_answer') else ''}</div>")
    b.append("<div><b>슬롯 → CSV 값 접지</b> (출처: rule=규칙 사전 · csv=CSV 값 · term>csv=용어 사전→CSV · learned=학습)</div>")
    b.append(_tbl(["슬롯", "원래 표현", "표준 값", "출처", "일치", "CSV에 있음", "가진 표 수", "근거 (표:값(종류))", "메모"],
                  [[r["slot"], r["raw"], json.dumps(r["value"], ensure_ascii=False) if isinstance(r["value"], dict) else r["value"],
                    r["source"], r["match"], "○" if r["grounded"] else "✗", r["n_tables"], r["csv"] or ", ".join(r["tables"]),
                    r["note"]] for r in q.get("slots") or []], 20, hl=lambda i, v: v[5] == "✗"))
    if q.get("sub_queries"):
        b.append(f"<div><b>서브쿼리</b> — {_e(q.get('decompose_reason'))}</div>"
                 + _tbl(["id", "문장", "근거", "후보 표"], [[s["id"], s["text"], s["reason"], ", ".join(s["tables"])]
                                                     for s in q["sub_queries"]]))
    elif q.get("decompose_reason"):
        b.append(f"<div class='g'>서브쿼리: {_e(q['decompose_reason'])}</div>")
    vb = q.get("view_bundle") or {}
    if vb.get("filters") is not None or vb.get("search_text"):
        b.append(f"<div>검색 문장 <b>{_e(vb.get('search_text'))}</b> · View 슬롯 <code>{_e(json.dumps(vb.get('filters'), ensure_ascii=False))}</code></div>")
    parts.append("<div class='box'>" + "".join(b) + "</div>")
    if not rec.get("units"):
        parts.append(f"<div class='box g'>② 이후 단계 없음 (분석 상태 {_e(q.get('status'))})</div>")
    # ② 검색 + ③ View + ④ 충돌 (단위마다)
    for u in rec.get("units") or []:
        b = [f"<div class='uh'>검색 단위 <code>{_e(u['unit_id'])}</code> — 검색 문장 <b>{_e(u['search_query'])}</b> · "
             f"슬롯 <code>{_e(json.dumps(u['filters'], ensure_ascii=False))}</code></div>"]
        if u is rec["units"][0]:
            b.insert(0, _stage_head(rec, "search"))
        b.append(_tbl(["순위", "조사", "표", "ID", "점수", "BM25", "못 맞춘 조건", "View"],
                      [[f"★{c['rank']}" if is_gold(g, c["tbl_id"], c.get("survey_nm")) else c["rank"], c["survey_nm"],
                        c["tbl_nm"], c["tbl_id"], c["score"], c["bm25_rank"],
                        "; ".join(c["unmet"]), "●" if c["has_view"] else ""] for c in u["candidates"]], 10,
                      hl=lambda i, v: bool(v[6])))
        parts.append("<div class='box'>" + "".join(b) + "</div>")
        b = [_stage_head(rec, "view")] if u is rec["units"][0] else []
        for v in u["views"]:
            rc = v.get("raw") or {}
            if rc.get("error"):
                raw_h = f"<span class='w'>원본 대조 오류 {_e(rc['error'])}</span>"
            elif rc.get("exists") is False:
                raw_h = "<span class='w'>원본 CSV 없음</span>"
            elif rc.get("n"):
                good = rc["ok"] == rc["n"]
                raw_h = (f"<b style='color:{'#15803d' if good else '#b91c1c'}'>{'✅' if good else '⚠️'} 원본 대조 {rc['ok']}/{rc['n']}칸 일치</b>"
                         f" <span class='g'>(원본 같은 좌표 {rc.get('n_raw')}행)</span>"
                         + "".join(f"<div class='w'>✗ {_e(x)}</div>" for x in rc.get("bad", [])))
            else:
                raw_h = "<span class='g'>대조할 값 없음</span>"
            used = " ".join(f"{k}{'○' if ok else '✗'}" for k, ok in (v.get("used") or {}).items())
            inc = "· <b>비교에 넣음</b>" if v.get("usable") else "· <b style='color:#b91c1c'>비교 제외</b>"
            ev = "; ".join(f"{k}: {c.get('status')} — {c.get('evidence')}" for k, c in (v.get("checks") or {}).items()
                           if c.get("status") not in ("not_requested",))
            b.append(
                f"<div class='vb'><div><b>{'★ ' if is_gold(g, v['tbl_id'], v.get('survey_nm')) else ''}"
                f"#{_e(v['rank'])} {_e(v['tbl_nm'] or v['tbl_id'])}</b> "
                f"<span class='g'>{_e(v['survey_nm'])} · {_e(v['tbl_id'])} · {_e(v['period'])} ({_e(v['prd_se'])}) · 단위 {_e(v['unit'] or '-')}"
                f" · {_e(v['view_type'])} · 값 {_e(v['n_points'])}칸</span></div>"
                f"<div>🔗 KOSIS {_link(v['kosis_url'])}</div>"
                f"<div>📄 원본 CSV {_file_link(rc.get('path') or '', '열기')}</div>"
                f"<div>🧾 View CSV {_file_link(v['view_csv'], '열기')}</div>"
                f"<div>필수 메타 사용 <b>{_e(used or '-')}</b> {inc}</div>"
                f"<div class='g'>판단 근거: {_e(ev)}</div>"
                + ("".join(f"<div class='w'>⚠ {_e(n)}</div>" for n in v["notes"]))
                + f"<div class='g'>좌표: {_e(json.dumps(v['source'], ensure_ascii=False))}</div>"
                + "<div class='two'><div><b>잘라 낸 View</b>" + _tbl(v["columns"], v["rows"], 12) + "</div>"
                + f"<div><b>원본 CSV 같은 좌표</b> {raw_h}" + _tbl(list((rc.get('raw_rows') or [{}])[0].keys()), rc.get("raw_rows") or [], 12)
                + "</div></div></div>")
        if not u["views"]:
            b.append("<div class='g'>View 없음</div>")
        parts.append("<div class='box'>" + "".join(b) + "</div>")
        c = u["conflict"]
        b = [_stage_head(rec, "conflict")] if u is rec["units"][0] else []
        b.append(f"<div>판정 <code>{_e(c['status'])}</code> · 비교한 교차점 {c['n_compared_keys']} · {_e(' / '.join(c['notes']))}"
                 f"{' · 선택 ' + _e(c['selected_option']) if c.get('selected_option') else ''}</div>")
        if c["differing_points"]:
            tbls = sorted({x["tbl_id"] for d in c["differing_points"] for x in d["values"]})
            b.append(_tbl(["교차점"] + tbls, [[d["key_str"]] + [next((f"{_fmt(x['value'])} {x['unit']}" for x in d["values"]
                                                                  if x["tbl_id"] == t), "") for t in tbls]
                                             for d in c["differing_points"]]))
        for o in c["options"]:
            fn = "".join(f"<div class='g'>※ [{_e(f['type'])}{' ' + _e(f['target']) if f.get('target') else ''}] {_e(f['text'])}</div>"
                         for f in o.get("footnotes") or [])
            b.append(f"<div class='op'><b>{_e(o['option_id'])}</b>{' ✔' if o['option_id'] == c.get('selected_option') else ''} "
                     f"{_e(o['tbl_nm'])} <code>{_e(', '.join(o['tbl_ids']))}</code> {_link(o.get('kosis_url'), 'KOSIS')}"
                     f"<div class='g'>기준 {_e(json.dumps({k: v for k, v in (o.get('basis') or {}).items() if v}, ensure_ascii=False))}</div>{fn}</div>")
        parts.append("<div class='box'>" + "".join(b) + "</div>")
    if rec.get("answer"):
        a = rec["answer"]
        ans = _e(a.get("answer"))
        for nn in sorted(set(a.get("unverified_numbers") or []), key=len, reverse=True):
            ans = ans.replace(_e(nn), f"<mark>{_e(nn)}</mark>")
        parts.append(f"<div class='box'>{_stage_head(rec, 'answer')}<div>{ans}</div>"
                     f"<div class='g'>사용 View {_e(a.get('used_ids'))} · 미검증 숫자 {_e(a.get('unverified_numbers'))}</div></div>")
    fin = rec.get("final") or {}
    parts.append(f"<div class='g'>최종: {_e(fin.get('status'))} · 넘긴 View {len(fin.get('records') or [])}개"
                 f"{' · 선택 대기 ' + _e(fin.get('pending')) if fin.get('pending') else ''}</div>")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
.card{{width:1100px;padding:18px 22px;font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#000;
font-size:13.5px;line-height:1.5;background:#fff;text-align:left}} .card h2{{margin:0 0 6px;font-size:18px;color:#000}}
.card .box{{border:1px solid #cbd5e1;border-radius:8px;padding:8px 12px;margin:8px 0}} .card .g{{color:#475569;font-size:12px}}
.card .w{{background:#fff7ed;border:1px solid #fdba74;padding:2px 8px;border-radius:6px;margin:3px 0}}
.card .hm{{background:#eff6ff;border-color:#93c5fd}} .card .sh{{font-size:14.5px;margin-bottom:4px}}
.card .uh{{margin:4px 0;padding:3px 6px;background:#f8fafc;border-radius:4px}} .card .vb{{border-top:1px dashed #cbd5e1;padding:6px 0;margin-top:6px}}
.card .op{{border-left:3px solid #94a3b8;padding:2px 8px;margin:4px 0}} .card ul.rs{{margin:2px 0 6px 0;padding-left:18px}}
.card .bd{{font-weight:700;padding:1px 7px;border-radius:6px;font-size:12px}} .card .two{{display:flex;gap:10px}} .card .two>div{{flex:1;min-width:0}}
.card table.t{{border-collapse:collapse;width:100%;margin-top:4px;font-size:12px}}
.card .t th,.card .t td{{border:1px solid #cbd5e1;padding:2px 5px;text-align:left;color:#000;background:#fff;vertical-align:top}}
.card .t th{{background:#f1f5f9}} .card .t tr.hl td{{background:#fef2f2}} .card mark{{background:#fecaca}} .card code{{font-size:11.5px;color:#000}}
.card a{{color:#1d4ed8}}
</style></head><body><div class="card">{''.join(parts)}</div></body></html>"""


CARD_WIDTH = 1180          # 카드 1100px + 여백 (PNG 화면 폭)


def write_card(run, rec, png=True):
    """카드 HTML (+ PNG 한 장). PNG 는 별도 프로세스에서 (review_80.png_many — Windows Jupyter 에서도 동작)"""
    run.card_dir.mkdir(parents=True, exist_ok=True)
    hp = run.card_dir / f"{rec['id']}.html"
    hp.write_text(card_html(rec), encoding="utf-8")
    pp = run.card_dir / f"{rec['id']}.png"
    return hp, (pp if png and r80.png_many([(hp, pp)], CARD_WIDTH) else None)


def write_cards(run, ids=None, png=True, log=print, queries=None):
    """카드 여러 장: HTML 을 모두 쓴 뒤 PNG 는 한 번에 (브라우저 한 번만 띄움).
    queries 를 주면 정답 참고를 다시 읽어 붙임 (예전 결과에도 ★·hit 표시)"""
    data = load_results(run)
    if queries is not None:
        refs = references(queries)
        for k in data:
            data[k]["gold_ref"] = refs.get(k) or {}
        save_results(run, data)
    keys = [k for k in sorted(data) if not ids or k in ids]
    pairs = [(write_card(run, data[k], png=False)[0], run.card_dir / f"{k}.png") for k in keys]
    made = r80.png_many(pairs, CARD_WIDTH, log) if png else []
    log(f"카드 HTML {len(keys)}장, PNG {len(made)}장 → {run.card_dir}")


# ═════════════════════════════ CLI ═════════════════════════════
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--queries", default=None)
    r.add_argument("--n", type=int)
    r.add_argument("--ids", nargs="*")
    r.add_argument("--force", action="store_true")
    r.add_argument("--today", default=r80.DEFAULT_TODAY)
    r.add_argument("--clarify", choices=["first", "none"], default="first")
    r.add_argument("--select", choices=["first", "none"], default="first")
    r.add_argument("--n-views", type=int, default=3)
    r.add_argument("--config", default=None, help="검색 구성 (configs/retrieval/<이름>, 기본 = 기존 검색)")
    r.add_argument("--answer", action="store_true", help="⑤ HCX 답변까지 (문항당 HCX 1회 추가)")
    r.add_argument("--no-raw", action="store_true", help="원본 CSV 대조 생략")
    r.add_argument("--no-png", action="store_true")
    c = sub.add_parser("cards")
    c.add_argument("--queries", default=None)
    c.add_argument("--png", action="store_true")
    s = sub.add_parser("summary")
    s.add_argument("--queries", default=None)
    h = sub.add_parser("hits", help="정답 표 기준 hit@k·MRR (정답 참고 파일 · 사람이 지정한 정답 표 · 조사명)")
    h.add_argument("--queries", default=None)
    a = ap.parse_args()
    if a.cmd == "list":
        list_sets()
    elif a.cmd == "run":
        run_batch(a.queries, a.ids, a.n, a.force, png=not a.no_png, today=a.today, clarify=a.clarify, select=a.select,
                  n_views=a.n_views, retrieval_config=a.config, answer=a.answer, raw=not a.no_raw)
    elif a.cmd == "cards":
        write_cards(run_for(a.queries)[0], png=a.png)
    elif a.cmd == "summary":
        run = run_for(a.queries)[0]
        gt, rt = stage_summary(load_results(run))
        print(gt.to_string(), "\n")
        print(rt.to_string(index=False))
    elif a.cmd == "hits":
        run = run_for(a.queries)[0]
        df, sm = hit_table(load_results(run), references(a.queries))
        print(sm.to_string(index=False), "\n")
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
