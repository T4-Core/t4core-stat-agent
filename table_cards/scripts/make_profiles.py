"""
표본 표 메타 → 프로필 (기존 992개의 meta_profiles.jsonl 과 같은 형식)

공용 meta_profile.table_profile 을 그대로 쓰고, 읽는 폴더(DATA)만 이 실행 안에서 표본 폴더로 지정 (공용 파일 수정 없음)
입력  storage/kosis_data/catalog.csv (is_sample == True), table_cards/sample_meta/*.json
출력  table_cards/sample/out/meta_profiles.jsonl

실행  저장소 루트에서:  .venv/Scripts/python.exe table_cards/scripts/make_profiles.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "sample"     # 표본 표 작업 폴더 (메타는 ../sample_meta)
SAMPLE.mkdir(exist_ok=True)
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd                                                  # noqa: E402

from backend.core.config import KOSIS_DATA_DIR                      # noqa: E402
from backend.rag.ingestion import meta_profile as mp                # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    class SampleData:                                                # 이 실행에서만: meta/ 를 표본 폴더에서 읽음
        def __truediv__(self, name):
            return HERE.parent / "sample_meta" if name == "meta" else SAMPLE / name
    mp.DATA = SampleData()
    cat = pd.read_csv(KOSIS_DATA_DIR / "catalog.csv", dtype=str)
    cat = cat[cat["is_sample"] == "True"].drop_duplicates(["org_id", "tbl_id"])
    out_dir = SAMPLE / "out"
    out_dir.mkdir(exist_ok=True)
    profs, failed = [], []
    for r in cat.itertuples():
        try:
            p = mp.table_profile(r)
            pq = SAMPLE / "data" / f"{r.org_id}_{r.tbl_id}.parquet"     # 수치 데이터는 parquet (없으면 쓰일 때 받음)
            p["raw"] = {"exists": pq.exists(), "mb": round(pq.stat().st_size / 2**20, 1) if pq.exists() else None}
            profs.append(p)
        except Exception as e:
            failed.append((r.tbl_id, str(e)[:150]))
    with (out_dir / "meta_profiles.jsonl").open("w", encoding="utf-8") as f:
        for p in profs:
            f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
    print(f"프로필 {len(profs)}개 | 실패 {len(failed)} | 메타 비어 있음 {sum(not p['meta_ok'] for p in profs)} | "
          f"수치 데이터 있음 {sum(p['raw']['exists'] for p in profs)} | 조사구분 {sorted({p['survey_type'] for p in profs})}")
    for x in failed[:10]:
        print("  실패:", x)


if __name__ == "__main__":
    main()
