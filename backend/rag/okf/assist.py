"""
개념 초안 채우기 — 사람이 정의를 처음부터 쓰지 않게

  ① 사실 정의 (늘, 비용 없음)  묶인 표 파일에서만 만든다 — 지어내는 말이 없음
       조사 · 항목/코드/표 · 단위 · 같은 이름이 있는 표 수 · 나누는 분류
       + KOSIS 주석 중 이 개념을 설명하는 줄 ('주1) 미혼모·부의 개념 : …' · 산식 · 집계 대상)
     → description · 본문 '# 정의' · '# 헷갈리는 말' · '# 표' (아직 draft 이고 사람이 고치지 않은 것만 다시 씀)
  ② HCX 보조 (--hcx)  제안만 — 아무것도 승인하지 않음
       정의를 한두 문장으로 (주어진 사실만 · 사실에 없는 숫자가 나오면 버리고 ① 을 씀)
       별칭 판정  same · narrow · broad · wrong + 이유 → 별칭의 review 에 기록
                  broad·wrong 이면 예문 질문 안의 더 좁은 표현을 제안 → 새 미승인 별칭 ('낳은 아이' → '미혼모가 낳은 아이')
       헷갈리는 말  같은 표의 다른 항목·코드 · 별칭이 colloquial 로 바뀌는 말 중에서만 골라 not 에
     verify 는 별칭을 고르지 않으면 review 가 broad·wrong 인 것을 빼고 승인한다 (--alias 로 고르면 그대로)

  python -m backend.rag.okf assist [개념 경로 …] [--no-hcx] [--force]   (경로가 없으면 concepts/_inbox 의 draft 전부)
  python -m backend.rag.okf drafts --runs … --write --hcx                (초안을 쓰면서 바로)
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf.doc import Doc, concept_id, now

FACTS_BY = "process:okf-facts/1"
HCX_BY = "process:okf-assist-hcx/1"
VERDICTS = ("same", "narrow", "broad", "wrong")
SKIP_VERDICTS = ("broad", "wrong")  # verify 가 기본으로 승인하지 않는 판정

_CUE = [(3, re.compile(r"개념|정의|이란|(?<![가-힣])란\s|말함|말한다|의미|뜻함|뜻한다")),
        (2, re.compile(r"대상|집계")),
        (1, re.compile(r"포함|제외"))]
_FORMULA = re.compile(r"[/÷]\s*.*(?:[x×*]\s*100|백분율)|(?:[x×*]\s*100)")
_ADMIN = re.compile(r"공표|잠정|변경|명칭|보도자료|서비스|수정|확정|※|^ㅇ|^-|-{4,}|제공")
MAX_NOTES = 3


# ── 표 사실 ─────────────────────────────────────────────────────
def _table(bundle, path):
    p = Path(bundle) / str(path).lstrip("/")
    d = Doc.read(p) if p.exists() else None
    return None if d is None or d.error else d


def table_notes(doc) -> list:
    """표 파일 본문 '# 주석' 의 줄들"""
    m = re.search(r"^# 주석\s*\n(.*?)(?=^# |\Z)", doc.body or "", re.DOTALL | re.MULTILINE)
    if not m:
        return []
    return [ln.strip()[2:].strip() for ln in m.group(1).splitlines() if ln.strip().startswith("- ") and ln.strip()[2:].strip()]


def table_definitions(doc, max_n=3, max_len=160) -> list:
    """표 파일의 KOSIS 주석 중 정의·집계 대상·산식 줄 (개념 이름과 관계없이) → [줄]. build 가 catalog.json 에 넣고
    LLM 재정렬 카드가 씀 ('주1) 미혼모·부의 개념 : …' · '… 체류기간 90일을 초과하여 … 집계' · '… / … x 100')"""
    out = []
    for ln in table_notes(doc):
        if _ADMIN.search(ln):
            continue
        cue = max([w for w, rx in _CUE if rx.search(ln)] + [0])
        if cue < 2 and not _FORMULA.search(ln):
            continue
        ln = re.sub(r"^[*·•]\s*", "", ln)
        ln = ln if len(ln) <= max_len else ln[:max_len - 1] + "…"
        if ln not in out:
            out.append(ln)
        if len(out) >= max_n:
            break
    return out


def _forms(name):
    from backend.rag.okf.drafts import GENERIC, morphs
    return {f for f, _, _ in morphs(name) if len(f) >= 2 and f not in GENERIC}


def concept_notes(bundle, binds, name) -> list:
    """묶인 표들의 KOSIS 주석 중 이 개념을 설명하는 줄 → [(줄, tbl_id)] (점수 높은 것 먼저, 최대 3)"""
    forms = _forms(name)
    table_level = any("table" in b and "item" not in b and "dim" not in b for b in binds)
    seen, scored = set(), []
    for b in binds:
        doc = _table(bundle, b.get("table", ""))
        if doc is None:
            continue
        tid = (doc.meta.get("x-t4-table") or {}).get("tbl_id") or ""
        for ln in table_notes(doc):
            key = norm(ln)
            if key in seen or _ADMIN.search(ln):
                continue
            hit = any(f in ln for f in forms)
            cue = max([w for w, rx in _CUE if rx.search(ln)] + [0])
            formula = bool(_FORMULA.search(ln))
            if not (cue or formula) or not (hit or (table_level and (cue >= 2 or formula))):
                continue  # 표 전체 개념이면 이름이 안 나와도 되지만 약한 단서('포함')만으로는 안 됨 ('계는 제3의 성을 포함')
            seen.add(key)
            ln = re.sub(r"^[*·•]\s*", "", ln)
            text = ln if len(ln) <= 220 else ln[:217] + "…"
            scored.append((2 * hit + cue + formula, len(scored), text, tid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(t, tid) for _, _, t, tid in scored[:MAX_NOTES]]


def facts(bundle, binds) -> dict:
    """묶인 표에서 → {kind, name, survey, unit, dim, code, titles[], dims[], items[], periods, siblings[]}"""
    out = {"kind": "", "name": "", "survey": "", "unit": "", "dim": "", "code": "", "titles": [], "dims": [], "items": [],
           "periods": "", "siblings": []}
    dims, surveys = Counter(), Counter()
    for i, b in enumerate(x for x in binds if isinstance(x, dict) and "table" in x):
        doc = _table(bundle, b["table"])
        if doc is None:
            continue
        xt = doc.meta.get("x-t4-table") or {}
        title = doc.meta.get("title") or ""
        out["titles"].append(title)
        surveys[xt.get("survey") or ""] += 1
        for dm in xt.get("dims") or []:
            if dm.get("kind") != "geo":
                dims[re.sub(r"\(.*?\)", "", str(dm.get("name"))).removesuffix("별")] += 1
        items = xt.get("items") or []
        if i:
            continue
        # 첫 표(정답 표)에서 종류 · 단위 · 헷갈릴 만한 옆 이름
        out["name"] = b.get("name") or title
        if "item" in b:
            out["kind"] = "item"
            it = next((x for x in items if str(x.get("id")) == str(b["item"])), {})
            out["unit"] = str(it.get("unit") or "")
            out["siblings"] = [str(x.get("name")) for x in items if str(x.get("id")) != str(b["item"])]
        elif "dim" in b:
            out["kind"], out["dim"], out["code"] = "code", str(b["dim"]), str(b.get("code") or "")
            dm = next((x for x in xt.get("dims") or [] if norm(x.get("name")) == norm(b["dim"])), {})
            out["siblings"] = [str(c.get("name")) for c in dm.get("codes") or []
                               if not c.get("total") and str(c.get("code")) != out["code"]][:20]
        else:
            out["kind"] = "table"
            out["items"] = [f"{x.get('name')}" + (f"({x.get('unit')})" if x.get("unit") else "") for x in items][:8]
            per = xt.get("periods") or {}
            out["periods"] = " · ".join(f"{k} {v[0]}~{v[-1]}" for k, v in per.items() if v)
    out["survey"] = surveys.most_common(1)[0][0] if surveys else ""
    out["dims"] = [d for d, _ in dims.most_common(6) if d]
    return out


def fact_definition(f) -> str:
    """사실만으로 된 정의 한 단락"""
    sv = f"{f['survey']} " if f["survey"] else ""
    titles = list(dict.fromkeys(f["titles"]))
    n = len(titles)
    where = (f"표: {titles[0]}." if n == 1 else
             f"같은 이름이 있는 표 {n}개 (예: {titles[0]}" + (f" · {titles[1]}" if n > 1 else "") + (f" 외 {n - 2}개)." if n > 2 else ")."))
    dims = f" 나누는 분류: {', '.join(f['dims'])}." if f["dims"] else ""
    if f["kind"] == "item":
        unit = f" (단위 {f['unit']})" if f["unit"] else ""
        return f"{sv}통계표의 항목 '{f['name']}'{unit}. {where}{dims}"
    if f["kind"] == "code":
        return f"{sv}통계표의 분류 '{f['dim']}' 에 있는 코드 '{f['name']}' ({f['code']}). {where}{dims}"
    if f["kind"] == "table":
        items = f" 항목: {', '.join(f['items'])}." if f["items"] else ""
        per = f" 수록 기간: {f['periods']}." if f["periods"] else ""
        return f"{sv}통계표 '{f['name']}' (표 전체).{items}{dims}{per}"
    return ""


# ── 본문 ────────────────────────────────────────────────────────
def set_section(body, title, text) -> str:
    """본문의 '# 제목' 단락을 text 로 (없으면 끝에 더함)"""
    body = body or ""
    m = re.search(rf"^# {re.escape(title)}[ \t]*\n(.*?)(?=^# |\Z)", body, re.DOTALL | re.MULTILINE)
    block = f"# {title}\n\n{text.strip()}\n\n"
    if not m:
        return body.rstrip("\n") + ("\n\n" if body.strip() else "") + block
    return body[:m.start()] + block + body[m.end():]


def get_section(body, title) -> str:
    m = re.search(rf"^# {re.escape(title)}[ \t]*\n(.*?)(?=^# |\Z)", body or "", re.DOTALL | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _not_lines(nots):
    return "\n".join(f"- {n['text']}" + (f" — {n['why']}" if n.get("why") else "") for n in nots) or \
        _NOT_PLACEHOLDER


_NOT_PLACEHOLDER = "- (같은 뜻이 아닌 말이 있으면 x-t4-concept.not 에)"


def _with_nots(body, nots) -> str:
    """'# 헷갈리는 말' 을 not 목록으로 — 사람이 본문에만 적은 줄이 있으면 그대로 둠"""
    sec = get_section(body, "헷갈리는 말")
    lines = [ln.strip() for ln in sec.splitlines() if ln.strip()]
    if all(ln == _NOT_PLACEHOLDER or any(ln.startswith(f"- {n['text']}") for n in nots) for ln in lines):
        return set_section(body, "헷갈리는 말", _not_lines(nots))
    return body


def _definition_block(text, fact_text, notes):
    lines = [text]
    if fact_text and fact_text != text:
        lines += ["", f"근거(표 정보): {fact_text}"]
    if notes:
        lines += ["", "공식 설명 (KOSIS 주석):"] + [f"- {t} ({tid})" for t, tid in notes]
    return "\n".join(lines)


def _auto(d) -> bool:
    """정의가 아직 자동(초안 문장 · 사실 · HCX)인지 — 사람이 고쳤으면 다시 쓰지 않음"""
    from backend.rag.okf.drafts import DRAFT_MARK
    desc = str(d.meta.get("description") or "")
    mark = d.meta.get("x-t4-draft") or {}
    return not desc or desc.startswith(DRAFT_MARK) or (bool(mark.get("text")) and desc == mark.get("text"))


def refresh(bundle, path, force=False) -> dict:
    """draft 개념의 사실 정의 · 본문 단락을 다시 씀 → {concept, definition: facts|kept|skip}"""
    from backend.rag.okf.curate import bind_lines
    from backend.rag.okf.lint import concept_body
    p = Path(path)
    d = Doc.read(p)
    cid = concept_id(bundle, p)
    if d.error or d.type != "Stat Concept" or d.meta.get("status") != "draft":
        return {"concept": cid, "definition": "skip"}
    _, _, nots, binds = concept_body(d.meta)
    f = facts(bundle, binds)
    fact_text = fact_definition(f)
    notes = concept_notes(bundle, binds, f["name"] or d.meta.get("title") or "")
    mark = d.meta.get("x-t4-draft") or {}
    state = "kept"
    if fact_text and (_auto(d) and (force or mark.get("definition") != "hcx")):
        d.meta["description"] = fact_text
        d.meta["x-t4-draft"] = {"definition": "facts", "text": fact_text, "by": FACTS_BY, "at": now()}
        d.body = set_section(d.body, "정의", _definition_block(fact_text, "", notes))
        state = "facts"
    d.body = _with_nots(d.body, nots)
    d.body = set_section(d.body, "표", "\n".join(bind_lines(binds)))
    d.body = d.body.rstrip("\n") + "\n"
    p.write_text(d.text(), encoding="utf-8", newline="\n")
    return {"concept": cid, "definition": state, "facts": f, "fact_text": fact_text, "notes": notes}


# ── HCX 보조 ────────────────────────────────────────────────────
SCHEMA = {"type": "object", "properties": {
    "definition": {"type": "string"},
    "aliases": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"}, "suggest": {"type": "string"}}, "required": ["text", "verdict"]}},
    "not": {"type": "array", "items": {"type": "object", "properties": {
        "choice": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["choice"]}}},
    "required": ["definition", "aliases"]}

SYSTEM = (
    "국가통계 지식 카탈로그의 '개념' 초안을 검토한다. 개념은 통계표의 항목·분류 코드·표 하나에 묶인다.\n"
    "1) definition: 주어진 '표 정보'와 'KOSIS 주석'만 써서 이 개념이 무엇을 세는지 한두 문장으로. "
    "주어지지 않은 숫자·연도·기관·조건을 지어내지 않는다. 표 이름을 늘어놓지 않는다.\n"
    "2) aliases: 일상어 별칭마다 예문 질문 속에서 그 말이 가리키는 대상이 이 개념과 같은지 판정한다.\n"
    "   same=같음 · narrow=이 개념의 일부만 가리킴 · broad=이 개념보다 넓어 다른 항목·표도 가리킴 · wrong=다른 것을 가리킴.\n"
    "   broad 나 wrong 이면 suggest 에 예문 질문 안에 그대로 있는(이어진 글자) 더 정확한 표현을 적는다. 없으면 빈 문자열.\n"
    "3) not: '헷갈리기 쉬운 말' 후보 중 이 개념과 헷갈리기 쉽지만 다른 것만 번호로 (최대 3개, 없으면 빈 배열).\n"
    "JSON 만: {\"definition\": 문장, \"aliases\": [{\"text\", \"verdict\", \"reason\", \"suggest\"}], "
    "\"not\": [{\"choice\": 번호, \"reason\": 짧은 이유}]}")


def not_candidates(f, aliases) -> list:
    from backend.rag.okf.drafts import colloquial_targets
    cands = list(f["siblings"])
    for a in aliases:
        cands += [t for t in colloquial_targets(a["text"]) if norm(t) not in norm(f["name"])]
    return [c for c in dict.fromkeys(cands) if c and norm(c) != norm(f["name"])][:20]


def prompt(title, f, fact_text, notes, aliases, cands):
    kind = {"item": "항목", "code": f"분류 '{f['dim']}' 의 코드", "table": "표 전체"}.get(f["kind"], "")
    L = [f"개념: {f['name'] or title} ({kind})", f"표 정보: {fact_text}"]
    L += ["KOSIS 주석:"] + ([f"- {t}" for t, _ in notes] or ["- (없음)"])
    L += ["", "별칭 (예문 질문):"]
    L += [f"- '{a['text']}' — 예문: {a.get('example') or '(없음)'}" for a in aliases]
    L += ["", "헷갈리기 쉬운 말 후보:"] + ([f"{i}) {c}" for i, c in enumerate(cands, 1)] or ["(없음)"])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(L)}]


def _grounded(text, source) -> bool:
    """HCX 정의의 숫자가 모두 근거 문장에 있는지 (지어낸 숫자 막기)"""
    return all(n in source for n in re.findall(r"\d+", text))


def assist(bundle, path, chat_fn=None, force=False) -> dict:
    """draft 개념 하나 → 사실 정의 + HCX 제안 (정의 · 별칭 판정 · 좁은 별칭 제안 · 헷갈리는 말). 승인은 안 함"""
    from backend.rag.okf.curate import bind_lines
    from backend.rag.okf.lint import concept_body
    r = refresh(bundle, path, force=force)
    if r["definition"] == "skip":
        return r
    p = Path(path)
    d = Doc.read(p)
    c, aliases, nots, binds = concept_body(d.meta)
    todo = [a for a in aliases if not a.get("verified") and (force or not a.get("review"))]
    mark = d.meta.get("x-t4-draft") or {}
    if not todo and mark.get("definition") == "hcx" and not force:
        return {**r, "hcx": "done"}
    f, fact_text, notes = r["facts"], r["fact_text"], r["notes"]
    cands = not_candidates(f, aliases)
    if chat_fn is None:
        from backend.rag.query_analyzer.config import chat as chat_fn
    try:
        res = chat_fn(prompt(d.meta.get("title") or "", f, fact_text, notes, aliases, cands), schema=SCHEMA, max_tokens=900)
    except Exception as e:  # noqa: BLE001  (HCX 가 안 되면 사실 정의까지만)
        return {**r, "hcx": f"오류: {e.__class__.__name__}"}
    res = res if isinstance(res, dict) else {}
    out = {**r, "hcx": "ok", "verdicts": {}, "suggested": [], "not": [], "definition_hcx": ""}
    at = now()
    # 정의 — 사람이 고친 정의는 건드리지 않음 · 근거에 없는 숫자면 버림
    dfn = " ".join(str(res.get("definition") or "").split())[:300]
    source = fact_text + " " + " ".join(t for t, _ in notes)
    if dfn and _auto(d) and _grounded(dfn, source):
        d.meta["description"] = dfn
        d.meta["x-t4-draft"] = {**mark, "definition": "hcx", "text": dfn, "by": HCX_BY, "at": at}
        d.body = set_section(d.body, "정의", _definition_block(dfn, fact_text, notes))
        out["definition_hcx"] = dfn
    elif dfn:
        out["definition_hcx"] = f"(버림: 근거에 없는 숫자 또는 사람이 고친 정의) {dfn}"
    # 별칭 판정 · 좁은 별칭 제안
    al = c.setdefault("aliases", [])
    by_text = {norm(a.get("text") if isinstance(a, dict) else a): a for a in al}
    for it in res.get("aliases") or []:
        a = by_text.get(norm(it.get("text")))
        v = str(it.get("verdict") or "").lower()
        if not isinstance(a, dict) or v not in VERDICTS or not any(a is x for x in todo):
            continue  # 승인된 것 · 이미 판정한 것(--force 가 아니면)은 그대로
        a["review"] = {"by": HCX_BY, "at": at, "verdict": v, "reason": str(it.get("reason") or "")[:120]}
        out["verdicts"][a["text"]] = v
        sug = " ".join(str(it.get("suggest") or "").split())
        ex = norm(a.get("example") or "")
        if v in SKIP_VERDICTS and 2 <= len(norm(sug)) <= 30 and norm(sug) in ex and norm(sug) not in by_text:
            new = {"text": sug, "by": HCX_BY, "at": at, "records": list(a.get("records") or []),
                   **({"example": a["example"]} if a.get("example") else {}),
                   "review": {"by": HCX_BY, "at": at, "verdict": "same", "reason": f"'{a['text']}' 보다 정확한 표현 (HCX 제안)"}}
            al.append(new)
            by_text[norm(sug)] = new
            out["suggested"].append(sug)
    # 헷갈리는 말 — 후보 안에서만
    have = {norm(n["text"]) for n in nots}
    nl = c.setdefault("not", [])
    for it in (res.get("not") or [])[:3]:
        try:
            k = int(it.get("choice") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= k <= len(cands) and norm(cands[k - 1]) not in have and norm(cands[k - 1]) not in by_text:
            nl.append({"text": cands[k - 1], "why": str(it.get("reason") or "")[:100], "by": HCX_BY})
            have.add(norm(cands[k - 1]))
            out["not"].append(cands[k - 1])
    _, _, nots, binds = concept_body(d.meta)
    d.body = _with_nots(d.body, nots)
    d.body = set_section(d.body, "표", "\n".join(bind_lines(binds)))
    d.body = d.body.rstrip("\n") + "\n"
    p.write_text(d.text(), encoding="utf-8", newline="\n")
    return out


def inbox(bundle) -> list:
    """concepts/_inbox 의 draft 개념 파일"""
    root = Path(bundle) / "concepts" / "_inbox"
    return sorted(p for p in root.glob("*.md") if p.name != "index.md" and Doc.read(p).meta.get("status") == "draft") \
        if root.exists() else []
