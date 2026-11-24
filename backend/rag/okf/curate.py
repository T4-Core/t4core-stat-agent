"""
개념 파일 관리 — 별칭 옮기기 · 승인 (런타임은 번들을 쓰지 않음. 쓰기는 사람이 부르는 이 명령만)

  migrate_aliases   query_analyzer/dictionary/vocab_aliases.csv → 개념 파일 (분류 코드 하나 = 개념 하나)
  migrate_learned   학습 사전의 승인된(active) 짝 → 개념 별칭 (verified: 옮긴 사람)
  approve           학습 사전 '승인 대기' 짝(벡터+HCX 제안 등) → 개념 별칭 (verified: 승인한 사람)
                    개념이 없으면 concepts/_inbox/ 에 새 개념(draft 아님 — 승인했으므로 바로 쓰임)을 만들고 binds 를 프로필에서 찾음
                    학습 사전의 그 짝은 status 'okf' 로 (다시 '승인 대기'에 뜨지 않게, Lexicon 은 active 만 씀)
  pending           학습 사전 '승인 대기' 목록 + 맞을 개념 후보

  configs/colloquial.yaml(정규식 → 검색어)은 표·코드에 묶이지 않는 검색 확장이라 옮기지 않음
"""
from __future__ import annotations

import csv
import getpass
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf import tables as T
from backend.rag.okf.doc import Doc, concept_id, iter_docs, now

MIGRATOR = "process:okf-migrate/1"
KNOWN_SLUGS = {("세대구성별", "모+미혼자녀"): "household/single-mother-with-children",
               ("세대구성별", "부+미혼자녀"): "household/single-father-with-children"}
# vocab_aliases.csv 머리말에 적어 둔 경계 ('미혼모' 는 별칭이 아님)
KNOWN_NOTS = {("세대구성별", "모+미혼자녀"): [{"text": "미혼모", "why": "어머니의 혼인 상태(미혼)까지 정함 — 모+미혼자녀(사별·이혼 포함)의 일부"}],
              ("세대구성별", "부+미혼자녀"): [{"text": "미혼부", "why": "아버지의 혼인 상태(미혼)까지 정함 — 부+미혼자녀의 일부"}]}


def who(by=None) -> str:
    b = by or getpass.getuser() or "unknown"
    return b if ":" in b else f"human:{b}"


def find_binds(recs, value, dim=None, limit=30):
    """프로필에서 이름이 value 인 분류 코드 · 항목 → binds"""
    v, out = norm(value), []
    for r in recs:
        for lv in r["levels"]:
            if dim and norm(lv["name"]) != norm(dim):
                continue
            for c in lv["codes"]:
                if norm(c["name"]) == v:
                    out.append({"table": T.table_path(r), "dim": lv["name"], "code": c["code"], "name": c["name"]})
        if not dim:
            for i in r["items"]:
                if norm(i["name"]) == v:
                    out.append({"table": T.table_path(r), "item": i["id"], "name": i["name"]})
    return out[:limit]


def concepts(bundle):
    return [(p, Doc.read(p)) for p in iter_docs(bundle, ("concepts",))]


def find_concept(bundle, value, dim=None):
    """정규 이름(binds 의 name 또는 제목)이 value 인 개념 파일"""
    v = norm(value)
    for p, d in concepts(bundle):
        if d.error or d.meta.get("status") == "deprecated":
            continue
        c = d.meta.get("x-t4-concept") or {}
        names = {norm(b.get("name")) for b in c.get("binds") or [] if isinstance(b, dict) and (not dim or norm(b.get("dim")) == norm(dim))}
        if v in names or v == norm(d.meta.get("title")):
            return p
    return None


def concept_doc(title, description, binds, aliases=(), nots=(), calc=(), by=MIGRATOR, status="stable", tags=()) -> Doc:
    meta = {"type": "Stat Concept", "title": title, "description": description, "tags": list(tags), "status": status,
            "generated": {"by": by, "at": now()},
            "x-t4-concept": {"aliases": list(aliases), "not": list(nots), "binds": list(binds), "calc": list(calc)}}
    if by.startswith("human:"):
        meta["verified"] = [{"by": by, "at": meta["generated"]["at"]}]
    lines = ["# 정의", "", description or "(정의를 적어 주세요)", "", "# 헷갈리는 말", ""]
    lines += [f"- {n['text']} — {n.get('why', '')}" for n in nots] or ["- (같은 뜻이 아닌 말이 있으면 x-t4-concept.not 에)"]
    lines += ["", "# 표", ""] + bind_lines(binds)
    return Doc(meta, "\n".join(lines) + "\n")


def bind_lines(binds) -> list:
    """본문 '# 표' 줄 — '- [이름](/tables/…) — 항목 T1 | 분류 '…' 코드 … | 표 전체'"""
    return [f"- [{b.get('name')}]({b['table']}) — " + (f"분류 '{b['dim']}' 코드 {b['code']}" if "dim" in b else
                                                      f"항목 {b['item']}" if "item" in b else "표 전체")
            for b in binds if isinstance(b, dict) and "table" in b]


def write_new(bundle: Path, rel: str, doc: Doc) -> Path:
    p = Path(bundle) / "concepts" / f"{rel}.md"
    if p.exists():
        raise FileExistsError(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.text(), encoding="utf-8", newline="\n")
    return p


def add_alias(path, entry: dict) -> str:
    """개념 파일에 별칭 더함 → 'added' | 'verified' (있던 미승인 별칭을 승인) | 'exists'"""
    d = Doc.read(path)
    c = d.meta.setdefault("x-t4-concept", {})
    al = c.setdefault("aliases", [])
    for i, a in enumerate(al):
        a = a if isinstance(a, dict) else {"text": str(a)}
        if norm(a.get("text")) == norm(entry["text"]):
            if entry.get("verified") and not a.get("verified") and a.get("by"):
                al[i] = {**a, "verified": entry["verified"]}
                Path(path).write_text(d.text(), encoding="utf-8", newline="\n")
                return "verified"
            return "exists"
    al.append(entry)
    Path(path).write_text(d.text(), encoding="utf-8", newline="\n")
    return "added"


def _inbox_rel(binds, value):
    b = next((x for x in binds if "table" in x), None)
    if b:
        tbl = b["table"].rsplit("/", 1)[-1].removesuffix(".md")
        return f"_inbox/{T.slugify(tbl)}-{T.slugify(b.get('code') or b.get('item') or value)}"
    return f"_inbox/{T.slugify(value)}"


def migrate_aliases(bundle, recs, csv_path=None, log=print) -> list:
    from backend.rag.query_analyzer.vocab import ALIAS_PATH
    p = Path(csv_path or ALIAS_PATH)
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    groups = {}
    for r in csv.DictReader(lines):
        key = ((r.get("dim") or "").strip(), (r.get("canon") or "").strip())
        if key[1]:
            g = groups.setdefault(key, {"aliases": [], "memo": ""})
            g["aliases"].append((r.get("alias") or "").strip())
            g["memo"] = g["memo"] or (r.get("memo") or "").strip()
    out = []
    for (dim, canon), g in groups.items():
        path = find_concept(bundle, canon, dim)
        if path is None:
            binds = find_binds(recs, canon, dim or None)
            if not binds:
                log(f"! '{canon}'({dim}) 을 프로필에서 못 찾음 — 표 생성(tables) 뒤 다시")
            rel = KNOWN_SLUGS.get((dim, canon)) or _inbox_rel(binds, canon)
            path = write_new(bundle, rel, concept_doc(canon, g["memo"], binds, nots=KNOWN_NOTS.get((dim, canon), []),
                                                      by=MIGRATOR, tags=[t for t in [dim.rstrip("별")] if t]))
            log(f"+ {concept_id(bundle, path)} (binds {len(binds)})")
        for a in g["aliases"]:
            st = add_alias(path, {"text": a})
            out.append((a, canon, concept_id(bundle, path), st))
    T.write_dir_indexes(bundle)
    return out


def _ensure_concept(bundle, recs, value, slot=None, by=MIGRATOR, log=print):
    path = find_concept(bundle, value)
    if path is not None:
        return path
    binds = find_binds(recs, value)
    if not binds:
        log(f"! '{value}' 를 프로필에서 못 찾음 — binds 없이 만듦 (검사에서 경고)")
    path = write_new(bundle, _inbox_rel(binds, value), concept_doc(value, "", binds, by=by))
    log(f"+ {concept_id(bundle, path)} (binds {len(binds)}) — 정의·경계를 채우고 알맞은 폴더로 옮기세요")
    return path


def migrate_learned(bundle, recs, lex, by=None, log=print) -> list:
    by, out = who(by), []
    for k, e in sorted(lex.learned.items()):
        if e.get("status") != "active" or not e.get("value"):
            continue
        path = _ensure_concept(bundle, recs, e["value"], e.get("slot"), log=log)
        st = add_alias(path, {"text": e.get("surface") or k, "by": f"learned:{e.get('source') or '?'}",
                              "verified": {"by": by, "at": e.get("approved") or now()}})
        out.append((e.get("surface") or k, e["value"], concept_id(bundle, path), st))
    T.write_dir_indexes(bundle)
    return out


def approve(bundle, recs, lex, surface, by=None, value=None, log=print) -> dict:
    """학습 사전 '승인 대기' → 개념 별칭 (verified). value 를 주면 그 이름으로 (제안과 다르게 고칠 때)"""
    by = who(by)
    e = lex.learned.get(norm(surface))
    val = value or (e or {}).get("value")
    if not val:
        raise KeyError(f"학습 사전에 '{surface}' 가 없고 value 도 없음")
    path = _ensure_concept(bundle, recs, val, (e or {}).get("slot"), log=log)
    src = f"{(e or {}).get('source') or 'manual'}"
    st = add_alias(path, {"text": (e or {}).get("surface") or surface, "by": src, "at": (e or {}).get("added") or now(),
                          "verified": {"by": by, "at": now()}})
    if e is not None:
        e["status"], e["okf"] = "okf", concept_id(bundle, path)
        lex.save()
    T.write_dir_indexes(bundle)
    return {"surface": surface, "value": val, "concept": concept_id(bundle, path), "result": st}


def pending(bundle, lex) -> list:
    out = []
    for k, e in sorted(lex.learned.items(), key=lambda x: -(x[1].get("count") or 0)):
        if e.get("status") != "pending":
            continue
        p = find_concept(bundle, e.get("value") or "")
        out.append({"surface": e.get("surface") or k, "value": e.get("value"), "source": e.get("source"),
                    "count": e.get("count"), "examples": e.get("examples", [])[:2],
                    "concept": concept_id(bundle, p) if p else "(새 개념 — concepts/_inbox/)"})
    return out
