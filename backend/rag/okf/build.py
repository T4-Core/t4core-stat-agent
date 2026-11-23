"""
번들 → 파생물 빌드 + 원자적 교체

  1) 검사 (lint) — 오류면 멈춤 (--force 로 무시)
  2) 입력 해시 = 생성기 버전 + 번들 md 내용 + 프로필 내용 + CSV 값 사전 서명  → 빌드 이름
  3) okf_build/<해시>.tmp-<pid>/ 에 전부 쓴 뒤 폴더 이름을 <해시> 로 바꿈 (이미 있으면 다시 만들지 않음)
  4) okf_build/CURRENT 를 임시 파일 → os.replace 로 한 번에 교체 (Windows 에서도 원자적). 읽는 쪽은 요청마다 CURRENT 를 한 번 읽음
  5) 최근 빌드 KEEP 개만 남김 (되돌리기: python -m backend.rag.okf use <해시>)

  파생물
    catalog.json     표 {tbl_id: 경로·제목·설명·분류(이름·종류·코드 수·합계·분류 id·작은 코드 목록)·항목·기간·형제·상태}
    codebooks.json   {분류 id: {code: name}}  코드가 많은 차원 (표 파일에는 예시만)
    concepts.json    개념 [{id, title, description, status, aliases(사용), pending, not, binds, calc, trust}]
    backlinks.json   {tbl_id: [개념 id]} + rules (표 대신 dim_kind 로 묶인 개념)
    aliases.json     정규 어휘 사전의 별칭 (vocab.load_vocab 이 vocab_aliases.csv 대신 읽음)
    vocab.json       정규 어휘 사전 (프로필 + CSV 값 사전) · [--embed] vocab_vectors.<임베더>.npz
    manifest.json    해시·시각·개수·검사 결과
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf import tables as T
from backend.rag.okf.doc import Doc, concept_id, iter_docs, resolve
from backend.rag.okf.lint import alias_active, concept_body, follow, lint

BUILD_VERSION = "okf-build/1"
KEEP = 3


def _sha(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def input_hash(bundle: Path, profiles_dir=None, idx_dir=None) -> str:
    h = hashlib.sha1(BUILD_VERSION.encode())
    for p in iter_docs(bundle):
        h.update(p.relative_to(bundle).as_posix().encode() + b"\0" +
                 _sha(p.read_bytes().replace(b"\r\n", b"\n")).encode())
    if profiles_dir and Path(profiles_dir).exists():
        for f in sorted(Path(profiles_dir).glob("*.json")):
            h.update(f.name.encode() + b"\0" + _sha(f.read_bytes()).encode())
    if idx_dir and Path(idx_dir).exists():
        for name in ("tables.jsonl", "values.parquet"):
            f = Path(idx_dir) / name
            if f.exists():
                h.update(name.encode() + b"\0" + str(f.stat().st_size).encode() +
                         (_sha(f.read_bytes()).encode() if name == "tables.jsonl" else b""))
    return h.hexdigest()[:12]


def codebooks_from(recs) -> dict:
    out = {}
    for r in recs:
        for lv in r["levels"]:
            if T.is_large(lv):
                out.setdefault(T.classification_id(lv), {c["code"]: c["name"] for c in lv["codes"]})
    return out


def _catalog(bundle: Path):
    cat = {}
    for p in iter_docs(bundle, ("tables",)):
        d = Doc.read(p)
        if d.error or d.type != "Stat Table":
            continue
        xt = d.meta.get("x-t4-table") or {}
        tid = str(xt.get("tbl_id") or p.stem)
        dims = []
        for dm in xt.get("dims") or []:
            cid = str(dm.get("classification") or "").rsplit("/", 1)[-1].removesuffix(".md")
            dims.append({k: v for k, v in {"name": dm.get("name"), "kind": dm.get("kind"), "n_codes": dm.get("n_codes"),
                                           "total_code": dm.get("total_code"), "classification": cid or None,
                                           "codes": dm.get("codes"), "examples": dm.get("examples")}.items() if v is not None})
        cat[tid] = {"path": concept_id(bundle, p), "title": d.meta.get("title"), "description": d.meta.get("description"),
                    "org_id": xt.get("org_id"), "survey": xt.get("survey"), "periods": xt.get("periods"), "dims": dims,
                    "items": xt.get("items") or [], "siblings": xt.get("siblings") or [],
                    "status": d.meta.get("status") or "stable", "superseded_by": d.meta.get("superseded_by")}
    return cat


def _concepts(bundle: Path, cat: dict):
    by_path = {v["path"]: k for k, v in cat.items()}
    tables = {p.resolve(): Doc.read(p) for p in iter_docs(bundle, ("tables",))}
    concepts, back, rules, aliases = [], {}, [], {}
    for p in iter_docs(bundle, ("concepts",)):
        d = Doc.read(p)
        if d.error or d.type != "Stat Concept":
            continue
        cid = concept_id(bundle, p)
        c, als, nots, binds = concept_body(d.meta)
        status = d.meta.get("status") or "stable"
        rb = []
        for b in binds:
            if "table" in b:
                t = resolve(bundle, p, b["table"])
                final, _ = follow(bundle, tables, t) if t is not None else (None, [])
                path = concept_id(bundle, final) if final is not None and final.exists() else str(b["table"])
                rb.append({**b, "table": path, "tbl_id": by_path.get(path)})
            else:
                rb.append(b)
        active = [a["text"] for a in als if alias_active(d.meta, a)]
        pending = [a["text"] for a in als if not alias_active(d.meta, a) and status not in ("deprecated",)]
        ver = d.meta.get("verified")
        vs = ver if isinstance(ver, list) else [ver] if isinstance(ver, dict) else []
        trust = "human-reviewed" if any(str(v.get("by", "")).startswith("human:") for v in vs if isinstance(v, dict)) \
            else "machine-confirmed" if vs else "unverified"
        rec = {"id": cid, "title": d.meta.get("title") or p.stem, "description": d.meta.get("description") or "",
               "status": status, "superseded_by": d.meta.get("superseded_by"), "aliases": active, "pending": pending,
               "not": nots, "binds": rb, "calc": [str(x) for x in c.get("calc") or []], "tags": d.meta.get("tags") or [],
               "trust": trust}
        concepts.append(rec)
        if status == "deprecated":
            continue
        for b in rb:
            if b.get("tbl_id"):
                back.setdefault(b["tbl_id"], [])
                if cid not in back[b["tbl_id"]]:
                    back[b["tbl_id"]].append(cid)
            elif "dim_kind" in b and cid not in rules:
                rules.append(cid)
        # 정규 어휘 사전 별칭 (vocab.Vocab.aliases 모양) — 표에 묶인 이름(코드·항목)을 정규 이름으로
        canon = {(b.get("name") or "", b.get("dim") or "", "분류" if "dim" in b else "지표") for b in rb
                 if b.get("name") and ("dim" in b or "item" in b)}
        for a in active:
            for name, dim, slot in sorted(canon):
                lst = aliases.setdefault(norm(a), [])
                if not any(x["canon"] == name and x["dim"] == dim for x in lst):
                    lst.append({"alias": a, "canon": name, "slot": slot, "dim": dim, "memo": rec["title"], "concept": cid})
    return concepts, {"tables": back, "rules": rules}, aliases


def build_root(settings=None) -> Path:
    from backend.core.config import OKF_BUILD_DIR
    p = getattr(settings, "okf_build_dir", "") if settings is not None else ""
    return Path(p) if p else Path(OKF_BUILD_DIR)


def bundle_dir(settings=None) -> Path:
    from backend.core.config import OKF_DIR
    p = getattr(settings, "okf_dir", "") if settings is not None else ""
    return Path(p) if p else Path(OKF_DIR)


def set_current(root: Path, h: str):
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"CURRENT.tmp-{os.getpid()}"
    tmp.write_text(h + "\n", encoding="utf-8")
    os.replace(tmp, root / "CURRENT")


def current(root: Path) -> str:
    p = Path(root) / "CURRENT"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def prune(root: Path, keep=KEEP):
    cur = current(root)
    builds = sorted((d for d in Path(root).iterdir() if d.is_dir() and ".tmp-" not in d.name),
                    key=lambda d: d.stat().st_mtime, reverse=True)
    for d in builds[keep:]:
        if d.name != cur:
            shutil.rmtree(d, ignore_errors=True)


def build(bundle=None, root=None, profiles_dir=None, idx=None, idx_dir=None, *, force=False, embed=None,
          settings=None, log=print) -> dict:
    """→ manifest. 검사 오류면 {"ok": False, "lint": …} 를 돌려주고 CURRENT 는 그대로"""
    bundle = Path(bundle or bundle_dir(settings))
    root = Path(root or build_root(settings))
    recs = T.load_profiles(profiles_dir) if profiles_dir and Path(profiles_dir).exists() else []
    cbs = codebooks_from(recs)
    rep = lint(bundle, cbs or None)
    for ln in rep.lines(("error", "warn")):
        log(ln)
    if not rep.ok and not force:
        log(f"검사 오류 {len(rep.of('error'))}개 → 빌드하지 않음 (CURRENT 그대로: {current(root) or '-'})")
        return {"ok": False, "lint": rep.summary(), "issues": rep.issues}
    h = input_hash(bundle, profiles_dir, idx_dir or (getattr(idx, "dir", None) if idx is not None else None))
    out = root / h
    if out.exists() and (out / "manifest.json").exists() and not embed:
        set_current(root, h)
        log(f"같은 입력의 빌드가 이미 있음 → CURRENT = {h}")
        return {**json.loads((out / "manifest.json").read_text(encoding="utf-8")), "ok": True, "reused": True}
    tmp = root / f"{h}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    cat = _catalog(bundle)
    concepts, back, aliases = _concepts(bundle, cat)
    files = {"catalog.json": cat, "codebooks.json": cbs, "concepts.json": concepts, "backlinks.json": back,
             "aliases.json": aliases}
    for name, obj in files.items():
        (tmp / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    from backend.rag.query_analyzer.vocab import Vocab, build_vocab, save_vocab
    v = build_vocab(profiles_dir if recs else None, idx)
    save_vocab(Vocab(v.entries, {}, v.source, v.n_tables), tmp / "vocab.json")
    n_vec = 0
    if embed:
        from backend.rag.query_analyzer.vocab_suggest import build_vectors, get_embedder
        emb = get_embedder(embed)
        if emb is not None:
            _, n_vec = build_vectors(v, emb, tmp / f"vocab_vectors.{embed}.npz")
    manifest = {"hash": h, "created": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
                "version": BUILD_VERSION, "bundle": str(bundle), "profiles": len(recs), "tables": len(cat),
                "concepts": len(concepts), "aliases": sum(len(x) for x in aliases.values()),
                "codebooks": len(cbs), "vocab_entries": len(v), "vectors": {embed: n_vec} if embed else {},
                "lint": rep.summary()}
    (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    set_current(root, h)
    prune(root)
    log(f"빌드 {h} → CURRENT (표 {len(cat)} · 개념 {len(concepts)} · 별칭 {manifest['aliases']} · 코드북 {len(cbs)})")
    return {**manifest, "ok": True}
