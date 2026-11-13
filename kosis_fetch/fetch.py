"""
공용 KOSIS 추가 다운로드 — 표본조사 표(메타·수치) + 조사별 통계설명을 '한 코드'로 받는다

  이미 있는 것   storage/kosis_data/            전수·인구 14개 조사 (collector.py 로 받은 48GB, 읽기만)
  여기서 받는 것  <KOSIS_EXTRA_DIR>/sample/       표본 표 — collector.py 와 같은 폴더 모양
                    catalog.csv                  kosis_data/catalog.csv 의 is_sample 행 (selected=True 로 표시해
                                                 meta_profile·csv_index·normalize 가 그대로 읽게)
                    meta/<기관>_<표>.json         TBL·ITM·PRD·CMMT·SOURCE (collector·table_cards/fetch_meta 와 같은 모양)
                    raw/<조사>/<기관>_<표>.csv    원본 CSV (collector.KEEP_COLS 열)
                    parts/ · logs/               조각(끊겨도 이어받기) · 표별 기록
                 <KOSIS_EXTRA_DIR>/expl/<stat_id>.json   통계설명(statisticsExplData) — 전수·표본 모든 조사
  기본 KOSIS_EXTRA_DIR = storage/kosis_extra

가공은 따로: table_card(table_cards/scripts) 와 table_card_expend 가 이 폴더를 각자 읽어 자기 결과를 만든다.
이미 받아 둔 table_cards/sample_meta/*.json · table_cards/sample/data/*.parquet 이 있으면 API 를 다시 부르지 않고
그대로 가져온다(seed) → 두 가공이 같은 메타·수치를 보게 됨.

수집 방법은 collector.py 함수를 가져다 쓴다 (수정 없음):
  get_meta · parse_itm · parse_prd · real_periods(실제 자료가 있는 시점만) · plan(요청당 4만 셀) · fetch_part(조각 저장)
  호출 간격·재시도·오류코드 처리(call)도 그대로. API 키는 .env 의 KOSIS_API_KEY — 로그·파일에 남기지 않음(가림 처리)

실행  저장소 루트에서
  python -m kosis_fetch.fetch status                          # 무엇이 있고 무엇을 받을지 (호출 없음)
  python -m kosis_fetch.fetch meta                            # 표본 메타 (seed 우선, 없는 것만 API)
  python -m kosis_fetch.fetch data --years 2015 2020 --max-cells 2000000   # 표본 수치
  python -m kosis_fetch.fetch expl                            # 조사별 통계설명
  python -m kosis_fetch.fetch all --limit 20                  # 시험
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

META_TYPES = ("TBL", "ITM", "PRD", "CMMT", "SOURCE")
SEED_META = ROOT / "table_cards" / "sample_meta"
SEED_DATA = ROOT / "table_cards" / "sample" / "data"
LOG_FIELDS = ["stage", "org_id", "tbl_id", "ok", "source", "requests", "rows", "est_cells", "sec", "reason"]


# ── 경로 ─────────────────────────────────────────────────────────
def extra_dir() -> Path:
    from backend.core.config import ROOT as REPO, STORAGE_DIR
    v = (os.getenv("KOSIS_EXTRA_DIR") or "").strip()
    if v:
        p = Path(v).expanduser()
        return (p if p.is_absolute() else REPO / p).resolve()
    return Path(STORAGE_DIR) / "kosis_extra"


def sample_dir() -> Path:
    return extra_dir() / "sample"


def safe(name):
    from backend.core.utils import safe as _safe
    return _safe(name)


def scrub(text) -> str:
    """오류 문장에 API 키가 섞여 나가지 않게 (requests 예외 문장에는 URL 전체가 들어감)"""
    s = str(text)
    key = (os.getenv("KOSIS_API_KEY") or "").strip()
    if key:
        s = s.replace(key, "***")
    return re.sub(r"(apiKey=)[^&\s'\"]+", r"\1***", s)


def _log(stage, row):
    d = sample_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stage}_log.csv"
    new = not p.exists()
    with p.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({"stage": stage, **{k: (scrub(v) if k == "reason" else v) for k, v in row.items()}})


# ── 대상 표 ──────────────────────────────────────────────────────
def full_catalog() -> pd.DataFrame:
    from backend.core.config import KOSIS_DATA_DIR
    p = Path(KOSIS_DATA_DIR) / "catalog.csv"
    if not p.exists():
        raise SystemExit(f"catalog.csv 없음: {p}  (collector.py catalog 를 먼저, 또는 KOSIS_DATA_DIR 확인)")
    return pd.read_csv(p, dtype=str).fillna("")


def sample_catalog(args=None) -> pd.DataFrame:
    """kosis_data/catalog.csv 의 표본 표 → 표본 폴더 catalog (selected=True 로 표시)"""
    cat = full_catalog()
    s = cat[cat["is_sample"] == "True"].drop_duplicates(["org_id", "tbl_id"]).copy()
    s["selected"] = "True"
    s["sample_source"] = "kosis_data/catalog.csv(is_sample)"
    if args is not None:
        if getattr(args, "surveys", None):
            s = s[s["category"].isin(args.surveys)]
        if getattr(args, "tables", None):
            s = s[s["tbl_id"].isin(args.tables)]
        if getattr(args, "limit", None):
            s = s.head(args.limit)
    return s


def write_catalog(s: pd.DataFrame):
    d = sample_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "catalog.csv"
    old = pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame(columns=s.columns)
    merged = pd.concat([old, s]).drop_duplicates(["org_id", "tbl_id"], keep="last")
    merged.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def meta_file(org, tbl) -> Path:
    return sample_dir() / "meta" / f"{org}_{tbl}.json"


def raw_file(category, org, tbl) -> Path:
    return sample_dir() / "raw" / safe(category) / f"{org}_{tbl}.csv"


def est_cells(meta, years=None):
    from backend.rag.ingestion.collector import parse_itm, parse_prd
    levels, items = parse_itm(meta.get("ITM") or [])
    prds = parse_prd(meta.get("PRD") or [])
    per = max(1, len(items)) * math.prod(len(l["codes"]) for l in levels) if levels else max(1, len(items))
    n_prd = sum(len([p for p in v if not years or int(p[:4]) in years]) for v in prds.values())
    return per * max(n_prd, 0), levels, items, prds


# ── 1) 메타 ──────────────────────────────────────────────────────
def stage_meta(args):
    from backend.rag.ingestion.collector import API_KEY, get_meta
    s = sample_catalog(args)
    write_catalog(s)
    (sample_dir() / "meta").mkdir(parents=True, exist_ok=True)
    todo, seeded, have = [], 0, 0
    for r in s.itertuples():
        out = meta_file(r.org_id, r.tbl_id)
        if out.exists():
            have += 1
            continue
        seed = SEED_META / out.name
        if seed.exists() and not args.no_seed:
            shutil.copyfile(seed, out)
            seeded += 1
            _log("meta", {"org_id": r.org_id, "tbl_id": r.tbl_id, "ok": True, "source": "seed:table_cards/sample_meta"})
            continue
        todo.append((r.org_id, r.tbl_id))
    print(f"[meta] 표본 표 {len(s)}개 | 이미 있음 {have} · seed 복사 {seeded} · API 로 받을 것 {len(todo)}", flush=True)
    if not todo:
        return
    if not API_KEY:
        raise SystemExit(".env 에 KOSIS_API_KEY 가 없습니다 (seed 로 채우지 못한 표가 남음).")

    def one(org, tbl):
        t0 = time.time()
        meta = {t: get_meta(org, tbl, t) for t in META_TYPES}
        errs = [t for t, v in meta.items() if v and isinstance(v[0], dict) and "_error" in v[0]]
        for v in meta.values():                                       # 오류 문장 속 키 가리기
            for x in v or []:
                if isinstance(x, dict) and "_error" in x:
                    x["_error"] = scrub(x["_error"])
        if not errs:
            meta_file(org, tbl).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"org_id": org, "tbl_id": tbl, "ok": not errs, "source": "api", "requests": len(META_TYPES),
                "sec": round(time.time() - t0, 1), "reason": ",".join(errs)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, o, t) for o, t in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                row = fu.result()
            except Exception as e:  # noqa: BLE001  (한 표 실패해도 계속)
                row = {"ok": False, "source": "api", "reason": repr(e)[:200]}
            _log("meta", row)
            if i % 20 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}  {time.time() - t0:.0f}초", flush=True)


# ── 2) 수치 ──────────────────────────────────────────────────────
def _seed_raw(r, out):
    seed = SEED_DATA / f"{r.org_id}_{r.tbl_id}.parquet"
    if not seed.exists():
        return None
    from backend.rag.ingestion.collector import KEEP_COLS
    df = pd.read_parquet(seed)
    df = df[[c for c in KEEP_COLS if c in df.columns]]
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return len(df)


def fetch_table(org, tbl, category, meta, years, workers):
    from backend.rag.ingestion.collector import KEEP_COLS, KosisError, fetch_part, parse_itm, parse_prd, plan, real_periods
    levels, items = parse_itm(meta["ITM"])
    prds = parse_prd(meta["PRD"])
    if not levels or not prds:
        return {"ok": False, "reason": "메타 파싱 실패 (분류 또는 시점 없음)", "requests": 0, "rows": 0}
    part_dir = sample_dir() / "parts" / f"{org}_{tbl}"
    tasks = []
    for prd_se, periods in prds.items():
        if years:
            periods = [p for p in periods if int(p[:4]) in years]
        if not periods:
            continue
        periods = real_periods(org, tbl, prd_se, levels, items, periods)
        tasks += [(prd_se, sel, s, e) for sel, s, e in plan(levels, items, periods)]
    frames, fails = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_part, part_dir, org, tbl, *t): t for t in tasks}
        for fu in as_completed(futs):
            try:
                df = fu.result()
                if df is not None and len(df):
                    frames.append(df)
            except KosisError as e:
                fails.append(scrub(e)[:160])
    if not frames:
        return {"ok": False, "reason": "자료 없음 " + "; ".join(fails[:2]), "requests": len(tasks), "rows": 0}
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in KEEP_COLS if c in df.columns]].drop_duplicates()
    out = raw_file(category, org, tbl)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    if not fails:
        shutil.rmtree(part_dir, ignore_errors=True)
    return {"ok": not fails, "reason": "; ".join(fails[:2]), "requests": len(tasks), "rows": len(df)}


def stage_data(args):
    from backend.rag.ingestion.collector import API_KEY
    s = sample_catalog(args)
    write_catalog(s)
    years = set(args.years or [])
    plan_rows, n_have, n_nometa = [], 0, 0
    for r in s.itertuples():
        out = raw_file(r.category, r.org_id, r.tbl_id)
        if out.exists():
            n_have += 1
            continue
        mp = meta_file(r.org_id, r.tbl_id)
        if not mp.exists():
            n_nometa += 1
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        cells, *_ = est_cells(meta, years)
        plan_rows.append((r, meta, cells))
    big = [x for x in plan_rows if args.max_cells and x[2] > args.max_cells]
    todo = [x for x in plan_rows if not (args.max_cells and x[2] > args.max_cells) and x[2] > 0]
    todo.sort(key=lambda x: x[2])                                     # 작은 표부터 → 문제를 일찍 발견
    print(f"[data] 표본 표 {len(s)}개 | 이미 있음 {n_have} · 메타 없음 {n_nometa} · "
          f"셀 상한 초과 건너뜀 {len(big)} · 받을 것 {len(todo)} (예상 {sum(x[2] for x in todo):,}셀)", flush=True)
    for r, _, cells in big:
        _log("data", {"org_id": r.org_id, "tbl_id": r.tbl_id, "ok": False, "source": "skip", "est_cells": cells,
                      "reason": f"예상 {cells:,}셀 > --max-cells {args.max_cells:,}"})
    need_api = False
    t0 = time.time()
    for i, (r, meta, cells) in enumerate(todo, 1):
        st = time.time()
        out = raw_file(r.category, r.org_id, r.tbl_id)
        n = None if args.no_seed else _seed_raw(r, out)
        if n is not None:
            row = {"ok": True, "source": "seed:table_cards/sample/data", "rows": n, "requests": 0, "reason": ""}
        else:
            if not API_KEY:
                need_api = True
                continue
            try:
                row = {"source": "api", **fetch_table(r.org_id, r.tbl_id, r.category, meta, years, args.workers)}
            except Exception as e:  # noqa: BLE001
                row = {"ok": False, "source": "api", "reason": repr(e)[:200], "requests": 0, "rows": 0}
        row.update(org_id=r.org_id, tbl_id=r.tbl_id, est_cells=cells, sec=round(time.time() - st, 1))
        _log("data", row)
        print(f"  [{i}/{len(todo)}] {r.tbl_id} {row['source']} 행 {row.get('rows', 0):,} (예상 {cells:,}셀) "
              f"{'' if row['ok'] else '✗ ' + scrub(row['reason'])[:80]} | 누적 {time.time() - t0:.0f}초", flush=True)
    if need_api:
        print("  ! KOSIS_API_KEY 가 없어 seed 가 없는 표는 받지 못했습니다.")


# ── 3) 통계설명 ──────────────────────────────────────────────────
def stage_expl(args):
    from backend.rag.ingestion.collector import API_KEY, URL_EXPL, KosisError, call
    cat = full_catalog()
    ids = sorted({x for x in cat.get("stat_id", pd.Series(dtype=str)) if str(x).strip()})
    d = extra_dir() / "expl"
    d.mkdir(parents=True, exist_ok=True)
    todo = [x for x in ids if not (d / f"{x}.json").exists()]
    print(f"[expl] 조사 {len(ids)}개 | 이미 있음 {len(ids) - len(todo)} · 받을 것 {len(todo)}", flush=True)
    if todo and not API_KEY:
        raise SystemExit(".env 에 KOSIS_API_KEY 가 없습니다.")
    surveys = cat.groupby("stat_id")["category"].agg(lambda x: sorted(set(x))).to_dict() if "stat_id" in cat else {}
    for sid in todo:
        try:
            rows = call(URL_EXPL, {"method": "getList", "statId": sid, "metaItm": "All"})
            ok, reason = True, ""
        except KosisError as e:
            rows, ok, reason = [], False, scrub(e)
        (d / f"{sid}.json").write_text(json.dumps({"stat_id": sid, "surveys": surveys.get(sid, []), "rows": rows},
                                                  ensure_ascii=False), encoding="utf-8")
        _log("expl", {"tbl_id": sid, "ok": ok, "source": "api", "requests": 1, "rows": len(rows), "reason": reason})


# ── 현황 ─────────────────────────────────────────────────────────
def stage_status(args):
    s = sample_catalog(args)
    years = set(args.years or [])
    n_meta = n_raw = 0
    sizes = []
    for r in s.itertuples():
        mp = meta_file(r.org_id, r.tbl_id)
        seed = SEED_META / mp.name
        src = mp if mp.exists() else (seed if seed.exists() else None)
        n_meta += mp.exists()
        n_raw += raw_file(r.category, r.org_id, r.tbl_id).exists()
        if src:
            sizes.append(est_cells(json.loads(src.read_text(encoding="utf-8")), years)[0])
    sizes.sort()
    print(f"출력 폴더: {sample_dir()}")
    print(f"표본 표 {len(s)}개 | 메타 {n_meta} (seed 가능 {sum((SEED_META / f'{r.org_id}_{r.tbl_id}.json').exists() for r in s.itertuples())})"
          f" | 원본 CSV {n_raw}")
    if sizes:
        q = lambda f: sizes[min(len(sizes) - 1, int(len(sizes) * f))]  # noqa: E731
        print(f"예상 셀 수 (메타 코드 곱, {'연도 ' + str(sorted(years)) if years else '전체 시점'}): "
              f"중앙 {q(.5):,} · 90% {q(.9):,} · 최대 {sizes[-1]:,} · 합계 {sum(sizes):,} "
              f"(요청 약 {sum(math.ceil(x / 40000) for x in sizes):,}번)")
    ed = extra_dir() / "expl"
    print(f"통계설명: {len(list(ed.glob('*.json'))) if ed.exists() else 0}개 조사")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="공용 KOSIS 추가 다운로드 (표본 표 + 통계설명)")
    ap.add_argument("stage", choices=["status", "meta", "data", "expl", "all"])
    ap.add_argument("--surveys", nargs="*")
    ap.add_argument("--tables", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--years", nargs="*", type=int, help="수치를 받을 연도 (생략 = 전체)")
    ap.add_argument("--max-cells", type=int, default=2_000_000, help="예상 셀 수가 이보다 큰 표는 건너뜀 (0 = 제한 없음)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-seed", action="store_true", help="table_cards 에 받아 둔 메타·수치를 쓰지 않고 다시 받기")
    a = ap.parse_args(argv)
    if a.stage == "status":
        return stage_status(a)
    if a.stage in ("meta", "all"):
        stage_meta(a)
    if a.stage in ("data", "all"):
        stage_data(a)
    if a.stage in ("expl", "all"):
        stage_expl(a)


if __name__ == "__main__":
    main()
