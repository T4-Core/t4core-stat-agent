"""
정규 어휘 사전의 벡터 후보 — 질문 속 낱말이 사전에 없을 때 '비슷한 표 이름' 후보를 뽑고, 확정은 따로 한다

  사전 일치(vocab.py) ─ 없음 ─▶ 벡터 후보 top-k ─▶ 확정 (HCX 가 후보 목록 안에서만 고름 · 사람이 승인) ─▶ 학습 사전

  벡터가 하는 일은 '후보를 내는 것'까지다. 비슷하다고 바로 바꾸지 않는다:
    '미혼모' ~ '모+미혼자녀', '1인가구' ~ '2인가구' 처럼 가깝지만 뜻이 다른 값이 많아서다 (docs/VOCAB_GROUNDING.md)

  build_vectors(vocab, emb, path)          사전 이름(지표·분류)을 한 번 임베딩해 파일로 (분석 때는 질문 낱말만 임베딩)
  unmatched_terms(question, raw, vocab, lex)  질문 낱말 중 사전·별칭·CSV·슬롯 어디에도 안 맞는 것
  suggest_for_question(…)                    → 기록 [{term, candidates, choice, by, applied, why}], 새 슬롯, 고른 결과

  모드 (settings.vocab_suggest)
    off  아무것도 안 함
    log  후보만 기록 (notes·trace·응답 vocab_suggestions). 슬롯은 그대로. 사람이 승인한 학습 사전 짝만 적용
    hcx  HCX 가 후보 목록 안에서 '같은 뜻'만 고름 (없으면 0). 고른 분류 코드는 조건에, 지표는 지표가 비었을 때만 더함.
         고른 짝은 학습 사전에 '승인 대기'로 (vocab_suggest_learn) → 사람이 승인하면 다음부터 HCX 없이 적용

  python -m backend.rag.query_analyzer.vocab build --embed hcx          # 사전 + 벡터 파일
  python -m backend.rag.query_analyzer.vocab suggest "2020년 세종 싱글맘 가정 식구"
"""
import json
import re
import threading
from pathlib import Path

import numpy as np

from backend.rag.csv_index.store import norm

SUGGEST_SLOTS = ("지표", "분류")
# 후보를 찾지 않을 낱말 — 물음·지시·때·양을 묻는 말 (QTERM_STOP 에 더해)
STOP = {"몇", "몇명", "몇개", "몇건", "몇가구", "얼마", "얼마나", "어떻게", "어떤", "어느", "무엇", "뭐", "누구", "왜", "정도", "다",
        "모두", "전부", "각각", "알려", "알려줘", "보여줘", "말해줘", "비교", "비교해줘", "작년", "올해", "금년", "재작년", "최근",
        "요즘", "지난", "지난해", "현재", "지금", "그동안", "동안", "사이", "경우", "관련", "대해", "대한", "통해", "그리고", "또는",
        "가장", "제일", "많이", "적게", "얼마큼", "어때", "궁금해", "있어", "있나", "없어", "어디", "언제", "순위", "변했어"}
# 풀이말(용언) 끝 — '합치면'·'키우는'·'늘었어' 는 표 이름 후보가 아님
PRED_END = re.compile(r"(?:하면|치면|되면|으면|면|니|나요|까요?|어요?|아요?|해줘|줘|는데|었어|았어|였어|했어|했나|된|되|돼|인가요?|"
                      r"이야|야|하는|있는|없는|많은|적은|높은|낮은|사는|키우는|늘었|줄었|됐|됨|함|해)$")
_TIME = re.compile(r"^\d{2,4}(?:년|월|분기)?(?:도)?$|^\d+(?:년|개월|월|일|세|명|가구|건)")


def entry_key(e):
    return f"{e['slot']}\x1f{e.get('dim') or ''}\x1f{e['name']}"


def embed_text(e):
    """분류 코드는 분류 이름과 같이 ('세대구성별 모+미혼자녀'), 항목은 이름만"""
    return f"{e['dim']} {e['name']}" if e["slot"] == "분류" and e.get("dim") else e["name"]


def targets(vocab):
    """임베딩할 사전 줄 — 지표·분류, 합계('계')·한 글자·숫자로 시작하는 이름 제외"""
    out = []
    for e in vocab.entries:
        n = norm(e["name"])
        if e["slot"] in SUGGEST_SLOTS and not e.get("is_total") and len(n) >= 2 and not n[:1].isdigit():
            out.append(e)
    return out


def vectors_path(settings=None, name=None):
    from backend.rag.query_analyzer.vocab import vocab_path
    name = name or getattr(settings, "vocab_suggest_embedder", "hcx")
    return vocab_path(settings).with_name(f"vocab_vectors.{name}.npz")


def get_embedder(name):
    from backend.rag.search.index import embedder
    return embedder(name)


def build_vectors(vocab, emb, path):
    es = targets(vocab)
    M = np.asarray(emb.embed_docs([embed_text(e) for e in es]), dtype=np.float32)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(p, keys=np.array([entry_key(e) for e in es]), M=M.astype(np.float16),
                        embedder=np.array(getattr(emb, "id", "")))
    return p, len(es)


class VocabVectors:
    """벡터 파일 + 지금 사전 (파일의 이름 중 지금 사전에 없는 줄은 후보에서 뺌 — 사전을 다시 만들어도 파일을 그대로 씀)"""

    def __init__(self, path, vocab):
        z = np.load(path, allow_pickle=False)
        by = {entry_key(e): e for e in vocab.entries}
        keys = [str(k) for k in z["keys"]]
        keep = [i for i, k in enumerate(keys) if k in by]
        M = z["M"].astype(np.float32)[keep] if keep else np.zeros((0, 1), dtype=np.float32)
        self.M = M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-12)
        self.entries = [by[keys[i]] for i in keep]
        self.embedder_id = str(z["embedder"]) if "embedder" in z else ""

    def search(self, qv, k=5, min_score=0.5):
        if not len(self.entries):
            return []
        sc = self.M @ np.asarray(qv, dtype=np.float32).reshape(-1)
        out, seen = [], set()
        for i in np.argsort(-sc):
            if sc[i] < min_score or len(out) >= k:
                break
            e = self.entries[int(i)]
            if norm(e["name"]) in seen:
                continue
            seen.add(norm(e["name"]))
            out.append({"name": e["name"], "slot": e["slot"], "dim": e.get("dim") or "", "score": round(float(sc[i]), 4),
                        "n_tables": e.get("n_tables", 0), "tables": (e.get("tables") or [])[:3]})
        return out


_CACHE, _LOCK = {}, threading.Lock()


def load_vectors(vocab, settings=None):
    """→ VocabVectors | None (파일 없음)"""
    p = vectors_path(settings)
    if not p.exists():
        return None
    key = (str(p), p.stat().st_mtime, id(vocab))
    with _LOCK:
        if key not in _CACHE:
            _CACHE.clear()
            _CACHE[key] = VocabVectors(p, vocab)
        return _CACHE[key]


# ── 질문 낱말 ──────────────────────────────────────────────────
def unmatched_terms(question, raw, vocab, lex=None, max_terms=3):
    """질문 낱말 중 어디에도 안 맞는 것 → [낱말] (질문 순서)
    빼는 것: 두 글자 미만 · 숫자·때 · 물음·풀이말 · 계산 단어·일반 말 · 지역·성별 · 사전에 있음 · 별칭 · CSV 접지(포함 일치 제외)
             · 슬롯 값과 서로 포함 관계 (이미 담긴 말)"""
    from backend.rag.query_analyzer.lexicon import QTERM_STOP, _strip_josa
    from backend.rag.query_analyzer.measures import is_generic, is_measure
    from backend.rag.query_analyzer.vocab import SOURCES_OK
    covered = [norm(v) for vs in (raw or {}).values() for v in (vs if isinstance(vs, (list, tuple)) else [vs]) if norm(v)]
    alias_keys = [k for k in vocab.aliases if k in norm(question)]
    out = []
    for tok in re.findall(r"[가-힣A-Za-z0-9+]+", str(question or "")):
        w = _strip_josa(norm(tok))
        w = re.sub(r"(?<=..)(?:이랑|랑|하고|께서)$", "", w)  # _strip_josa 가 안 떼는 말 ('엄마랑' → '엄마')
        if len(w) < 2 or w in out or w in STOP or w in QTERM_STOP or _TIME.match(w) or w[:1].isdigit():
            continue
        if PRED_END.search(w) and not vocab.lookup(w)["entries"]:
            continue
        if is_measure(w) or is_generic(w):
            continue
        if any(w in c or c in w for c in covered) or any(w in a or a in w for a in alias_keys):
            continue
        if vocab.lookup(w)["entries"] or vocab.other_slot(w):
            continue
        if lex is not None:
            h = lex.best(w, "지표")
            if h is not None and h.grounded and h.source in SOURCES_OK:
                continue
            if any(sl in ("지역", "성별", "연령", "시점") for sl, _ in lex.rules.get(w, [])):
                continue
        out.append(w)
    return out[:max_terms]


# ── HCX: 후보 목록 안에서만 고르기 ───────────────────────────────
CHOOSE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "term": {"type": "string"}, "choice": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["term", "choice"]}}}, "required": ["items"]}

CHOOSE_SYSTEM = (
    "국가통계 질문 속 낱말이 아래 후보(통계표의 항목·분류 이름) 중 어느 것과 '같은 뜻'인지 고른다.\n"
    "- 질문 안에서 그 낱말이 가리키는 대상과 후보가 정확히 같을 때만 그 번호를 고른다.\n"
    "- 상위 개념·하위 개념·관련 있는 말·조건이 더 붙거나 빠진 말이면 0 (예: '미혼모' 와 '모+미혼자녀' 는 다름 — "
    "모+미혼자녀는 사별·이혼한 어머니도 포함).\n"
    "- 후보에 없는 이름을 지어내지 않는다. 확신이 없으면 0.\n"
    "JSON 만: {\"items\": [{\"term\": 낱말, \"choice\": 번호 또는 0, \"reason\": 짧은 이유}]}")


def choose_prompt(question, cands):
    lines = [f"질문: {question}", ""]
    for j, (term, cs) in enumerate(cands.items(), 1):
        lines.append(f"[{j}] 낱말 '{term}'")
        for i, c in enumerate(cs, 1):
            where = f"분류 '{c['dim']}'" if c["slot"] == "분류" else "항목"
            lines.append(f"  {i}) {c['name']} ({where})")
    return [{"role": "system", "content": CHOOSE_SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def choose_with_hcx(question, cands, chat_fn=None):
    """{낱말: 후보 목록} → {낱말: (고른 후보 | None, 이유)}. 후보 밖 번호·모르는 낱말은 None"""
    if not cands:
        return {}
    if chat_fn is None:
        from backend.rag.query_analyzer.config import chat as chat_fn
    res = chat_fn(choose_prompt(question, cands), schema=CHOOSE_SCHEMA, max_tokens=600)
    out = {t: (None, "HCX 응답에 없음") for t in cands}
    for it in (res or {}).get("items") or []:
        t = norm(it.get("term"))
        term = next((k for k in cands if norm(k) == t), None)
        if term is None:
            continue
        try:
            n = int(it.get("choice") or 0)
        except (TypeError, ValueError):
            n = 0
        why = str(it.get("reason") or "")[:80]
        out[term] = (cands[term][n - 1], why) if 1 <= n <= len(cands[term]) else (None, why or "같은 뜻 후보 없음")
    return out


# ── 적용 ────────────────────────────────────────────────────────
def _grounded_target(raw, vocab):
    return any(vocab.lookup(v, k)["entries"] for k in ("대상", "지표") for v in raw.get(k) or [])


def apply_choice(raw, choice, vocab):
    """고른 후보 → (새 슬롯, 넣은 칸 | '', 사유). 분류 코드 → 조건 · 항목 → 대상·지표가 사전에 근거 없을 때만 지표"""
    out = {k: list(v) for k, v in raw.items()}
    have = {norm(x) for k in ("대상", "지표", "조건") for x in out.get(k) or []}
    if norm(choice["name"]) in have:
        return out, "", "이미 슬롯에 있음"
    if choice["slot"] == "분류":
        out.setdefault("조건", []).append(choice["name"])
        return out, "조건", ""
    if _grounded_target(raw, vocab):
        return out, "", "지표가 이미 사전에 근거가 있어 더하지 않음 (서브쿼리가 늘지 않게)"
    out.setdefault("지표", []).append(choice["name"])
    return out, "지표", ""


def _learned(lex, term):
    e = (lex.learned.get(norm(term)) if lex is not None else None) or {}
    return e if e.get("status") == "active" and e.get("value") else None


def suggest_for_question(question, raw, vocab, lex, s, *, previous=None, chat_fn=None, embed=None):
    """→ (새 슬롯, 기록 목록, 고른 결과 {낱말: {...}}, 건너뛴 사유 | '')
    previous: 직전 state 의 vocab_choices — 있으면 그 낱말은 HCX 를 다시 부르지 않음 (되묻기 응답)"""
    mode = getattr(s, "vocab_suggest", "off")
    if mode == "off":
        return raw, [], {}, "off"
    terms = unmatched_terms(question, raw, vocab, lex, getattr(s, "vocab_suggest_max_terms", 3))
    if not terms:
        return raw, [], dict(previous or {}), ""
    recs, choices = [], dict(previous or {})
    new = {k: list(v) for k, v in raw.items()}
    # 1) 사람이 승인한 학습 사전 짝 — 모드와 상관없이 적용 (벡터·HCX 없음)
    rest = []
    for t in terms:
        e = _learned(lex, t)
        if not e:
            rest.append(t)
            continue
        hit = vocab.lookup(e["value"])
        c = ({"name": e["value"], "slot": hit["entries"][0]["slot"], "dim": hit["entries"][0].get("dim") or "", "score": 1.0}
             if hit["entries"] else {"name": e["value"], "slot": "지표", "dim": "", "score": 1.0})
        new, where, why = apply_choice(new, c, vocab)
        recs.append({"term": t, "candidates": [c], "choice": c["name"], "by": "learned", "applied": where,
                     "why": why or "학습 사전(승인됨)"})
    if not rest:
        return new, recs, choices, ""
    # 2) 벡터 후보
    vv = load_vectors(vocab, s)
    if vv is None:
        cmd = f"python -m backend.rag.query_analyzer.vocab embed --embed {getattr(s, 'vocab_suggest_embedder', 'hcx')}"
        return new, recs, choices, f"벡터 파일 없음: {vectors_path(s)} ({cmd})"
    emb = embed or get_embedder(getattr(s, "vocab_suggest_embedder", "hcx"))
    if emb is None:
        return new, recs, choices, "임베더 없음 (vocab_suggest_embedder: none)"
    if vv.embedder_id and getattr(emb, "id", "") and vv.embedder_id != emb.id:
        return new, recs, choices, f"벡터 파일의 임베더({vv.embedder_id})와 지금 임베더({emb.id})가 다름 → build --embed 다시"
    Q = np.asarray(emb.embed_queries(rest), dtype=np.float32)
    k, ms = getattr(s, "vocab_suggest_k", 5), getattr(s, "vocab_suggest_min_score", 0.55)
    cands = {t: vv.search(Q[i], k, ms) for i, t in enumerate(rest)}
    # 3) 확정 (hcx 모드). 직전 state 에 고른 결과가 있으면 그것
    picked = {}
    if mode == "hcx":
        ask = {t: cs for t, cs in cands.items() if cs and t not in choices}
        if ask:
            try:
                for t, (c, why) in choose_with_hcx(question, ask, chat_fn).items():
                    choices[t] = {"choice": c, "why": why, "by": "hcx"}
            except Exception as e:  # noqa: BLE001 (고르기 실패 → 후보만 기록)
                for t in ask:
                    choices[t] = {"choice": None, "why": f"HCX 오류: {e.__class__.__name__}", "by": "hcx"}
        picked = {t: choices[t] for t in cands if t in choices}
    for t, cs in cands.items():
        rec = {"term": t, "candidates": cs, "choice": None, "by": "", "applied": "", "why": "" if cs else "후보 없음 (점수 미달)"}
        p = picked.get(t)
        if p:
            rec.update(by=p["by"], why=p["why"])
            c = p["choice"]
            if c:
                rec["choice"] = c["name"]
                new, rec["applied"], why = apply_choice(new, c, vocab)
                rec["why"] = why or rec["why"]
                if getattr(s, "vocab_suggest_learn", True) and lex is not None:
                    lex.learn(t, c["name"], slot="조건" if c["slot"] == "분류" else "지표", source="vector+hcx",
                              status="pending", example=question)
                    rec["learned"] = "pending"
        recs.append(rec)
    if any(r.get("learned") for r in recs):
        try:
            lex.save()
        except OSError as e:
            for r in recs:
                if r.get("learned"):
                    r["learned"] = f"저장 실패: {e}"
    return new, recs, choices, ""


def describe(recs):
    """기록 → 메모 한 줄씩"""
    out = []
    for r in recs:
        top = ", ".join(f"{c['name']}({c['score']:.2f})" for c in r["candidates"][:3]) or "없음"
        if r["choice"] and r["applied"]:
            out.append(f"'{r['term']}' → {r['applied']} '{r['choice']}' ({r['by']}: {r['why'] or '같은 뜻'})")
        elif r["choice"]:
            out.append(f"'{r['term']}' ≈ '{r['choice']}' ({r['by']}) — 적용 안 함: {r['why']}")
        else:
            out.append(f"'{r['term']}' 사전에 없음 · 후보 {top}" + (f" — {r['by']}: {r['why']}" if r["by"] else ""))
    return out


def as_json(recs):
    return json.loads(json.dumps(recs, ensure_ascii=False, default=str))
