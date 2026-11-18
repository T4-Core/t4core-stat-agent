"""
카드용 검색 진입점 — 세 방법을 같은 모양으로 부른다

  baseline           configs/retrieval/baseline.yaml (기존 그대로: 표 설명문 · meta_profiles)
  table_card         table_card_search/configs/table_card.yaml
  table_card_expend  table_card_search/configs/table_card_expend.yaml
  세 방법 모두 같은 단계: BM25(kiwi) 50 → 조건 확인 → 상위 top_k → dense 재정렬 (cost, -dense)

  dense = hcx  (기본, HCX bge-m3 — 기존과 같음) | hash (글자 2-gram 해시, 오프라인 확인용) | none (조건 확인까지만)

코드에서
  from table_card_search.search import get_pipeline_for, search_fn
  p = get_pipeline_for("table_card_expend")             # RetrievalPipeline (backend.rag.retrieval.pipeline 그대로)
  p.search("1인가구 수", filters={"지역": ["서울특별시"], "시점": [2020]})
  views.run_query(bundle, search_fn=search_fn("table_card"))   # 기존 View 단계에 끼우기 (table_search.search 와 같은 모양)

CLI (저장소 루트)
  python -m table_card_search.search --method table_card_expend "2020년 서울 혼자 사는 가구 수"
  python -m table_card_search.search --method all --dense none "시군구별 고령자 인구"
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import table_card_search  # noqa: F401  (카드 부품 등록)

PACKAGE = Path(__file__).resolve().parent
CONFIGS = {"baseline": "baseline", "table_card": str(PACKAGE / "configs" / "table_card.yaml"),
           "table_card_expend": str(PACKAGE / "configs" / "table_card_expend.yaml")}
METHODS = tuple(CONFIGS)
EMBEDDERS = {"hcx": {"type": "hcx_bge_m3"}, "hash": {"type": "hash"},
             # [NEW 11-17] 로컬 임베딩 모델 (sentence-transformers, CPU) — 하이브리드에서 모델만 바꿔 비교
             "bgem3": {"type": "sentence_transformers", "model": "BAAI/bge-m3", "max_seq_length": 512, "batch_size": 8},
             "kure": {"type": "sentence_transformers", "model": "nlpai-lab/KURE-v1", "max_seq_length": 512, "batch_size": 8},
             "bgeko": {"type": "sentence_transformers", "model": "dragonkue/BGE-m3-ko", "max_seq_length": 512,
                       "batch_size": 8}}


def hybrid_methods():
    """[NEW 11-17] configs/hybrid.yaml 의 하이브리드 구성 이름들"""
    from table_card_search.hybrid import variant_names
    return variant_names()


def method_config(method, dense="hcx", set_name="full", dirs=None, top_k=None):
    """방법 이름 → 펼친 구성 dict. dense 만 바꾸고 나머지 단계는 YAML 그대로"""
    from backend.rag.retrieval.factory import load_config
    if method not in CONFIGS:
        raise ValueError(f"method 는 {METHODS}: {method}")
    cfg = copy.deepcopy(load_config(CONFIGS[method]))
    card = method != "baseline"
    cond, emb = (cfg["rerank"][0], cfg["rerank"][1]) if len(cfg["rerank"]) >= 2 else (cfg["rerank"][0], None)
    if dense == "none":
        cfg["rerank"] = [cond]
    else:
        if dense not in EMBEDDERS:
            raise ValueError(f"dense 는 hcx | hash | none: {dense}")
        emb = dict(emb or {"type": "card_embed" if card else "embed", "respect_cost": True})
        emb["embedder"] = dict(EMBEDDERS[dense])
        cfg["rerank"] = [cond, emb]
    if card:
        cfg["corpus"] = {**cfg["corpus"], "set_name": set_name, **({"dirs": dirs} if dirs else {})}
    if top_k:
        cfg["top_k"] = int(top_k)
    cfg["name"] = f"{method}[{dense}]"
    return cfg


def get_pipeline_for(method, dense="hcx", set_name="full", dirs=None, top_k=None):
    from backend.rag.retrieval.factory import get_pipeline
    if method in hybrid_methods():                       # [NEW 11-17] 하이브리드 (조건표 거르기 → BM25+dense → RRF)
        from table_card_search.hybrid import get_hybrid
        if dense != "none" and dense not in EMBEDDERS:
            raise ValueError(f"dense 는 {tuple(EMBEDDERS)} | none: {dense}")
        return get_hybrid(method, None if dense == "none" else dict(EMBEDDERS[dense]), set_name, dirs, top_k,
                          dense_name=dense)
    return get_pipeline(method_config(method, dense, set_name, dirs, top_k))


def search_fn(method, dense="hcx", set_name="full", dirs=None):
    """views.run_query(search_fn=…) 에 넣는 함수 (table_search.search(query, top_k, filters) 와 같은 모양)"""
    p = get_pipeline_for(method, dense, set_name, dirs)
    return lambda query, top_k=10, filters=None, pool=None: p.search_compat(query, top_k, filters=filters)


def clarification_bundle(a, question):
    """[NEW 11-17] 되묻기(needs_clarification) 분석 결과 → 검색용 view_bundle.
    분석기는 필수 조건(주로 시점)이 비면 되묻기로 멈추지만, 그때도 지역·지표·대상은 이미 뽑아 둠.
    그 단서로 ok 일 때와 같은 방법(canonical_slots → to_view_bundle → v3_text)으로 검색 문장·조건을 만듦.
    빠진 조건은 비워 둔 채 검색 (backend 분석기는 바꾸지 않음)"""
    from backend.rag.query_analyzer.adapter import to_view_bundle
    from backend.rag.query_analyzer.query_bundle import slot_text
    from backend.rag.query_analyzer.v4.decompose import concepts
    from backend.rag.query_analyzer.v4.pipeline import canonical_slots
    from backend.rag.query_analyzer.v4.search_text import v3_text
    state, grounded = a.get("state") or {}, a.get("slots") or {}
    raw = state.get("raw_slots") or {}
    if not raw:
        return None
    b = state.get("bundle") or {}
    rb = {"original": question, "rewritten": b.get("rewritten") or question,
          "intent": (state.get("intents") or [b.get("intent")])[0], "filters": canonical_slots(raw, grounded),
          "sub_questions": [], "sub_filters": None}
    vb, _ = to_view_bundle(rb, None, "rewritten", None)
    weak = (rb["rewritten"] or "").strip() == question.strip()
    no_intent = {k: v for k, v in (vb.get("filters") or {}).items() if k != "의도"}
    vb["search_text"] = v3_text(slot_text(no_intent) if weak else rb["rewritten"], vb.get("filters"),
                                [c["name"] for c in concepts(grounded)])
    return vb


def analyze_units(question, mode="v4", today=None):
    """질문 → 검색 단위 [{unit, text, search_query, filters}] (기존 lab 과 같은 처리: v4 분석 → views.units_of → search_query)
    mode = v4 | v4c ([NEW 11-17] v4 + 되묻기 상태에서도 이미 뽑은 조건으로 검색) | none"""
    if mode == "none":
        return [{"unit": "main", "text": question, "search_query": question, "filters": None, "status": "none"}]
    from backend.rag.query_analyzer.v4 import analyze
    from backend.rag.retrieval.lab import _units_from_bundle
    a = analyze(question, today=today)
    vb = a.get("view_bundle")
    if not vb and mode == "v4c" and a["status"] == "needs_clarification":
        vb = clarification_bundle(a, question)
    if not vb:
        return [{"unit": "main", "text": question, "search_query": question, "filters": None, "status": a["status"]}]
    units = _units_from_bundle({**vb, "_view": True}, "q", question)
    return [{"unit": u["unit"], "text": u["text"], "search_query": u["search_query"], "filters": u["filters"],
             "status": a["status"], "notes": a.get("notes", [])} for u in units]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m table_card_search.search")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--method", default="all", choices=[*METHODS, "all"])
    ap.add_argument("--dense", default="hcx", choices=["hcx", "hash", "none"])
    ap.add_argument("--set", dest="set_name", default="full", choices=["full", "sample", "both"])
    ap.add_argument("--analyze", default="v4", choices=["v4", "v4c", "none"])
    ap.add_argument("--top-k", type=int, default=10)
    a = ap.parse_args(argv)
    q = " ".join(a.question)
    units = analyze_units(q, a.analyze)
    for m in (METHODS if a.method == "all" else [a.method]):
        p = get_pipeline_for(m, a.dense, a.set_name)
        for u in units:
            r = p.search(u["search_query"], u["filters"], a.top_k)
            print(f"\n[{p.name}] 단위 {u['unit']} | 검색 문장: {u['search_query']} | 슬롯: {u['filters']}")
            for h in r["hits"]:
                miss = ", ".join(x.get("text", "") for x in h.get("unmet") or [])
                print(f"  {h['rank']:2d}. {h['tbl_id']:20s} cost={h.get('cost', '-')} dense={h.get('dense')} "
                      f"bm25#{h.get('bm25_rank')}  {h['survey_nm']} | {h['tbl_nm']}" + (f"  ⚠ {miss}" if miss else ""))


if __name__ == "__main__":
    main()
