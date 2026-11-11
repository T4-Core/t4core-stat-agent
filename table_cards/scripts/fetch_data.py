"""
표본 표 수치 데이터 미리 받기 — 2015·2020년 + 4만 셀 초과 표 (size_report.csv 기준)

나머지 표본 표는 미리 받지 않음 → 실제로 쓰일 때 필요한 조각만 받음 (지연 수집, 별도 작업)
방법  공용 수집기(collector.py)의 함수를 가져다 쓰기만 함 (수정 없음)
        parse_itm · parse_prd   메타 → 분류·항목·시점
        real_periods            실제 자료가 있는 시점만
        plan                    4만 셀 이하가 되도록 요청 나누기
        fetch_part              요청 1건 → 조각 CSV (받은 조각은 다시 받지 않음 → 끊겨도 이어서)
      속도 제한(분당 180번, 모든 스레드 합산)도 수집기 설정을 그대로 따름
저장  table_cards/sample/data/<기관>_<표>.parquet     표 하나 = 파일 하나 (CSV 보다 훨씬 작음)
      table_cards/sample/parts/<기관>_<표>/*.csv    중간 조각 (표가 실패 없이 끝나면 지움)
      table_cards/sample/data_log.csv               표마다 요청 수·행 수·용량·시간·실패

실행  저장소 루트에서:
  .venv/Scripts/python.exe table_cards/scripts/fetch_data.py --limit 2      # 시험
  .venv/Scripts/python.exe table_cards/scripts/fetch_data.py                # 전체 (이미 받은 표는 건너뜀)
"""
import argparse
import csv
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "sample"     # 표본 표 작업 폴더 (메타는 ../sample_meta)
SAMPLE.mkdir(exist_ok=True)
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd                                                                  # noqa: E402

from backend.rag.ingestion.collector import (API_KEY, KEEP_COLS, KosisError,       # noqa: E402  (읽기만)
                                             fetch_part, parse_itm, parse_prd, plan, real_periods)

LIMIT = 40_000
DATA, PARTS, LOG = SAMPLE / "data", SAMPLE / "parts", SAMPLE / "data_log.csv"


def targets():
    d = pd.read_csv(SAMPLE / "size_report.csv", dtype={"tbl_id": str, "org_id": str})
    d = d[d["조사연도"].isin([2015, 2020]) & (d["전체"] > LIMIT)]
    return d.sort_values("전체")                       # 작은 표부터 → 문제를 일찍 발견


def fetch_table(org, tbl, workers):
    meta = json.loads((HERE.parent / "sample_meta" / f"{org}_{tbl}.json").read_text(encoding="utf-8"))
    levels, items = parse_itm(meta["ITM"])
    prds = parse_prd(meta["PRD"])
    if not levels or not prds:
        return {"ok": False, "reason": "메타 파싱 실패", "requests": 0, "rows": 0, "mb": 0}
    part_dir = PARTS / f"{org}_{tbl}"
    tasks = []
    for prd_se, periods in prds.items():
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
                fails.append(str(e)[:120])
    if not frames:
        return {"ok": False, "reason": "자료 없음 " + "; ".join(fails[:2]), "requests": len(tasks), "rows": 0, "mb": 0}
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in KEEP_COLS if c in df.columns]].drop_duplicates()
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"{org}_{tbl}.parquet"
    df.to_parquet(out, index=False)
    if not fails:
        shutil.rmtree(part_dir, ignore_errors=True)
    return {"ok": not fails, "reason": ("; ".join(fails[:2]) if fails else ""), "requests": len(tasks),
            "rows": len(df), "mb": round(out.stat().st_size / 1e6, 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if not API_KEY:
        raise SystemExit(".env 에 KOSIS_API_KEY 가 없습니다.")

    t = targets()
    todo = [r for r in t.itertuples() if not (DATA / f"{r.org_id}_{r.tbl_id}.parquet").exists()]
    print(f"대상 {len(t)}개 (2015·2020, 4만 셀 초과) | 이미 받음 {len(t) - len(todo)}개 | 이번에 {len(todo[:a.limit] if a.limit else todo)}개", flush=True)
    if a.limit:
        todo = todo[:a.limit]

    new_log = not LOG.exists()
    t0 = time.time()
    with LOG.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["org_id", "tbl_id", "조사연도", "예상셀", "ok", "requests", "rows", "mb", "sec", "reason"])
        if new_log:
            w.writeheader()
        for i, r in enumerate(todo, 1):
            s = time.time()
            try:
                res = fetch_table(r.org_id, r.tbl_id, a.workers)
            except Exception as e:                                       # 한 표가 실패해도 다음 표로
                res = {"ok": False, "reason": repr(e)[:200], "requests": 0, "rows": 0, "mb": 0}
            row = {"org_id": r.org_id, "tbl_id": r.tbl_id, "조사연도": r.조사연도, "예상셀": r.전체,
                   "sec": round(time.time() - s, 1), **res}
            w.writerow(row)
            f.flush()
            print(f"[{i}/{len(todo)}] {r.tbl_id} 요청 {row['requests']} · 행 {row['rows']:,} (예상 {r.전체:,}) · "
                  f"{row['mb']}MB · {row['sec']}초 {'' if row['ok'] else '✗ ' + row['reason']}"
                  f" | 누적 {time.time() - t0:.0f}초", flush=True)


if __name__ == "__main__":
    main()
