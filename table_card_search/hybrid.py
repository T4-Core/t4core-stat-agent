"""
[NEW 11-17] 하이브리드 카드 검색 — 조건표로 먼저 거르고, BM25 와 dense 를 '함께' 써서 찾는다

기존(순차)  BM25 50 → 조건 확인 20 → dense 재정렬      (BM25 가 놓친 표는 dense 가 볼 기회가 없음)
하이브리드   ① 조건표 거르기 (지역 맞음 + 요청 연도와 하나라도 겹침)
            ② 통과한 표 '전부' 를 BM25 · dense 가 각각 줄 세움 → RRF 로 합침
            ③ 정렬: 관련도(RRF) 우선, 조건 불일치는 감점, 기간을 덜 담은 표는 작은 감점
            ④ 결과마다 '있는 연도 / 없는 연도' 를 붙임 (일부 기간만 있는 표도 버리지 않고 안내할 수 있게)

읽는 데이터는 table_card_expend 카드 그대로 (bm25_text · dense_text · conditions 의 프로필).
조건 계산은 기존 함수(resolve.unmet · period_cover) 를 그대로 쓴다. backend 파일은 건드리지 않는다.

구성(variant)은 configs/hybrid.yaml — 실험용 스위치
  lists      RRF 에 넣을 순위 목록. '<검색기>:<질의>'  검색기 = bm25 | dense, 질의 = sq(분석된 검색 문장) | orig(원래 질문)
  prefilter  true | false (거르기 끄기 = 비교용)
  rank       soft(관련도 우선 + 감점) | cost_first(예전처럼 벌점이 1순위) | none(RRF 그대로)

  기본 구성 = hybrid_all (세 채점셋 모두에서 가장 좋았음, 11-17)

  from table_card_search.hybrid import get_hybrid
  p = get_hybrid(embedder={"type": "hcx_bge_m3"}, dense_name="hcx")      # 구성 생략 = hybrid_all
  p.search("1인가구 수", {"지역": ["서울특별시"], "시점": [2010, 2015, 2020]}, original="2010년부터 서울 혼자 사는 가구 수")
"""
from __future__ import annotations

import copy
import pickle
import time
from pathlib import Path

import numpy as np
import yaml

PACKAGE = Path(__file__).resolve().parent
CONFIG = PACKAGE / "configs" / "hybrid.yaml"
DEFAULT_VARIANT = "hybrid_all"     # [NEW 11-17] 기본으로 쓰는 구성 (BM25·dense × 분석 문장·원래 질문 4개 순위를 합침)
DEFAULT = {"lists": ["bm25:sq", "dense:sq"], "weights": {}, "rrf_k": 60, "pool": 100, "prefilter": True,
           "min_pass": 20, "rank": "soft", "alpha": 0.5, "beta": 0.3, "top_k": 10,
           "tokenizer": {"type": "kiwi", "variant": "table"}}


def load_variants():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    base = {**DEFAULT, **(data.get("defaults") or {})}
    return {name: {**copy.deepcopy(base), **(v or {})} for name, v in (data.get("variants") or {}).items()}


def variant_names():
    return tuple(load_variants())


class CardDenseRetriever:
    """카드 dense_text 전체를 한 번 임베딩해 두고(디스크 캐시) 코사인 점수를 냄"""

    def __init__(self, embedder, name="dense"):
        self.name, self.emb, self.fit_info = name, embedder, {}

    def fit(self, corpus):
        from backend.rag.retrieval.retrievers import _cache_file
        docs = corpus.docs()
        f = _cache_file("dense", corpus.signature(), self.emb.id, getattr(self.emb, "doc_prefix", ""), "dense_text")
        if f.exists():
            self.M = pickle.loads(f.read_bytes())
            self.fit_info["vectors"] = "disk cache"
        else:
            t0 = time.time()
            self.M = self.emb.embed_docs([d.meta.get("dense_text") or d.text for d in docs])
            self.fit_info.update(vectors="computed", embed_seconds=round(time.time() - t0, 1))
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(self.M))
        self.fit_info["n_docs"] = len(docs)
        return self

    def scores(self, query):
        return self.M @ self.emb.embed_queries([query])[0]

    def search(self, query, k):
        s = self.scores(query)
        return [(int(i), float(s[i])) for i in np.argsort(-s)[:k]]


def _years_of(profile):
    return [(x["year_from"], x["year_to"]) for x in (profile or {}).get("periods") or [] if x.get("year_to")]


def period_split(profile, want):
    """요청 연도 → (표에 있는 연도, 없는 연도). 표에 기간 정보가 없으면 (None, None)"""
    spans = _years_of(profile)
    if not want or not spans:
        return None, None
    have = [y for y in want if any(a <= y <= b for a, b in spans)]
    return have, [y for y in want if y not in have]


class HybridCardPipeline:
    wants_original = True          # compare 가 원래 질문을 함께 넘겨 줌

    def __init__(self, cfg, corpus, bm25, dense):
        self.cfg, self.corpus, self.bm25, self.dense = cfg, corpus, bm25, dense
        self.name = cfg["name"]
        self.docs = corpus.docs()
        self.docs_by_id = {d.id: d for d in self.docs}
        self.retrievers = [r for r in (bm25, dense) if r is not None]
        self.rerankers = []
        self.lists = [x for x in cfg["lists"] if dense is not None or not x.startswith("dense")]
        self._spans = [_years_of(d.meta.get("profile")) for d in self.docs]
        self._region_cache = {}

    # ── ① 조건표 거르기 ──────────────────────────────────────────
    def _region_mask(self, regions):
        key = tuple(sorted(regions))
        if key not in self._region_cache:
            from backend.rag.ingestion.resolve import all_names, region_ok, sido_names
            m = np.zeros(len(self.docs), dtype=bool)
            for i, d in enumerate(self.docs):
                p = d.meta.get("profile")
                if not p:
                    continue
                names, sidos = all_names(p), sido_names(p)
                m[i] = all(region_ok(p, r, names, sidos) for r in key)
            self._region_cache[key] = m
        return self._region_cache[key]

    def _period_mask(self, want):
        w = list(want)
        return np.array([(not sp) or any(a <= y <= b for y in w for a, b in sp) for sp in self._spans], dtype=bool)

    def prefilter(self, filters):
        """→ (통과 여부 배열, 기록). 지역 = 요청 지역이 모두 있음, 시점 = 요청 연도와 하나라도 겹침.
        너무 적게 남으면 단계적으로 풂: 지역+시점 → 시점만 → 전부"""
        n = len(self.docs)
        info = {"mode": "off", "n_pass": n, "no_period_data": False}
        if not self.cfg["prefilter"] or not filters:
            return np.ones(n, dtype=bool), info
        regions = [r for r in (filters.get("지역") or []) if r != "전국"]
        want = [y for y in (filters.get("시점") or []) if isinstance(y, int)]
        pm = self._period_mask(want) if want else np.ones(n, dtype=bool)
        rm = self._region_mask(regions) if regions else np.ones(n, dtype=bool)
        info["no_period_data"] = bool(want) and not pm.any()
        for mode, m in (("region+period", pm & rm), ("period", pm)):
            if m.sum() >= self.cfg["min_pass"]:
                return m, {**info, "mode": mode, "n_pass": int(m.sum())}
        return np.ones(n, dtype=bool), {**info, "mode": "relaxed_all"}

    def passes(self, filters):
        """거르기를 통과한 표 id 집합 (채점용)"""
        m, info = self.prefilter(filters)
        return {self.docs[i].id for i in np.flatnonzero(m)}, info

    # ── ② 검색기별 순위 → RRF ────────────────────────────────────
    def _ranked(self, spec, queries, mask):
        kind, qk = spec.split(":")
        q = queries[qk]
        if kind == "bm25":
            toks = self.bm25.tok(q)
            s = np.asarray(self.bm25.bm25.get_scores(toks)) if toks else np.zeros(len(self.docs))
            ok = mask & (s > 0)                         # 한 단어도 안 겹친 표는 BM25 순위에 넣지 않음
        else:
            s = self.dense.scores(q)
            ok = mask
        idx = np.flatnonzero(ok)
        order = idx[np.argsort(-s[idx], kind="stable")][: self.cfg["pool"]]
        return [(int(i), float(s[i])) for i in order]

    def search(self, query, filters=None, top_k=None, tracer=None, original=None):
        from backend.rag.ingestion.resolve import cost, period_cover, search_query, unmet
        from backend.rag.retrieval.fusion import fuse_rrf
        t0 = time.time()
        cfg = self.cfg
        top_k = int(top_k or cfg["top_k"])
        # 원래 질문은 연도·지역 단어만 빼고 그대로 (분석이 바꿔 쓴 단어 대신 사용자가 쓴 단어를 살림)
        orig = search_query(original, {"지역": (filters or {}).get("지역")}) if original else query
        queries = {"sq": query, "orig": orig}
        mask, pre = self.prefilter(filters)
        ranked = {spec: self._ranked(spec, queries, mask) for spec in self.lists}
        fused = fuse_rrf(ranked, k=cfg["rrf_k"], weights=cfg.get("weights"))[: cfg["pool"]]
        rank_of = {spec: {i: (r, sc) for r, (i, sc) in enumerate(h, 1)} for spec, h in ranked.items()}
        want = [y for y in ((filters or {}).get("시점") or []) if isinstance(y, int)]
        cands = []
        for i, sc in fused:
            d = self.docs[i]
            p = d.meta.get("profile")
            c = {"tbl_id": d.id, "rrf": sc, "stages": {s: {"rank": ro[i][0], "score": round(ro[i][1], 4)}
                                                       for s, ro in rank_of.items() if i in ro}}
            if filters is not None and p:
                c["unmet"] = unmet(p, filters)
                c["cover"] = round(period_cover(p, filters), 2)
                c["cost"] = round(cost(c["unmet"], c["cover"]), 3)
                n_other = sum(not (u["slot"] == "시점" and isinstance(u["requested"], list)) for u in c["unmet"])
            else:
                c["unmet"], c["cover"], c["cost"], n_other = [], 1.0, 0.0, 0
            # ③ 관련도 우선: 조건 불일치 하나마다 1/(1+alpha) 배, 기간을 못 담은 만큼 beta 비율로 감점
            c["score"] = sc / (1 + cfg["alpha"] * n_other) * (1 - cfg["beta"] * (1 - c["cover"]))
            c["years_have"], c["years_missing"] = period_split(p, want)
            cands.append(c)
        if cfg["rank"] == "soft":
            cands.sort(key=lambda c: -c["score"])
        elif cfg["rank"] == "cost_first":
            cands.sort(key=lambda c: (c["cost"], -c["rrf"]))
        elif cfg["rank"] != "none":
            raise ValueError(f"rank 는 soft | cost_first | none: {cfg['rank']}")
        if cfg.get("rerank_model") and cands:
            cands = self._rerank(cands, original or query, query)
        first = {"bm25": next((s for s in self.lists if s.startswith("bm25")), None),
                 "dense": next((s for s in self.lists if s.startswith("dense")), None)}
        hits = []
        for r, c in enumerate(cands[:top_k], 1):
            d = self.docs_by_id[c["tbl_id"]]
            b, dn = c["stages"].get(first["bm25"]), c["stages"].get(first["dense"])
            hits.append({"rank": r, "tbl_id": c["tbl_id"], "tbl_nm": d.meta.get("tbl_nm", ""),
                         "survey_nm": d.meta.get("survey_nm", ""), "score": round(float(c["score"]), 5),
                         "rrf": round(float(c["rrf"]), 5), "dense": dn["score"] if dn else None,
                         "dense_rank": dn["rank"] if dn else None, "bm25_rank": b["rank"] if b else None,
                         "bm25": b["score"] if b else None, "unmet": c["unmet"], "cover": c["cover"], "cost": c["cost"],
                         "years_have": c["years_have"], "years_missing": c["years_missing"], "stages": c["stages"],
                         "ce": c.get("ce")})
        if want and cfg.get("stitch", True):              # ⑥ [NEW 11-17] 기간 이어붙이기 (순위는 그대로, 정보만 붙임)
            from table_card_search.period_groups import stitch_plan
            for h in hits:
                h["stitch"] = stitch_plan(h["tbl_id"], want)
        return {"config": self.name, "query": query, "search_query": query, "queries": queries, "filters": filters,
                "top_k": top_k, "hits": hits, "prefilter": pre, "pool_ids": [c["tbl_id"] for c in cands],
                "seconds": round(time.time() - t0, 3), "trace": []}

    # ── ⑤ [NEW 11-17] 리랭커 (cross-encoder) — 상위 rerank_top 개를 (질문, 카드 설명) 쌍으로 다시 점수 ──
    def _ce_scores(self, q, ids):
        """리랭커 점수 (0~1). (질문, 표) 쌍마다 한 번만 계산해 기억 (설정 바꿔 가며 채점할 때 다시 안 돎)"""
        if not hasattr(self, "_ce"):
            from backend.rag.retrieval.rerankers import CrossEncoderReranker
            self._ce = CrossEncoderReranker(self.cfg["rerank_model"], max_length=self.cfg.get("rerank_max_length", 512),
                                            batch_size=8, device="cpu")
            self._ce_memo = {}
        todo = [t for t in ids if (q, t) not in self._ce_memo]
        if todo:
            pairs = [(q, self.docs_by_id[t].meta.get("dense_text") or self.docs_by_id[t].text) for t in todo]
            s = np.asarray(self._ce.model.predict(pairs, batch_size=8, show_progress_bar=False), dtype=float)
            s = s[:, -1] if s.ndim > 1 else s
            if s.min() < 0 or s.max() > 1:           # 로짓이면 0~1 로 (이미 확률이면 그대로)
                s = 1 / (1 + np.exp(-s))
            self._ce_memo.update({(q, t): float(v) for t, v in zip(todo, s)})
        return [self._ce_memo[(q, t)] for t in ids]

    def _rerank(self, cands, original, sq):
        """rerank_mode  ce  = 리랭커 점수 × 조건 감점(soft 와 같은 비율)
                        rrf = 지금 순서와 리랭커 순서를 RRF 로 섞음 (리랭커 가중치 rerank_weight)
        rerank_query    orig = 사용자가 쓴 질문 그대로 | sq = 분석된 검색 문장"""
        cfg = self.cfg
        n = int(cfg.get("rerank_top", 30))
        head, tail = cands[:n], cands[n:]
        q = original if cfg.get("rerank_query", "orig") == "orig" else sq
        ce = self._ce_scores(q, [c["tbl_id"] for c in head])
        for c, v in zip(head, ce):
            c["ce"] = round(v, 4)
        if cfg.get("rerank_mode", "ce") == "ce":
            for c in head:
                pen = c["score"] / c["rrf"] if c["rrf"] else 1.0
                c["score"] = c["ce"] * pen
            head.sort(key=lambda c: -c["score"])
        else:
            k, w = cfg["rrf_k"], float(cfg.get("rerank_weight", 1.0))
            ce_rank = {c["tbl_id"]: r for r, c in enumerate(sorted(head, key=lambda c: -c["ce"]), 1)}
            for r, c in enumerate(head, 1):
                c["score"] = 1 / (k + r) + w / (k + ce_rank[c["tbl_id"]])
            head.sort(key=lambda c: -c["score"])
        return head + tail

    def search_compat(self, query, top_k=10, filters=None, pool=None):
        keep = ("rank", "tbl_id", "tbl_nm", "survey_nm", "score", "dense", "bm25_rank", "bm25", "unmet", "cover", "cost",
                "years_have", "years_missing", "stitch")
        return [{k: h[k] for k in keep if k in h} for h in self.search(query, filters, top_k)["hits"]]


_pipes = {}


def get_hybrid(variant=DEFAULT_VARIANT, embedder=None, set_name="full", dirs=None, top_k=None, dense_name=""):
    """variant = configs/hybrid.yaml 의 이름, embedder = 임베더 구성 dict (None 이면 dense 없이 BM25 만)"""
    from backend.rag.retrieval import factory
    variants = load_variants()
    if variant not in variants:
        raise ValueError(f"hybrid variant 는 {tuple(variants)}: {variant}")
    cfg = variants[variant]
    cfg["name"] = f"{variant}[{dense_name or 'none'}]"
    if top_k:
        cfg["top_k"] = int(top_k)
    corpus = factory.build_corpus({"type": "table_card_expend", "set_name": set_name, **({"dirs": dirs} if dirs else {})})
    key = (factory.config_hash(cfg), corpus.signature(), factory.config_hash(embedder or {}))
    if key not in _pipes:
        bm25 = factory.build_retriever({"type": "bm25", "name": "bm25", "tokenizer": cfg["tokenizer"]}, corpus)
        dense = None
        if embedder:
            emb = factory.build_embedder(embedder)
            dense = factory._cached("retriever", {"corpus": corpus.signature(), "card_dense": embedder},
                                    lambda: CardDenseRetriever(emb).fit(corpus))
        _pipes[key] = HybridCardPipeline(cfg, corpus, bm25, dense)
    return _pipes[key]
