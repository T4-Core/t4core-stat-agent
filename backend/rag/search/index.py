"""검색 기본 부품 — 표 하나 = 문서 하나

  TableTextCorpus   표 설명문 색인 (ingestion/table_text.py → storage/indices/table_index)
  csv_table_text    CSV 값 사전의 표 하나 → 설명문 (View 선택지 설명에 사용)
  KiwiTokenizer     Kiwi 형태소 (table_text.tokenize 와 같음)
  CharNgramTokenizer 공백을 뺀 글자 n-gram
  BM25Retriever     rank_bm25 Okapi. 문서 토큰은 색인 토큰 → 디스크 캐시 → 새로 계산 순
  DenseRetriever    임베더로 코퍼스 전체를 벡터화(디스크 캐시) 후 코사인
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
    def __init__(self, embedder, name="dense", cache=True):
        self.name, self.emb, self.cache = name, embedder, cache

    def fit(self, corpus):
        docs = corpus.docs()
        f = _cache_file("dense", corpus.signature(), self.emb.id)
        if self.cache and f.exists():
            self.M = pickle.loads(f.read_bytes())
        else:
            self.M = self.emb.embed_docs([d.text for d in docs])
            if self.cache:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(pickle.dumps(self.M))
        return self

    def search(self, query, k):
        sims = self.M @ self.emb.embed_queries([query])[0]
        return [(int(i), float(sims[i])) for i in np.argsort(-sims)[:k]]


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


def embedder(name):
    """hcx | hash | none → 임베더 (none 이면 None)"""
    if not name or name == "none":
        return None
    if name not in EMBEDDERS:
        raise ValueError(f"dense 는 {' | '.join(EMBEDDERS)} | none: {name}")
    return EMBEDDERS[name]()
