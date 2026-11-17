"""
답변 — Record 목록 → HCX 답변 + 차트 + 출처 (HCX 1회)

  answer_from_records(question, records, notes, titles, ...)   POST /api/v1/agent/answer · /chat 의 마지막 단계
  verify_numbers(answer, context)                              답변 숫자 중 [자료]에 없는 것 (계산값일 수 있음)
"""
import math
import re

from backend.agent.prompts import ANSWER_SCHEMA, ANSWER_SYS
from backend.core.llm import chat

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
NO_RECORDS = {"answer": "질문에 맞는 통계표를 찾지 못했습니다.", "summary": "", "key_points": [], "insufficient": True,
              "unverified_numbers": [], "used_ids": [], "chart_id": None, "chart": None, "sources": [], "caveats": []}


def fmt_v(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "자료없음"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def nums(text):
    out = set()
    for n in NUM_RE.findall(str(text)):
        try:
            v = float(n.replace(",", ""))
        except ValueError:
            continue
        out.add(f"{v:.2f}")
        out.add(f"{round(v):.2f}")
    return out


def verify_numbers(answer_text, context_text):
    ctx = nums(context_text)
    bad = []
    for n in NUM_RE.findall(answer_text):
        if len(n.replace(",", "").replace(".", "")) <= 2:      # 1~2자리(순위·개수)는 제외
            continue
        if not (nums(n) & ctx):
            bad.append(n)
    return sorted(set(bad))


def record_title(rec, titles=None):
    return (titles or {}).get(rec["id"]) or " ".join(str(rec.get("lexical_text", "")).split()[:8])


def record_context(rec, max_rows, notes=None, title=None):
    """Record → [자료] 블록"""
    md, src, t = rec.get("metadata") or {}, rec.get("source") or {}, rec.get("table") or {}
    cols, rows = t.get("columns") or [], t.get("rows") or []
    lines = [f"[자료 id={rec['id']}]",
             f"제목: {title or record_title(rec)}",
             f"출처: {md.get('survey_nm', '')} {src.get('kosis_url', '')}".strip(),
             f"조건: {rec.get('lexical_text', '')}",
             f"기간: {md.get('prd_from')}~{md.get('prd_to')} ({md.get('prd_se')})"
             + (" · 최신" if md.get("is_latest") else "") + f" / 단위: {md.get('unit') or '-'}"]
    if notes:
        lines.append("⚠ 질문 조건 중 이 자료에 맞추지 못한 것: " + "; ".join(notes)
                     + " → 이 자료의 값을 질문 대상의 값으로 답하지 말 것")
    if rows:
        lines.append(f"데이터({' | '.join(cols)}):")
        for r in rows[:max_rows]:
            lines.append("  " + " | ".join(fmt_v(x) if isinstance(x, (int, float)) else str(x) for x in r))
        if len(rows) > max_rows:
            lines.append(f"  … 외 {len(rows) - max_rows}행")
    else:
        lines.append("데이터: 조건에 맞는 값이 없음")
    return "\n".join(lines)


def pick_context(records, notes, groups=None, k=4, k_max=6):
    """답변에 넣을 Record: 조건을 모두 맞춘 View → 일부 → 빈 View 순 앞 k 개.
    groups = {record id: 검색 단위 id} 를 주면 단위마다 가장 좋은 1개를 먼저 넣고 남는 자리를 채움
    (비슷한 표가 앞자리를 차지해 다른 단위의 표가 빠지지 않게. 단위가 k 보다 많으면 k_max 까지)"""
    def key(r):
        return (not (r.get("table") or {}).get("rows"), len(notes.get(r["id"], [])))
    ordered = sorted(records, key=key)
    if not groups:
        return ordered[:k]
    order = list(dict.fromkeys(groups.get(r["id"]) for r in records))
    first = [next(r for r in ordered if groups.get(r["id"]) == g) for g in order]
    k = min(max(k, len(first)), k_max)
    seen = {(r.get("source") or {}).get("tbl_id") for r in first}
    rest = []
    for r in ordered:
        t = (r.get("source") or {}).get("tbl_id")
        if r not in first and t not in seen:
            seen.add(t)
            rest.append(r)
    return (first + rest)[:k]


def answer_from_records(question, records, notes=None, titles=None, max_rows=40, queries=None, extra_context=None,
                        groups=None):
    """Record 목록 → AnswerResult(dict).
    extra_context: [자료] 뒤에 붙일 블록 (코드 계산 결과 등). 숫자 검증 근거에도 포함"""
    from backend.data_engine.chart_generator import chart_from_record
    notes, titles = notes or {}, titles or {}
    by_id = {r["id"]: r for r in records}
    ctx = pick_context(records, notes, groups)
    if not ctx:
        return dict(NO_RECORDS)
    if len(ctx) > 4:                                   # 표가 많으면 표마다 행 수를 줄여 전체 분량 유지
        max_rows = max(12, max_rows * 4 // len(ctx))
    context = "\n\n".join(record_context(r, max_rows, notes.get(r["id"]), titles.get(r["id"])) for r in ctx)
    if extra_context:
        context = f"{context}\n\n{extra_context}"
    out = chat([{"role": "system", "content": ANSWER_SYS},
                {"role": "user", "content": f"[질문]\n{question}\n\n[검색어]\n{' / '.join(queries or [question])}"
                                            f"\n\n[자료]\n{context}"}],
               schema=ANSWER_SCHEMA, max_tokens=1200)
    ans = out.get("answer") or out.get("_raw", "")
    used = [u for u in (out.get("used_ids") or []) if u in by_id] or [ctx[0]["id"]]
    chart_id = out.get("chart_id") if out.get("chart_id") in by_id else used[0]
    cond_ok = any(not notes.get(r["id"]) and (r.get("table") or {}).get("rows") for r in ctx)
    return {"answer": ans, "summary": out.get("summary", ""), "key_points": out.get("key_points") or [],
            "insufficient": bool(out.get("insufficient")) or not cond_ok,
            "unverified_numbers": verify_numbers(" ".join([ans, out.get("summary", "")] + list(out.get("key_points") or [])),
                                                 context),
            "used_ids": used, "chart_id": chart_id,
            "chart": chart_from_record(by_id[chart_id], record_title(by_id[chart_id], titles)),
            "sources": list(dict.fromkeys(
                f"{(by_id[u].get('metadata') or {}).get('survey_nm', '')} {record_title(by_id[u], titles)} "
                f"{(by_id[u].get('source') or {}).get('kosis_url', '')}".strip() for u in used)),
            "caveats": list(dict.fromkeys(n for u in used for n in notes.get(u, [])))[:6]}
