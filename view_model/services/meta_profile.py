"""
[엔드포인트 0] meta_profile — 카탈로그 전체(992개 표)의 메타 JSON 만 읽어 가벼운 표 프로필 생성

입력  kosis_data/catalog.csv (selected == True), kosis_data/meta/<기관_표>.json   (원본 CSV 는 읽지 않음)
출력  view_model/output/meta_profiles.jsonl   한 줄 = 표 하나

용도  ③ resolve 가 "어떤 표로 답할지" 고를 때의 탐색 범위. 표를 미리 정하지 않고 전체에서 찾기 위함
      고른 표만 normalize.ensure_normalized() 로 정규화하고, 실제 parquet 프로필로 조건을 다시 확인한다

실행  API : POST /meta/profiles/build  (routers/meta.py)
      CLI : cd view_model && ../.venv/Scripts/python.exe -m services.meta_profile

주의  메타는 "정의된 코드·시점" 이라 실제 수집 데이터와 다를 수 있음 (예: 메타 주기에 월이 있어도 원본에 월 자료 없음)
      그래서 모든 값은 사실 기록만 하고 점수·판단은 하지 않는다 (판단은 resolve 의 일)
"""
import json
import sys
from collections import Counter

import pandas as pd

from config import DATA, OUT, norm_space, safe
from services.normalize import PRD_SE_MAP, build_level_dims, parse_meta

SAMPLE_NAMES = 300       # 분류마다 기록할 코드 이름 상한 (지역은 전국·시도만 따로 전부 기록)


def se_std(se):
    # normalize.se_case_sql 과 같은 규칙의 파이썬판: 매핑 → 'N년' 은 F → 그 외 원본 유지
    s = norm_space(se)
    return PRD_SE_MAP.get(s) or ("F" if s.endswith("년") else (s or "Y"))


def year_of(prd_de):
    d = "".join(ch for ch in str(prd_de or "") if ch.isdigit())
    return int(d[:4]) if len(d) >= 4 else None


def meta_periods(meta):
    out = []
    for p in meta.get("PRD") or []:
        if not isinstance(p, dict):
            continue
        out.append({"se": se_std(p.get("PRD_SE")), "se_raw": norm_space(p.get("PRD_SE")),
                    "start": p.get("STRT_PRD_DE"), "end": p.get("END_PRD_DE"),
                    "year_from": year_of(p.get("STRT_PRD_DE")), "year_to": year_of(p.get("END_PRD_DE"))})
    return out


def level_summary(info, rows):
    # build_level_dims 결과(코드별 행) → 표 선택에 필요한 요약만
    name_of = {r["code"]: r["std"] for r in rows}
    s = {"obj_id": info["obj_id"], "obj_nm": info["obj_nm"], "kind": info["kind"], "role": info["role"],
         "n_codes": info["n_codes"], "total": name_of.get(info["total_code"]),
         "default": name_of.get(info["default_code"]), "default_reason": info["default_reason"]}
    if info["kind"] == "regions":
        s["geo_types"] = dict(Counter(r["geo_type"] for r in rows))
        s["sido"] = sorted({r["std"] for r in rows if r["geo_type"] == "시도"})
        s["names"] = [r["name"] for r in rows if r["geo_type"] in ("전국", "시도", "동읍면부", "기타")][:SAMPLE_NAMES]
    else:
        s["names"] = [r["name"] for r in rows][:SAMPLE_NAMES]
    if info["kind"] == "ages":
        ages = [(r["age_from"], r["age_to"]) for r in rows if r["age_from"] is not None]
        s["ages"] = [{"name": r["name"], "from": r["age_from"], "to": r["age_to"]} for r in rows if r["age_from"] is not None]
        s["age_min"] = min((a for a, _ in ages), default=None)
        s["age_max"] = None if any(b is None for _, b in ages) else max((b for _, b in ages), default=None)
    if info["kind"] == "scenario":
        s["scenarios"] = [r["std"] for r in rows]
    return s


def cat(v):
    # 카탈로그 빈 칸(NaN) → None. NaN 은 JSON 표준이 아니라 다른 도구에서 파일이 깨짐
    return None if pd.isna(v) else v


def table_profile(row):
    key = f"{row.org_id}_{row.tbl_id}"
    mp = DATA / "meta" / f"{key}.json"
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    raw = DATA / "raw" / safe(row.category) / f"{key}.csv"
    levels_meta, items_meta = parse_meta(meta)
    levels = [level_summary(*build_level_dims(n, lv)) for n, lv in enumerate(levels_meta, 1)]
    notes = [norm_space(c.get("CMMT_DC")) for c in (meta.get("CMMT") or [])
             if isinstance(c, dict) and c.get("CMMT_NM") == "통계표" and norm_space(c.get("CMMT_DC"))]
    source = next((s for s in (meta.get("SOURCE") or []) if isinstance(s, dict)), {})
    return {
        "table_key": key, "org_id": row.org_id, "tbl_id": row.tbl_id, "tbl_nm": norm_space(row.tbl_nm),
        "category": cat(row.category), "section": cat(row.section), "path": cat(row.path),
        "survey_nm": norm_space(source.get("JOSA_NM", "")).strip("「」") or row.category,
        "survey_type": cat(row.survey_type), "send_de": cat(row.send_de),
        "also_in": cat(row.also_in) or "",
        "meta_ok": bool(meta.get("ITM")),
        "raw": {"exists": raw.exists(), "mb": round(raw.stat().st_size / 2**20, 1) if raw.exists() else None},
        "periods": meta_periods(meta),
        "levels": levels,
        "items": [{"itm_id": i["itm_id"], "name": i["name"], "unit": i["unit"]} for i in items_meta],
        "units": sorted({i["unit"] for i in items_meta if i["unit"]}),
        "notes": list(dict.fromkeys(notes))[:5],
        "profile_from": "meta",
    }


def load_meta_profiles():
    # resolve 등에서 쓰는 읽기 함수
    p = OUT / "meta_profiles.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_all():
    # 카탈로그 전체 → meta_profiles.jsonl, 결과 요약 반환 (API·CLI 공용)
    catalog = pd.read_csv(DATA / "catalog.csv", dtype=str)
    catalog = catalog[catalog["selected"] == "True"]
    OUT.mkdir(parents=True, exist_ok=True)
    profs, failed = [], []
    for r in catalog.itertuples():
        try:
            profs.append(table_profile(r))
        except Exception as e:   # 표 하나 실패해도 계속
            failed.append({"tbl_id": r.tbl_id, "error": str(e)[:150]})
    out = OUT / "meta_profiles.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for p in profs:
            f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
    return {
        "file": str(out), "n_tables": len(profs), "failed": failed,
        "n_meta_empty": sum(not p["meta_ok"] for p in profs),
        "n_raw_missing": sum(not p["raw"]["exists"] for p in profs),
        "kinds": dict(Counter(l["kind"] for p in profs for l in p["levels"]).most_common()),
        "n_with_regions": sum(any(l["kind"] == "regions" for l in p["levels"]) for p in profs),
        "n_with_sido": sum(any(l.get("sido") for l in p["levels"]) for p in profs),
        "periods": dict(Counter(pr["se"] for p in profs for pr in p["periods"]).most_common()),
        "n_no_unit": sum(not p["units"] for p in profs),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = build_all()
    print(f"[메타 프로필] 표 {s['n_tables']}개 → {s['file']}  (실패 {len(s['failed'])})")
    print("  메타 없음/비어 있음:", s["n_meta_empty"], "| 원본 CSV 없음:", s["n_raw_missing"])
    print("  분류 종류:", s["kinds"])
    print("  지역 분류가 있는 표:", s["n_with_regions"], "| 시도 표준명이 있는 표:", s["n_with_sido"])
    print("  주기:", s["periods"])
    print("  단위 없음:", s["n_no_unit"])
    for f in s["failed"][:10]:
        print("  ✗", f["tbl_id"], f["error"])


if __name__ == "__main__":
    main()
