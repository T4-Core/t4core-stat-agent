"""검색 기본 부품 — 표 하나 = 문서 하나

  TableTextCorpus   표 설명문 색인 (ingestion/table_text.py → storage/indices/table_index)
  csv_table_text    CSV 값 사전의 표 하나 → 설명문 (View 선택지 설명에 사용)
  KiwiTokenizer     Kiwi 형태소 (table_text.tokenize 와 같음)
  CharNgramTokenizer 공백을 뺀 글자 n-gram
  BM25Retriever     rank_bm25 Okapi. 문서 토큰은 색인 토큰 → 디스크 캐시 → 새로 계산 순
  DenseRetriever    임베더로 코퍼스 전체를 벡터화(디스크 캐시) 후 코사인. 문서 묶음(view)이 여럿이면 표마다 최댓값
  dense_doc_views   dense 에 넣을 문서: rule(표 설명문) · def · slot · tmpl · tslot (dense 카드) · kos14 (팀 카드)
  HcxEmbedder       CLOVA Studio 임베딩 v2 (bge-m3)
  HashEmbedder      글자 2-gram 해시 벡터 (네트워크 없이 구조 확인용)
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.core.config import STORAGE_DIR

CACHE_DIR = STORAGE_DIR / "indices" / "search_cache"
SMALL_DIM = 30
MAX_ITEMS = 30
_SPLIT = re.compile(r"[\s\|/,·()\[\]{}:;~\-\"'<>]+")


@dataclass
class Doc:
    id: str
    text: str
    meta: dict = field(default_factory=dict)


def _mtime_sig(*paths) -> str:
    parts = [f"{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in map(Path, paths) if p.exists()]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _cache_file(kind, *keys):
    h = hashlib.sha1("|".join(map(str, keys)).encode()).hexdigest()[:16]
    return CACHE_DIR / kind / f"{h}.pkl"


def normalize(m):
    m = np.asarray(m, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)


# ── 코퍼스 ──────────────────────────────────────────────────────
class TableTextCorpus:
    name = "table_text"

    def __init__(self, index_dir=None):
        from backend.rag.ingestion.table_text import INDEX
        self.dir = Path(index_dir or INDEX)
        self._docs, self._sig = None, None

    def _files(self):
        return [self.dir / n for n in ("ids.json", "texts.jsonl", "tokens.json")]

    def signature(self):
        return f"table_text:{_mtime_sig(*self._files())}"

    def docs(self):
        sig = self.signature()
        if self._docs is None or self._sig != sig:
            self._sig = sig
            if not (self.dir / "tokens.json").exists():
                raise FileNotFoundError(f"표 색인이 없습니다: {self.dir}  →  POST /api/v1/ingest/table-index/build "
                                        f"또는 python -m backend.rag.ingestion.table_text")
            from backend.rag.ingestion.meta_profile import load_meta_profiles
            ids = json.loads((self.dir / "ids.json").read_text(encoding="utf-8"))
            texts = {r["tbl_id"]: r["text"] for r in
                     map(json.loads, (self.dir / "texts.jsonl").read_text(encoding="utf-8").splitlines())}
            prof = {p["tbl_id"]: p for p in load_meta_profiles()}
            self._docs = [Doc(i, texts[i], {"tbl_nm": (prof.get(i) or {}).get("tbl_nm", ""),
                                            "survey_nm": (prof.get(i) or {}).get("survey_nm", "")}) for i in ids]
        return self._docs

    def cached_tokens(self, tokenizer_id):
        if tokenizer_id == KiwiTokenizer.id and (self.dir / "tokens.json").exists():
            return json.loads((self.dir / "tokens.json").read_text(encoding="utf-8"))
        return None


_corpus, _corpus_lock = None, threading.Lock()


def table_corpus() -> TableTextCorpus:
    global _corpus
    with _corpus_lock:
        if _corpus is None:
            _corpus = TableTextCorpus()
        return _corpus


def csv_table_text(t: dict) -> str:
    """CSV 값 사전의 표 하나 → 설명문 ("무엇을 세었는가"만, 지역 코드·연도 목록은 넣지 않음)"""
    from backend.rag.ingestion.table_text import is_region_list, is_sido
    dims = []
    for d in t.get("dims") or []:
        names = [v["name"] for v in d.get("values") or []]
        if d.get("kind") == "regions" or is_region_list(names):
            geo = sorted({v.get("geo") for v in d.get("values") or [] if v.get("geo") and v.get("geo") != "전국"})
            dims.append(f"{d['obj_nm']}({'·'.join(geo) or '지역'})")
        elif d.get("n_values", len(names)) <= SMALL_DIM:
            dims.append(f"{d['obj_nm']}({', '.join(names[:15])})")
        else:
            dims.append(f"{d['obj_nm']}({d.get('n_values')}개: {', '.join(names[:8])} …)")
    items = [i["name"] for i in t.get("items") or []]
    if is_region_list(items):
        items = [n for n in items if not is_sido(n) and n != "전국"] + ["지역(시도)"]
    units = sorted({i.get("unit") for i in t.get("items") or [] if i.get("unit")})
    ys = t.get("years") or []
    notes = [f["text"] for f in t.get("footnotes") or [] if f.get("type") in ("통계표", "항목") and f.get("text")]
    parts = [f"{t.get('survey_nm') or ''} | {t.get('tbl_nm') or ''}",
             "분류: " + " / ".join(dims) if dims else "",
             "항목: " + ", ".join(items[:MAX_ITEMS]) + (f" 외 {len(items) - MAX_ITEMS}개" if len(items) > MAX_ITEMS else "")
             if items else "",
             "단위: " + ", ".join(units) if units else "",
             f"기간: {ys[0]}~{ys[-1]}" if ys else "",
             "경로: " + (t.get("menu_path") or ""),
             "주석: " + " / ".join(n[:80] for n in notes[:2]) if notes else ""]
    return "\n".join(x for x in parts if x)[:1500]


# ── 토크나이저 ──────────────────────────────────────────────────
class KiwiTokenizer:
    id = "kiwi:table"

    def __call__(self, text):
        from backend.rag.ingestion.table_text import tokenize
        return tokenize(str(text or ""))


class CharNgramTokenizer:
    def __init__(self, n=(2, 3), keep_words=True):
        self.n = tuple(sorted(int(x) for x in (n if isinstance(n, (list, tuple)) else [n])))
        self.keep_words = keep_words
        self.id = f"char_ngram:{'-'.join(map(str, self.n))}:{int(keep_words)}"

    def __call__(self, text):
        out = []
        for w in _SPLIT.split(str(text or "").lower()):
            if not w:
                continue
            if self.keep_words and len(w) > max(self.n):
                out.append(w)
            for n in self.n:
                if len(w) >= n:
                    out += [w[i:i + n] for i in range(len(w) - n + 1)]
                elif n == self.n[0]:
                    out.append(w)
        return out


# ── 검색기 ──────────────────────────────────────────────────────
class BM25Retriever:
    def __init__(self, tokenizer, name="bm25", k1=1.5, b=0.75, epsilon=0.25, cache=True):
        self.name, self.tok = name, tokenizer
        self.k1, self.b, self.epsilon, self.cache = k1, b, epsilon, cache

    def _doc_tokens(self, corpus):
        docs = corpus.docs()
        toks = corpus.cached_tokens(self.tok.id) if hasattr(corpus, "cached_tokens") else None
        if toks is not None and len(toks) == len(docs):
            return toks
        f = _cache_file("tokens", corpus.signature(), self.tok.id)
        if self.cache and f.exists():
            return pickle.loads(f.read_bytes())
        toks = [self.tok(d.text) for d in docs]
        if self.cache:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(toks))
        return toks

    def fit(self, corpus):
        import rank_bm25
        toks = self._doc_tokens(corpus)
        self.bm25 = rank_bm25.BM25Okapi(toks, k1=self.k1, b=self.b, epsilon=self.epsilon)
        self.n = len(toks)
        return self

    def search(self, query, k):
        toks = self.tok(query)
        scores = self.bm25.get_scores(toks) if toks else np.zeros(self.n)
        return [(int(i), float(scores[i])) for i in np.argsort(-scores)[:k]]


class DenseRetriever:
    """views = [(이름, 글 목록)] — 코퍼스 순서. 없으면 코퍼스 문서 글 하나.
    글 목록의 한 칸은 글 하나 또는 글 여러 개(표 하나를 여러 조각으로 — vals). 조각은 표마다 최댓값.
    묶음이 여럿이면 표 점수 = 묶음별 코사인의 최댓값 ('+' 로 묶은 구성. 점수 크기가 다른 묶음은 ',' 로 따로 채널을 쓰는 편이 낫다)"""

    def __init__(self, embedder, name="dense", cache=True, views=None):
        self.name, self.emb, self.cache, self.views = name, embedder, cache, views

    def _embed(self, corpus, vname, texts):
        keys = (corpus.signature(), self.emb.id) if vname == "rule" else \
            (corpus.signature(), self.emb.id, vname, hashlib.sha1("\x1f".join(texts).encode()).hexdigest()[:16])
        f = _cache_file("dense", *keys)  # rule 은 예전 캐시 키 그대로 (이미 만든 임베딩을 다시 씀)
        if self.cache and f.exists():
            return pickle.loads(f.read_bytes())
        M = self.emb.embed_docs(texts)
        if self.cache:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(M))
        return M

    def fit(self, corpus):
        docs = corpus.docs()
        self.n = len(docs)
        views = self.views or [("rule", [d.text for d in docs])]
        self.view_names = [n for n, _ in views]
        self.Ms, self.owners = [], []
        for n, items in views:
            flat, own = [], []
            for i, t in enumerate(items):
                for x in (t if isinstance(t, (list, tuple)) else [t]):
                    flat.append(str(x))
                    own.append(i)
            self.Ms.append(self._embed(corpus, n, flat))
            self.owners.append(None if len(flat) == self.n and own == list(range(self.n)) else np.asarray(own))
        self.M = self.Ms[0]
        return self

    def _view_scores(self, k, q):
        s = self.Ms[k] @ q
        own = self.owners[k]
        if own is None:
            return s
        out = np.full(self.n, -1.0, dtype=s.dtype)
        np.maximum.at(out, own, s)
        return out

    def scores(self, text):
        q = self.emb.embed_queries([text])[0]
        out = self._view_scores(0, q)
        for k in range(1, len(self.Ms)):
            out = np.maximum(out, self._view_scores(k, q))
        return out

    def search(self, query, k):
        sims = self.scores(query)
        return [(int(i), float(sims[i])) for i in np.argsort(-sims)[:k]]


DOC_VIEWS = ("rule", "def", "slot", "tmpl", "tslot", "kos14", "vals")
_CARD_FIELD = {"def": "def_text", "slot": "slot_text", "tmpl": "tmpl_text", "tslot": "tslot_text"}


def parse_docs(spec):
    """dense 문서 구성 → (채널 목록, rw)
      ','  채널 나누기 — 묶음마다 dense 채널을 따로 두고 RRF 로 합침 (점수 크기가 달라도 공정)
      '+'  한 채널 안에서 표마다 최댓값
      'rw' 재작성 문장(검색 문장)으로도 첫 채널을 한 번 더 (rw_dense)
    'rule,def+vals+rw' → ([['rule'], ['def', 'vals']], True) · 빈 값 → ([['rule']], False)"""
    rw = False
    groups = []
    for g in str(spec or "rule").split(","):
        vs = [p.strip() for p in g.split("+") if p.strip()]
        rw |= "rw" in vs
        vs = [v for v in vs if v != "rw"]
        if vs:
            groups.append(vs)
    groups = groups or [["rule"]]
    bad = [v for g in groups for v in g if v not in DOC_VIEWS]
    if bad:
        raise ValueError(f"dense_docs 는 {' | '.join(DOC_VIEWS)} 를 '+'(최댓값) · ','(채널 나누기) 로 (끝에 +rw): {spec}")
    return groups, rw


def group_name(views):
    return "+".join(views)


def dense_doc_views(corpus, spec="rule", cards=None, kos14=None, log=None, facets=None):
    """dense 에 넣을 문서 → {묶음 이름: 글 목록} (코퍼스 순서). 카드가 없는 표는 규칙 설명문으로 채우고 수를 알림
    cards: dense 카드 파일 (ingestion/dense_cards.py, 기본 경로) · kos14: 팀 카드 cards.jsonl (dense_text 칸)
    vals: 표의 항목·분류 값을 조각으로 (표 하나 = 여러 글, ingestion/dense_cards.value_chunks). facets 를 주면 다시 만들지 않음"""
    groups, _ = parse_docs(spec)
    docs = corpus.docs()
    out, loaded = {}, {}
    for v in dict.fromkeys(x for g in groups for x in g):
        if v == "rule":
            out["rule"] = [d.text for d in docs]
            continue
        if v == "vals":
            from backend.rag.ingestion.dense_cards import Vocab, value_chunks
            if facets is None:
                from backend.rag.search.facets import build_facets
                facets = build_facets(docs, "auto", log)
            vocab = Vocab()
            out["vals"] = [value_chunks(facets[d.id], vocab) if d.id in facets else [d.text] for d in docs]
            if log:
                log(f"[search] dense 문서 vals: 조각 {sum(len(x) for x in out['vals'])}개 (표 {len(docs)})")
            continue
        if v == "kos14":
            if not kos14:
                raise ValueError("dense_docs kos14 는 팀 카드 파일 경로가 필요합니다 (settings kos14_cards / compare --kos14)")
            if "kos14" not in loaded:
                loaded["kos14"] = _read_kos14(kos14)
            src, field_ = loaded["kos14"], None
        else:
            if "cards" not in loaded:
                from backend.rag.ingestion.dense_cards import CARDS_PATH, load_cards
                loaded["cards"] = load_cards(cards)
                if not loaded["cards"]:
                    raise FileNotFoundError(f"dense 카드가 없습니다: {cards or CARDS_PATH}  →  "
                                            f"python -m backend.rag.ingestion.dense_cards build")
            src, field_ = loaded["cards"], _CARD_FIELD[v]
        texts, miss = [], 0
        for d in docs:
            r = src.get(d.id)
            t = (r if field_ is None else (r or {}).get(field_)) if r else None
            if not t:
                miss += 1
            texts.append(t or d.text)
        if log:
            log(f"[search] dense 문서 {v}: 표 {len(docs) - miss}/{len(docs)} (없는 {miss}개는 표 설명문)")
        out[v] = texts
    return out


def _read_kos14(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("dense_text"):
                out[str(r["tbl_id"])] = r["dense_text"]
    return out


# ── 임베더 ──────────────────────────────────────────────────────
class HcxEmbedder:
    id = "hcx:bge-m3"

    def __init__(self, workers=4):
        self.workers = workers

    def embed_queries(self, texts):
        from backend.core import llm
        return normalize(np.vstack([llm.embed_one(t) for t in texts]))

    def embed_docs(self, texts):
        from backend.core import llm
        return normalize(llm.embed_many(list(texts), workers=self.workers, progress=lambda m: None))


class HashEmbedder:
    def __init__(self, dim=256):
        self.dim, self.id = dim, f"hash:{dim}"

    def _one(self, text):
        t = "".join(str(text or "").split())
        v = np.zeros(self.dim, dtype=np.float32)
        for i in range(max(len(t) - 1, 0)):
            v[int(hashlib.md5(t[i:i + 2].encode()).hexdigest()[:8], 16) % self.dim] += 1
        return v + 1e-3

    def embed_queries(self, texts):
        return normalize(np.vstack([self._one(t) for t in texts]))

    embed_docs = embed_queries


EMBEDDERS = {"hcx": HcxEmbedder, "hash": HashEmbedder}


def dense_names():
    """--dense 로 고를 수 있는 이름: hcx · hash · 로컬 모델(search/embedders.py) · none"""
    from backend.rag.search.embedders import NAMES
    return [*EMBEDDERS, *NAMES, "none"]


def embedder(name):
    """hcx | hash | arctic-ko | bge-m3-ko | ens-ko | none → 임베더 (none 이면 None)"""
    if not name or name == "none":
        return None
    if name in EMBEDDERS:
        return EMBEDDERS[name]()
    from backend.rag.search.embedders import NAMES, local_embedder
    if name in NAMES:
        return local_embedder(name)
    raise ValueError(f"dense 는 {' | '.join(dense_names())}: {name}")
