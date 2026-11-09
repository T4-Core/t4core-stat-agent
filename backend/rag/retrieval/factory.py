"""[NEW v4] 구성(YAML·dict) → RetrievalPipeline 조립

  cfg = load_config("baseline")                                # configs/retrieval/baseline.yaml
  cfg = load_config("baseline", {"rerank.1.embedder.type": "hash"})   # 점 경로로 일부만 바꾸기
  cfg = load_config({"extends": "baseline", "top_k": 5})       # dict 도 됨. extends 로 다른 구성을 물려받음
  p = get_pipeline(cfg)                                        # 같은 구성이면 만든 것을 다시 씀 (BM25·벡터 캐시)
  p.search("인구 수", filters={...})

새 구현 붙이기:
  @register("reranker", "my_llm")
  class MyLlmReranker: ...                                      # interfaces.Reranker 모양
  → YAML 에서 rerank: [{type: my_llm, …}]

구성 모양 (configs/retrieval/README.md 에 전체 설명)
  name, description, requires: [패키지]
  corpus:     {type: table_text | csv_index | external, …}
  query:      {prep: none | resolve}          resolve = resolve.search_query (지역·시점 단어 빼고 지표 더함)
  retrievers: [{name, type: bm25 | dense, k, tokenizer: {…} | embedder: {…}}, …]   2개 이상이면 fusion
  fusion:     {type: rrf | weighted, k: 60, weights: {검색기 이름: 가중치}, norm: minmax, pool: 50}
  rerank:     [{type: condition | embed | cross_encoder | rrf_stages | none, top_n, …}, …]
  top_k
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import yaml

from backend.core.config import CONFIGS_DIR
from backend.rag.retrieval import corpus as _corpus
from backend.rag.retrieval import embedders as _emb
from backend.rag.retrieval import rerankers as _rr
from backend.rag.retrieval import retrievers as _ret
from backend.rag.retrieval import tokenizers as _tok

RETRIEVAL_CONFIGS_DIR = CONFIGS_DIR / "retrieval"

REGISTRY: dict[str, dict] = {"corpus": {}, "tokenizer": {}, "embedder": {}, "retriever": {}, "reranker": {}}


def register(kind, name):
    def deco(obj):
        REGISTRY[kind][name] = obj
        return obj
    return deco


for _n, _c in {"table_text": _corpus.TableTextCorpus, "csv_index": _corpus.CsvIndexCorpus,
               "external": _corpus.ExternalCorpus}.items():
    register("corpus", _n)(_c)
register("tokenizer", "kiwi")(_tok.KiwiTokenizer)
register("tokenizer", "okt")(lambda **kw: _tok.KonlpyTokenizer("okt", **kw))
register("tokenizer", "mecab")(lambda **kw: _tok.KonlpyTokenizer("mecab", **kw))
register("tokenizer", "char_ngram")(_tok.CharNgramTokenizer)
register("tokenizer", "whitespace")(_tok.WhitespaceTokenizer)
register("embedder", "hcx_bge_m3")(_emb.HcxBgeM3Embedder)
register("embedder", "sentence_transformers")(_emb.SentenceTransformerEmbedder)
register("embedder", "hash")(_emb.HashEmbedder)
register("reranker", "none")(_rr.NoneReranker)
register("reranker", "condition")(_rr.ConditionReranker)
register("reranker", "cross_encoder")(_rr.CrossEncoderReranker)
register("reranker", "rrf_stages")(_rr.RrfStagesReranker)

# 무거운 것(모델·코퍼스)은 같은 설정이면 한 번만 만든다
_cache: dict = {}
_lock = threading.RLock()


def _key(kind, spec):
    return kind + ":" + json.dumps(spec, sort_keys=True, ensure_ascii=False, default=str)


def _cached(kind, spec, make):
    k = _key(kind, spec)
    with _lock:
        if k not in _cache:
            _cache[k] = make()
        return _cache[k]


def _new(kind, spec):
    spec = dict(spec or {})
    t = spec.pop("type", None)
    if t not in REGISTRY[kind]:
        raise ValueError(f"{kind} type '{t}' 없음. 가능: {sorted(REGISTRY[kind])}")
    return REGISTRY[kind][t](**spec)


def build_corpus(spec):
    return _cached("corpus", spec, lambda: _new("corpus", spec))


def build_tokenizer(spec):
    return _cached("tokenizer", spec, lambda: _new("tokenizer", spec))


def build_embedder(spec):
    return _cached("embedder", spec, lambda: _new("embedder", spec))


def build_retriever(spec, corpus):
    orig = dict(spec)
    spec = dict(spec)
    t = spec.pop("type")
    name = spec.pop("name", None) or t
    spec.pop("k", None)
    if t == "bm25":
        tok = build_tokenizer(spec.pop("tokenizer", None) or {"type": "kiwi"})
        make = lambda: _ret.BM25Retriever(tok, name=name, **spec)  # noqa: E731
    elif t == "dense":
        emb = build_embedder(spec.pop("embedder", None) or {"type": "hcx_bge_m3"})
        make = lambda: _ret.DenseRetriever(emb, name=name, **spec)  # noqa: E731
    elif t in REGISTRY["retriever"]:
        make = lambda: REGISTRY["retriever"][t](name=name, **spec)  # noqa: E731
    else:
        raise ValueError(f"retriever type '{t}' 없음. 가능: bm25, dense, {sorted(REGISTRY['retriever'])}")
    # 같은 코퍼스 + 같은 설정이면 fit 한 것을 다시 씀
    orig.pop("k", None)                                        # k 는 검색 때만 씀 → 캐시 키에서 뺌
    return _cached("retriever", {"corpus": corpus.signature(), "spec": orig}, lambda: make().fit(corpus))


def build_reranker(spec):
    spec = dict(spec)
    t = spec.get("type")
    if t == "embed":
        s = dict(spec)
        s.pop("type")
        emb = build_embedder(s.pop("embedder", None) or {"type": "hcx_bge_m3"})
        return _rr.EmbedReranker(emb, name=s.pop("name", "embed"), **s)
    if t == "cross_encoder":                                   # 모델은 무거우므로 캐시
        return _cached("reranker", spec, lambda: _new("reranker", spec))
    return _new("reranker", spec)


# ── 구성 읽기 ────────────────────────────────────────────────────
def config_path(name):
    p = Path(name)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return p
    return RETRIEVAL_CONFIGS_DIR / f"{name}.yaml"


def _deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _set_path(d, path, value):
    keys = path.split(".")
    cur = d
    for i, k in enumerate(keys):
        last = i == len(keys) - 1
        if isinstance(cur, list):
            k = int(k)
            if last:
                cur[k] = value
            else:
                cur = cur[k]
        else:
            if last:
                cur[k] = value
            else:
                cur = cur.setdefault(k, {} if not keys[i + 1].isdigit() else [])


def apply_overrides(cfg, overrides=None):
    """overrides: {"top_k": 5, "rerank.1.model": "…", "fusion": {"k": 30}} — 점 경로는 그 자리만, 아니면 깊은 병합"""
    cfg = copy.deepcopy(cfg)
    for k, v in (overrides or {}).items():
        if "." in k:
            _set_path(cfg, k, copy.deepcopy(v))
        else:
            cfg = _deep_merge(cfg, {k: v})
    return cfg


def load_config(cfg, overrides=None, _seen=None):
    """이름 | YAML 경로 | dict → 펼친 구성 dict (extends 반영, name 채움)"""
    _seen = set(_seen or ())
    if isinstance(cfg, str):
        p = config_path(cfg)
        if not p.exists():
            raise FileNotFoundError(f"검색 구성 없음: {cfg}  (configs/retrieval/ 에 {sorted(list_config_names())})")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        data.setdefault("name", p.stem)
    else:
        data = copy.deepcopy(dict(cfg))
    base = data.pop("extends", None)
    if base:
        if base in _seen:
            raise ValueError(f"extends 순환: {base}")
        parent = load_config(base, _seen=_seen | {base})
        parent.pop("description", None)
        data = _deep_merge(parent, data)
        data.setdefault("extends", base)
    data = apply_overrides(data, overrides)
    data.setdefault("name", "inline")
    data.setdefault("corpus", {"type": "table_text"})
    data.setdefault("query", {"prep": "none"})
    data.setdefault("fusion", {"type": "rrf"} if len(data.get("retrievers") or []) > 1 else {"type": "none"})
    data.setdefault("rerank", [])
    data.setdefault("top_k", 10)
    if not data.get("retrievers"):
        raise ValueError(f"구성 {data['name']}: retrievers 가 비었음")
    return data


def config_hash(cfg):
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:10]


def list_config_names():
    return sorted(p.stem for p in RETRIEVAL_CONFIGS_DIR.glob("*.yaml")) if RETRIEVAL_CONFIGS_DIR.exists() else []


PIP_NAME = {"sentence_transformers": "sentence-transformers", "konlpy": "konlpy", "torch": "torch"}


def missing_requirements(cfg):
    """구성의 requires(파이썬 패키지 import 이름) 중 설치 안 된 것"""
    req = cfg.get("requires") or []
    return [r for r in req if importlib.util.find_spec(r.replace("-", "_")) is None]


def list_configs():
    out = []
    for n in list_config_names():
        try:
            c = load_config(n)
            out.append({"name": n, "description": c.get("description", ""), "extends": c.get("extends"),
                        "requires": c.get("requires") or [], "missing": missing_requirements(c),
                        "corpus": c["corpus"].get("type"), "retrievers": [r.get("name") or r["type"] for r in c["retrievers"]],
                        "rerank": [r.get("name") or r["type"] for r in c["rerank"]], "error": None})
        except Exception as e:  # noqa: BLE001  (깨진 YAML 하나가 목록 전체를 막지 않게)
            out.append({"name": n, "error": f"{e.__class__.__name__}: {e}"})
    return out


# ── 조립 ────────────────────────────────────────────────────────
_pipes: dict = {}


def build_pipeline(cfg, overrides=None):
    from backend.rag.retrieval.pipeline import RetrievalPipeline
    cfg = load_config(cfg, overrides)
    miss = missing_requirements(cfg)
    if miss:
        raise ImportError(f"구성 {cfg['name']}: 설치 필요 {miss}  (pip install {' '.join(PIP_NAME.get(m, m) for m in miss)})")
    corpus = build_corpus(cfg["corpus"])
    rets, ks = [], {}
    for spec in cfg["retrievers"]:
        r = build_retriever(spec, corpus)
        rets.append(r)
        ks[r.name] = int(spec.get("k", 50))
    if len({r.name for r in rets}) != len(rets):
        raise ValueError(f"구성 {cfg['name']}: 검색기 name 이 겹침 — 같은 type 을 두 번 쓰면 name 을 따로 주세요")
    rerankers = [build_reranker(s) for s in cfg["rerank"]]
    return RetrievalPipeline(cfg, corpus, rets, ks, rerankers)


def get_pipeline(cfg, overrides=None):
    """같은 구성(펼친 dict 기준)이면 만든 파이프라인을 다시 씀. 코퍼스가 바뀌면(서명) 새로 만듦"""
    c = load_config(cfg, overrides)
    corp = build_corpus(c["corpus"])
    k = (config_hash(c), corp.signature())
    with _lock:
        if k not in _pipes:
            _pipes[k] = build_pipeline(c)
        return _pipes[k]


def clear_cache():
    with _lock:
        _cache.clear()
        _pipes.clear()
