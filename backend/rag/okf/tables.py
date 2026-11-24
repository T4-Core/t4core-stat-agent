"""
프로필(VIEW_OUT_DIR/profiles/*.json) → 표 파일 · 분류 파일 · 목록(index.md) · 기록(log.md)

  표 파일      tables/<org_id>/<tbl_id>.md        type: Stat Table
  분류 파일    classifications/<kind>-<해시8>.md  type: Classification   코드가 MAX_INLINE_CODES 를 넘는 차원
               (같은 이름 + 같은 코드 묶음이면 표가 달라도 한 파일. 코드 전체는 빌드의 codebooks.json 으로만)
  사라진 표    지우지 않고 status: deprecated 로 (사람이 superseded_by 를 적으면 개념 링크가 따라감 — OKF v0.3)

프로필 schema 1(build_profile: name·kind·is_total, periods{se:[{prd_de,label,year}]}, symbols, notes) 과
schema 2(items.nm·role·additive, codes.parallel, n_symbols) 를 모두 읽는다.
표 파일은 프로필만의 함수다 (개념 파일이 바뀌어도 표 파일은 그대로 → git diff 는 데이터 변경만). 역링크는 빌드가 계산
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from backend.rag.okf.doc import Doc, human_block, iter_docs, write_if_changed

GENERATOR = "process:okf-tables/1"
MAX_INLINE_CODES = 50
N_EXAMPLES = 8
TABLE_OWNED = {"type", "title", "description", "resource", "tags", "status", "generated", "x-t4-table"}
CLS_OWNED = {"type", "title", "description", "tags", "generated", "x-t4-classification"}
KIND = {"regions": "geo", "geo": "geo", "sex": "sex", "ages": "age", "age": "age", "nationality": "nationality"}
KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}"
ROOT_META = {"okf_version": "0.3", "title": "KOSIS 통계표 지식 카탈로그",
             "description": "KOSIS 통계표의 차원·코드·항목과 일상어 개념. 통계 질문에서 표를 찾고 확인할 때 쓴다",
             "license": "내부용"}


# ── 프로필 읽기 ─────────────────────────────────────────────────
def _kind(level, names):
    k = str(level.get("kind") or "")
    if k in KIND:
        return KIND[k]
    from backend.rag.ingestion.normalize import level_kind
    return KIND.get(level_kind(level.get("obj_nm") or "", names), "other")


def _periods(p):
    out = {}
    for se, ps in (p or {}).items():
        labels = [str(x.get("label") or x.get("prd_de") or "") if isinstance(x, dict) else str(x) for x in ps or []]
        labels = [x for x in labels if x]
        if labels:
            out[se] = labels if len(labels) <= 30 else {"from": labels[0], "to": labels[-1], "n": len(labels)}
    return out


def norm_profile(prof: dict) -> dict | None:
    """프로필 → 표 레코드 (schema 1·2 공통). 표 프로필이 아니면(요약 파일 등) None"""
    if not isinstance(prof.get("levels"), list) or not isinstance(prof.get("items"), list) or not prof.get("tbl_id"):
        return None
    levels = []
    for lv in prof["levels"]:
        codes = [c for c in lv.get("codes") or [] if isinstance(c, dict)]
        levels.append({
            "level": lv.get("level"), "name": lv.get("obj_nm") or f"분류{lv.get('level')}",
            "kind": _kind(lv, [c.get("name") for c in codes]),
            "n_codes": lv.get("n_codes") or len(codes), "total_code": lv.get("total_code"),
            "codes": [{"code": str(c.get("code")), "name": str(c.get("name") or ""),
                       **({"parent": str(c["parent"])} if c.get("parent") not in (None, "") else {}),
                       **({"total": True} if c.get("is_total") else {}),
                       **({"parallel": True} if c.get("parallel") else {})} for c in codes]})
    items = [{"id": str(i.get("itm_id")), "name": str(i.get("nm") or i.get("name") or ""), "unit": i.get("unit") or "",
              **({"role": i["role"]} if i.get("role") else {}),
              **({"additive": bool(i["additive"])} if i.get("additive") is not None else {}),
              **({"total": True} if i.get("is_total") else {})} for i in prof["items"] if isinstance(i, dict)]
    sym = prof.get("symbols")
    symbols = {s: {"count": v.get("count"), **({"meaning": v["meaning"]} if v.get("meaning") else {})}
               for s, v in sym.items() if isinstance(v, dict)} if isinstance(sym, dict) else {}
    if not symbols and prof.get("n_symbols"):
        symbols = {"*": {"count": prof["n_symbols"]}}
    return {"org_id": str(prof.get("org_id") or "").strip() or "000", "tbl_id": str(prof["tbl_id"]),
            "title": str(prof.get("tbl_nm") or prof["tbl_id"]), "survey": str(prof.get("survey_nm") or prof.get("category") or ""),
            "dept": str(prof.get("dept_nm") or ""), "periods": _periods(prof.get("periods")), "levels": levels,
            "items": items, "symbols": symbols, "notes": [str(n) for n in prof.get("notes") or [] if n]}


def load_profiles(profiles_dir) -> list[dict]:
    out, seen = [], set()
    for f in sorted(Path(profiles_dir).glob("*.json")):
        try:
            rec = norm_profile(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if rec and (rec["org_id"], rec["tbl_id"]) not in seen:
            seen.add((rec["org_id"], rec["tbl_id"]))
            out.append(rec)
    return out


# ── 경로 · 분류 ─────────────────────────────────────────────────
def table_path(rec):
    return f"/tables/{rec['org_id']}/{rec['tbl_id']}.md"


def classification_id(level) -> str:
    sig = level["kind"] + "|" + level["name"] + "|" + "|".join(sorted(f"{c['code']}={c['name']}" for c in level["codes"]))
    return f"{level['kind']}-{hashlib.sha1(sig.encode('utf-8')).hexdigest()[:8]}"


def is_large(level) -> bool:
    return len(level["codes"]) > MAX_INLINE_CODES


def examples(level, n=N_EXAMPLES):
    tot = [c["name"] for c in level["codes"] if c.get("total")]
    rest = [c["name"] for c in level["codes"] if not c.get("total")]
    return (tot + rest)[:n]


# ── 형제 표 (search/siblings.py 와 같은 묶기 규칙) ─────────────
def sibling_groups(recs):
    from backend.rag.search.siblings import (
        LEVEL_TAIL,
        YEAR_PAREN,
        core_title,
        table_sex,
    )
    by = defaultdict(list)
    for r in recs:
        by[(r["survey"], core_title(r["title"]))].append(r)
    out = {}
    for members in by.values():
        if not 2 <= len(members) <= 12:
            continue
        for r in members:
            sibs = []
            for o in members:
                if o is r:
                    continue
                rel = []
                if table_sex(r["title"]) != table_sex(o["title"]):
                    rel.append("성별판")
                lv = lambda t: (LEVEL_TAIL.search(t).group(1) if LEVEL_TAIL.search(t) else "")
                if lv(r["title"]) != lv(o["title"]):
                    rel.append("지역 수준판")
                if bool(YEAR_PAREN.search(r["title"])) != bool(YEAR_PAREN.search(o["title"])) or \
                        YEAR_PAREN.search(r["title"]) and YEAR_PAREN.search(o["title"]).group(0) != YEAR_PAREN.search(r["title"]).group(0):
                    rel.append("연도판")
                sibs.append({"path": table_path(o), "rel": "·".join(rel) or "같은 무리", "title": o["title"]})
            out[(r["org_id"], r["tbl_id"])] = sorted(sibs, key=lambda s: s["path"])
    return out


# ── 표 파일 ─────────────────────────────────────────────────────
def _period_text(periods):
    parts = []
    for se, v in periods.items():
        if isinstance(v, dict):
            parts.append(f"{se} {v['from']}~{v['to']} ({v['n']}개)")
        else:
            parts.append(f"{se} {v[0]}~{v[-1]} ({len(v)}개)" if len(v) > 1 else f"{se} {v[0]}")
    return " · ".join(parts)


def _md_cell(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def table_doc(rec, siblings=()) -> Doc:
    dims = []
    for lv in rec["levels"]:
        d = {"level": lv["level"], "name": lv["name"], "kind": lv["kind"], "n_codes": lv["n_codes"]}
        if lv.get("total_code") not in (None, ""):
            d["total_code"] = str(lv["total_code"])
        if is_large(lv):
            d["classification"] = f"/classifications/{classification_id(lv)}.md"
            d["examples"] = examples(lv)
        else:
            d["codes"] = lv["codes"]
        dims.append(d)
    xt = {"org_id": rec["org_id"], "tbl_id": rec["tbl_id"], **({"survey": rec["survey"]} if rec["survey"] else {}),
          "periods": rec["periods"], "dims": dims, "items": rec["items"]}
    if rec["symbols"]:
        xt["symbols"] = rec["symbols"]
    if siblings:
        xt["siblings"] = [{"path": s["path"], "rel": s["rel"]} for s in siblings]
    item_names = [i["name"] for i in rec["items"]]
    desc = " · ".join(x for x in [
        rec["survey"], _period_text(rec["periods"]),
        "분류 " + ", ".join(lv["name"] for lv in rec["levels"]) if rec["levels"] else "",
        f"항목 {len(item_names)}개 ({', '.join(item_names[:3])}{' …' if len(item_names) > 3 else ''})" if item_names else ""] if x)
    meta = {"type": "Stat Table", "title": rec["title"], "description": desc,
            "resource": KOSIS_URL.format(org=rec["org_id"], tbl=rec["tbl_id"]),
            "tags": [t for t in [rec["survey"]] if t], "x-t4-table": xt}

    b = [f"# {rec['title']}", "", f"- 조사: {rec['survey'] or '-'}" + (f" · 작성: {rec['dept']}" if rec["dept"] else ""),
         f"- 수록 기간: {_period_text(rec['periods']) or '-'}", f"- KOSIS: {meta['resource']}", "", "# Schema", "",
         "## 분류", "", "| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |", "|---|---|---|---|---|---|"]
    for lv, d in zip(rec["levels"], dims):
        codes = (f"[{len(lv['codes'])}개 — 분류 파일]({d['classification']}) 예: " + ", ".join(d["examples"])) if is_large(lv) \
            else ", ".join(f"{c['code']} {c['name']}" for c in lv["codes"])
        b.append(f"| {lv['level']} | {_md_cell(lv['name'])} | {lv['kind']} | {lv['n_codes']} | {d.get('total_code', '')} | {_md_cell(codes)} |")
    b += ["", "## 항목", "", "| ID | 이름 | 단위 | 성격 | 더할 수 있음 |", "|---|---|---|---|---|"]
    for i in rec["items"]:
        add = {True: "예", False: "아니오"}.get(i.get("additive"), "")
        b.append(f"| {i['id']} | {_md_cell(i['name'])} | {_md_cell(i['unit'])} | {i.get('role', '')} | {add} |")
    if rec["symbols"]:
        b += ["", "# 부호", ""] + [f"- `{s}` {v.get('count')}칸" + (f" — {v['meaning']}" if v.get("meaning") else "")
                                    for s, v in rec["symbols"].items()]
    if rec["notes"]:
        b += ["", "# 주석", ""] + [f"- {_md_cell(n)[:400]}" for n in rec["notes"][:20]]
    if siblings:
        b += ["", "# 형제 표", ""] + [f"- [{s['title']}]({s['path']}) — {s['rel']}" for s in siblings]
    b += ["", "# 메모", "", human_block()]
    return Doc(meta, "\n".join(b))


def classification_doc(cid, level, users) -> Doc:
    depth = Counter(len(c.get("parent", "")) > 0 for c in level["codes"])
    meta = {"type": "Classification", "title": f"{level['name']} ({len(level['codes'])}개 코드)",
            "description": f"{level['kind']} 분류 · 코드 {len(level['codes'])}개 · 표 {len(users)}개가 씀. "
                           f"코드 전체는 빌드의 codebooks.json (catalog.has_code 로 확인)",
            "tags": [level["kind"]],
            "x-t4-classification": {"id": cid, "name": level["name"], "kind": level["kind"], "n_codes": len(level["codes"]),
                                    "n_child_codes": depth.get(True, 0), "examples": examples(level, 20),
                                    "n_tables": len(users)}}
    b = [f"# {level['name']}", "", f"코드 {len(level['codes'])}개. 예: " + ", ".join(examples(level, 20)), "",
         "# 쓰는 표", ""] + [f"- [{t}]({p})" for p, t in sorted(users)[:50]]
    if len(users) > 50:
        b.append(f"- … 외 {len(users) - 50}개")
    b += ["", "# 메모", "", human_block()]
    return Doc(meta, "\n".join(b))


# ── 목록 · 기록 ─────────────────────────────────────────────────
def write_root_index(bundle: Path, counts: dict):
    p = bundle / "index.md"
    old = Doc.read(p) if p.exists() else None
    meta = {**ROOT_META, **(old.meta if old and not old.error else {})}  # v0.3: 번들 프론트매터는 보존
    body = ["# 목록", "", f"- [표](/tables/index.md) — {counts.get('tables', 0)}개 (자동 생성)",
            f"- [분류](/classifications/index.md) — {counts.get('classifications', 0)}개 (코드가 많은 차원, 자동 생성)",
            f"- [개념](/concepts/index.md) — {counts.get('concepts', 0)}개 (사람이 관리)", "", "- [변경 기록](/log.md)"]
    doc = Doc(meta, "\n".join(body))
    if old is None or old.error or old.body.strip() != doc.body.strip() or old.meta != meta:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc.text(), encoding="utf-8", newline="\n")


def _write_plain(p: Path, text: str):
    text = text.rstrip("\n") + "\n"
    if p.exists() and p.read_text(encoding="utf-8").replace("\r\n", "\n") == text:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def write_dir_indexes(bundle: Path):
    """tables/ · tables/<org>/ · classifications/ · concepts/ 의 index.md (프론트매터 없음 — OKF §index)"""
    bundle = Path(bundle)
    counts = {}
    for top in ("tables", "classifications", "concepts"):
        docs = [(p, Doc.read(p)) for p in iter_docs(bundle, (top,))]
        docs = [(p, d) for p, d in docs if not d.error and d.type]
        counts[top] = len(docs)
        by_dir = defaultdict(list)
        for p, d in docs:
            by_dir[p.parent].append((p, d))
        root = bundle / top
        if top == "tables":
            subs = sorted(by_dir)
            lines = [f"# 표 ({len(docs)}개)", ""] + [f"- [{s.name}](/{top}/{s.name}/index.md) — {len(by_dir[s])}개" for s in subs]
            _write_plain(root / "index.md", "\n".join(lines) + "\n")
            for s in subs:
                ls = [f"# 기관 {s.name} 표", ""]
                for p, d in sorted(by_dir[s]):
                    tag = " (폐기)" if d.meta.get("status") == "deprecated" else ""
                    ls.append(f"- [{d.meta.get('title', p.stem)}](/{top}/{s.name}/{p.name}){tag} — {d.meta.get('description', '')}")
                _write_plain(s / "index.md", "\n".join(ls) + "\n")
        else:
            title = {"classifications": "분류", "concepts": "개념"}[top]
            lines = [f"# {title} ({len(docs)}개)", ""]
            for p, d in sorted(docs, key=lambda x: str(x[0])):
                rel = p.relative_to(bundle).as_posix()
                st = d.meta.get("status")
                tag = f" ({st})" if st and st != "stable" else ""
                lines.append(f"- [{d.meta.get('title', p.stem)}](/{rel}){tag} — {d.meta.get('description', '')}")
            if docs or root.exists():
                _write_plain(root / "index.md", "\n".join(lines) + "\n")
    write_root_index(bundle, counts)
    return counts


def append_log(bundle: Path, line: str, day=None):
    """log.md: 날짜(YYYY-MM-DD) 제목 아래 최신 먼저 (OKF §log)"""
    p = Path(bundle) / "log.md"
    day = (day or date.today()).isoformat()
    text = p.read_text(encoding="utf-8").replace("\r\n", "\n") if p.exists() else "# 변경 기록\n"
    head = f"## {day}"
    if head in text:
        text = text.replace(head + "\n", f"{head}\n- {line}\n", 1)
    else:
        first = text.find("\n## ")
        block = f"\n{head}\n- {line}\n"
        text = text.rstrip("\n") + "\n" + block if first < 0 else text[:first] + "\n" + block.strip("\n") + "\n" + text[first:]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")


# ── 생성 ────────────────────────────────────────────────────────
def generate(bundle, profiles_dir=None, recs=None, log=print) -> dict:
    """프로필 → 표·분류 파일. → {"new", "changed", "same", "deprecated", "classifications", "tables"}"""
    bundle = Path(bundle)
    recs = recs if recs is not None else load_profiles(profiles_dir)
    sibs = sibling_groups(recs)
    stat = Counter()
    keep = set()
    cls_users, cls_level = defaultdict(set), {}
    for r in recs:
        for lv in r["levels"]:
            if is_large(lv):
                cid = classification_id(lv)
                cls_users[cid].add((table_path(r), r["title"]))
                cls_level.setdefault(cid, lv)
        path = bundle / table_path(r).lstrip("/")
        keep.add(path.resolve())
        st = write_if_changed(path, table_doc(r, sibs.get((r["org_id"], r["tbl_id"]), [])), TABLE_OWNED, GENERATOR)
        stat[st] += 1
    for cid, lv in cls_level.items():
        st = write_if_changed(bundle / "classifications" / f"{cid}.md", classification_doc(cid, lv, cls_users[cid]),
                              CLS_OWNED, GENERATOR)
        stat["cls_" + st] += 1
    # 프로필에서 사라진 표 → 폐기 표시 (사람이 적은 superseded_by 는 보존)
    for p in iter_docs(bundle, ("tables",)):
        if p.resolve() in keep:
            continue
        d = Doc.read(p)
        if d.error or d.meta.get("status") == "deprecated":
            continue
        d.meta["status"] = "deprecated"
        note = "프로필에서 사라진 표 (개편·삭제). 새 표가 있으면 superseded_by 에 경로를 적으세요"
        d.body = f"> {note}\n\n" + d.body
        write_if_changed(p, d, None, GENERATOR)
        stat["deprecated"] += 1
    counts = write_dir_indexes(bundle)
    summary = {"tables": len(recs), "new": stat["new"], "changed": stat["changed"], "same": stat["same"],
               "deprecated": stat["deprecated"], "classifications": len(cls_level),
               "cls_changed": stat["cls_new"] + stat["cls_changed"], **{f"n_{k}": v for k, v in counts.items()}}
    if stat["new"] or stat["changed"] or stat["deprecated"] or summary["cls_changed"]:
        append_log(bundle, f"**tables** 표 {len(recs)}개 — 새 {stat['new']} · 바뀜 {stat['changed']} · 폐기 {stat['deprecated']}"
                           f" · 분류 파일 변경 {summary['cls_changed']}")
    log(json.dumps(summary, ensure_ascii=False))
    return summary


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s or hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]
