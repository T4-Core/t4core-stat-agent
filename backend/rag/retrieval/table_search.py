"""
[엔드포인트 3] search — 자연어 질의로 메타데이터(표 설명문 989개) 검색 (순차: BM25 → bge-m3 재정렬)

  1단계 BM25 : 자연어 ─ kiwi 형태소 ─▶ BM25 로 989개 표 점수 → 상위 top_k (기본 10)
  2단계 dense: 그 10개만 bge-m3(HCX) 임베딩 코사인 유사도로 다시 줄 세움 → 상위 n_views(기본 3)개로 View 생성

  [CHANGED 11-03] filters(슬롯) 를 넘기면: BM25 상위 50개 → resolve 로 조건 확인(시점·지역·성별·연령·지표)
                  → 못 맞춘 조건이 적은 10개만 dense → 최종 순서 = (cost, dense)
                  cost = 시점 외 못 맞춘 조건 수 + (1 - 요청 연도 중 담은 비율)
- 순차인 이유: 본 프로젝트에서 raw 데이터 전체로 늘어나면 dense 를 모든 표에 계산하기 느리므로, 싼 BM25 로 먼저 좁힌다
- 검색에는 자연어만 쓴다. 슬롯(지역·시점 …)은 View 를 자를 때 쓴다 (build_view)
- 표 설명문 임베딩은 캐시(embed_cache.sqlite)에 있으면 다시 호출하지 않는다

실행  API : POST /search
      CLI : python -m backend.rag.retrieval.table_search "최근 5년간 대전의 인구 변화 추이"   (저장소 루트에서)
      [CHANGED] 이전: cd view_model && ../.venv/Scripts/python.exe -m services.search "..."
(구 view_model/services/search.py — 파일 이름만 table_search.py 로 바꿈. 표 메타데이터 검색 = BM25 → bge-m3 재정렬)
"""
import json
import sys

import numpy as np
from rank_bm25 import BM25Okapi

from backend.rag.ingestion.meta_profile import load_meta_profiles
from backend.rag.ingestion.resolve import POOL, rerank
from backend.rag.ingestion.table_text import INDEX, tokenize
from backend.rag.retrieval.dense import embed_many, embed_one, normalize
# [CHANGED] 이전: from services.embedding import embed_many, embed_one, normalize
#                from services.meta_profile import load_meta_profiles
#                from services.table_text import INDEX, tokenize

_idx = {"mtime": None}


def index():
    # BM25 색인(토큰)과 표 설명문을 메모리에 올려 두고, tokens.json 이 바뀌었을 때만 다시 읽음
    p = INDEX / "tokens.json"
    if not p.exists():
        raise FileNotFoundError("표 색인이 없습니다. services.table_text 로 먼저 만드세요 (POST /api/v1/ingest/table-index/build)")  # [CHANGED] 안내 문구만: 이전 POST /search/index/build
    m = p.stat().st_mtime
    if _idx["mtime"] != m:
        ids = json.loads((INDEX / "ids.json").read_text(encoding="utf-8"))
        texts = {r["tbl_id"]: r["text"] for r in map(json.loads, (INDEX / "texts.jsonl").read_text(encoding="utf-8").splitlines())}
        prof = {p["tbl_id"]: p for p in load_meta_profiles()}
        _idx.update(mtime=m, ids=ids, texts=texts, prof=prof,
                    bm25=BM25Okapi(json.loads(p.read_text(encoding="utf-8"))))
    return _idx


def search(query, top_k=10, filters=None, pool=POOL):
    # 반환: BM25 후보를 dense 로 다시 줄 세운 목록 (rank = 재정렬 순위, bm25_rank = 1단계 순위)
    # filters(슬롯 dict) 가 있으면: BM25 상위 pool 개 → resolve 로 조건 확인 → 상위 top_k 만 dense
    #   → 최종 순서 = (cost, dense). 후보마다 unmet(못 맞춘 조건)·cover(요청 연도 중 담은 비율)·cost 를 붙임
    # filters 가 없으면 예전과 같음: BM25 상위 top_k → dense
    ix = index()
    toks = tokenize(query)
    bm = ix["bm25"].get_scores(toks) if toks else np.zeros(len(ix["ids"]))
    first = [int(i) for i in np.argsort(-bm)[:pool if filters is not None else top_k]]   # 1단계: BM25
    cands = [{"tbl_id": ix["ids"][i], "bm25_rank": r, "bm25": round(float(bm[i]), 3)} for r, i in enumerate(first, 1)]
    if filters is not None:
        cands = rerank(cands, filters)[:top_k]                        # 조건을 많이 맞춘 표부터
    vecs = normalize(embed_many([ix["texts"][c["tbl_id"]] for c in cands], progress=lambda m: None))
    dense = vecs @ normalize(embed_one(query))                        # 2단계: 그 안에서만 dense
    order = sorted(range(len(cands)), key=lambda j: (cands[j].get("cost", 0), -dense[j]))
    out = []
    for r, j in enumerate(order, 1):
        c, p = cands[j], ix["prof"][cands[j]["tbl_id"]]
        out.append({"rank": r, "tbl_id": p["tbl_id"], "tbl_nm": p["tbl_nm"], "survey_nm": p["survey_nm"],
                    "score": round(float(dense[j]), 4), "dense": round(float(dense[j]), 4),
                    "bm25_rank": c["bm25_rank"], "bm25": c["bm25"],
                    **({k: c[k] for k in ("unmet", "cover", "cost")} if "unmet" in c else {})})
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "최근 5년간 대전의 인구 변화 추이"
    print("질의:", q)
    for c in search(q):
        print(f"  {c['rank']:2d}. {c['tbl_id']:18s} dense={c['dense']:.3f} bm25#{c['bm25_rank']}  {c['survey_nm']} | {c['tbl_nm']}")


if __name__ == "__main__":
    main()
