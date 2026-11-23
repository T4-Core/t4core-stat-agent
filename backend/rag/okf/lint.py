"""
참조 무결성 검사 — 빌드 전에 돌려 오류(error)가 있으면 빌드를 멈춘다

  error   tables/·classifications/·concepts/ 아래 파일의 프론트매터 오류 · (프론트매터는 있는데) type 없음
          개념 binds 의 표가 없음 · 그 표에 분류·코드·항목이 없음 · superseded_by 가 없는 경로
          한 개념 안에서 별칭이 not(같은 뜻 아님)과 같음
  warn    코드·항목은 있는데 이름이 다름 (개편 의심) · binds 가 폐기된 표를 가리킴 (superseded_by 를 따라가 확인)
          별칭이 두 개념에 걸림 · 별칭이 다른 개념의 not 과 같음 · binds 없는 개념 · 본문 링크 깨짐
  info    승인 안 된 별칭 수 · 합계 코드에 묶인 개념 · 프론트매터 없는 파일(README 등 — 건너뜀)

코드가 많은 차원(분류 파일)은 표 파일에 코드가 다 없으므로 프로필(codebook)로 확인한다. 프로필이 없으면 그 검사는 info
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf.doc import Doc, concept_id, iter_docs, resolve

DIM_KINDS = {"geo", "sex", "age", "nationality", "other"}


@dataclass
class Report:
    issues: list = field(default_factory=list)

    def add(self, level, where, msg):
        self.issues.append({"level": level, "where": where, "msg": msg})

    def of(self, level):
        return [i for i in self.issues if i["level"] == level]

    @property
    def ok(self):
        return not self.of("error")

    def summary(self):
        return {lv: len(self.of(lv)) for lv in ("error", "warn", "info")}

    def lines(self, levels=("error", "warn", "info")):
        mark = {"error": "✗", "warn": "!", "info": "·"}
        return [f"{mark[i['level']]} [{i['level']}] {i['where']}: {i['msg']}" for i in self.issues if i["level"] in levels]


def alias_active(concept_meta: dict, alias: dict) -> bool:
    """사용할 별칭: 개념이 draft·deprecated 가 아니고, (사람·개념 작성자가 쓴 별칭) 또는 (기계 제안 + human: 승인)"""
    if concept_meta.get("status") in ("draft", "deprecated"):
        return False
    if not alias.get("by"):
        return True
    v = alias.get("verified")
    vs = v if isinstance(v, list) else [v] if isinstance(v, dict) else []
    return any(str(x.get("by", "")).startswith("human:") for x in vs if isinstance(x, dict))


def concept_body(meta):
    c = meta.get("x-t4-concept") or {}
    al = [a if isinstance(a, dict) else {"text": str(a)} for a in c.get("aliases") or []]
    nots = [n if isinstance(n, dict) else {"text": str(n)} for n in c.get("not") or []]
    return c, [a for a in al if a.get("text")], [n for n in nots if n.get("text")], [b for b in c.get("binds") or [] if isinstance(b, dict)]


def load_tables(bundle: Path):
    """→ {resolved path: Doc} (표 파일)"""
    return {p.resolve(): Doc.read(p) for p in iter_docs(bundle, ("tables",))}


def table_codes(doc: Doc, dim_name: str, codebooks=None):
    """표 파일의 분류 → ({code: name} | None(모름), 분류 정보)"""
    xt = doc.meta.get("x-t4-table") or {}
    for d in xt.get("dims") or []:
        if norm(d.get("name")) == norm(dim_name):
            if d.get("codes") is not None:
                return {str(c.get("code")): str(c.get("name")) for c in d["codes"]}, d
            cid = str(d.get("classification") or "").rsplit("/", 1)[-1].removesuffix(".md")
            return (codebooks or {}).get(cid), d
    return {}, None


def follow(bundle, tables, path, hops=3):
    """폐기된 표의 superseded_by 를 따라감 → (최종 경로, 거친 경로들)"""
    seen = [path]
    while hops > 0 and path in tables and tables[path].meta.get("status") == "deprecated" and tables[path].meta.get("superseded_by"):
        nxt = resolve(bundle, path, tables[path].meta["superseded_by"])
        if nxt is None or nxt in seen:
            break
        path, hops = nxt, hops - 1
        seen.append(path)
    return path, seen


def lint(bundle, codebooks=None) -> Report:
    """codebooks: {분류 id: {code: name}} — 빌드가 프로필에서 만든 것 (없으면 큰 차원의 코드 검사는 info)"""
    bundle = Path(bundle)
    rep = Report()
    docs = {}
    for p in iter_docs(bundle):
        d = Doc.read(p)
        cid = concept_id(bundle, p)
        if d.error == "프론트매터 없음":  # README.md 같은 설명 파일 — OKF v0.3 은 type 없는 파일을 건너뜀
            rep.add("info", cid, "프론트매터 없는 파일 → 건너뜀 (OKF 문서가 아님)")
            continue
        if d.error:
            rep.add("error", cid, d.error)
            continue
        if not d.type:
            rep.add("error", cid, "type 이 없음 (OKF 필수 필드)")
            continue
        docs[p.resolve()] = d
        sup = d.meta.get("superseded_by")
        if sup:
            t = resolve(bundle, p, sup)
            if t is not None and not t.exists():
                rep.add("error", cid, f"superseded_by '{sup}' 가 없는 경로")
        for ref in d.links():
            t = resolve(bundle, p, ref)
            if t is not None and t.suffix == ".md" and not t.exists():
                rep.add("warn", cid, f"본문 링크 깨짐: {ref}")
    tables = {k: v for k, v in docs.items() if v.type == "Stat Table"}
    concepts = {k: v for k, v in docs.items() if v.type == "Stat Concept"}

    alias_owner, not_owner = defaultdict(set), defaultdict(set)
    n_pending = 0
    for p, d in concepts.items():
        cid = concept_id(bundle, p)
        _, aliases, nots, binds = concept_body(d.meta)
        if d.meta.get("status") == "deprecated":
            continue
        nn = {norm(n["text"]) for n in nots}
        for a in aliases:
            if norm(a["text"]) in nn:
                rep.add("error", cid, f"별칭 '{a['text']}' 이 같은 개념의 not 에도 있음")
            if alias_active(d.meta, a):
                alias_owner[norm(a["text"])].add(cid)
            else:
                n_pending += 1
        for n in nn:
            not_owner[n].add(cid)
        if not binds:
            rep.add("warn", cid, "binds 가 없음 (어느 표·코드인지 모름)")
        for b in binds:
            _check_bind(rep, bundle, p, cid, b, tables, codebooks)
    for a, owners in alias_owner.items():
        if len(owners) > 1:
            rep.add("warn", ", ".join(sorted(owners)), f"별칭 '{a}' 이 개념 {len(owners)}개에 걸림")
        clash = not_owner.get(a, set()) - owners
        if clash:
            rep.add("warn", ", ".join(sorted(owners)), f"별칭 '{a}' 이 다른 개념({', '.join(sorted(clash))})의 not 과 같음")
    if n_pending:
        rep.add("info", "concepts", f"승인 안 된 별칭 {n_pending}개 (쓰이지 않음 — python -m backend.rag.okf approve)")
    return rep


def _check_bind(rep, bundle, p, cid, b, tables, codebooks):
    if "table" not in b:
        k = b.get("dim_kind")
        if k not in DIM_KINDS:
            rep.add("error", cid, f"규칙 binds 의 dim_kind '{k}' 를 모름 ({', '.join(sorted(DIM_KINDS))})")
        return
    t = resolve(bundle, p, b["table"])
    if t is None or t not in tables:
        rep.add("error", cid, f"표 '{b['table']}' 가 없음")
        return
    final, _ = follow(bundle, tables, t)
    if tables[t].meta.get("status") == "deprecated":
        if final == t:
            rep.add("warn", cid, f"표 '{b['table']}' 가 폐기됨 (superseded_by 없음)")
            return
        rep.add("warn", cid, f"표 '{b['table']}' 가 폐기됨 → '{concept_id(bundle, final)}' 로 따라가 확인 (binds 를 고치세요)")
        if final not in tables:
            rep.add("error", cid, f"superseded_by 를 따라간 표 '{concept_id(bundle, final)}' 가 없음")
            return
    doc = tables[final]
    where = f"{concept_id(bundle, final)}"
    if "item" in b:
        items = {str(i.get("id")): str(i.get("name")) for i in (doc.meta.get("x-t4-table") or {}).get("items") or []}
        if str(b["item"]) not in items:
            rep.add("error", cid, f"{where} 에 항목 '{b['item']}' 가 없음")
        elif b.get("name") and norm(items[str(b["item"])]) != norm(b["name"]):
            rep.add("warn", cid, f"{where} 항목 {b['item']} 이름이 '{items[str(b['item'])]}' (개념에는 '{b['name']}')")
        return
    if "dim" not in b:
        rep.add("error", cid, "binds 에 dim·item 이 없음")
        return
    codes, dim = table_codes(doc, b["dim"], codebooks)
    if dim is None:
        rep.add("error", cid, f"{where} 에 분류 '{b['dim']}' 가 없음")
        return
    if "code" not in b:
        return
    if codes is None:
        rep.add("info", cid, f"{where} '{b['dim']}' 는 코드가 많아 프로필(코드북) 없이 확인 못 함")
        return
    code = str(b["code"])
    if code not in codes:
        rep.add("error", cid, f"{where} '{b['dim']}' 에 코드 '{code}' 가 없음")
        return
    if b.get("name") and norm(codes[code]) != norm(b["name"]):
        rep.add("warn", cid, f"{where} '{b['dim']}' 코드 {code} 이름이 '{codes[code]}' (개념에는 '{b['name']}') — 개편 의심")
    if dim.get("total_code") is not None and str(dim.get("total_code")) == code:
        rep.add("info", cid, f"{where} '{b['dim']}' 합계 코드({code})에 묶임")
