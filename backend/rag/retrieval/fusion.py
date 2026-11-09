"""
하이브리드 검색기: BM25 + Dense → RRF 결합 (+ 연도·최신 보정)  (구 kosis_rag_qa.py Index 클래스를 그대로 옮김)

  입력 인덱스: RAG_INDEX_DIR/<variant>/{bm25.pkl, dense.npy, dense_owner.npy, meta.json}  (indexer.stage_index 가 생성)
  출력 hit   : {id, score, title, doc_type, bm25_rank, dense_rank, dense_sim}   → schemas/search.py HybridHit
"""
import json
import pickle
import re

import numpy as np

from backend.core.llm import embed_one, normalize
from backend.rag.ingestion.indexer import INDEX_DIR, load_records
from backend.rag.retrieval.lexical import tokenize

RRF_K = 60

# ─── 아래는 구 kosis_rag_qa.py 322~403행 를 그대로 옮긴 코드 ───
class Index:
    """하이브리드 검색기: BM25 + Dense → RRF, 연도·최신 보정, 표(parent) 맥락 연결"""

    def __init__(self, variant):
        d = INDEX_DIR / variant
        if not (d / "meta.json").exists():
            # [CHANGED] SystemExit → FileNotFoundError (API 서버에서 SystemExit 은 프로세스를 끝내므로). 메시지는 그대로
            raise FileNotFoundError(f"인덱스 없음: {d}  →  python -m backend.agent.light_agent index --variant {variant}")  # [CHANGED] 안내 문구: 이전 python kosis_rag_qa.py index
        self.meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.variant = variant
        recs = load_records(self.meta["records"])
        keep = {m["id"] for m in self.meta["docs"]}
        self.by_id = {r["id"]: r for r in recs if r["id"] in keep}
        self.ids = [m["id"] for m in self.meta["docs"]]
        with (d / "bm25.pkl").open("rb") as f:
            self.bm25 = pickle.load(f)
        self.dense = np.load(d / "dense.npy")
        self.owner = np.load(d / "dense_owner.npy")

    def search_bm25(self, query, k=10):
        """BM25 단독 검색 → [{id, score, title}] (점수 > 0 인 것만)"""
        bs = self.bm25.get_scores(tokenize(query))
        return [{"id": self.ids[i], "score": float(bs[i]), "title": self.by_id[self.ids[i]]["title"]}
                for i in np.argsort(-bs)[:k] if bs[i] > 0 and self.ids[i] in self.by_id]

    def search_dense(self, query, k=10, query_vec=None):
        """Dense 단독 검색 → [{id, score(코사인 유사도), title}] (multi-vector 면 레코드별 최고값)"""
        qv = query_vec if query_vec is not None else normalize(embed_one(query))
        sims = self.dense @ qv
        best = {}
        for vi in np.argsort(-sims)[: k * 20]:
            o = int(self.owner[vi])
            if o not in best:
                best[o] = float(sims[vi])
            if len(best) >= k:
                break
        return [{"id": self.ids[o], "score": s, "title": self.by_id[self.ids[o]]["title"]}
                for o, s in sorted(best.items(), key=lambda x: -x[1]) if self.ids[o] in self.by_id]

    def search(self, query, k=10, pool=50, doc_type=None, query_vec=None):
        # 1) BM25
        bs = self.bm25.get_scores(tokenize(query))
        bm_rank = {int(i): r for r, i in enumerate(np.argsort(-bs)[:pool]) if bs[i] > 0}
        # 2) Dense (multi-vector 면 레코드별 최고 점수)
        qv = query_vec if query_vec is not None else normalize(embed_one(query))
        sims = self.dense @ qv
        best = {}
        for vi in np.argsort(-sims)[: pool * 4]:
            o = int(self.owner[vi])
            if o not in best:
                best[o] = float(sims[vi])
            if len(best) >= pool:
                break
        de_rank = {o: r for r, o in enumerate(sorted(best, key=lambda x: -best[x]))}
        # 3) RRF 결합
        cand = set(bm_rank) | set(de_rank)
        years = [int(y) for y in re.findall(r"(19\d{2}|20\d{2})", query)]
        wants_latest = bool(re.search(r"최근|최신|요즘|현재|올해|작년", query))
        scored = []
        for i in cand:
            rec = self.by_id.get(self.ids[i])
            if rec is None or (doc_type and rec.get("doc_type") != doc_type):
                continue
            s = sum(1 / (RRF_K + r + 1) for r in (bm_rank.get(i), de_rank.get(i)) if r is not None)
            f = rec.get("filters", {})
            try:                                       # 질문의 연도가 수록 범위 안이면 가산
                lo, hi = int(str(f.get("prd_from"))[:4]), int(str(f.get("prd_to"))[:4])
                if years and any(lo <= y <= hi for y in years):
                    s += 0.004
            except (TypeError, ValueError):
                pass
            if wants_latest and f.get("is_latest"):
                s += 0.002
            scored.append((s, i))
        scored.sort(reverse=True)
        hits = []
        for s, i in scored[:k]:
            rec = self.by_id[self.ids[i]]
            hits.append({"id": rec["id"], "score": round(s, 5), "title": rec["title"],
                         "doc_type": rec.get("doc_type"), "bm25_rank": bm_rank.get(i), "dense_rank": de_rank.get(i),
                         "dense_sim": round(best.get(i, float("nan")), 4)})
        return hits



# ─── [NEW v4] 여러 검색기 결과 합치기 (retrieval/pipeline.py 가 씀. 위 Index 클래스는 그대로) ───
def fuse_rrf(ranked: dict, k=RRF_K, weights=None):
    """ranked = {검색기 이름: [(문서 번호, 점수), …] (순위 순)} → [(문서 번호, RRF 점수)] (높은 순)
    점수 = Σ weight / (k + 순위)   (순위는 1부터)"""
    weights = weights or {}
    acc = {}
    for name, hits in ranked.items():
        w = float(weights.get(name, 1.0))
        for r, (i, _) in enumerate(hits, 1):
            acc[i] = acc.get(i, 0.0) + w / (k + r)
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))


def fuse_weighted(ranked: dict, weights=None, norm="minmax"):
    """점수 가중합. norm: minmax(검색기마다 0~1) | zscore | none. 한 검색기 후보에 없는 문서는 그 검색기 0점"""
    weights = weights or {}
    acc = {}
    for name, hits in ranked.items():
        if not hits:
            continue
        s = np.array([x[1] for x in hits], dtype=float)
        if norm == "minmax":
            s = (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else np.ones_like(s)
        elif norm == "zscore":
            s = (s - s.mean()) / (s.std() or 1.0)
        w = float(weights.get(name, 1.0))
        for (i, _), v in zip(hits, s):
            acc[i] = acc.get(i, 0.0) + w * float(v)
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))
