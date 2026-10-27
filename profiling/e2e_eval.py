"""
골든셋 E2E 평가: 질문 → kosis_rag_qa.answer() → 관문 3개로 실패 지점 판정

관문 1 검색   정답 표의 레코드가 최종 검색 상위 k 안에 있나        → 아니면 ① Retrieval 실패
관문 2 문맥   LLM 에게 준 [자료] 안에 정답 숫자가 들어 있나          → 아니면 ② 조회 실패
관문 3 답변   답변의 숫자·단위·필수 언급이 맞고 지어낸 숫자가 없나   → 아니면 ③ Generation 실패
모두 통과                                                          → ④ 정답

answer() 는 최종 답변만 돌려주므로, 문맥은 answer() 와 같은 함수(apply_conditions → condition_rows →
context_block, 모두 LLM 호출 없음)로 다시 만들어 확인한다. 베이스라인 코드는 수정하지 않는다.

입력  profiling/golden/golden_set.built.jsonl  (python -m profiling.golden.build_gold 결과)
출력  profiling/output/e2e_runs/<YYYYMMDD_HHMMSS>/{results.jsonl, report.md}   실행마다 보존
      profiling/output/e2e_results.jsonl · e2e_report.md   최신 '정상' 실행 (실행 오류가 0건일 때만 갱신)

시작 전에 HCX 임베딩·대화를 1회씩 호출해 인증을 확인하고, 실패하면 아무 파일도 쓰지 않는다.
실행 중 인증 오류(401·403)가 나면 남은 문항을 건너뛴다.

실행  python -m profiling.e2e_eval                    # 실행 A(재작성 사용) + B(재작성 없음)
      python -m profiling.e2e_eval --qids Q1 Q4 --skip-no-rewrite
      python -m profiling.e2e_eval --rescore e2e_results_criteria.jsonl   # 저장 결과 재채점 (LLM·HCX 호출 없음)
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from profiling import config
from profiling import criteria as cr
from profiling.criteria import NEG_WORDS, answer_text, extract_numbers, matches  # noqa: F401  (기존 import 경로 유지)

os.chdir(config.REPO_ROOT)            # kosis_rag_qa 의 인덱스·레코드 경로가 저장소 루트 기준 상대 경로
import kosis_rag_qa as qa  # noqa: E402

qa.VIEWS_DIR = config.VIEWS_DIR

GOLDEN = config.PROFILING_DIR / "golden" / "golden_set.built.jsonl"
K = 5                                  # answer() 기본값과 같은 검색 상위 개수
MAX_ROWS = 40                          # answer() 기본값과 같은 문맥 행 수
VERDICT = {1: "① Retrieval 실패", 2: "② 조회 실패", 3: "③ Generation 실패", 4: "④ 정답"}
AUTH_FAIL = {401, 403}                 # 키·주소 문제: 재시도해도 소용없으므로 즉시 중단
RUNS_DIR = config.OUTPUT_DIR / "e2e_runs"
CRITERIA = ("C1", "C2", "C3", "C4")    # 점수형 기준 (C5 는 혼동표로 따로 집계)


def contexts(idx, rec_ids, question):
    """answer() 가 LLM 에 넣은 [자료] 블록을 같은 함수로 재현 (LLM 호출 없음)"""
    out = {}
    for rid in rec_ids:
        r = idx.by_id[rid]
        try:
            src, applied, missing = qa.apply_conditions(r, question)
            crow = qa.condition_rows(src, MAX_ROWS)[1] if applied else None
        except Exception as e:  # noqa: BLE001  (answer() 와 같은 예외 처리)
            applied, missing, crow = {}, [f"조건 적용 실패: {e.__class__.__name__}"], None
        out[rid] = {"text": qa.context_block(r, MAX_ROWS, (applied, missing, crow)),
                    "applied": applied, "missing": missing}
    return out


def raw_search(idx, question):
    """재작성 없이 원 질문 그대로 검색한 상위 10개. id 까지 저장해 두면 정답 id 가 바뀌어도 다시 판정할 수 있다"""
    return [{"id": h["id"], "title": h["title"], "bm25_rank": h.get("bm25_rank"), "dense_rank": h.get("dense_rank")}
            for h in idx.search(question, k=10)]


def retrieval_from(g, raw_top, fused_top):
    """저장된 검색 결과 + 현재 정답 id → 관문 1 판정 (검색을 다시 하지 않는다. 정답표가 바뀐 뒤 재판정에도 쓴다)"""
    gold = set(g["gold_ids"])
    raw_rank = next((i + 1 for i, h in enumerate(raw_top) if h["id"] in gold), None)
    raw_hit = raw_top[raw_rank - 1] if raw_rank else {}
    fused_rank = next((i + 1 for i, (x, _) in enumerate(fused_top) if x in gold), None)
    return {"raw_rank": raw_rank, "raw_bm25_rank": raw_hit.get("bm25_rank"),
            "raw_dense_rank": raw_hit.get("dense_rank"), "raw_top3": [h["title"] for h in raw_top[:3]],
            "raw_top": raw_top, "fused_rank": fused_rank, "fused_top": [list(x) for x in fused_top],
            "pass": fused_rank is not None}


def gate_retrieval(idx, g, res):
    return retrieval_from(g, raw_search(idx, g["question"]), [(h["id"], h["title"]) for h in res["retrieved"]])


def required_tokens(g):
    """정답 칸을 가리키는 말: 분류값(서울특별시, 여자, 1985 …) + 시점(2025, 2/4)"""
    e = g["expect"]
    toks = list(e["dims"].values()) + [e["prd_de"][:4]]
    if e["prd_se"] == "Q":
        toks.append(f"{int(e['prd_de'][4:])}/4")
    return toks


def block_has_gold(text, g):
    """자료 블록 안에 '정답 칸'의 값이 있나. 숫자만 같으면 다른 칸(예: 다른 년생)의 우연한 일치일 수 있어서,
    정답 숫자가 있는 데이터 행에 분류값·시점이 행 자체나 블록 머리말(제목·설명·조건 줄)에 모두 있어야 인정한다."""
    lines = text.splitlines()
    header = " ".join(l for l in lines if " | " not in l)
    for line in lines:
        if " | " not in line or not matches(extract_numbers(line), g["gold_value"], g["tolerance"]):
            continue
        if all(t in line or t in header for t in required_tokens(g)):
            return True
    return False


def gate_context(idx, g, res):
    """문맥 재현. 정답 칸 판정(lookup: block_has_gold, 지표형: C3)은 judge() 에서 한다"""
    ctx = contexts(idx, list(res["conditions"]), g["question"])
    answerable = {v["id"] for v in g.get("answerable_views") or g.get("fit_views") or []}
    return {"ctx_ids": list(ctx), "ctx_answerable": [r for r in ctx if r in answerable],
            "conditions": {r: {"applied": c["applied"], "missing": c["missing"]} for r, c in ctx.items()},
            "_texts": {r: c["text"] for r, c in ctx.items()}}


def silent_values(g, res, texts, g3):
    """조용한 오답: 정답 숫자는 없고, 자료 부족이라고도 하지 않았는데, 문맥에 있는 '다른 칸'의 숫자로 답함.
    질문에 나온 숫자(연도·나이·년생)와 연도처럼 생긴 값은 제외한다 (문맥의 시점 표기와 겹치므로)."""
    if g3["numbers_matched"] or res.get("insufficient"):
        return []
    q_nums = {v for v, _ in extract_numbers(g["question"])}
    ctx = [n for t in texts.values() for n in extract_numbers(t)]
    return sorted({v for v, tol in extract_numbers(answer_text(res))
                   if v not in q_nums and not (v.is_integer() and 1900 <= v <= 2100) and matches(ctx, v, tol)})


def gate_answer(g, res):
    text = answer_text(res)
    hit = matches(extract_numbers(text), g["gold_value"], g["tolerance"])
    reasons = []
    if not hit:
        reasons.append("정답 숫자 없음")
    if g["gold_value"] < 0 and hit and not (any(v < 0 for v in hit) or NEG_WORDS.search(text)):
        reasons.append("음수(감소·순유출)를 밝히지 않음")
    unit_ok = any(u in text for u in g.get("unit_expect", []))
    if g.get("unit_expect") and not unit_ok:
        reasons.append(f"단위 없음 (기대: {'/'.join(g['unit_expect'])})")
    for group in g.get("must_mention", []):
        if not any(w in text for w in group):
            reasons.append(f"필수 언급 없음 ({'/'.join(group)})")
    if res.get("unverified_numbers"):
        reasons.append(f"문맥에 없는 숫자 {res['unverified_numbers']}")
    if res.get("insufficient"):
        reasons.append("모델이 자료 부족(insufficient)으로 답함")
    return {"numbers_matched": hit, "unit_ok": unit_ok, "reasons": reasons, "pass": not reasons}


def judge(g, res, g1, texts):
    """관문 판정 + 기준별 점수. 저장된 결과로 다시 채점할 때도 쓰도록 answer() 호출과 분리"""
    lookup = g.get("type", "lookup") == "lookup"
    if lookup:
        with_gold = [rid for rid, t in texts.items() if block_has_gold(t, g)]
        g2_pass, g3 = bool(with_gold), gate_answer(g, res)
    else:
        with_gold = []
    crit = cr.score_all(g, res, texts, [x for x, _ in g1["fused_top"]])
    if not lookup:
        g2_pass = crit["C3"]["raw"] == 1 or crit["C3"]["facts"] is True   # 원시 칸이 없어도 맞는 facts 로 답할 수 있음
        bad = [f"{k}: {v}" for k, v in crit["C4"]["items"].items() if v is not True]
        flags = cr.wrong_flags(g, res)               # 정답 지표가 맞아도 틀린 숫자를 섞었으면 통과시키지 않는다
        if flags:                                    # (정답을 계산해 낸 값에 뜬 경고는 오탐이므로 제외)
            bad.append(f"문맥에 없는 숫자 {flags}")
        g3 ={"numbers_matched": [], "reasons": bad, "pass": not bad}
    stage = 1 if not g1["pass"] else 2 if not g2_pass else 3 if not g3["pass"] else 4
    silent = silent_values(g, res, texts, g3) if lookup and stage in (2, 3) else []
    if silent:
        crit["C5"] = cr.c5(g, {**res, "_silent_values": silent}, texts)
    return stage, silent, with_gold, g2_pass, g3, crit


def evaluate(idx, g, use_rewrite):
    t0 = time.time()
    res = qa.answer(g["question"], variant="base", k=K, use_rewrite=use_rewrite, max_rows=MAX_ROWS,
                    save=False, idx=idx)
    g1 = gate_retrieval(idx, g, res)
    g2 = gate_context(idx, g, res)
    texts = g2.pop("_texts")
    return build_row(g, res, g1, g2, texts, use_rewrite, round(time.time() - t0, 2))


def build_row(g, res, g1, g2, texts, use_rewrite, elapsed_s):
    """판정 + 결과 행 조립. evaluate() 와 저장 결과 재채점(rescore_row)이 함께 쓴다"""
    stage, silent, with_gold, g2_pass, g3, crit = judge(g, res, g1, texts)
    g2.update(ctx_with_gold=with_gold, **{"pass": g2_pass})
    return {"qid": g["qid"], "type": g.get("type", "lookup"), "run": "rewrite" if use_rewrite else "no_rewrite",
            "question": g["question"], "gold_value": g.get("gold_value"), "gold_unit": g.get("gold_unit"),
            "stage": stage, "verdict": VERDICT[stage] + (" · 조용한 오답" if silent else ""), "silent_values": silent,
            "insufficient": bool(res.get("insufficient")), "unverified_numbers": res.get("unverified_numbers") or [],
            "criteria": crit, "retrieval": g1, "context": g2, "answer_check": g3,
            "rewritten": res.get("rewritten"), "sub_questions": res.get("sub_questions"),
            "answer": res.get("answer"), "summary": res.get("summary"), "key_points": res.get("key_points"),
            "used_ids": res.get("used_ids"), "caveats": res.get("caveats"),
            "elapsed_s": elapsed_s, "context_texts": texts}


def fmt_num(v):
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"


def fmt_rank(r):
    return f"{r}위" if r else "없음"


def use_conditions(name):
    """--conditions v2: answer() 와 문맥 재현이 모두 qa.apply_conditions 를 이름으로 찾으므로 모듈 속성만 바꾼다"""
    if name == "v2":
        from profiling.conditions_v2 import apply_conditions_v2
        qa.apply_conditions = apply_conditions_v2


def use_context(name):
    """--context v2: 조건 적용 단면·기간으로 facts 를 코드가 계산해 문맥에 넣는다 (condition_rows·context_block 교체)"""
    if name == "v2":
        from profiling.context_v2 import install
        install()


def criteria_section(results):
    """팀 기준 C1~C5 점수표 · 기준별 평균 · C5 혼동표 · 전체 C2(check_facts)"""
    ok = [r for r in results if r.get("criteria")]
    head = ["qid", "유형", "실행"] + list(CRITERIA) + ["C5 틀림/놓침", "판정"]
    md = ["## 팀 기준 점수 (C1~C5, EVAL_CRITERIA.md)", "",
          "O 통과 · △ 부분 · X 실패 · - 해당 없음", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in ok:
        c = r["criteria"]
        md.append("| " + " | ".join([r["qid"], r.get("type", "lookup"), r["run"]]
                                    + [cr.mark(c[k]["score"]) for k in CRITERIA]
                                    + [f"{len(c['C5']['wrong'])}/{c['C5']['FN']}", r["verdict"]]) + " |")
    md += ["", "| 기준 | 채점 문항×실행 | 평균 점수 | 통과 |", "|---|---|---|---|"]
    for k in CRITERIA:
        s = [r["criteria"][k]["score"] for r in ok if r["criteria"][k]["score"] is not None]
        md.append(f"| {k} | {len(s)} | {sum(s) / len(s):.2f} | {sum(x >= 1 for x in s)} |" if s else f"| {k} | 0 | - | - |")
    c3f = [r["criteria"]["C3"]["facts"] for r in ok if r["criteria"]["C3"]["facts"] is not None]
    if c3f:
        md.append(f"| C3 중 facts | {len(c3f)} | {sum(c3f) / len(c3f):.2f} | {sum(c3f)} |")
    t = {k: sum(r["criteria"]["C5"][k] for r in ok) for k in ("TP", "FN", "FP", "TN", "unknown", "out_of_scope")}
    rec = t["TP"] / (t["TP"] + t["FN"]) if t["TP"] + t["FN"] else None
    prec = t["TP"] / (t["TP"] + t["FP"]) if t["TP"] + t["FP"] else None
    md += ["", "### C5 자동 환각 검증 (verify_numbers 혼동표)", "",
           "| | verify 표시함 | verify 표시 안 함 |", "|---|---|---|",
           f"| 틀린 숫자 | TP {t['TP']} | **FN {t['FN']}** (그중 1~2자리라 검사 대상 밖 {t['out_of_scope']}) |",
           f"| 맞는 숫자 | FP {t['FP']} | TN {t['TN']} |", "",
           f"- 재현율(틀린 숫자를 잡은 비율) **{'-' if rec is None else f'{rec:.0%}'}**, "
           f"정밀도 {'-' if prec is None else f'{prec:.0%}'}, 확인 불가(문맥엔 있으나 묻지 않은 숫자) {t['unknown']}"]
    cf = config.OUTPUT_DIR / "check_facts.md"
    if cf.exists():
        lines = cf.read_text(encoding="utf-8").splitlines()
        i = next((n for n, l in enumerate(lines) if l.startswith("## 검사별 요약")), None)
        if i is not None:
            md += ["", "### C2 전체 (check_facts.py, 뷰 1,651개)", ""] + \
                  [l for l in lines[i + 2:] if l.startswith("|")][:8]
    return md + [""]


def report(results, gold, conditions="base"):
    by_q = {g["qid"]: g for g in gold}
    head = ["qid", "실행", "원 질문 순위 (BM25/Dense)", "최종 검색", "문맥에 정답", "답변 숫자", "판정", "사유"]
    md = ["# E2E 평가 결과", "",
          f"- 문항 {len(gold)}개, 실행 {len({r['run'] for r in results})}종, 검색 상위 k={K}, "
          f"조건 적용 `{conditions}`", ""] + criteria_section(results) + \
         ["## 관문 요약", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in results:
        rt, cx, an = r["retrieval"], r["context"], r["answer_check"]
        md.append("| " + " | ".join([
            r["qid"], r["run"],
            f"{fmt_rank(rt['raw_rank'])} ({rt['raw_bm25_rank']}/{rt['raw_dense_rank']})" if rt["raw_rank"]
            else "없음",
            fmt_rank(rt["fused_rank"]), "O" if cx["pass"] else "X",
            ", ".join(fmt_num(v) for v in sorted(set(an["numbers_matched"])))
            or ("⚠ " + ", ".join(fmt_num(v) for v in r["silent_values"]) if r.get("silent_values") else "-"),
            r["verdict"], "; ".join(an["reasons"]) if r["stage"] == 3 else "",
        ]) + " |")
    for qid, g in by_q.items():
        gold_txt = fmt_num(g["gold_value"]) if g.get("type", "lookup") == "lookup" else " / ".join(
            f"{k} {m.get('name', '')}{m.get('period', '')} {fmt_num(m['value']) if isinstance(m['value'], (int, float)) else m['value']}"
            for k, m in g["gold_metrics"].items() if k in g["metrics"])
        md += ["", f"## {qid}. {g['question']}", "",
               f"- 정답: **{gold_txt}** ({g.get('gold_unit', '')}) · 함정: {g['trap']} · 확인할 한계: "
               f"{', '.join(g['limits'])}"]
        fit = {v["id"] for v in g.get("answerable_views") or g.get("fit_views") or []}
        gold_ids = set(g["gold_ids"])

        def mk(rid):
            return "★" if rid in fit else "✅" if rid in gold_ids else "  "
        for r in [x for x in results if x["qid"] == qid]:
            rt, cx = r["retrieval"], r["context"]
            raw3 = [f"{mk(h['id'])} {h['title']}".strip() for h in rt["raw_top"][:3]] if rt.get("raw_top") else rt["raw_top3"]
            md += ["", f"### 실행: {r['run']} → {r['verdict']} ({r['elapsed_s']}초)", "",
                   f"- 재작성: {r['rewritten']}" + (f" / 하위 질문: {r['sub_questions']}" if r["sub_questions"] else ""),
                   f"- 원 질문 상위 3: {' | '.join(raw3)}",
                   "- 최종 검색 상위 5 (★ 맞는 뷰 · ✅ 정답 표이지만 맞는 뷰 아님):"]
            md += [f"  {i}. {mk(rid)} {t} `{rid}`" for i, (rid, t) in enumerate(rt["fused_top"], 1)]
            md.append("- 문맥에 넣은 자료:")
            for rid, c in cx["conditions"].items():
                mark = "정답 포함" if rid in cx["ctx_with_gold"] else ""
                md.append(f"  - `{rid}` 적용 {c['applied'] or '-'} / 누락 {c['missing'] or '-'} {mark}")
            md += ["- 답변:", "", "  > " + str(r["answer"]).replace("\n", "\n  > ")]
            if r["answer_check"]["reasons"]:
                md.append(f"- 관문 3 사유: {'; '.join(r['answer_check']['reasons'])}")
            c = r.get("criteria")
            if c:
                md.append(f"- 기준: C1 {cr.mark(c['C1']['score'])} (표 {c['C1']['table_rank']}위·맞는 뷰 "
                          f"{c['C1']['fit_rank']}위 {c['C1']['note']}) · C2 {cr.mark(c['C2']['score'])} ({c['C2']['note']}) · "
                          f"C3 {cr.mark(c['C3']['score'])} (원시 {c['C3']['raw']}, facts {c['C3']['facts']}, "
                          f"없는 칸 {c['C3']['cells_missing']}) · C4 {cr.mark(c['C4']['score'])} "
                          f"{ {k: v for k, v in c['C4']['items'].items() if v is not True} or ''} · "
                          f"C5 틀린 숫자 {c['C5']['wrong']} / verify 놓침 {c['C5']['FN']} / 오탐 {c['C5']['false_alarm']}")
    return md


def preflight():
    """HCX 임베딩·대화 1회씩. 실패하면 파일을 쓰기 전에 종료 (틀린 키로 문항 수만큼 호출하지 않게)"""
    for name, call in [("임베딩", lambda: qa._post(qa.EMBED_PATH, {"text": "ping"})),
                       ("대화", lambda: qa.chat([{"role": "user", "content": "ping"}], max_tokens=5))]:
        try:
            call()
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"HCX {name} 사전 확인 실패 → 실행하지 않음 (파일 변경 없음): "
                             f"{e.__class__.__name__}: {str(e)[:150]}\n.env 의 HCX 키·주소를 확인하세요.")


def error_row(g, use_rw, e):
    return {"qid": g["qid"], "type": g.get("type", "lookup"), "run": "rewrite" if use_rw else "no_rewrite",
            "question": g["question"], "criteria": None,
            "verdict": f"실행 오류: {e.__class__.__name__}: {str(e)[:150]}", "stage": 0, "silent_values": [],
            "retrieval": {"raw_rank": None, "raw_bm25_rank": None, "raw_dense_rank": None,
                          "raw_top3": [], "fused_rank": None, "fused_top": []},
            "context": {"pass": False, "conditions": {}, "ctx_with_gold": []},
            "answer_check": {"numbers_matched": [], "reasons": [], "pass": False},
            "rewritten": None, "sub_questions": None, "answer": None, "elapsed_s": 0}


def write_outputs(results, md, d, results_name, report_name):
    d.mkdir(parents=True, exist_ok=True)
    with (d / results_name).open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in results)
    (d / report_name).write_text("\n".join(md) + "\n", encoding="utf-8")


def rescore_row(get_idx, g, old):
    """저장된 결과 1행을 현재 정답표로 다시 채점 (LLM 호출 없음). 답변·문맥 텍스트는 저장된 것을 그대로 쓰고,
    원 질문 상위 id 가 저장돼 있지 않은 옛 결과만 로컬 검색을 다시 한다 (질문 임베딩이 캐시에 있을 때만)"""
    if not old.get("criteria"):                     # 실행 오류 행은 그대로 둔다
        return old
    rt = old["retrieval"]
    raw_top = rt.get("raw_top")
    if raw_top is None:
        if qa.cache().get(g["question"][:6000]) is None:
            raise SystemExit(f"{g['qid']}: 질문 임베딩이 캐시에 없어 HCX 호출이 필요함 → 재채점 중단 (파일 변경 없음)")
        raw_top = raw_search(get_idx(), g["question"])
    answerable = {v["id"] for v in g.get("answerable_views") or g.get("fit_views") or []}
    cx = old["context"]
    g2 = {"ctx_ids": cx["ctx_ids"], "ctx_answerable": [r for r in cx["ctx_ids"] if r in answerable],
          "conditions": cx["conditions"]}
    res = {k: old.get(k) for k in ("answer", "summary", "key_points", "unverified_numbers", "insufficient",
                                   "rewritten", "sub_questions", "caveats", "used_ids")}
    return build_row(g, res, retrieval_from(g, raw_top, rt["fused_top"]), g2, old["context_texts"],
                     old["run"] == "rewrite", old["elapsed_s"])


def snapshot(r):
    c, rt = r.get("criteria") or {}, r["retrieval"]
    s = {"원 질문 순위": rt["raw_rank"], "최종 검색 순위": rt["fused_rank"], "판정": r["verdict"]}
    for k in CRITERIA:
        s[k] = round(c[k]["score"], 3) if c and c[k]["score"] is not None else None
    if c:
        s["C5"] = "TP{TP} FN{FN} FP{FP} TN{TN}".format(**c["C5"])
        s["C4 사유"] = {k: v for k, v in c["C4"]["items"].items() if v is not True}
    return s


def rescore(paths):
    """--rescore: 저장된 결과를 새 이름(_rescored)으로 다시 채점하고 바뀐 항목을 _rescored_diff.md 에 남긴다"""
    gold = {g["qid"]: g for g in map(json.loads, GOLDEN.open(encoding="utf-8")) if g.get("status") == "ok"}
    state = {}

    def get_idx():
        state.setdefault("idx", qa.Index("base"))
        return state["idx"]
    for p in paths:
        p = p if p.exists() else config.OUTPUT_DIR / p
        old_rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
        new_rows, diffs = [], []
        for o in old_rows:
            n = rescore_row(get_idx, gold[o["qid"]], o) if o["qid"] in gold else o
            new_rows.append(n)
            a, b = snapshot(o), snapshot(n)
            if a != b:
                diffs.append(f"- {o['qid']} [{o['run']}] " + "; ".join(f"{k}: {a.get(k)} → {b[k]}" for k in b if a.get(k) != b[k]))
        qids = list(dict.fromkeys(r["qid"] for r in new_rows if r["qid"] in gold))
        md = report(new_rows, [gold[q] for q in qids], "저장 결과 재채점")
        write_outputs(new_rows, md, config.OUTPUT_DIR, f"{p.stem}_rescored.jsonl",
                      f"{p.stem.replace('results', 'report', 1)}_rescored.md")
        (config.OUTPUT_DIR / f"{p.stem}_rescored_diff.md").write_text(
            f"# {p.name} 재채점에서 바뀐 항목 ({len(diffs)}행 / {len(new_rows)}행)\n\n" + "\n".join(diffs) + "\n",
            encoding="utf-8")
        print(f"{p.name}: 바뀐 행 {len(diffs)}/{len(new_rows)} → {p.stem}_rescored.jsonl · _rescored_diff.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", nargs="+", type=Path, metavar="RESULTS.jsonl",
                    help="저장된 결과를 LLM 호출 없이 현재 정답표로 다시 채점 (새 이름 파일로 저장)")
    ap.add_argument("--qids", nargs="*", help="특정 문항만 (예: Q1 Q4)")
    ap.add_argument("--skip-no-rewrite", action="store_true", help="실행 B(재작성 없음) 생략")
    ap.add_argument("--tag", default="", help="실행 폴더·최신 결과 파일 이름에 붙일 꼬리표 (다른 작업과 파일이 겹치지 않게)")
    ap.add_argument("--context", choices=["base", "v2"], default="base",
                    help="v2: profiling/context_v2 로 조건 단면 facts 를 문맥에 추가")
    ap.add_argument("--conditions", choices=["base", "v2"], default="base",
                    help="v2: profiling/conditions_v2.apply_conditions_v2 로 바꿔 끼움")
    args = ap.parse_args()
    if args.rescore:
        return rescore(args.rescore)
    use_conditions(args.conditions)
    use_context(args.context)
    sfx = ("" if args.conditions == "base" else f"_{args.conditions}") + \
          ("" if args.context == "base" else f"_ctx{args.context}") + (f"_{args.tag}" if args.tag else "")
    gold = [json.loads(l) for l in GOLDEN.open(encoding="utf-8") if l.strip()]
    gold = [g for g in gold if g.get("status") == "ok" and (not args.qids or g["qid"] in args.qids)]
    preflight()
    idx = qa.Index("base")
    runs = [True] + ([] if args.skip_no_rewrite else [False])
    results, aborted = [], None
    for g in gold:
        for use_rw in runs:
            try:
                r = evaluate(idx, g, use_rw)
            except qa.HcxError as e:
                r = error_row(g, use_rw, e)
                if e.http in AUTH_FAIL:
                    aborted = e
            except Exception as e:  # noqa: BLE001  (한 문항 실패가 전체를 멈추지 않게)
                r = error_row(g, use_rw, e)
            results.append(r)
            print(f"{r['qid']} [{r['run']}] {r['verdict']}", flush=True)
            if aborted:
                break
        if aborted:
            print(f"인증 오류로 중단: {aborted} → 남은 문항 건너뜀", flush=True)
            break

    md = report(results, gold, f"{args.conditions}` · 문맥 `{args.context}")
    run_dir = RUNS_DIR / (datetime.now().strftime("%Y%m%d_%H%M%S") + sfx)
    write_outputs(results, md, run_dir, "results.jsonl", "report.md")
    n_err = sum(r["stage"] == 0 for r in results)
    print("\n".join(md[: md.index("## 관문 요약")]))
    print(f"→ 실행 기록: {run_dir}")
    if n_err or aborted:
        print(f"⚠ 실행 오류 {n_err}건 → 최신 결과(e2e_results{sfx}.jsonl, e2e_report{sfx}.md)는 갱신하지 않음")
    else:
        write_outputs(results, md, config.OUTPUT_DIR, f"e2e_results{sfx}.jsonl", f"e2e_report{sfx}.md")
        print(f"→ 최신 결과 갱신: {config.OUTPUT_DIR / f'e2e_report{sfx}.md'}")


if __name__ == "__main__":
    main()
