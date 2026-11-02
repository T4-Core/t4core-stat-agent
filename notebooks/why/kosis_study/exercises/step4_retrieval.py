"""
STEP 4 (학습용) — 검색기 3종: BM25 / Dense / Hybrid

  BM25   : 질문과 '같은 단어'가 많이 겹치는 문서를 찾음 (키워드 검색, API 필요 없음)
  Dense  : 질문과 '뜻'이 비슷한 문서를 찾음 (HCX 임베딩 벡터의 코사인 유사도)
  Hybrid : 두 결과의 '순위'를 RRF 로 합침  → 점수 = Σ 1 / (60 + 순위)

※ STEP 3 의 study_out/docs.jsonl 이 있어야 합니다.
※ Dense / Hybrid 는 .env 의 HCX_API_KEY 가 필요합니다. 키가 없으면 BM25 부터 완성하세요.

실행
  python step4_retrieval.py "서울 주택 수"                 # 3가지 방식 결과 비교
  python step4_retrieval.py "서울 주택 수" --mode bm25     # 하나만
처음 Dense 를 쓸 때 문서 전체를 임베딩하고 study_out/doc_vectors.npy 에 저장합니다 (다음부터는 재사용).
막히면: ../solutions/step4_retrieval.py
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Plus   # BM25Okapi 는 모든 문서에 나오는 단어(예: '주택')의 점수를 0 이하로 만들어
                                 # 문서가 적을 때 결과가 비는 경우가 있어, 항상 양수 가중치를 주는 BM25Plus 를 씁니다

import hcx_client

OUT_DIR = Path("study_out")
DOCS_PATH = OUT_DIR / "docs.jsonl"
VEC_PATH = OUT_DIR / "doc_vectors.npy"
VEC_IDS_PATH = OUT_DIR / "doc_vectors_ids.json"
RRF_K = 60


def load_docs(path=DOCS_PATH):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


# ─────────────── 4-1. 토큰화 (BM25 용) ───────────────
_kiwi = None


def tokenize(text):
    """'서울의 주택수는?' → ['서울', '주택', '수']  (조사·어미 제거)
    kiwipiepy 가 없으면 한글/영문/숫자 덩어리로만 자름"""
    global _kiwi
    try:
        if _kiwi is None:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        # TODO(4-1): Kiwi 로 형태소 분석 후, 품사(tag)가 명사(NN*)·외국어(SL)·숫자(SN)·어근(XR)인 것의 form 만 반환
        # 힌트: _kiwi.tokenize(text) 는 토큰 리스트. 각 토큰 t 에 t.form(글자), t.tag(품사)
        #       t.tag.startswith(("NN", "SL", "SN", "XR"))
        raise NotImplementedError("TODO 4-1")
    except ImportError:
        return re.findall(r"[가-힣A-Za-z0-9]+", str(text))


# ─────────────── 4-2. BM25 ───────────────
class BM25Retriever:
    def __init__(self, docs):
        # TODO(4-2a): 모든 문서의 text 를 토큰화한 '리스트의 리스트'로 BM25Plus 를 만드세요.
        # 힌트: BM25Plus([tokenize(d["text"]) for d in docs])
        raise NotImplementedError("TODO 4-2a")

    def search(self, query, k=5):
        """반환: [(문서 번호, 점수), ...] 점수 높은 순 k개 (점수 0 은 제외)"""
        # TODO(4-2b): 질문을 토큰화해 점수를 구하고, 점수가 큰 순서로 k 개를 반환하세요.
        # 힌트: scores = self.bm25.get_scores(tokenize(query))   → 문서 수만큼의 numpy 배열
        #       top = np.argsort(-scores)[:k]                      → 큰 순서의 '번호'
        raise NotImplementedError("TODO 4-2b")


# ─────────────── 4-3. Dense (HCX 임베딩) ───────────────
def normalize(v):
    """벡터 길이를 1로 맞춤 → 내적 = 코사인 유사도 (완성되어 있음)"""
    v = np.asarray(v, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


class DenseRetriever:
    def __init__(self, docs):
        self.vecs = self._load_or_embed(docs)

    @staticmethod
    def _load_or_embed(docs):
        ids = [d["id"] for d in docs]
        if VEC_PATH.exists() and VEC_IDS_PATH.exists() and json.loads(VEC_IDS_PATH.read_text()) == ids:
            return np.load(VEC_PATH)                          # 문서가 그대로면 저장된 벡터 재사용
        print(f"문서 {len(docs)}개 임베딩 중 (HCX) ...")
        vecs = []
        for n, d in enumerate(docs, 1):
            # TODO(4-3a): 문서 text(앞 2000자)를 hcx_client.embed 로 벡터로 바꿔 vecs 에 추가
            raise NotImplementedError("TODO 4-3a")
            if n % 10 == 0:
                print(f"  {n}/{len(docs)}")
        vecs = normalize(np.array(vecs))
        OUT_DIR.mkdir(exist_ok=True)
        np.save(VEC_PATH, vecs)
        VEC_IDS_PATH.write_text(json.dumps(ids))
        return vecs

    def search(self, query, k=5):
        # TODO(4-3b): 질문 벡터를 만들어(정규화 포함) 모든 문서와의 유사도를 구하고, 큰 순 k 개 반환
        # 힌트: q = normalize(hcx_client.embed(query))
        #       sims = self.vecs @ q          ← 행렬곱 한 번으로 문서 전체와의 유사도
        raise NotImplementedError("TODO 4-3b")


# ─────────────── 4-4. Hybrid (RRF) ───────────────
def rrf(result_lists, k=5):
    """여러 검색 결과를 '순위'로 합치기. 점수 = Σ 1 / (RRF_K + 순위 + 1)   (순위는 0부터)
    BM25 점수(예: 7.3)와 코사인 유사도(예: 0.62)는 크기가 달라 직접 더할 수 없어서 순위를 씁니다."""
    scores = {}
    for results in result_lists:
        for rank, (i, _) in enumerate(results):
            # TODO(4-4): 문서 i 의 점수에 1 / (RRF_K + rank + 1) 을 더하세요.
            raise NotImplementedError("TODO 4-4")
    return sorted(scores.items(), key=lambda x: -x[1])[:k]


class Searcher:
    """mode 하나로 세 가지 검색을 골라 쓰는 창구. Dense 는 필요할 때만 준비(API 호출)합니다. (완성되어 있음)"""

    def __init__(self, docs=None):
        self.docs = docs or load_docs()
        self.bm25 = BM25Retriever(self.docs)
        self._dense = None

    @property
    def dense(self):
        if self._dense is None:
            self._dense = DenseRetriever(self.docs)
        return self._dense

    def search(self, query, mode="hybrid", k=5):
        if mode == "bm25":
            res = self.bm25.search(query, k)
        elif mode == "dense":
            res = self.dense.search(query, k)
        elif mode == "hybrid":
            res = rrf([self.bm25.search(query, k * 4), self.dense.search(query, k * 4)], k)
        else:
            raise ValueError(f"mode 는 bm25 / dense / hybrid 중 하나: {mode}")
        return [(self.docs[i], score) for i, score in res]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="지역별 주택 수")
    ap.add_argument("--mode", default="all", choices=["all", "bm25", "dense", "hybrid"])
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    searcher = Searcher()
    print(f"문서 {len(searcher.docs)}개 / 질문: {args.query}")
    modes = ["bm25", "dense", "hybrid"] if args.mode == "all" else [args.mode]
    for mode in modes:
        print(f"\n=== {mode} ===")
        try:
            for doc, score in searcher.search(args.query, mode, args.k):
                print(f"  {score:8.4f}  [{doc['doc_type']:5s}] {doc['title']}")
        except RuntimeError as e:                             # API 키 없음 등
            print(f"  (건너뜀) {e}")
    # 🤔 비교해 보기: "서울 아파트" (키워드형) vs "집이 제일 많은 동네는?" (구어체)
    #    어느 질문에서 BM25 가 강하고, 어느 질문에서 Dense 가 강한가요?


if __name__ == "__main__":
    main()
