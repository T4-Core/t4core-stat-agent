"""
표본조사 표 메타만 수집 (수치 데이터는 받지 않음 — 실제로 쓰일 때 따로 받음)

대상  storage/kosis_data/catalog.csv 에서 is_sample == True 인 표 (1,372개, 전부 인구총조사)
      공용 수집기(collector.py)는 selected == True 만 받으므로 표본 표는 받은 적 없음
방법  collector.get_meta 를 가져다 쓰기만 함 (공용 코드 수정 없음). 속도 제한(_throttle, 분당 180번)도 그대로 따름
      표마다 TBL · ITM · PRD · CMMT · SOURCE 5번 호출 → 공용 수집기의 meta/*.json 과 같은 모양
저장  table_cards/sample_meta/<기관>_<표>.json   (공용 storage 와 따로)
      table_cards/sample/fetch_log.csv            표마다 결과·걸린 시간·오류
      이미 받은 표는 건너뜀 → 끊겨도 다시 실행하면 이어서

실행  저장소 루트에서:
  .venv/Scripts/python.exe table_cards/scripts/fetch_meta.py --limit 50     # 시험 수집
  .venv/Scripts/python.exe table_cards/scripts/fetch_meta.py                # 전체
"""
import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "sample"     # 표본 표 작업 폴더 (메타는 ../sample_meta)
SAMPLE.mkdir(exist_ok=True)
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd                                                      # noqa: E402

from backend.core.config import KOSIS_DATA_DIR                          # noqa: E402
from backend.rag.ingestion.collector import API_KEY, get_meta           # noqa: E402  (읽기만)

META_DIR = HERE.parent / "sample_meta"
LOG = SAMPLE / "fetch_log.csv"
TYPES = ("TBL", "ITM", "PRD", "CMMT", "SOURCE")


def sample_tables():
    cat = pd.read_csv(KOSIS_DATA_DIR / "catalog.csv", dtype=str)
    s = cat[cat["is_sample"] == "True"].drop_duplicates(["org_id", "tbl_id"])
    return s


def fetch_one(org, tbl):
    t0 = time.time()
    meta = {t: get_meta(org, tbl, t) for t in TYPES}
    errs = [t for t, v in meta.items() if v and isinstance(v[0], dict) and "_error" in v[0]]
    (META_DIR / f"{org}_{tbl}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    n_itm = len(meta["ITM"]) if not errs else 0
    return {"org_id": org, "tbl_id": tbl, "ok": not errs, "errors": ",".join(errs),
            "itm_rows": n_itm, "sec": round(time.time() - t0, 1)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if not API_KEY:
        raise SystemExit(".env 에 KOSIS_API_KEY 가 없습니다.")

    META_DIR.mkdir(parents=True, exist_ok=True)
    s = sample_tables()
    todo = [(r.org_id, r.tbl_id) for r in s.itertuples() if not (META_DIR / f"{r.org_id}_{r.tbl_id}.json").exists()]
    total, done_before = len(s), len(s) - len(todo)
    if a.limit:
        todo = todo[:a.limit]
    print(f"표본 표 {total}개 | 이미 받음 {done_before}개 | 이번에 받을 것 {len(todo)}개 (호출 {len(todo) * len(TYPES)}번)", flush=True)

    new_log = not LOG.exists()
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex, LOG.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["org_id", "tbl_id", "ok", "errors", "itm_rows", "sec"])
        if new_log:
            w.writeheader()
        futs = {ex.submit(fetch_one, o, t): (o, t) for o, t in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                r = fu.result()
            except Exception as e:                                       # 한 표가 실패해도 계속
                o, t = futs[fu]
                r = {"org_id": o, "tbl_id": t, "ok": False, "errors": repr(e)[:200], "itm_rows": 0, "sec": 0}
            rows.append(r)
            w.writerow(r)
            f.flush()
            if i % 10 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"  {i}/{len(todo)}  경과 {el:.0f}초  (표당 {el / i:.2f}초)", flush=True)

    el = time.time() - t0
    ok = sum(r["ok"] for r in rows)
    print(f"\n완료: 성공 {ok} / 실패 {len(rows) - ok}  | 걸린 시간 {el:.0f}초")
    left = total - done_before - len(rows)
    if rows and left > 0:
        print(f"남은 {left}개 예상 시간: 약 {left * el / len(rows) / 60:.0f}분")
    for r in rows:
        if not r["ok"]:
            print("  실패:", r["tbl_id"], r["errors"])


if __name__ == "__main__":
    main()
