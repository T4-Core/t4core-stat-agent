"""
빌드 전 골든셋 검사 — 새 빌드가 검색을 나쁘게 만들면 CURRENT 로 바꾸지 않는다

  python -m backend.rag.okf build --gate <compare 실행 이름|폴더> [--gate-max-loss 0] [--gate-mrr-drop 0.01]

  왜   별칭이 반자동으로 늘어난다 (drafts → assist → verify). 틀린 별칭 하나가 그 말이 든 모든 질문의 검색을 흔들 수 있어,
       빌드를 바꾸기 전에 같은 질문으로 지금 빌드와 새 빌드를 나란히 재 본다
  어떻게
    1) 이전 compare 실행의 골든셋 · 변형 · split · alt · audit · 날짜 · 질의 분석 캐시를 그대로 씀 (HCX 를 부르지 않음 —
       캐시에 없는 질문은 건너뜀). dense 는 그 실행의 첫 dense
    2) 같은 질의 분석으로 지금 빌드 · 새 빌드를 각각 검색 (OKF_BUILD_OVERRIDE 로 빌드만 바꿈, CURRENT 는 그대로)
    3) 같은 질문끼리 hit@5 (alt 가 있으면 완화 hit@5) · mrr 비교
         새 빌드에서 잃은 질문 수 − 얻은 질문 수 > max_loss  또는  mrr 이 mrr_drop 넘게 떨어짐  → 불합격
       불합격이면 새 빌드는 폴더에 남기고 CURRENT 는 그대로. 잃은 질문과 그 질문에 걸린 새 별칭을 보여 줌
       (그래도 쓰려면 python -m backend.rag.okf use <해시>)
  한계  질의 분석은 캐시를 쓰므로, 별칭이 질의 분석(어휘 사전 aliases.json)에 주는 영향은 재지 않음 — 검색 값 채널 · dense 문서만
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

OVERRIDE_ENV = "OKF_BUILD_OVERRIDE"


@contextmanager
def use_build(h: str | None):
    """이 안에서만 OKF 빌드를 h 로 (build.current 가 봄). None 이면 OKF 없이 (빌드가 아직 없을 때의 기준)"""
    old = os.environ.get(OVERRIDE_ENV)
    os.environ[OVERRIDE_ENV] = h if h else "-"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(OVERRIDE_ENV, None)
        else:
            os.environ[OVERRIDE_ENV] = old


def load_run(run):
    """compare 실행 → (설정, 평가 행, 질의 분석, 건너뛴 질문 수)"""
    from backend.rag.search.tuning import compare as C
    prev = C.find_run(str(run))
    cfg = json.loads((prev / "config.json").read_text(encoding="utf-8"))
    rows = C.load_golden(cfg["golden"], tuple(cfg.get("variants") or ("O", "P")), split=cfg.get("split"))
    if cfg.get("alt"):
        from backend.rag.search.tuning.alt_gold import load_alt
        alt = load_alt(cfg["alt"], include_rounded=not cfg.get("alt_exact_only"))
        for r in rows:
            r["alt_groups"] = alt.get(r["record_id"], {})
    if cfg.get("audit"):
        from backend.rag.search.tuning.gold_audit import load_audit
        aud = load_audit(cfg["audit"])
        for r in rows:
            r["audit"] = aud.get((r["record_id"], r["variant"]), {"alt": [], "exclude": False, "flags": []})
    cache = {}
    f = prev / "analysis_cache.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                cache[x["key"]] = x
    mode, today = cfg.get("analyze") or "analyze", cfg.get("today")
    analysis, keep = {}, []
    for r in rows:
        key = hashlib.sha1(f"{mode}|{today}|{r['question']}".encode()).hexdigest()[:16]
        if key in cache:
            analysis[r["qid"]] = cache[key]["units"]
            keep.append(r)
    if not cfg.get("raw_units"):
        analysis, _ = C.prune_analysis(keep, analysis, log=lambda *_: None)
    return cfg, keep, analysis, len(rows) - len(keep)


def evaluate(h, rows, analysis, cfg, log=print):
    from backend.rag.search.tuning import compare as C
    dense = (cfg.get("dense") or ["none"])[0]
    docs = (cfg.get("dense_docs") or ["rule"])[:1]
    with use_build(h):
        per, _ = C.run(rows, analysis, [dense], False, cfg.get("top_k") or 10, cfg.get("pool") or 50, log=lambda *_: None,
                       docs=docs, okf=["on"])
    return {r["qid"]: r for r in per}


def _hit(r):
    return r.get("hit@5_alt") if r.get("hit@5_alt") is not None else r.get("hit@5")


def _mrr(r):
    return r.get("mrr_alt") if r.get("mrr_alt") is not None else r.get("mrr")


def added_aliases(root, base, new):
    """새 빌드에서 쓰이게 된 별칭 → {표현: [개념…]}"""
    def act(h):
        if not h:
            return {}
        f = Path(root) / h / "concepts.json"
        out = {}
        for c in json.loads(f.read_text(encoding="utf-8")) if f.exists() else []:
            for a in c.get("aliases") or []:
                out.setdefault(a, set()).add(c["id"])
        return out
    b, n = act(base), act(new)
    return {a: sorted(cs - b.get(a, set())) for a, cs in n.items() if cs - b.get(a, set())}


def gate(root, new, base, run, max_loss=0, mrr_drop=0.01, log=print) -> dict:
    """→ {ok, n, skipped, base, new, lost[], gained[], aliases{}} (base 가 없으면 OKF 없는 검색과 비교)"""
    from backend.rag.csv_index.store import norm
    cfg, rows, analysis, skipped = load_run(run)
    if not rows:
        return {"ok": True, "n": 0, "skipped": skipped, "note": "질의 분석 캐시가 있는 질문이 없음 — 검사 못 함 (통과로 둠)"}
    log(f"[검사] {len(rows)}문항 (캐시 없음 {skipped} 건너뜀) · dense {(cfg.get('dense') or ['none'])[0]} · "
        f"지금 빌드 {base or '(없음)'} ↔ 새 빌드 {new}")
    a, b = evaluate(base, rows, analysis, cfg), evaluate(new, rows, analysis, cfg)
    lost = [q for q in a if _hit(a[q]) and not _hit(b[q])]
    gained = [q for q in a if _hit(b[q]) and not _hit(a[q])]
    ma = sum(_mrr(a[q]) or 0 for q in a) / len(a)
    mb = sum(_mrr(b[q]) or 0 for q in a) / len(a)
    new_al = added_aliases(root, base, new)
    why = {}
    for q in lost + [q for q in a if (_mrr(b[q]) or 0) < (_mrr(a[q]) or 0)]:
        qt = norm(a[q]["question"])
        hit = [al for al in new_al if norm(al) and norm(al) in qt]
        if hit:
            why[q] = hit
    ok = (len(lost) - len(gained)) <= max_loss and (ma - mb) <= mrr_drop
    res = {"ok": ok, "n": len(rows), "skipped": skipped, "run": str(run),
           "base": {"hash": base, "hit@5": round(sum(bool(_hit(a[q])) for q in a) / len(a), 4), "mrr": round(ma, 4)},
           "new": {"hash": new, "hit@5": round(sum(bool(_hit(b[q])) for q in a) / len(a), 4), "mrr": round(mb, 4)},
           "lost": [{"qid": q, "question": a[q]["question"][:80], "rank": [a[q].get("rank_alt") or a[q].get("rank"),
                                                                           b[q].get("rank_alt") or b[q].get("rank")],
                     "aliases": why.get(q, [])} for q in lost],
           "gained": gained, "aliases_added": new_al, "rule": {"max_loss": max_loss, "mrr_drop": mrr_drop}}
    log(f"[검사] hit@5 {res['base']['hit@5']} → {res['new']['hit@5']} · mrr {res['base']['mrr']} → {res['new']['mrr']} · "
        f"잃음 {len(lost)} · 얻음 {len(gained)} → {'통과' if ok else '불합격'}")
    for x in res["lost"]:
        log(f"   - {x['qid']} 순위 {x['rank'][0]} → {x['rank'][1]}" + (f" · 걸린 새 별칭 {x['aliases']}" if x["aliases"] else "")
            + f" · {x['question']}")
    return res
