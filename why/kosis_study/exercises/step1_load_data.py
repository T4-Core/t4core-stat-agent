"""
STEP 1 (학습용) — 수집한 CSV와 메타데이터를 직접 열어보고 연결하기

kosis_rag_builder.py 가 만든 결과물은 3가지입니다.
  kosis_data/catalog.csv                       어떤 통계표들이 있는지 (목록)
  kosis_data/raw/<조사이름>/<기관_표>.csv       실제 숫자 데이터
  kosis_data/meta/<기관_표>.json                표 설명서 (분류·항목·시점·주석)

세 파일은 org_id, tbl_id 로 연결됩니다. 이번 단계는 '주택' 관련 표 하나를 골라
세 파일을 직접 열어 보고, 숫자 데이터의 코드가 메타의 코드와 맞는지 확인합니다.

👉 할 일: 아래 TODO 를 채우세요. 채우기 전에 파일을 직접 열어 보는 걸 추천합니다.
   - catalog.csv 를 엑셀/VSCode 로 열어 어떤 컬럼이 있는지
   - raw CSV 하나를 열어 C1, C1_NM, ITM_ID, PRD_DE, DT 컬럼이 무엇인지
   - meta JSON 하나를 열어 "ITM" 안의 OBJ_ID, OBJ_NM, ITM_ID, ITM_NM 이 무엇인지

실행: python step1_load_data.py
     (다른 표를 보고 싶으면)  TABLE_INDEX=3 python step1_load_data.py
막히면: ../solutions/step1_load_data.py
"""
import json
import os
import re
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.getenv("KOSIS_DATA", "kosis_data"))
KEYWORD = "주택"


def safe(name):
    """kosis_rag_builder.py 가 폴더 이름을 만들 때 쓴 규칙 (공백·특수문자 → _). 그대로 써야 경로가 맞습니다."""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


# ─────────────── 1-1. 목록(catalog) 읽기 ───────────────
def load_catalog():
    # TODO(1-1a): DATA_DIR / "catalog.csv" 를 읽고, selected 컬럼이 "True" 인 행만 남겨 반환하세요.
    # 힌트: pd.read_csv(..., dtype=str)  ← 모든 값을 문자열로 읽어야 "True" 와 비교할 수 있습니다.
    #       마지막에 .reset_index(drop=True)
    raise NotImplementedError("TODO 1-1a")


def find_tables(cat, keyword=KEYWORD):
    # TODO(1-1b): category(조사 이름) 또는 tbl_nm(표 이름)에 keyword 가 들어간 행만 반환하세요.
    # 힌트: cat["category"].str.contains(keyword, na=False)  →  True/False 시리즈
    #       두 조건을 | (또는)로 묶고 cat[mask]
    raise NotImplementedError("TODO 1-1b")


# ─────────────── 1-2. 표 1개의 파일 경로 만들기 ───────────────
def raw_path(row):
    # TODO(1-2a): raw CSV 경로를 만드세요.
    # 모양: DATA_DIR / "raw" / <safe(조사이름)> / "<org_id>_<tbl_id>.csv"
    # 힌트: row["category"], row["org_id"], row["tbl_id"]
    raise NotImplementedError("TODO 1-2a")


def meta_path(row):
    # TODO(1-2b): meta JSON 경로를 만드세요.   모양: DATA_DIR / "meta" / "<org_id>_<tbl_id>.json"
    raise NotImplementedError("TODO 1-2b")


def with_raw(tables):
    """실제로 숫자 데이터(raw CSV)가 받아져 있는 표만 남기기 (완성되어 있음)"""
    ok = tables.apply(lambda r: raw_path(r).exists(), axis=1)
    return tables[ok].reset_index(drop=True)


def load_raw(row):
    # TODO(1-2c): raw CSV 를 DataFrame 으로 읽어 반환하세요.
    # 힌트: dtype=str 로 읽어야 코드 '01' 의 앞자리 0 이 사라지지 않습니다.
    raise NotImplementedError("TODO 1-2c")


def load_meta(row):
    # TODO(1-2d): meta JSON 을 dict 로 읽어 반환하세요.
    # 힌트: json.loads(경로.read_text(encoding="utf-8"))
    raise NotImplementedError("TODO 1-2d")


# ─────────────── 1-3. 메타데이터 정리 ───────────────
def summarize_meta(meta):
    """메타 JSON → 사람이 보기 쉬운 dict
    ITM 안에는 '분류'(행정구역, 주택종류 …)와 '항목'(주택수, 가구수 …)이 섞여 있는데,
    OBJ_ID == 'ITEM' 이면 항목, 나머지는 분류입니다."""
    tbl_rows = [r for r in meta.get("TBL") or [] if isinstance(r, dict) and "_error" not in r]
    tbl_nm = tbl_rows[0].get("TBL_NM", "") if tbl_rows else ""

    dims, items = {}, []
    for r in meta.get("ITM") or []:
        if not isinstance(r, dict) or "_error" in r:
            continue
        # TODO(1-3): r 을 항목(items) 또는 분류(dims) 중 한 곳에 넣으세요.
        #   항목이면  items.append({"id": ITM_ID, "name": ITM_NM, "unit": UNIT_NM(없으면 "")})
        #   분류이면  dims[OBJ_NM] 리스트에 {"code": ITM_ID, "name": ITM_NM} 추가
        # 힌트: r.get("OBJ_ID") == "ITEM" 으로 구분.  코드는 str(...) 로 감싸 문자열로 통일
        #       dims.setdefault(키, []).append(...)  → 키가 없으면 빈 리스트를 만들고 추가
        raise NotImplementedError("TODO 1-3")

    periods = []
    for r in meta.get("PRD") or []:
        if not isinstance(r, dict) or "_error" in r:
            continue
        for k in ("PRD_DE", "STRT_PRD_DE", "END_PRD_DE"):
            if r.get(k):
                periods.append(str(r[k]))

    comments = [str(v).strip() for r in meta.get("CMMT") or [] if isinstance(r, dict)
                for k, v in r.items() if k != "_error" and isinstance(v, str) and len(v.strip()) > 4]

    return {"tbl_nm": tbl_nm, "dims": dims, "items": items,
            "period": f"{min(periods)}~{max(periods)}" if periods else "",
            "comment": " ".join(dict.fromkeys(comments))}


# ─────────────── 1-4. 데이터 ↔ 메타 연결 확인 ───────────────
def check_link(raw, summary):
    """raw CSV 의 코드(C1, ITM_ID)가 메타에 정의된 코드와 얼마나 맞는지"""
    # TODO(1-4): 아래 4개의 집합(set)을 만드세요.
    #   meta_codes : summary["dims"] 안의 모든 code
    #   raw_codes  : raw["C1"] 의 값들 (결측 제외, 문자열)
    #   meta_items : summary["items"] 의 id
    #   raw_items  : raw["ITM_ID"] 의 값들
    # 힌트: set(raw["C1"].dropna().astype(str)),  {c["code"] for codes in ... for c in codes}
    raise NotImplementedError("TODO 1-4")
    return {"분류코드(C1) 연결": f"{len(raw_codes & meta_codes)}/{len(raw_codes)}",
            "항목코드(ITM_ID) 연결": f"{len(raw_items & meta_items)}/{len(raw_items)}"}


def main():
    cat = load_catalog()
    houses = with_raw(find_tables(cat))
    print(f"선택된 표 {len(cat)}개 중 '{KEYWORD}' 관련 + 데이터 있는 표 {len(houses)}개")
    if houses.empty:
        print("→ 표가 없습니다. KOSIS_DATA 경로나 KEYWORD 를 확인하세요.")
        return
    print(houses[["category", "tbl_id", "tbl_nm"]].head(10).to_string())

    row = houses.iloc[int(os.getenv("TABLE_INDEX", 0))]
    raw, meta = load_raw(row), load_meta(row)

    print(f"\n=== 선택한 표: {row['tbl_nm']} ({row['tbl_id']}) ===")
    print(f"[raw CSV] 모양 {raw.shape}")
    print(f"컬럼: {list(raw.columns)}")
    print(raw.head(5).to_string())

    print(f"\n[meta JSON] 키: {list(meta.keys())}")
    s = summarize_meta(meta)
    print(f"표 이름: {s['tbl_nm']}")
    for obj_nm, codes in s["dims"].items():
        print(f"분류 '{obj_nm}' ({len(codes)}개): {', '.join(c['name'] for c in codes[:8])} ...")
    print(f"항목: {[(it['name'], it['unit']) for it in s['items'][:5]]}")
    print(f"수록기간: {s['period']}")
    print(f"주석: {s['comment'][:150]}")

    print(f"\n[연결 확인] {check_link(raw, s)}")
    # ✅ 확인: '분류코드 연결'이 n/n 처럼 거의 전부 맞으면 raw ↔ meta 연결 성공입니다.
    # 🤔 생각해 보기: C2, C3 컬럼은 meta 의 어느 분류와 연결될까요?


if __name__ == "__main__":
    main()
