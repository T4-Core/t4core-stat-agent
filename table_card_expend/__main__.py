"""
table_card_expend 실행 — 저장소 루트에서

  python -m table_card_expend all --set full                      # 전수·인구 14개 조사 (storage/kosis_data, selected)
  python -m table_card_expend all --set sample                    # 표본 표 (kosis_fetch 로 받은 폴더)
  python -m table_card_expend all --set full --llm hcx --workers 4  # 설명을 HCX 로 (기본 template)
  python -m table_card_expend split --set full --limit 20         # 단계별: split → describe → assemble
  옵션  --scope all (selected 아닌 원본 CSV 표까지) · --tables DT_A DT_B · --no-csv-index · --out <폴더>

출력  table_card_expend/out/<set>/  conditions.jsonl · pieces.jsonl · descriptions.jsonl · cards.jsonl
                                    split_report.txt · report.txt · unmapped.csv · cache/scan/
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_ROOT = ROOT / "table_card_expend" / "out"


def _load(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["tbl_id"]] = r
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m table_card_expend")
    ap.add_argument("stage", choices=["split", "describe", "assemble", "all"])
    ap.add_argument("--set", dest="set_name", default="full", choices=["full", "sample"])
    ap.add_argument("--scope", default="selected", choices=["selected", "all"])
    ap.add_argument("--tables", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--llm", default="template", choices=["template", "hcx"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="LLM 설명 캐시 무시")
    ap.add_argument("--no-csv-index", action="store_true", help="기존 CSV 값 사전(tables.jsonl) 재사용 안 함")
    ap.add_argument("--out", default=None)
    ap.add_argument("--table-card-dir", default=None, help="보고서에서 비교할 table_card 결과 폴더 (기본 table_cards/full|sample_cards)")
    a = ap.parse_args(argv)

    from table_card_expend import assemble, describe, split
    from table_card_expend.sources import list_tables, scan_all
    out = Path(a.out) if a.out else OUT_ROOT / a.set_name
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if a.stage in ("split", "all"):
        tables = list_tables(a.set_name, a.scope, a.limit, a.tables)
        print(f"[split] {a.set_name} 표 {len(tables)}개", flush=True)
        scans, stat, errors = scan_all(tables, out / "cache" / "scan", a.workers, not a.no_csv_index,
                                       log=lambda m: print(m, flush=True))
        print(f"  원본 CSV: {stat}", flush=True)
        for e in errors[:10]:
            print("  스캔 실패", e)
        split.run(tables, scans, out, log=print)
    if a.stage in ("describe", "all"):
        P, C = _load(out / "pieces.jsonl"), _load(out / "conditions.jsonl")
        print(f"[describe] {len(P)}개 ({a.llm})", flush=True)
        describe.run(P, C, out, a.llm, a.workers, a.force, log=print)
    if a.stage in ("assemble", "all"):
        P, C, D = _load(out / "pieces.jsonl"), _load(out / "conditions.jsonl"), _load(out / "descriptions.jsonl")
        print("[assemble]", flush=True)
        assemble.run(P, C, D, out, a.set_name, log=print, table_card_dir=a.table_card_dir)
    print(f"완료 {time.time() - t0:.1f}초 → {out}")


if __name__ == "__main__":
    main()
