"""
표본 표 크기 계산 — 4만 셀 넘는 표 중 무엇을 미리 받을지 판단하는 근거

표마다 (메타의 분류 코드 수를 모두 곱한 '최대' 셀 수 — 실제로 없는 조합이 있어 받아 보면 더 적을 수 있음)
  전체      = 항목 수 × 분류 코드 수의 곱 × 시점 수
  시점1     = 시점 하나만
  시도1     = 시점 하나 + 지역 분류를 '가장 큰 시도 하나의 하위 지역' 으로 좁힌 양 (시도 하나를 묻는 보통 질문)
  요청_전체 = 전체 ÷ 40,000 (올림)  — 4만 셀씩 나눠 받는 최소 요청 수
  판단      = 미리받기 후보 (시도1 > 4만: 질문 하나에도 여러 번 나눠 받아야 함) / 지연수집 (그 외)

입력  table_cards/sample_meta/*.json, storage/kosis_data/catalog.csv (표 이름·경로)
출력  table_cards/sample/size_report.csv

실행  저장소 루트에서:  .venv/Scripts/python.exe table_cards/scripts/size_report.py
"""
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "sample"     # 표본 표 작업 폴더 (메타는 ../sample_meta)
SAMPLE.mkdir(exist_ok=True)
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import pandas as pd                                                                  # noqa: E402

from backend.core.config import KOSIS_DATA_DIR                                      # noqa: E402
from backend.rag.ingestion.normalize import build_level_dims, parse_meta           # noqa: E402
from step1_split import sido_std, NOT_REGION_AXIS                                   # noqa: E402  (읽기만)

LIMIT = 40_000
SEC_PER_REQ = 1.5          # 요청 1번 평균 (속도 제한 0.33초 + 응답 대기) — 메타 수집 실측 표당 1.7초/5요청보다 넉넉히


def sido_slice(info, rows):
    """지역 분류를 시도 하나로 좁혔을 때 코드 수 (가장 큰 시도 기준). 지역이 아니면 None"""
    if info["kind"] == "regions":
        by = {r["code"]: r for r in rows}

        def top(r, seen=()):
            if r["geo_type"] == "시도":
                return r["std"]
            p = by.get(r["parent"])
            return None if p is None or r["code"] in seen else top(p, seen + (r["code"],))
        cnt = Counter(t for r in rows if (t := top(r)))
        return max(cnt.values()) if cnt else 1
    if not NOT_REGION_AXIS.search(info["obj_nm"]) and sum(bool(sido_std(r["name"])) for r in rows) >= 3:
        return 1                                     # 시도 목록인 '기타' 분류 (현거주지별 등) → 시도 하나
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cat = pd.read_csv(KOSIS_DATA_DIR / "catalog.csv", dtype=str)
    cat = cat[cat["is_sample"] == "True"].drop_duplicates(["org_id", "tbl_id"]).set_index("tbl_id")
    out = []
    for f in sorted((HERE.parent / "sample_meta").glob("*.json")):
        org, tbl = f.stem.split("_", 1)
        meta = json.loads(f.read_text(encoding="utf-8"))
        levels, items = parse_meta(meta)
        dims = [build_level_dims(i + 1, l) for i, l in enumerate(levels)]
        n_items = max(1, len(items))
        prd = [p for p in meta.get("PRD") or [] if isinstance(p, dict) and "_error" not in p]
        years = sorted({int(str(p.get(k, ""))[:4]) for p in prd for k in ("STRT_PRD_DE", "END_PRD_DE")
                        if str(p.get(k, ""))[:4].isdigit()})
        n_prd = max(1, len(years)) if years else 1
        full_codes = math.prod(max(1, info["n_codes"]) for info, _ in dims) if dims else 1
        sl = [sido_slice(info, rows) for info, rows in dims]
        sido_codes = math.prod(s if s is not None else max(1, info["n_codes"]) for s, (info, _) in zip(sl, dims)) if dims else 1
        per_prd = n_items * full_codes
        per_sido = n_items * sido_codes
        total = per_prd * n_prd
        r = cat.loc[tbl] if tbl in cat.index else None
        out.append({"tbl_id": tbl, "org_id": org,
                    "제목": (r["tbl_nm"] if r is not None else ""),
                    "조사연도": years[-1] if years else "",
                    "분류": " / ".join(f"{info['obj_nm']}({info['n_codes']})" for info, _ in dims),
                    "항목수": len(items), "지역분류": sum(s is not None for s in sl),
                    "전체": total, "시점1": per_prd, "시도1": per_sido,
                    "요청_전체": math.ceil(total / LIMIT),
                    "판단": "미리받기 후보" if per_sido > LIMIT else ("지연수집(큰 표)" if total > LIMIT else "지연수집")})

    with (SAMPLE / "size_report.csv").open("w", encoding="utf-8-sig", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(sorted(out, key=lambda x: -x["시도1"]))

    df = pd.DataFrame(out)
    big = df[df["전체"] > LIMIT]
    cand = df[df["판단"] == "미리받기 후보"]
    hr = lambda reqs: f"{reqs:,}번 ≈ {reqs * SEC_PER_REQ / 3600:.1f}시간"
    print(f"표본 표 {len(df)}개")
    print(f"  4만 셀 이하 (한 번에 받음)          : {(df['전체'] <= LIMIT).sum()}개")
    print(f"  4만 셀 초과                          : {len(big)}개 → 전부 미리 받기: 요청 {hr(int(big['요청_전체'].sum()))}")
    print(f"  └ 시도 하나로 좁혀도 4만 초과 (후보) : {len(cand)}개 → 미리 받기: 요청 {hr(int(cand['요청_전체'].sum()))}")
    print("\n조사연도별 (전체 / 4만 초과 / 후보 / 후보 요청 수)")
    for y, g in df.groupby("조사연도"):
        c = g[g["판단"] == "미리받기 후보"]
        print(f"  {y}: {len(g):4d} / {int((g['전체'] > LIMIT).sum()):4d} / {len(c):4d} / {int(c['요청_전체'].sum()):,}")
    print("\n후보 상위 8개 (시도 하나 기준 셀 수)")
    for _, x in cand.sort_values("시도1", ascending=False).head(8).iterrows():
        print(f"  {x['tbl_id']:<14} {x['조사연도']}  시도1 {x['시도1']:>10,}  전체 {x['전체']:>11,}  {x['제목'][:30]}  [{x['분류'][:60]}]")
    print(f"\n저장 → {HERE / 'size_report.csv'}")


if __name__ == "__main__":
    main()
