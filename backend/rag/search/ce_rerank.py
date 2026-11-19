"""(선택) 교차 인코더 재정렬 — 합친 순위의 상위 top_n 표를 [질문, 표 글] 쌍으로 다시 채점한다

왜     정답이 이미 상위 10 안인데 1위가 아닌 실패가 대부분 (hard 합성 셋 66개 중 60개, 골든 37개 중 28개).
       채널 점수 합은 '이름이 비슷한 표' 사이를 가르지 못한다. 교차 인코더는 질문과 표 글을 한꺼번에 읽어 고른다.
       LLM 재정렬(llm_rerank.py)보다 빠르고(로컬 GPU 로 질문당 수십 ms, CPU 로 1~2초) 비용이 없다.
모델   bge-reranker-ko = dragonkue/bge-reranker-v2-m3-ko (한국어 미세조정) · bge-reranker = BAAI/bge-reranker-v2-m3
       · 폴더 경로 = 우리 데이터로 미세조정한 모델 (tuning/ce_train.py — 학습 때의 max_length 를 따름)
       (sentence-transformers CrossEncoder. 첫 실행 때 내려받음. 장치는 EMBED_DEVICE 또는 자동)
표 글  struct     제목 · 조사 · 항목 · 분류(값 몇 개) · 지역 수준 · 연도 범위 · 주기   (표 단면에서 그때 조립)
       struct+def 위 + dense 카드의 '구분'과 정의문 (ingestion/dense_cards.py — 카드가 없는 표는 struct 만)
합치기 replace  교차 인코더 점수 순서로 바꿈
       blend    순위 융합: w_ce/(k+교차 인코더 순위) + w_base/(k+원래 순위). 원래 순위에 든 구조 계수(연도·지역 수준)를
                버리지 않으면서 교차 인코더가 고른 표를 올림 (기본)
뒤처리 형제 무리 안의 선택은 engine 이 형제 규칙으로 한 번 더 (LLM 재정렬과 같음). 분모 단위는 건드리지 않음 (skip_roles)

설정 (configs/search.yaml)
  ce_rerank: {enabled: true, model: bge-reranker-ko, top_n: 20, mode: blend, k: 5, weight: 1.0, base_weight: 1.0,
              doc: struct+def, max_length: 512, batch: 16}
비교
  python -m backend.rag.search.tuning.compare --from-run docs_hard --dense bge-m3-ko --dense-docs "rule,def" --ce
"""
from __future__ import annotations

import os
import threading

MODELS = {"bge-reranker-ko": "dragonkue/bge-reranker-v2-m3-ko", "bge-reranker": "BAAI/bge-reranker-v2-m3"}
DEFAULT = {"enabled": False, "model": "bge-reranker-ko", "top_n": 20, "mode": "blend", "k": 5, "weight": 1.0,
           "base_weight": 1.0, "doc": "struct+def", "max_length": 512, "batch": 16, "skip_roles": ["분모"]}
_models, _mlock = {}, threading.Lock()
_cache, _clock = {}, threading.Lock()


def model_id(name):
    return os.getenv("CE_MODEL") or MODELS.get(name, name)


def load(name, max_length=512):
    """CrossEncoder 를 한 번만 올림 (스레드 안전)"""
    mid = model_id(name)
    with _mlock:
        m = _models.get((mid, max_length))
        if m is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise RuntimeError(f"교차 인코더 재정렬은 sentence-transformers 가 필요합니다: "
                                   f"pip install -r requirements-embed.txt ({e})") from e
            m = CrossEncoder(mid, max_length=max_length, device=os.getenv("EMBED_DEVICE") or None)
            _models[(mid, max_length)] = m
        return m


def struct_text(f):
    """표 단면 → 재정렬용 표 글 (llm_rerank.card 와 같은 재료, 번호·주의 없이)"""
    dims = []
    for obj, _, names in f.dims[:6]:
        dims.append(f"{obj}({', '.join(str(x) for x in names[:8])}{' 등' if len(names) > 8 else ''})")
    geo = "·".join(g for g in ("시도", "시군구", "읍면동", "동읍면부") if g in f.geo) or "전국"
    if f.years:
        ys = sorted(f.years)
        years = f"{ys[0]}~{ys[-1]}"
    else:
        years = ", ".join(f"{a}~{b}" for a, b in f.spans) or "-"
    cyc = {"Y": "연", "H": "반기", "Q": "분기", "M": "월"}
    return (f"{f.tbl_nm} | 조사: {f.survey_nm} | 항목: {', '.join(f.items[:15])}{' 등' if len(f.items) > 15 else ''}"
            f" | 분류: {' / '.join(dims) or '없음'} | 지역: {geo} | 연도: {years}"
            f" | 주기: {'·'.join(cyc.get(c, c) for c in sorted(f.cycles)) or '-'}")


def doc_text(f, card=None, doc="struct+def"):
    s = struct_text(f)
    if doc == "struct+def" and card and card.get("def_text"):
        lines = str(card["def_text"]).split("\n")[1:]          # 첫 줄(조사 | 제목)은 struct 에 이미 있음
        extra = " ".join(x.strip() for x in lines if x.strip())
        if extra:
            s = f"{s}\n{extra}"
    return s


def trained_max_length(name):
    """미세조정한 모델 폴더(tuning/ce_train.py)면 학습 때의 max_length (같은 길이로 읽어야 학습한 대로 채점)"""
    try:
        from pathlib import Path
        f = Path(model_id(name)) / "train_meta.json"
        if f.exists():
            import json
            return int(json.loads(f.read_text(encoding="utf-8"))["cfg"]["max_length"])
    except Exception:  # noqa: BLE001, S110
        pass
    return None


def scores(query, texts, cfg, keys=None):
    """[(질문, 글)] → 점수 목록 (클수록 맞음). keys 가 있으면 (모델, 질문, 키) 로 캐시"""
    name = cfg.get("model", DEFAULT["model"])
    ml = trained_max_length(name) or int(cfg.get("max_length", 512))
    out, todo = [None] * len(texts), []
    for i, t in enumerate(texts):
        k = (model_id(name), query, keys[i] if keys else t)
        with _clock:
            v = _cache.get(k)
        if v is None:
            todo.append(i)
        else:
            out[i] = v
    if todo:
        m = load(name, ml)
        got = m.predict([(query, texts[i]) for i in todo], batch_size=int(cfg.get("batch", 16)), show_progress_bar=False)
        with _clock:
            if len(_cache) > 200_000:
                _cache.clear()
            for i, v in zip(todo, got):
                out[i] = float(v)
                _cache[(model_id(name), query, keys[i] if keys else texts[i])] = float(v)
    return out


def rerank(query, hits, facets, cfg, cards=None, score_fn=None):
    """→ (다시 줄 세운 hits, 메모). 상위 top_n 만 바꾸고 나머지는 뒤에 그대로. 실패하면 hits 그대로
    score_fn(query, texts, keys) 를 주면 모델 대신 씀 (테스트)"""
    cfg = {**DEFAULT, **(cfg or {})}
    top_n = int(cfg["top_n"])
    head, tail = hits[:top_n], hits[top_n:]
    if len(head) < 2:
        return hits, None
    doc = cfg.get("doc", "struct+def")
    texts = [doc_text(facets[h["tbl_id"]], (cards or {}).get(h["tbl_id"]), doc) for h in head]
    keys = [f"{h['tbl_id']}|{doc}" for h in head]
    try:
        sc = (score_fn or (lambda q, t, k: scores(q, t, cfg, k)))(query, texts, keys)
    except Exception as e:  # noqa: BLE001  (재정렬은 보조 단계 — 실패해도 검색 결과는 그대로)
        return hits, f"실패: {e.__class__.__name__}: {str(e)[:100]}"
    ce_rank = {i: r for r, i in enumerate(sorted(range(len(head)), key=lambda i: -sc[i]), 1)}
    if cfg.get("mode") == "replace":
        order = sorted(range(len(head)), key=lambda i: ce_rank[i])
    else:
        k, w, wb = float(cfg["k"]), float(cfg["weight"]), float(cfg["base_weight"])
        val = {i: w / (k + ce_rank[i]) + wb / (k + i + 1) for i in range(len(head))}
        order = sorted(range(len(head)), key=lambda i: (-val[i], i))
    out = []
    for r, i in enumerate(order, 1):
        h = dict(head[i])
        h["stages"] = {**h.get("stages", {}), "ce": {"rank": ce_rank[i], "score": round(sc[i], 4)},
                       "fused": {"rank": h["rank"], "score": h["score"]}}
        h["rank"] = r
        out.append(h)
    return out + [dict(h, rank=len(out) + j) for j, h in enumerate(tail, 1)], f"ce:{cfg.get('mode')}"
