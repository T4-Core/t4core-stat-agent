"""교차 인코더 리랭커 미세조정 — '상위 후보 중 하나 고르기'를 우리 표·우리 질문으로 배운다

왜     범용 리랭커(dragonkue/bge-reranker-v2-m3-ko)는 '주제가 비슷한가'를 본다. 우리에게 필요한 건 이름이 거의 같은 표
       (형제판·시도/시군구판·초혼/혼인·연도판) 사이에서 질문에 답하는 표를 고르는 것. 그 오답들이 바로 검색 상위 20 안에 있다
       → 정답 표 + 상위 20 안의 오답(하드 네거티브)으로 리스트 단위 학습

  1) build  이전 compare 실행(--from-run)의 골든셋·질의 분석 캐시로 검색을 다시 돌려, 질문마다 상위 top_n 후보와 정답 여부를 저장
            정답 = golden_table_ids ∪ 근거 그룹의 acceptable_table_ids ∪ 대체 정답(같은 값, --alt 가 있던 실행)
            표 글은 추론 때와 똑같이 ce_rerank.doc_text (struct+def). 본 질의(main) 단위만 — 분모 단위는 재정렬하지 않음
            → storage/runs/ce_train/<name>/groups.jsonl
  2) train  dev 문항만으로 학습 (heldout 은 고르기·확인용, 사람이 만든 골든셋은 쓰지 않음 — 최종 판단용)
            한 묶음 = 질문 1 + 정답 1 + 오답 k (상위 순위의 오답을 우선). 손실 = 묶음 안 소프트맥스 교차 엔트로피 (정답이 1등이 되게)
            에폭마다 heldout 으로 '교차 인코더만' · '원래 순위와 섞기(blend)' 의 Hit@1 을 재고 가장 좋은 에폭을 저장
            → storage/models/ce/<name>/ (허깅페이스 형식 — CrossEncoder · ce_rerank 가 그대로 읽음)
  3) eval   저장한 후보로 오프라인 채점 (검색을 다시 돌리지 않음): 원래 순위 vs 교차 인코더만 vs blend(k·weight 격자)
            dev 에서 가장 좋은 blend 값을 고르고 heldout 으로 확인 → compare 에 넣을 --ce-k · --ce-weight 를 알려 줌

  python -m backend.rag.search.tuning.ce_train build --from-run docs_hard models_easy_rule --dense bge-m3-ko --dense-docs "rule,def" --name v1
  python -m backend.rag.search.tuning.ce_train train --data v1 --name v1
  python -m backend.rag.search.tuning.ce_train eval --data v1 --model storage/models/ce/v1
  python -m backend.rag.search.tuning.compare --from-run models_golden_ruledef --dense bge-m3-ko --dense-docs "rule,def" --ce --ce-model storage/models/ce/v1 --ce-k 5 --ce-weight 2

주의  합성 셋은 LLM 이 표에서 만든 질문이라 학습한 말투에 맞춰질 수 있다 — 채택은 사람이 만든 골든셋(retrieval_golden)으로 정한다.
      문항이 적다(dev 약 250). 에폭을 적게, 학습률을 낮게. GPU 권장 — 3060 12GB 기준: 낱말 임베딩 얼림(기본) · fp16 ·
      max_length 384 · 배치 2 × 누적 4. 메모리가 모자라면(CUDA out of memory) --grad-checkpointing 또는 --batch 1 --accum 8
      6GB(노트북 3060 등): --train-layers 6 --batch 1 --accum 8 (위쪽 6층만 학습, AdamW 로 약 3GB)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from backend.core.config import RUNS_DIR, STORAGE_DIR

DATA_DIR = Path(RUNS_DIR) / "ce_train"
MODEL_DIR = Path(STORAGE_DIR) / "models" / "ce"


# ── 1) build ─────────────────────────────────────────────────────
def _cache_by_question(path):
    """analysis_cache.jsonl → {질문: 단위 목록} (날짜 키와 상관없이 질문으로 찾음)"""
    out = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["question"]] = r["units"]
    return out


def build_groups(pipe, rows, units_of, top_n=20, doc="struct+def", add_missing=True, set_name=""):
    """→ [{qid, record_id, split, variant, set, question, cands: [{tbl_id, doc, label, base_rank}], n_pos}]
    rows: compare.load_golden 행 (alt_groups 가 있으면 대체 정답도 정답). units_of: {질문: 단위}"""
    from backend.rag.search.ce_rerank import doc_text
    cards = pipe._ce_cards({"doc": doc}) if doc == "struct+def" else None
    out, skipped = [], 0
    for row in rows:
        units = units_of.get(row["question"]) or [{"unit": "main", "search_query": row["question"], "filters": None}]
        main = next((u for u in units if (u.get("unit") or "main") == "main"), units[0])
        r = pipe.search(main["search_query"], main.get("filters"), top_n, question=row["question"], unit="main")
        acc = set(row["gold"]) | {t for v in row["groups"].values() for t in v}
        acc |= {t for v in (row.get("alt_groups") or {}).values() for t in v}
        cands = [{"tbl_id": h["tbl_id"], "base_rank": h["rank"], "label": int(h["tbl_id"] in acc)} for h in r["hits"][:top_n]]
        if add_missing and not any(c["label"] for c in cands):  # 정답이 후보 밖이면 학습용으로 정답 하나를 붙임
            g = next((t for t in row["gold"] if t in pipe.docs_by_id), None)
            if g:
                cands.append({"tbl_id": g, "base_rank": None, "label": 1})
        if not cands or not any(c["label"] for c in cands) or all(c["label"] for c in cands):
            skipped += 1
            continue
        for c in cands:
            c["doc"] = doc_text(pipe.facets[c["tbl_id"]], (cards or {}).get(c["tbl_id"]), doc)
        out.append({"qid": row["qid"], "record_id": row["record_id"], "split": row.get("split") or "dev",
                    "variant": row.get("variant", ""), "set": set_name, "question": row["question"], "cands": cands,
                    "n_pos": sum(c["label"] for c in cands)})
    return out, skipped


def cmd_build(a):
    from backend.rag.search.tuning.compare import find_run, get_search_for, load_golden
    settings = {"dense_docs": a.dense_docs} if a.dense_docs != "rule" else {}
    pipe = get_search_for(a.dense, False, settings or None)
    groups, stats = [], {}
    for key in a.from_run:
        prev = find_run(key)
        cfg = json.loads((prev / "config.json").read_text(encoding="utf-8"))
        rows = load_golden(cfg["golden"], tuple(cfg.get("variants") or ("O", "P")))
        if cfg.get("alt"):
            from backend.rag.search.tuning.alt_gold import load_alt
            alt = load_alt(cfg["alt"])
            for r in rows:
                r["alt_groups"] = alt.get(r["record_id"], {})
        units = _cache_by_question(prev / "analysis_cache.jsonl")
        miss = sum(1 for r in rows if r["question"] not in units)
        g, skipped = build_groups(pipe, rows, units, a.top_n, a.doc, not a.no_add_missing, prev.name)
        groups += g
        stats[prev.name] = {"golden": cfg["golden"], "rows": len(rows), "groups": len(g), "skipped": skipped,
                            "no_cache": miss, "dev": sum(x["split"] == "dev" for x in g),
                            "heldout": sum(x["split"] == "heldout" for x in g)}
        print(f"[ce_train] {prev.name}: 문항 {len(rows)} → 묶음 {len(g)} (건너뜀 {skipped}, 분석 캐시 없음 {miss})", flush=True)
    out = DATA_DIR / a.name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "groups.jsonl").open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    meta = {"dense": a.dense, "dense_docs": a.dense_docs, "top_n": a.top_n, "doc": a.doc, "sets": stats,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ce_train] → {out / 'groups.jsonl'} · 묶음 {len(groups)} "
          f"(dev {sum(g['split'] == 'dev' for g in groups)} · heldout {sum(g['split'] == 'heldout' for g in groups)})")


def load_groups(name_or_path):
    p = Path(name_or_path)
    p = p if p.suffix == ".jsonl" else (p / "groups.jsonl" if p.is_dir() else DATA_DIR / name_or_path / "groups.jsonl")
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── 채점 (오프라인) ───────────────────────────────────────────────
def blend_order(cands, scores, k=5.0, weight=1.0, base_weight=1.0):
    """ce_rerank.rerank 의 blend 와 같은 식 — 후보 순서(원래 순위) + 교차 인코더 순위"""
    n = len(cands)
    ce_rank = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: -scores[i]), 1)}
    base = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: (cands[i]["base_rank"] or 999, i)), 1)}
    val = {i: weight / (k + ce_rank[i]) + base_weight / (k + base[i]) for i in range(n)}
    return sorted(range(n), key=lambda i: (-val[i], base[i]))


def metrics(groups, orders):
    """orders: 묶음마다 후보 번호 순서 → Hit@1 · Hit@3 · MRR (base_rank 가 없는 '붙인 정답'은 원래 순위에서 꼴찌)"""
    h1 = h3 = mrr = 0.0
    for g, o in zip(groups, orders):
        pos = next((r for r, i in enumerate(o, 1) if g["cands"][i]["label"]), None)
        h1 += bool(pos and pos == 1)
        h3 += bool(pos and pos <= 3)
        mrr += 1 / pos if pos else 0
    n = max(1, len(groups))
    return {"n": len(groups), "hit@1": round(h1 / n, 3), "hit@3": round(h3 / n, 3), "mrr": round(mrr / n, 3)}


def base_orders(groups):
    return [sorted(range(len(g["cands"])), key=lambda i: (g["cands"][i]["base_rank"] or 999, i)) for g in groups]


def score_groups(groups, score_fn):
    """score_fn(question, docs) → 점수 목록"""
    return [score_fn(g["question"], [c["doc"] for c in g["cands"]]) for g in groups]


GRID_K = (1, 2, 5, 10, 20)
GRID_W = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0)


def evaluate(groups, scores, k=None, weight=None):
    """→ {base, ce, blend, best:{k,weight}, grid}. k·weight 를 안 주면 이 묶음들에서 가장 좋은 값(MRR)을 찾음"""
    res = {"base": metrics(groups, base_orders(groups)),
           "ce": metrics(groups, [sorted(range(len(s)), key=lambda i: -s[i]) for s in scores])}
    grid = []
    for kk in ([k] if k is not None else GRID_K):
        for ww in ([weight] if weight is not None else GRID_W):
            m = metrics(groups, [blend_order(g["cands"], s, kk, ww) for g, s in zip(groups, scores)])
            grid.append({"k": kk, "weight": ww, **m})
    best = max(grid, key=lambda x: (x["mrr"], x["hit@1"]))
    res.update(blend=best, best={"k": best["k"], "weight": best["weight"]}, grid=grid)
    return res


# ── 2) train ─────────────────────────────────────────────────────
def make_batches(groups, negs=7, batch=4, seed=0, top_bias=True):
    """dev 묶음 → [[(질문, 글 목록[정답, 오답…]), …], …]. 오답은 원래 순위가 높은 것을 더 자주 뽑음"""
    rnd = random.Random(seed)
    items = []
    for g in groups:
        pos = [c for c in g["cands"] if c["label"]]
        neg = [c for c in g["cands"] if not c["label"]]
        if not pos or not neg:
            continue
        p = rnd.choice(pos)
        if top_bias:
            neg = sorted(neg, key=lambda c: c["base_rank"] or 999)
            w = [1 / math.sqrt(i + 1) for i in range(len(neg))]
            pick = []
            pool = list(range(len(neg)))
            while pool and len(pick) < negs:
                j = rnd.choices(pool, weights=[w[i] for i in pool])[0]
                pick.append(neg[j])
                pool.remove(j)
        else:
            pick = rnd.sample(neg, min(negs, len(neg)))
        while len(pick) < negs:  # 오답이 모자라면 되풀이 (묶음 크기를 맞춤)
            pick.append(rnd.choice(neg))
        items.append((g["question"], [p["doc"]] + [c["doc"] for c in pick]))
    rnd.shuffle(items)
    return [items[i:i + batch] for i in range(0, len(items), batch)]


def freeze(model, train_layers=0, freeze_embeddings=True):
    """train_layers > 0: 인코더의 위쪽 N 층과 분류 머리만 학습 (나머지는 얼림 — 6GB GPU 용, 데이터가 적을 때 과적합도 줄임)
    0 이면 낱말 임베딩만 얼림(freeze_embeddings)"""
    base = getattr(model, getattr(model, "base_model_prefix", ""), None)
    layers = getattr(getattr(base, "encoder", None), "layer", None)
    if train_layers and base is not None and layers is not None:
        for prm in base.parameters():
            prm.requires_grad = False
        for layer in list(layers)[-int(train_layers):]:
            for prm in layer.parameters():
                prm.requires_grad = True
        for name in ("pooler",):
            for prm in (getattr(base, name).parameters() if getattr(base, name, None) is not None else []):
                prm.requires_grad = True
    elif freeze_embeddings:
        emb = getattr(base, "embeddings", None)
        for prm in (emb.parameters() if emb is not None else []):
            prm.requires_grad = False
    return model


def train_loop(model, tok, dev, held, cfg, device="cpu", log=print, save=None):
    """리스트 단위 미세조정. model: 시퀀스 분류(num_labels=1) · tok: 그 토크나이저. → 에폭별 기록
    save(model, tok, epoch, report): heldout 이 가장 좋을 때 부름"""
    import torch
    lr = cfg.get("lr")
    if lr is None:  # torch 의 Adafactor 는 학습률을 '파라미터 크기에 대한 비율'로 씀 — AdamW 와 같은 값이면 거의 안 움직임
        lr = 1e-3 if cfg.get("optimizer") == "adafactor" else 2e-5
    epochs, lr, negs, bs = int(cfg["epochs"]), float(lr), int(cfg["negs"]), int(cfg["batch"])
    ml, accum = int(cfg["max_length"]), int(cfg.get("accum", 1))
    use_amp = device.startswith("cuda") and cfg.get("fp16", True)
    model.to(device)
    freeze(model, int(cfg.get("train_layers", 0)), cfg.get("freeze_embeddings", True))
    params = [prm for prm in model.parameters() if prm.requires_grad]
    n_train = sum(prm.numel() for prm in params)
    log(f"  학습하는 파라미터 {n_train / 1e6:.0f}M / 전체 {sum(prm.numel() for prm in model.parameters()) / 1e6:.0f}M"
        f" · 위쪽 층 {cfg.get('train_layers') or '전부'} · 최적화 {cfg.get('optimizer', 'adamw')} · 학습률 {lr:g}")
    start = [prm.detach().float().cpu().clone() for prm in params]  # 가중치가 실제로 얼마나 움직였는지 보려고

    def moved():
        num = sum(float((prm.detach().float().cpu() - s0).norm() ** 2) for prm, s0 in zip(params, start))
        den = sum(float(s0.norm() ** 2) for s0 in start)
        return math.sqrt(num / max(den, 1e-12))
    if cfg.get("optimizer") == "adafactor" and hasattr(torch.optim, "Adafactor"):  # 모멘트를 거의 안 들고 있어 메모리가 작음
        opt = torch.optim.Adafactor(params, lr=lr, weight_decay=float(cfg.get("weight_decay", 0.01)))
    else:
        opt = torch.optim.AdamW(params, lr=lr, weight_decay=float(cfg.get("weight_decay", 0.01)))
    steps = epochs * max(1, math.ceil(len(make_batches(dev, negs, bs, 0)) / accum))
    warm = max(1, int(steps * float(cfg.get("warmup", 0.1))))
    def lr_at(s):  # 앞쪽 warm 걸음은 0 → 1 로 올리고, 그다음 끝까지 1 → 0 으로 내림
        return (s + 1) / warm if s < warm else max(0.0, (steps - s) / max(1, steps - warm))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_at)
    scaler = torch.amp.GradScaler("cuda") if use_amp else None

    def scorer(q, docs):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(docs), 32):
                enc = tok([q] * len(docs[i:i + 32]), docs[i:i + 32], truncation=True, max_length=ml, padding=True,
                          return_tensors="pt").to(device)
                with torch.autocast("cuda", enabled=use_amp):
                    out += model(**enc).logits.view(-1).float().tolist()
        return out

    def check(tag):
        if not held:
            return None
        rep = evaluate(held, score_groups(held, scorer))
        log(f"  [{tag}] heldout {rep['base']['n']}묶음 · 원래 Hit@1 {rep['base']['hit@1']} · 교차 인코더만 {rep['ce']['hit@1']} · "
            f"blend {rep['blend']['hit@1']} (k={rep['best']['k']}, w={rep['best']['weight']}) · MRR {rep['blend']['mrr']}")
        return rep
    history = [{"epoch": 0, "heldout": check("학습 전")}]
    best = (history[0]["heldout"] or {}).get("blend", {}).get("mrr", -1)
    step = 0
    for ep in range(1, epochs + 1):
        model.train()
        t0, tot, nb = time.time(), 0.0, 0
        batches = make_batches(dev, negs, bs, seed=ep)
        n_batches = len(batches)
        for bi, b in enumerate(batches):
            qs = [q for q, docs in b for _ in docs]
            ds = [d for _, docs in b for d in docs]
            enc = tok(qs, ds, truncation=True, max_length=ml, padding=True, return_tensors="pt").to(device)
            with torch.autocast("cuda", enabled=use_amp):
                logits = model(**enc).logits.view(len(b), -1).float()
                loss = torch.nn.functional.cross_entropy(logits, torch.zeros(len(b), dtype=torch.long, device=logits.device))
                loss = loss / accum
            (scaler.scale(loss) if scaler else loss).backward()
            if (bi + 1) % accum == 0:
                if scaler:
                    scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                if scaler:
                    scaler.step(opt)
                    scaler.update()
                else:
                    opt.step()
                opt.zero_grad(set_to_none=True)
                sched.step()
                step += 1
            tot += float(loss.detach()) * accum
            nb += 1
            every = int(cfg.get("log_every", 20))
            if every and nb % every == 0:
                done = nb / max(1, n_batches)
                log(f"    걸음 {nb}/{n_batches} · 손실 {tot / nb:.4f} · {time.time() - t0:.0f}초 "
                    f"(에폭 남은 시간 약 {(time.time() - t0) / done * (1 - done):.0f}초)")
        rep = check(f"에폭 {ep}")
        mv = moved()
        history.append({"epoch": ep, "loss": round(tot / max(1, nb), 4), "seconds": round(time.time() - t0, 1), "heldout": rep,
                        "moved": mv})
        log(f"  에폭 {ep}: 손실 {tot / max(1, nb):.4f} · {time.time() - t0:.0f}초 · 가중치 변화 {mv:.2e}"
            + ("  ⚠ 거의 안 움직임 — 학습률을 올리세요" if mv < 1e-4 else ""))
        score = (rep or {}).get("blend", {}).get("mrr", ep)  # heldout 이 없으면 마지막 에폭
        if save and score > best:
            best = score
            save(model, tok, ep, rep)
    return history


def cmd_train(a):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from backend.rag.search.ce_rerank import model_id
    groups = load_groups(a.data)
    dev = [g for g in groups if g["split"] == "dev"]
    held = [g for g in groups if g["split"] == "heldout"]
    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    base = model_id(a.base)
    print(f"[ce_train] 학습 dev {len(dev)} · 확인 heldout {len(held)} · 바탕 {base} · 장치 {device}", flush=True)
    if device.startswith("cuda"):
        gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        print(f"[ce_train] GPU {torch.cuda.get_device_name(0)} · 메모리 {gb:.1f}GB", flush=True)
        if gb < 10 and not a.train_layers:
            print("  ⚠ GPU 메모리가 10GB 보다 작습니다 — 이 모델 전체 학습은 들어가지 않아 아주 느려질 수 있습니다 (윈도우는 시스템 "
                  "메모리로 넘침). --train-layers 6 --batch 1 --accum 8 를 권합니다", flush=True)
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForSequenceClassification.from_pretrained(base, num_labels=1)
    if a.grad_checkpointing and hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()
    out = MODEL_DIR / a.name
    cfg = {"epochs": a.epochs, "lr": a.lr, "negs": a.negs, "batch": a.batch, "max_length": a.max_length,
           "accum": a.accum, "fp16": not a.no_fp16, "warmup": a.warmup, "weight_decay": 0.01,
           "freeze_embeddings": not a.train_embeddings, "train_layers": a.train_layers, "optimizer": a.optimizer,
           "log_every": a.log_every}
    saved = {}

    def save(m, t, ep, rep):
        out.mkdir(parents=True, exist_ok=True)
        m.save_pretrained(out)
        t.save_pretrained(out)
        saved.update(epoch=ep, heldout=rep)
        print(f"  → 저장 (에폭 {ep}) {out}", flush=True)
    hist = train_loop(model, tok, dev, held, cfg, device, log=lambda m: print(m, flush=True), save=save)
    if not saved:  # heldout 이 학습 전보다 나아진 에폭이 없음 — 그래도 마지막을 따로 남김 (비교용)
        last = out.with_name(out.name + "-last")
        last.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(last)
        tok.save_pretrained(last)
        print(f"  heldout 이 학습 전보다 좋아진 에폭이 없음 → 저장 안 함 (마지막 에폭은 {last})")
    meta = {"base": base, "data": a.data, "cfg": cfg, "dev": len(dev), "heldout": len(held), "best": saved, "history": hist}
    (out if saved else out.with_name(out.name + "-last")).mkdir(parents=True, exist_ok=True)
    ((out if saved else out.with_name(out.name + "-last")) / "train_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def cmd_eval(a):
    from backend.rag.search.ce_rerank import scores as ce_scores
    groups = load_groups(a.data)
    cfg = {"model": a.model, "max_length": a.max_length, "batch": 16}
    fn = lambda q, docs: ce_scores(q, docs, cfg)
    dev = [g for g in groups if g["split"] == "dev"]
    held = [g for g in groups if g["split"] == "heldout"]
    rd = evaluate(dev, score_groups(dev, fn)) if dev else None
    rh = evaluate(held, score_groups(held, fn), **(rd["best"] if rd else {})) if held else None
    print(f"\n[ce_train eval] 모델 {a.model} · 묶음 dev {len(dev)} · heldout {len(held)}")
    print("| 나눔 | 원래 순위 Hit@1 | 교차 인코더만 Hit@1 | blend Hit@1 | blend Hit@3 | blend MRR (원래) | k · weight |")
    print("|---|---|---|---|---|---|---|")
    for name, r in (("dev", rd), ("heldout (dev 에서 고른 k·weight)", rh)):
        if r:
            print(f"| {name} | {r['base']['hit@1']} | {r['ce']['hit@1']} | {r['blend']['hit@1']} | {r['blend']['hit@3']} | "
                  f"{r['blend']['mrr']} ({r['base']['mrr']}) | {r['best']['k']} · {r['best']['weight']} |")
    if rd:
        print(f"\n→ compare 에:  --ce --ce-model {a.model} --ce-k {rd['best']['k']} --ce-weight {rd['best']['weight']}")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.ce_train")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="이전 실행으로 학습 묶음(질문·상위 후보·정답 여부) 만들기")
    b.add_argument("--from-run", nargs="+", required=True, help="compare 실행 이름 일부 (여러 개 — 합성 셋 easy·hard)")
    b.add_argument("--dense", default="bge-m3-ko")
    b.add_argument("--dense-docs", default="rule,def")
    b.add_argument("--top-n", type=int, default=20)
    b.add_argument("--doc", default="struct+def", choices=["struct", "struct+def"])
    b.add_argument("--no-add-missing", action="store_true", help="정답이 후보 밖인 질문은 버림 (기본: 정답을 붙여 학습)")
    b.add_argument("--name", required=True)
    t = sub.add_parser("train", help="dev 묶음으로 미세조정")
    t.add_argument("--data", required=True, help="build 의 --name (또는 groups.jsonl 경로)")
    t.add_argument("--base", default="bge-reranker-ko", help="바탕 모델 (bge-reranker-ko | bge-reranker | 경로)")
    t.add_argument("--name", required=True)
    t.add_argument("--epochs", type=int, default=2)
    t.add_argument("--lr", type=float, default=None, help="기본: adamw 2e-5 · adafactor 1e-3 (torch Adafactor 는 비율 학습률)")
    t.add_argument("--negs", type=int, default=7, help="묶음마다 오답 수")
    t.add_argument("--batch", type=int, default=2, help="한 번에 묶음 몇 개 (묶음 × (1+오답) 개 문장)")
    t.add_argument("--accum", type=int, default=4, help="기울기 누적 (배치 × 누적 = 한 걸음의 묶음 수)")
    t.add_argument("--max-length", type=int, default=384)
    t.add_argument("--warmup", type=float, default=0.1)
    t.add_argument("--device", default=None)
    t.add_argument("--no-fp16", action="store_true")
    t.add_argument("--grad-checkpointing", action="store_true", help="GPU 메모리가 모자랄 때 (느려지는 대신 메모리 절약)")
    t.add_argument("--train-embeddings", action="store_true", help="낱말 임베딩도 학습 (기본: 얼림 — 메모리·과적합)")
    t.add_argument("--train-layers", type=int, default=0, help="인코더 위쪽 N 층 + 분류 머리만 학습 (0 = 전부). 6GB GPU 는 6~8")
    t.add_argument("--optimizer", default="adamw", choices=["adamw", "adafactor"], help="adafactor = 메모리 작음")
    t.add_argument("--log-every", type=int, default=20, help="에폭 안에서 몇 걸음마다 진행 상황 (0 = 끔)")
    e = sub.add_parser("eval", help="저장한 후보로 오프라인 채점 (원래 · 교차 인코더만 · blend)")
    e.add_argument("--data", required=True)
    e.add_argument("--model", default="bge-reranker-ko", help="bge-reranker-ko 또는 학습한 모델 경로")
    e.add_argument("--max-length", type=int, default=384)
    a = ap.parse_args(argv)
    {"build": cmd_build, "train": cmd_train, "eval": cmd_eval}[a.cmd](a)


if __name__ == "__main__":
    main()
