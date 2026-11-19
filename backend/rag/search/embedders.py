"""로컬 임베딩 모델 (sentence-transformers) — dense 채널을 HCX bge-m3 대신 내 PC 의 모델로

  이름            모델                                           질문 앞에 붙이는 말
  arctic-ko       dragonkue/snowflake-arctic-embed-l-v2.0-ko     prompt_name="query" ('query: ')
  bge-m3-ko       dragonkue/BGE-m3-ko                            없음
  kure            nlpai-lab/KURE-v1                              없음
  ens-ko          arctic-ko + bge-m3-ko                          (각 모델 그대로)

  앙상블: 두 모델의 정규화 벡터를 이어 붙이고 √2 로 나눈다 → 표와의 내적 = 두 코사인의 평균.
         채널 하나라 검색 가중치(q_dense)·캐시 구조가 그대로이고, 각 모델의 문서 임베딩 캐시를 다시 쓴다.

  설치 (기본 requirements 에는 없음 — 서버 이미지를 가볍게):
    pip install -r requirements-embed.txt      (sentence-transformers · torch. GPU 면 PyTorch 안내대로 CUDA 판)
  환경변수
    EMBED_DEVICE   cpu | cuda | mps (비우면 자동)
    EMBED_MAX_LEN  최대 토큰 (기본 2048. 표 설명문은 1500자 이하라 잘리지 않음 — info 로 확인)
    EMBED_BATCH    문서 임베딩 배치 (기본 8)
    EMBED_DTYPE    float32(기본) | bfloat16 | float16 — GPU 에서 메모리·시간 절약 (arctic 은 bf16 권장)
    EMBED_MODEL_ARCTIC_KO, EMBED_MODEL_BGE_M3_KO, EMBED_MODEL_KURE   모델 경로를 바꿀 때 (내려받아 둔 폴더 등)
  문서 임베딩은 <임베딩 캐시>/st_docs/ 에 모델·최대 길이·문서 내용별로 저장 → 처음 한 번만 오래 걸림

  python -m backend.rag.search.embedders warm arctic-ko bge-m3-ko   # 표 설명문 임베딩을 미리 (compare 전에)
  python -m backend.rag.search.embedders warm bge-m3-ko --docs def slot    # dense 카드 문서도 (ingestion/dense_cards.py)
  python -m backend.rag.search.embedders info                      # 모델·장치·문서 길이
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import sys
import threading

import numpy as np

HCX_MAX_CHARS = 6000          # HCX 임베딩과 같은 길이로 자른다 (core/llm.EMBED_MAX_CHARS)

LOCAL_MODELS = {
    "arctic-ko": {"model": "dragonkue/snowflake-arctic-embed-l-v2.0-ko", "query_prompt": "query", "query_prefix": "query: ",
                  "env": "EMBED_MODEL_ARCTIC_KO"},
    "bge-m3-ko": {"model": "dragonkue/BGE-m3-ko", "query_prompt": None, "query_prefix": "", "env": "EMBED_MODEL_BGE_M3_KO"},
    # feature/kos14/RAG-hybrid 의 임베딩 비교 후보 (bge-m3 한국어 미세조정, 질문·문서 그대로)
    "kure": {"model": "nlpai-lab/KURE-v1", "query_prompt": None, "query_prefix": "", "env": "EMBED_MODEL_KURE"},
}
DEFAULT_WARM = ["arctic-ko", "bge-m3-ko"]  # warm 의 기본 (kure 는 이름을 주면)
ENSEMBLES = {"ens-ko": ["arctic-ko", "bge-m3-ko"]}


def _norm(m):
    m = np.asarray(m, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)


class LocalEmbedder:
    """sentence-transformers 모델 하나. 모델은 처음 쓸 때 불러오고, 질문 임베딩은 메모리, 문서 임베딩은 파일에 캐시"""

    def __init__(self, key):
        spec = LOCAL_MODELS[key]
        self.key = key
        self.model_id = os.getenv(spec["env"]) or spec["model"]
        self.query_prompt, self.query_prefix = spec["query_prompt"], spec["query_prefix"]
        self.max_len = int(os.getenv("EMBED_MAX_LEN", "2048"))
        self.batch = int(os.getenv("EMBED_BATCH", "8"))
        self.device = os.getenv("EMBED_DEVICE") or None
        self.dtype = os.getenv("EMBED_DTYPE", "float32")
        self.id = f"st:{self.model_id}:{self.max_len}"
        self._m, self._lock, self._q = None, threading.RLock(), {}

    def model(self):
        if self._m is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RuntimeError(f"dense '{self.key}' 는 sentence-transformers 가 필요합니다: "
                                   f"pip install -r requirements-embed.txt ({e})") from e
            kw = {}
            if self.dtype != "float32":
                import torch
                kw["model_kwargs"] = {"torch_dtype": getattr(torch, self.dtype)}
            m = SentenceTransformer(self.model_id, device=self.device, **kw)
            m.max_seq_length = self.max_len
            self._m = m
        return self._m

    def _encode(self, texts, query):
        m = self.model()
        kw = {"batch_size": self.batch, "normalize_embeddings": True, "convert_to_numpy": True,
              "show_progress_bar": (not query) and len(texts) > 32}
        if query and self.query_prompt and self.query_prompt in (getattr(m, "prompts", None) or {}):
            kw["prompt_name"] = self.query_prompt
        elif query and self.query_prefix:            # 모델 설정에 prompt 가 없으면 같은 말을 직접 붙임
            texts = [self.query_prefix + t for t in texts]
        with self._lock:
            return _norm(m.encode([str(t or "")[:HCX_MAX_CHARS] for t in texts], **kw))

    def embed_queries(self, texts):
        with self._lock:                                  # compare 가 질문을 여러 스레드로 돌려도 모델은 한 번에 하나
            todo = [t for t in dict.fromkeys(texts) if t not in self._q]
            if todo:
                for t, v in zip(todo, self._encode(todo, True)):
                    self._q[t] = v
            return np.vstack([self._q[t] for t in texts])

    def embed_docs(self, texts):
        from backend.rag.search.index import CACHE_DIR
        texts = list(texts)
        h = hashlib.sha1(("\x1f".join(texts)).encode()).hexdigest()[:16]
        f = CACHE_DIR / "st_docs" / f"{hashlib.sha1(self.id.encode()).hexdigest()[:12]}_{h}.pkl"
        if f.exists():
            return pickle.loads(f.read_bytes())
        M = self._encode(texts, False)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(pickle.dumps(M))
        return M


class EnsembleEmbedder:
    """여러 임베더를 이어 붙임: [v1, v2] / √n → 내적 = 코사인 평균"""

    def __init__(self, key, members):
        self.key, self.members = key, members
        self.id = "ens:" + "+".join(m.id for m in members)

    def _join(self, mats):
        return np.hstack(mats).astype(np.float32) / np.sqrt(len(mats))

    def embed_queries(self, texts):
        return self._join([m.embed_queries(texts) for m in self.members])

    def embed_docs(self, texts):
        texts = list(texts)
        return self._join([m.embed_docs(texts) for m in self.members])


_instances: dict = {}
_inst_lock = threading.Lock()


def local_embedder(name):
    """이름 → 임베더 (같은 이름은 한 번만 만든다: 단일 모델과 앙상블이 같은 모델·캐시를 씀)"""
    with _inst_lock:
        if name not in _instances:
            if name in LOCAL_MODELS:
                _instances[name] = LocalEmbedder(name)
            elif name in ENSEMBLES:
                members = [_instances.get(k) or _instances.setdefault(k, LocalEmbedder(k)) for k in ENSEMBLES[name]]
                _instances[name] = EnsembleEmbedder(name, members)
            else:
                raise KeyError(name)
        return _instances[name]


NAMES = list(LOCAL_MODELS) + list(ENSEMBLES)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.embedders")
    ap.add_argument("cmd", choices=["warm", "info"])
    ap.add_argument("names", nargs="*", default=list(DEFAULT_WARM))
    ap.add_argument("--docs", nargs="*", default=["rule"], help="rule | def | slot | tmpl | tslot | kos14 | vals (dense 문서 묶음)")
    ap.add_argument("--cards", default=None)
    ap.add_argument("--kos14", default=None)
    a = ap.parse_args(argv)
    from backend.rag.search.index import dense_doc_views, table_corpus
    corpus = table_corpus()
    texts = [d.text for d in corpus.docs()]
    if a.cmd == "info":
        lens = sorted(len(t) for t in texts)
        print(f"표 설명문 {len(texts)}개 · 글자 수 중앙 {lens[len(lens) // 2]} · 90% {lens[int(len(lens) * .9)]} · 최대 {lens[-1]}"
              f" (HCX·로컬 모두 {HCX_MAX_CHARS}자에서 자름)")
        for n in a.names:
            e = local_embedder(n)
            for m in getattr(e, "members", [e]):
                print(f"  {n}: {m.model_id} · 최대 {m.max_len} 토큰 · 장치 {m.device or '자동'} · {m.dtype}")
        return
    import time
    views = dense_doc_views(corpus, "+".join(a.docs), a.cards, a.kos14, log=print)
    for n in a.names:
        for vname, vt in views.items():
            t = time.time()
            M = local_embedder(n).embed_docs([x for t_ in vt for x in (t_ if isinstance(t_, list) else [t_])])
            print(f"[{n}|{vname}] 표 {M.shape[0]}개 × {M.shape[1]}차원 · {time.time() - t:.0f}초")


if __name__ == "__main__":
    main()
