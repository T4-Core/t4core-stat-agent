"""[NEW v4] 검색 파이프라인 — 구성 하나 = 1단계 검색기(들) → (합치기) → 재정렬 체인

  p = get_pipeline("baseline")
  r = p.search("인구 수", filters={"지역": ["대전광역시"], "시점": [2025]})
  r["hits"]      → [{rank, tbl_id, tbl_nm, survey_nm, score, bm25_rank, bm25, dense, unmet, cover, cost, stages}, …]
  r["trace"]     → 단계별 params·출력 요약·초 (core/tracking.StepTrace)
  p.search_compat(q, top_k, filters=f)   → table_search.search 와 같은 모양 (views.run_query 에 끼울 수 있음)

hits[].stages[단계 이름] = {rank, score} — 단계마다 순위가 어떻게 바뀌었는지 사람이 비교할 수 있게
"""
from __future__ import annotations

import time

from backend.core.tracking import maybe_step
from backend.rag.retrieval.fusion import fuse_rrf, fuse_weighted
from backend.rag.retrieval.interfaces import SearchContext, mark

OUT_KEYS = ("unmet", "cover", "cost")


def _top(cands, n=10):
    return [(c["tbl_id"], None if c.get("score") is None else round(float(c["score"]), 4)) for c in cands[:n]]


class RetrievalPipeline:
    def __init__(self, cfg, corpus, retrievers, ks, rerankers):
        self.cfg, self.corpus, self.retrievers, self.ks, self.rerankers = cfg, corpus, retrievers, ks, rerankers
        self.name = cfg["name"]
        docs = corpus.docs()
        self.docs, self.docs_by_id = docs, {d.id: d for d in docs}

    def info(self):
        return {"name": self.name, "config": self.cfg, "corpus": self.corpus.signature(), "n_docs": len(self.docs),
                "retrievers": {r.name: getattr(r, "fit_info", {}) for r in self.retrievers},
                "rerank": [r.name for r in self.rerankers]}

    def prep(self, query, filters):
        mode = (self.cfg.get("query") or {}).get("prep", "none")
        if mode == "resolve":
            from backend.rag.ingestion.resolve import search_query
            return search_query(query, filters or {})
        if mode != "none":
            raise ValueError(f"query.prep 는 none | resolve: {mode}")
        return query

    def _first_stage(self, q, tracer):
        ranked = {}
        for r in self.retrievers:
            with maybe_step(tracer, f"retrieve:{r.name}", k=self.ks[r.name], type=type(r).__name__) as s:
                ranked[r.name] = r.search(q, self.ks[r.name])
                s.output = {"top": [(self.docs[i].id, round(v, 4)) for i, v in ranked[r.name][:10]],
                            **({"query_tokens": r.last_query_tokens} if hasattr(r, "last_query_tokens") else {})}
        if len(ranked) == 1:
            (name, hits), = ranked.items()
            fused = hits
        else:
            fz = self.cfg.get("fusion") or {}
            t = fz.get("type", "rrf")
            with maybe_step(tracer, "fuse", **fz) as s:
                if t == "rrf":
                    fused = fuse_rrf(ranked, k=fz.get("k", 60), weights=fz.get("weights"))
                elif t == "weighted":
                    fused = fuse_weighted(ranked, weights=fz.get("weights"), norm=fz.get("norm", "minmax"))
                else:
                    raise ValueError(f"fusion.type 는 rrf | weighted (검색기 2개 이상): {t}")
                pool = fz.get("pool") or max(self.ks.values())
                fused = fused[:pool]
                s.output = {"n": len(fused), "top": [(self.docs[i].id, round(v, 5)) for i, v in fused[:10]]}
        # 후보 dict (table_search 와 같은 키 + 단계 기록)
        rank_of = {name: {i: (r, sc) for r, (i, sc) in enumerate(h, 1)} for name, h in ranked.items()}
        cands, first_bm25, first_dense = [], None, None
        for r in self.retrievers:
            if first_bm25 is None and type(r).__name__ == "BM25Retriever":
                first_bm25 = r.name
            if first_dense is None and type(r).__name__ == "DenseRetriever":
                first_dense = r.name
        for i, sc in fused:
            c = {"tbl_id": self.docs[i].id, "score": sc, "stages": {}}
            for name, ro in rank_of.items():
                if i in ro:
                    c["stages"][name] = {"rank": ro[i][0], "score": round(ro[i][1], 4)}
            if first_bm25:
                b = rank_of[first_bm25].get(i)
                c["bm25_rank"], c["bm25"] = (b[0], round(b[1], 3)) if b else (None, None)
            if first_dense:
                d = rank_of[first_dense].get(i)
                c["dense_rank"], c["dense"] = (d[0], round(d[1], 4)) if d else (None, None)
            cands.append(c)
        if len(ranked) > 1:
            mark(cands, "fuse")
        return cands

    def search(self, query, filters=None, top_k=None, tracer=None):
        t0 = time.time()
        top_k = int(top_k or self.cfg.get("top_k", 10))
        with maybe_step(tracer, "query", prep=(self.cfg.get("query") or {}).get("prep", "none")) as s:
            q = self.prep(query, filters)
            s.output = {"search_query": q}
        cands = self._first_stage(q, tracer)
        ctx = SearchContext(filters=filters, corpus=self.corpus, docs_by_id=self.docs_by_id, top_k=top_k)
        for rr in self.rerankers:
            with maybe_step(tracer, f"rerank:{rr.name}", **{k: v for k, v in vars(rr).items()
                                                            if not k.startswith("_") and k not in ("emb", "name")
                                                            and isinstance(v, (str, int, float, bool, type(None)))}) as s:
                n_in = len(cands)
                cands = rr.rerank(q, cands, ctx)
                mark(cands, rr.name)
                s.output = {"n_in": n_in, "n_out": len(cands), "top": _top(cands)}
        hits = []
        for r, c in enumerate(cands[:top_k], 1):
            d = self.docs_by_id[c["tbl_id"]]
            h = {"rank": r, "tbl_id": c["tbl_id"], "tbl_nm": d.meta.get("tbl_nm", ""), "survey_nm": d.meta.get("survey_nm", ""),
                 "score": None if c.get("score") is None else round(float(c["score"]), 4),
                 "dense": c.get("dense"), "bm25_rank": c.get("bm25_rank"), "bm25": c.get("bm25"),
                 **({k: c[k] for k in OUT_KEYS} if "unmet" in c else {}),
                 **({"ce": c["ce"]} if "ce" in c else {}), "stages": c.get("stages", {})}
            hits.append(h)
        return {"config": self.name, "query": query, "search_query": q, "filters": filters, "top_k": top_k,
                "hits": hits, "seconds": round(time.time() - t0, 3),
                "trace": tracer.as_list() if tracer is not None else []}

    def search_compat(self, query, top_k=10, filters=None, pool=None):
        """table_search.search(query, top_k, filters) 와 같은 호출·반환 모양"""
        keep = ("rank", "tbl_id", "tbl_nm", "survey_nm", "score", "dense", "bm25_rank", "bm25", *OUT_KEYS)
        return [{k: h[k] for k in keep if k in h} for h in self.search(query, filters, top_k)["hits"]]
