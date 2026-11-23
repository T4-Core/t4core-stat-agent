"""
정규 어휘 사전 — 표 스키마(항목 이름 + 분류 코드 이름)로 만든 '쓸 수 있는 말' 목록과, 근거 없는 슬롯 값 지우기

  build_vocab(profiles_dir=…, idx=…)  → Vocab     profiles/*.json(정규화 프로필, schema 1·2) 우선, 없으면 CSV 값 사전
  get_vocab(idx, settings)            → Vocab     파일(index_dir()/vocab.json)이 있으면 읽고, 없으면 CSV 값 사전으로 바로 만듦
  Vocab.lookup(value, slot)           → 사전 근거 {match, slot, entries}
  prune_slots(slots, question, vocab, lex)  → (슬롯, 기록)   재작성 슬롯 값 중 근거 없는 값을 지움(null)

  python -m backend.rag.query_analyzer.vocab build [--profiles DIR] [--out PATH]
  python -m backend.rag.query_analyzer.vocab check "질문" 지표=고령인구비율 대상=싱글맘
  python -m backend.rag.query_analyzer.vocab build --embed hcx       # 사전 + 벡터 파일 (vocab_suggest.py)
  python -m backend.rag.query_analyzer.vocab embed --embed bge-m3-ko # 지금 사전으로 벡터 파일만
  python -m backend.rag.query_analyzer.vocab suggest "세종 모자가정 수" [--mode hcx] [--embed hash] [--min-score 0.5]

사전 한 줄(entry) = {name, norm, slot, dim, kind, unit, role, additive, is_total, n_tables, tables}
  slot : 지표(표 항목) · 분류(지역·성별·연령이 아닌 분류 코드, 예: 세대구성별 '모+미혼자녀') · 지역 · 성별 · 연령 · 국적
  role·additive·is_total 은 프로필에만 있음 (합산 가능한 수인가 — 비공개 값 하한 계산 등에 씀, docs/VOCAB_GROUNDING.md)

근거 있는 값(지우지 않음)
  1) 계산 단어('비율'·'평균')·일반 말('인구'·'가구') — 역할 단위·measure 가 다룸
  2) 사전에 그 슬롯으로 있는 이름 — 정확 · 표기 변형(괄호·'수'·'별') · 어간('혼인' ← '혼인건수') · 계산 단어를 뺀 핵심
  3) 별칭(dictionary/vocab_aliases.csv) — '싱글맘' → 세대구성별 '모+미혼자녀'
  4) 질문 원문에 그 말이 있음 (사용자가 직접 쓴 말은 사전에 없어도 지우지 않음)
  5) 용어 사전·동의어 사전·학습 사전(Lexicon) 이 CSV 값으로 이어 줌 (포함 일치만으로는 아님)
  사전에 다른 슬롯으로만 있는 값(지표 칸의 '청양군')은 지우지 않고 그 슬롯으로 옮김 (지역·성별)
  나머지 = HCX 가 지어낸 값 → 지움
"""
import csv
import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from backend.rag.csv_index.store import norm, variants

ALIAS_PATH = Path(__file__).resolve().parent / "dictionary" / "vocab_aliases.csv"
VOCAB_FILE = "vocab.json"
MAX_TABLES = 20

# 슬롯 값 → 사전에서 찾을 슬롯 (lexicon.SLOT_CSV 와 같은 뜻)
SLOT_VOCAB = {"대상": ("지표", "분류"), "지표": ("지표", "분류"), "조건": ("분류", "지표"), "국적": ("국적", "분류"),
              "이동": ("지표", "분류")}
MOVABLE = {"지역": "지역", "성별": "성별"}  # 다른 칸에 잘못 들어간 값을 옮길 슬롯
KIND_SLOT = {"regions": "지역", "geo": "지역", "sex": "성별", "ages": "연령", "age": "연령", "nationality": "국적"}
SOURCES_OK = ("rule", "learned", "csv", "term>csv")  # Lexicon 근거로 인정 (포함 일치 'contains'·근거 없는 'term' 제외)
COUNT_UNITS = {"가구", "명", "건", "호", "세대", "개", "개소"}
_CODE_PREFIX = re.compile(r"^\d{2,}\s+")  # '03 동부' → '동부'
_SYMBOLS = re.compile(r"[+()（）\[\]<>~]")


def keys_of(name):
    """이름 → 사전 조회 키 (norm · 표기 변형 · 코드 접두 · 기호 빼기)"""
    name = unicodedata.normalize("NFKC", str(name or "")).strip()
    out = set(variants(name)) | {norm(name)}
    bare = _CODE_PREFIX.sub("", name)
    if bare != name:
        out |= variants(bare)
    out |= {norm(_SYMBOLS.sub("", k)) for k in list(out)}
    return {k for k in out if k}


def core_keys(name):
    """계산 단어를 뺀 핵심과 그 어간 ('평균 가구원 수' → {'가구원수', '가구원'}, '혼인건수' → {'혼인건수', '혼인'})"""
    from backend.rag.search.resolve import indicator_core, indicator_stems
    c = norm(indicator_core(name))
    return {norm(s) for s in indicator_stems(c)} if len(c) >= 2 else set()


@dataclass
class Vocab:
    entries: list = field(default_factory=list)
    aliases: dict = field(default_factory=dict)   # norm(별칭) → [{alias, canon, slot, dim, memo}]
    source: str = ""
    n_tables: int = 0

    def __post_init__(self):
        self._by_key, self._by_core = {}, {}
        for i, e in enumerate(self.entries):
            ks = keys_of(e["name"])
            unit = norm(e.get("unit"))
            if e["slot"] == "지표" and unit in COUNT_UNITS and not norm(e["name"]).endswith(unit):
                ks |= keys_of(f"{e['name']}{unit}")  # 항목 '1인' + 단위 '가구' → '1인가구'
            for k in ks:
                self._by_key.setdefault(k, []).append(i)
            if e["slot"] in ("지표", "분류"):
                for k in core_keys(e["name"]):
                    self._by_core.setdefault(k, []).append(i)

    def __len__(self):
        return len(self.entries)

    def lookup(self, value, slot=None):
        """값 → {match: exact|variant|core|"" , slot, entries}. slot 을 주면 그 슬롯에 맞는 사전 슬롯만"""
        want = SLOT_VOCAB.get(slot) if slot else None
        ok = (lambda e: e["slot"] in want) if want else (lambda e: True)
        nk = norm(value)
        for match, ids in (("exact", self._by_key.get(nk, [])),
                           ("variant", [i for k in keys_of(value) - {nk} for i in self._by_key.get(k, [])]),
                           ("core", [i for k in (core_keys(value) | {nk}) for i in self._by_core.get(k, [])])):
            es = [self.entries[i] for i in dict.fromkeys(ids) if ok(self.entries[i])]
            if es:
                return {"match": match, "slot": es[0]["slot"], "entries": es}
        return {"match": "", "slot": "", "entries": []}

    def other_slot(self, value):
        """옮길 슬롯 — 사전에 지역·성별로만 있는 값 ('청양군' → 지역). 지표·분류로도 있으면 None"""
        from backend.rag.ingestion.normalize import std_geo_name
        ks = keys_of(value) | keys_of(std_geo_name(str(value or "")))  # '서울' → '서울특별시'
        es = [self.entries[i] for k in ks for i in self._by_key.get(k, [])]
        slots = {e["slot"] for e in es}
        if not slots or slots & {"지표", "분류"}:
            return None
        return next((MOVABLE[s] for s in ("지역", "성별") if s in slots), None)

    def alias_hits(self, text):
        """문장 속 별칭 → [{alias, canon, slot, dim}] (긴 별칭부터, 겹치면 한 번)"""
        t, out, used = norm(text), [], []
        for k in sorted(self.aliases, key=len, reverse=True):
            p = t.find(k)
            if p < 0 or any(a <= p < b for a, b in used):
                continue
            used.append((p, p + len(k)))
            out += self.aliases[k]
        return out

    def as_dict(self):
        return {"version": 1, "source": self.source, "n_tables": self.n_tables, "n_entries": len(self.entries),
                "entries": self.entries}


# ── 만들기 ───────────────────────────────────────────────────────
def load_aliases(path=ALIAS_PATH):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    for r in csv.DictReader(lines):
        a, c = (r.get("alias") or "").strip(), (r.get("canon") or "").strip()
        if a and c:
            out.setdefault(norm(a), []).append({"alias": a, "canon": c, "slot": (r.get("slot") or "분류").strip(),
                                                "dim": (r.get("dim") or "").strip(), "memo": (r.get("memo") or "").strip()})
    return out


class _Acc:
    """(슬롯, 분류 이름, 이름) 별로 모음. 지역·성별·연령은 분류 이름을 묶음 (표마다 '행정구역별(시도)' 처럼 달라서)"""

    def __init__(self):
        self.d, self.tables = {}, set()

    def add(self, tbl, name, slot, dim="", kind="", unit="", role="", additive=None, is_total=False, code=""):
        name = str(name or "").strip()
        if not name or not norm(name):
            return
        self.tables.add(tbl)
        key = (slot, "" if slot in ("지역", "성별", "연령") else dim, norm(name))
        e = self.d.get(key)
        if e is None:
            e = self.d[key] = {"name": name, "norm": norm(name), "slot": slot, "dim": key[1], "kind": kind,
                               "unit": unit or "", "role": role or "", "additive": additive, "is_total": bool(is_total),
                               "codes": [], "tables": set()}
        e["tables"].add(tbl)
        if code and code not in e["codes"] and len(e["codes"]) < 5:
            e["codes"].append(code)
        e["is_total"] = e["is_total"] or bool(is_total)
        if e["additive"] is None and additive is not None:
            e["additive"] = additive
        e["role"] = e["role"] or role or ""
        e["unit"] = e["unit"] or unit or ""

    def entries(self):
        out = []
        for e in self.d.values():
            ts = sorted(e["tables"])
            out.append({**e, "n_tables": len(ts), "tables": ts[:MAX_TABLES]})
        out.sort(key=lambda e: (e["slot"], -e["n_tables"], e["name"]))
        return out


def _level_slot(level, names):
    kind = str(level.get("kind") or "")
    if kind in KIND_SLOT:
        return KIND_SLOT[kind], kind
    from backend.rag.ingestion.normalize import level_kind
    k = level_kind(level.get("obj_nm") or "", names)  # schema 2 의 'other' 도 성별·연령일 수 있음
    return KIND_SLOT.get(k, "분류"), k


def add_profile(acc, prof):
    """정규화 프로필 하나 (schema 1: build_profile / schema 2: items.nm·role·additive, codes.parallel)"""
    tbl = prof.get("tbl_id") or prof.get("table_key") or ""
    levels = prof.get("levels") if isinstance(prof.get("levels"), list) else []
    for lv in levels:
        codes = lv.get("codes") or []
        slot, kind = _level_slot(lv, [c.get("name") for c in codes])
        for c in codes:
            acc.add(tbl, c.get("name"), slot, dim=lv.get("obj_nm") or "", kind=kind, is_total=c.get("is_total"),
                    code=c.get("code") or "")
    items = prof.get("items") if isinstance(prof.get("items"), list) else []
    for it in items:
        acc.add(tbl, it.get("nm") or it.get("name"), "지표", dim="항목", kind="item", unit=it.get("unit"),
                role=it.get("role") or "", additive=it.get("additive"), is_total=it.get("is_total"),
                code=it.get("itm_id") or "")


def add_index(acc, idx, scope="all"):
    """CSV 값 사전(values.parquet)의 항목·분류 값"""
    v = idx.v
    if scope == "selected":
        v = v[v["selected"]]
    slot_of = {"항목": "지표", "지역": "지역", "성별": "성별", "연령": "연령", "국적": "국적", "분류": "분류"}
    for r in v[v["kind"].isin(["item", "dim"])].itertuples(index=False):
        slot = slot_of.get(r.slot)
        if not slot:
            continue
        acc.add(r.tbl_id, r.name, slot, dim=r.obj_nm if slot != "지표" else "항목", kind=r.kind,
                unit=r.std if r.kind == "item" else "", code=r.code)


def build_vocab(profiles_dir=None, idx=None, scope="all", alias_path=ALIAS_PATH):
    acc, src = _Acc(), []
    files = sorted(Path(profiles_dir).glob("*.json")) if profiles_dir and Path(profiles_dir).exists() else []
    for f in files:
        try:
            prof = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(prof.get("levels"), list) or isinstance(prof.get("items"), list):
            add_profile(acc, prof)
    if files:
        src.append(f"profiles:{len(files)}")
    if idx is not None:
        add_index(acc, idx, scope)  # 프로필에 없는 표(원본 CSV 만 있는 표)도 덮음. 같은 이름은 한 줄로 합쳐짐
        src.append(f"csv_index:{scope}")
    return Vocab(acc.entries(), load_aliases(alias_path), "+".join(src), len(acc.tables))


def save_vocab(vocab, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(vocab.as_dict(), ensure_ascii=False), encoding="utf-8")
    return p


def load_vocab(path, alias_path=ALIAS_PATH):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Vocab(d.get("entries") or [], load_aliases(alias_path), d.get("source") or str(path), d.get("n_tables") or 0)


def vocab_path(settings=None):
    from backend.rag.csv_index.store import index_dir
    p = getattr(settings, "vocab_path", "") if settings is not None else ""
    return Path(p) if p else index_dir() / VOCAB_FILE


_CACHE, _LOCK = {}, threading.Lock()


def get_vocab(idx=None, settings=None):
    """파일이 있으면 파일(수정 시각이 바뀌면 다시 읽음), 없으면 CSV 값 사전으로 만듦 (settings.csv_scope)"""
    p = vocab_path(settings)
    scope = getattr(settings, "csv_scope", "selected")
    key = ("file", str(p), p.stat().st_mtime) if p.exists() else ("idx", id(idx), scope)
    with _LOCK:
        if key not in _CACHE:
            if p.exists():
                _CACHE[key] = load_vocab(p)
            else:
                if idx is None:
                    from backend.rag.csv_index.store import load_index
                    idx = load_index()
                _CACHE[key] = build_vocab(idx=idx, scope=scope)
        return _CACHE[key]


# ── 근거 없는 값 지우기 ─────────────────────────────────────────
def _numeric(v):
    return bool(re.fullmatch(r"[\d,\.\s~%]+(?:명|가구|건|세|년)?", str(v or "")))


def check_value(v, slot, question, vocab, lex=None, hints=(), protect=()):
    """값 하나 판정 → {value, slot, verdict: keep|drop|move, why, to, canon}"""
    from backend.rag.query_analyzer.measures import is_generic, is_measure
    s = str(v or "").strip()
    out = {"value": v, "slot": slot, "verdict": "keep", "why": "", "to": "", "canon": []}
    if not s or _numeric(s):
        return {**out, "why": "숫자·빈 값 (다른 단계가 다룸)"}
    if s in protect:
        return {**out, "why": "사용자 선택"}
    if is_measure(s) or is_generic(s):
        return {**out, "why": "계산 단어·일반 말"}
    hit = vocab.lookup(s, slot)
    if hit["entries"]:
        e = hit["entries"][0]
        return {**out, "why": f"사전 {hit['match']}: {e['slot']} '{e['name']}' ({e['dim'] or '-'}, 표 {e['n_tables']}개)",
                "canon": [x["name"] for x in hit["entries"][:3]]}
    al = vocab.aliases.get(norm(s)) or [a for a in vocab.alias_hits(question) if norm(a["canon"]) == norm(s)]
    if al:
        return {**out, "why": f"별칭 → {al[0]['dim'] or al[0]['slot']} '{al[0]['canon']}'", "canon": [a["canon"] for a in al]}
    to = vocab.other_slot(s)
    if to:
        return {**out, "verdict": "move", "to": to, "why": f"사전에 {to} 값으로만 있음"}
    if norm(s) in norm(question):
        return {**out, "why": "질문 원문"}
    if norm(s) in {norm(h) for h in hints}:
        return {**out, "why": "용어·동의어 사전 (질문의 말을 바꾼 값)"}
    if lex is not None:
        try:
            best = lex.best(s, slot)
        except Exception:  # noqa: BLE001 (사전 조회 실패로 분석이 멈추지 않게 — 근거 없음으로 봄)
            best = None
        if best is not None and best.grounded and best.source in SOURCES_OK:
            return {**out, "why": f"CSV 값 사전 ({best.source}: '{best.value}', 표 {best.n_tables}개)"}
    return {**out, "verdict": "drop", "why": "사전·질문·용어 사전 어디에도 근거 없음"}


def question_hints(question):
    """질문의 말을 통계 용어로 바꾼 값 (용어 사전 lookup_terms · 검색 동의어 synonyms)"""
    from backend.rag.query_analyzer.terms import lookup_terms
    out = [t for _, ts in lookup_terms(question) for t in ts]
    try:
        from backend.rag.search.query import synonyms
        syn = list(synonyms(question))
    except Exception:  # noqa: BLE001 (검색 패키지 없이도)
        syn = []
    return list(dict.fromkeys(out + syn))


def prune_slots(slots, question, vocab, lex=None, slot_names=("대상", "지표", "조건"), mode="drop", protect=(),
                hints=None, alias_fill=True):
    """재작성 슬롯 → (새 슬롯, 기록 [{value, slot, verdict, why, to, canon}])
    mode: drop = 근거 없는 값 지움 · log = 기록만 · off = 그대로. 지역·성별로 옮기는 것은 drop 일 때만
    alias_fill: 질문의 별칭('싱글맘')이면 정규 이름('모+미혼자녀')을 조건에 더함 (View 가 그 분류 코드를 고르게)"""
    if mode == "off" or not slots:
        return slots, []
    hints = question_hints(question) if hints is None else hints
    out, log = {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in slots.items()}, []
    for k in slot_names:
        keep = []
        for v in out.get(k) or []:
            r = check_value(v, k, question, vocab, lex, hints, protect)
            log.append(r)
            if mode != "drop" or r["verdict"] == "keep":
                keep.append(v)
            elif r["verdict"] == "move":
                out.setdefault(r["to"], [])
                if norm(v) not in {norm(x) for x in out[r["to"]]}:
                    out[r["to"]].append(v)
        if k in out:
            out[k] = keep
    if alias_fill and mode == "drop":
        have = {norm(x) for k in ("대상", "지표", "조건") for x in out.get(k) or []}
        for a in vocab.alias_hits(question):
            if norm(a["canon"]) not in have:
                out.setdefault("조건", []).append(a["canon"])
                have.add(norm(a["canon"]))
                log.append({"value": a["canon"], "slot": "조건", "verdict": "add", "to": "",
                            "why": f"질문의 별칭 '{a['alias']}' → {a['dim'] or a['slot']} '{a['canon']}'",
                            "canon": [a["canon"]]})
    return {k: v for k, v in out.items() if v}, log


def changed(log):
    return [r for r in log if r["verdict"] in ("drop", "move", "add")]


def describe(log):
    """기록 → 메모 한 줄씩 ('[지표] 고령인구비율 지움: …')"""
    word = {"drop": "지움", "move": "옮김", "add": "더함"}
    return [f"[{r['slot']}] '{r['value']}' {word[r['verdict']]}" + (f" → {r['to']}" if r["to"] else "") + f": {r['why']}"
            for r in changed(log)]


# ── CLI ─────────────────────────────────────────────────────────
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m backend.rag.query_analyzer.vocab")
    ap.add_argument("cmd", choices=["build", "embed", "check", "find", "suggest"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--profiles", default=None, help="정규화 프로필 폴더 (기본 VIEW_OUT_DIR/profiles)")
    ap.add_argument("--no-index", action="store_true", help="CSV 값 사전은 쓰지 않음 (프로필만)")
    ap.add_argument("--scope", default="all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--embed", default=None, help="build 뒤 벡터 파일도 (hcx | arctic-ko | bge-m3-ko | ens-ko | hash)")
    ap.add_argument("--mode", default=None, help="suggest 의 모드 (log | hcx). 비우면 설정값")
    ap.add_argument("--min-score", type=float, default=None, help="suggest 의 코사인 하한. 비우면 설정값")
    a = ap.parse_args(argv)
    from backend.core.settings import get_settings
    s = get_settings()
    if a.cmd == "build":
        from backend.core.config import VIEW_OUT_DIR
        prof = Path(a.profiles) if a.profiles else Path(VIEW_OUT_DIR) / "profiles"
        idx = None
        if not a.no_index:
            from backend.rag.csv_index.store import load_index
            try:
                idx = load_index()
            except FileNotFoundError as e:
                print(f"CSV 값 사전 없음 → 프로필만: {e}")
        v = build_vocab(prof, idx, a.scope)
        p = save_vocab(v, a.out or vocab_path(s))
        by = {}
        for e in v.entries:
            by[e["slot"]] = by.get(e["slot"], 0) + 1
        print(json.dumps({"path": str(p), "source": v.source, "n_tables": v.n_tables, "n_entries": len(v),
                          "by_slot": by, "n_aliases": sum(len(x) for x in v.aliases.values())}, ensure_ascii=False))
        if a.embed:
            _embed(v, a.embed, p)
        return
    v = get_vocab(settings=s)
    if a.cmd == "embed":
        _embed(v, a.embed or s.vocab_suggest_embedder, vocab_path(s))
        return
    if a.cmd == "suggest":
        from backend.rag.query_analyzer.lexicon import get_lexicon
        from backend.rag.query_analyzer.vocab_suggest import describe as sdescribe
        from backend.rag.query_analyzer.vocab_suggest import suggest_for_question
        up = {"vocab_suggest": a.mode or s.vocab_suggest, "vocab_suggest_learn": False}
        if a.embed:
            up["vocab_suggest_embedder"] = a.embed
        if a.min_score is not None:
            up["vocab_suggest_min_score"] = a.min_score
        s2 = s.model_copy(update=up)
        q = a.args[0] if a.args else ""
        new, recs, _, skipped = suggest_for_question(q, {}, v, get_lexicon(settings=s2), s2)
        print(json.dumps({"skipped": skipped, "slots": new, "suggestions": recs}, ensure_ascii=False, indent=1))
        print("\n".join(sdescribe(recs)))
        return
    if a.cmd == "find":
        for w in a.args:
            print(w, json.dumps({**v.lookup(w), "entries": [{k: e[k] for k in ("name", "slot", "dim", "n_tables")}
                                                          for e in v.lookup(w)["entries"][:5]]}, ensure_ascii=False))
        return
    q, pairs = (a.args[0] if a.args else ""), a.args[1:]
    slots = {}
    for p in pairs:
        k, _, val = p.partition("=")
        slots.setdefault(k, []).append(val)
    new, log = prune_slots(slots, q, v)
    print(json.dumps({"before": slots, "after": new, "log": log}, ensure_ascii=False, indent=1))


def _embed(vocab, name, vocab_file):
    """사전 이름 → 벡터 파일 (vocab.json 옆 vocab_vectors.<임베더>.npz). HCX 는 임베딩 캐시(sqlite)를 씀"""
    from backend.rag.query_analyzer.vocab_suggest import build_vectors, get_embedder
    emb = get_embedder(name)
    if emb is None:
        print("임베더 none → 벡터 파일 안 만듦")
        return
    out = Path(vocab_file).with_name(f"vocab_vectors.{name}.npz")
    p, n = build_vectors(vocab, emb, out)
    print(json.dumps({"vectors": str(p), "embedder": getattr(emb, "id", name), "n": n}, ensure_ascii=False))


if __name__ == "__main__":
    main()
