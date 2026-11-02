"""
하이브리드 인덱스 생성: records.jsonl → BM25(Kiwi) + Dense(HCX 임베딩)  (구 kosis_rag_qa.py index 단계를 그대로 옮김)

실행  python -m backend.agent.light_agent index --variant base            (CLI 는 예전처럼 light_agent 에 있음)
      [CHANGED] 이전: python kosis_rag_qa.py index --variant base

※ 구조안에는 indexer.py = '구 kosis_rag_builder.py' 로 되어 있었지만, kosis_rag_builder.py 는 KOSIS 수집기라
  ingestion/collector.py 로 옮기고, 실제 BM25·Dense 인덱싱 코드(kosis_rag_qa.py stage_index)를 여기 둠
"""
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.core.config import RAG_INDEX_DIR, resolve_data_path
from backend.core.llm import EMBED_MODEL, embed_many, normalize
from backend.rag.retrieval.lexical import tokenize

INDEX_DIR = RAG_INDEX_DIR   # [CHANGED] 이전: INDEX_DIR = DATA / "index"

# ─── 아래는 구 kosis_rag_qa.py 274~320행 를 그대로 옮긴 코드 ───
# 인덱스
def load_records(path):
    path = resolve_data_path(path)   # [CHANGED] 이전: 그대로 Path(path) — 폴더 이동 후 meta.json 의 예전 상대 경로도 찾도록
    return [json.loads(l) for l in Path(path).open(encoding="utf-8") if l.strip()]


def embed_texts_of(rec, mode):
    """Dense 에 넣을 텍스트. single: embed_text 1개 / multi: + 질문마다 별도 벡터(같은 레코드를 가리킴)"""
    texts = [rec["embed_text"]]
    if mode == "multi":
        texts += [q for q in (rec.get("questions") or [])[:12]] + [p for p in (rec.get("paraphrases") or [])[:5]]
    return texts


def stage_index(args):
    recs = load_records(args.records)
    if args.doc_type:
        recs = [r for r in recs if r.get("doc_type") == args.doc_type]
    if args.limit:
        recs = recs[: args.limit]
    out = INDEX_DIR / args.variant
    out.mkdir(parents=True, exist_ok=True)
    print(f"[{args.variant}] 레코드 {len(recs)}개 ← {args.records}")

    # BM25: Kiwi 형태소 + 축약형 토큰
    from rank_bm25 import BM25Okapi
    toks = [tokenize(r["bm25_text"]) for r in recs]   # 질의와 같은 규칙으로 토큰화
    bm25 = BM25Okapi(toks)
    print("  BM25 인덱스 완료")

    # Dense: HCX 임베딩
    owners, texts = [], []
    for i, r in enumerate(recs):
        for t in embed_texts_of(r, args.dense_mode):
            owners.append(i)
            texts.append(t)
    mat = normalize(embed_many(texts, workers=args.workers))
    np.save(out / "dense.npy", mat.astype(np.float32))
    np.save(out / "dense_owner.npy", np.asarray(owners, dtype=np.int32))
    with (out / "bm25.pkl").open("wb") as f:
        pickle.dump(bm25, f)
    meta = [{"id": r["id"], "doc_type": r.get("doc_type"), "parent_id": r.get("parent_id")} for r in recs]
    (out / "meta.json").write_text(json.dumps({
        "variant": args.variant, "records": str(args.records), "n": len(recs), "dense_mode": args.dense_mode,
        "embed_model": EMBED_MODEL, "dim": int(mat.shape[1]), "n_vectors": int(mat.shape[0]),
        "built": datetime.now().isoformat(timespec="seconds"), "docs": meta}, ensure_ascii=False), encoding="utf-8")
    print(f"  Dense 벡터 {mat.shape} 저장 → {out}")

