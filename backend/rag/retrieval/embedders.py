"""[NEW v4] 임베더 — 질의·문서 문장 → 정규화된 벡터 (코사인 = 내적)

  hcx_bge_m3            CLOVA Studio 임베딩 v2 (bge-m3, HCX API) = 현재 검색 (dense.py 그대로, 캐시 공유)
  sentence_transformers 로컬 모델 (HuggingFace 에서 받음, CPU·GPU 자동)  예:
                          BAAI/bge-m3 · intfloat/multilingual-e5-large(질의 'query: ', 문서 'passage: ')
                          nlpai-lab/KoE5 · dragonkue/BGE-m3-ko · jhgan/ko-sroberta-multitask
                        device: auto(cuda → mps → cpu) | cpu | cuda | cuda:1
                        필요: pip install sentence-transformers  (torch 는 CPU/GPU 에 맞게 따로 설치)
  hash                  글자 2-gram 해시 벡터 (네트워크·모델 없이 구조 확인용, 품질 비교 대상 아님)

캐시: 로컬 모델 벡터는 storage/indices/retrieval_lab/embed_cache.sqlite 에 (모델·앞머리·문장) 단위로 저장
     → 같은 구성으로 다시 돌리면 계산하지 않음. HCX 는 기존 embed_cache.sqlite 를 그대로 씀
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import numpy as np

from backend.core.config import STORAGE_DIR

LAB_DIR = STORAGE_DIR / "indices" / "retrieval_lab"


def normalize(m):
    m = np.asarray(m, dtype=np.float32)
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-12)


def resolve_device(device="auto"):
    if device and device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class VecCache:
    """(키 → float32 벡터) sqlite 캐시. 여러 스레드에서 써도 됨"""

    def __init__(self, path=None):
        path = Path(path or LAB_DIR / "embed_cache.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.lock = threading.Lock()

    @staticmethod
    def key(ns, text):
        return hashlib.sha1(f"{ns}\n{text}".encode()).hexdigest()

    def get_many(self, ns, texts):
        keys = [self.key(ns, t) for t in texts]
        found = {}
        with self.lock:
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                q = f"SELECT k, v FROM emb WHERE k IN ({','.join('?' * len(chunk))})"
                found.update({k: np.frombuffer(v, dtype=np.float32) for k, v in self.db.execute(q, chunk)})
        return [found.get(k) for k in keys]

    def put_many(self, ns, texts, vecs):
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?)",
                                [(self.key(ns, t), np.asarray(v, dtype=np.float32).tobytes()) for t, v in zip(texts, vecs)])
            self.db.commit()


_vec_cache = {}


def vec_cache(path=None):
    k = str(path or "")
    if k not in _vec_cache:
        _vec_cache[k] = VecCache(path)
    return _vec_cache[k]


class HcxBgeM3Embedder:
    """현재 검색이 쓰는 HCX bge-m3 (dense.py). 질의·문서 같은 방식"""
    id = "hcx:bge-m3"

    def __init__(self, workers=4):
        self.workers = workers

    def embed_queries(self, texts):
        from backend.rag.retrieval import dense
        return normalize(np.vstack([dense.embed_one(t) for t in texts]))

    def embed_docs(self, texts):
        from backend.rag.retrieval import dense
        return normalize(dense.embed_many(list(texts), workers=self.workers, progress=lambda m: None))


class SentenceTransformerEmbedder:
    """HuggingFace sentence-transformers 로컬 모델"""

    def __init__(self, model="BAAI/bge-m3", device="auto", batch_size=16, query_prefix="", doc_prefix="",
                 max_seq_length=512, cache=True, trust_remote_code=False, fp16=None, model_kwargs=None):
        self.model_name, self.device_req = model, device
        self.batch_size, self.query_prefix, self.doc_prefix = batch_size, query_prefix, doc_prefix
        self.max_seq_length, self.cache, self.trust_remote_code = max_seq_length, cache, trust_remote_code
        self.fp16, self.model_kwargs = fp16, model_kwargs or {}
        self.id = f"st:{model}:{max_seq_length}"
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError("sentence_transformers 임베더는 sentence-transformers 가 필요합니다: "
                                  "pip install sentence-transformers (torch 는 CPU/GPU 에 맞게)") from e
            self.device = resolve_device(self.device_req)
            m = SentenceTransformer(self.model_name, device=self.device, trust_remote_code=self.trust_remote_code,
                                    **self.model_kwargs)
            if self.max_seq_length:
                m.max_seq_length = self.max_seq_length
            if (self.fp16 if self.fp16 is not None else self.device.startswith("cuda")):
                m.half()
            self._model = m
        return self._model

    def _encode(self, texts, prefix):
        texts = [prefix + (t or "") for t in texts]
        ns = f"{self.id}"
        cached = vec_cache().get_many(ns, texts) if self.cache else [None] * len(texts)
        todo = [i for i, v in enumerate(cached) if v is None]
        if todo:
            vecs = self.model.encode([texts[i] for i in todo], batch_size=self.batch_size, convert_to_numpy=True,
                                     normalize_embeddings=True, show_progress_bar=len(todo) > 200)
            vecs = np.asarray(vecs, dtype=np.float32)
            for j, i in enumerate(todo):
                cached[i] = vecs[j]
            if self.cache:
                vec_cache().put_many(ns, [texts[i] for i in todo], vecs)
        return normalize(np.vstack(cached)) if cached else np.zeros((0, 1), np.float32)

    def embed_queries(self, texts):
        return self._encode(texts, self.query_prefix)

    def embed_docs(self, texts):
        return self._encode(texts, self.doc_prefix)


class HashEmbedder:
    """글자 2-gram 해시 (구조 확인·오프라인 테스트용)"""

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
