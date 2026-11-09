"""
[NEW v4] 원본 CSV 한 개 → 표 구조 (TableScan) — 행·열 머리와 고유 값을 직접 스캔

KOSIS 원본 CSV 열:  ORG_ID TBL_ID TBL_NM  C1 C1_NM C1_OBJ_NM … C8 …  ITM_ID ITM_NM UNIT_NM  PRD_SE PRD_DE  DT  LST_CHN_DE
  - 열(column) 머리 : CSV 헤더 + 분류 이름(C{i}_OBJ_NM, 예: '행정구역(시도)별')
  - 행(row) 값      : 분류 코드·이름(C{i}, C{i}_NM), 항목(ITM_ID, ITM_NM, UNIT_NM), 시점(PRD_SE, PRD_DE)
분류 종류·지역 표준명·연령 범위는 기존 normalize 규칙(level_kind, std_geo_name, geo_type_of, parse_age)을 그대로 씀
→ 질의 쪽 슬롯과 View 쪽 데이터가 같은 기준으로 비교됨

메타 JSON 은 '주석(CMMT)·조사명(SOURCE)·단위(UNIT_NM 이 비었을 때)'만 읽음 (구조는 원본 CSV 가 근거)
"""
import json
import re
from pathlib import Path

from backend.core.utils import norm_space, sql_str
from backend.rag.ingestion.normalize import STRONG_TOTAL, geo_type_of, level_kind, parse_age, std_geo_name

MAX_VALUES_PER_DIM = 3000          # tables.jsonl 에 남길 분류 값 수 상한 (역색인 values.parquet 에는 전부)
NUM = "try_cast(replace(DT, ',', '') AS DOUBLE)"
KIND_SLOT = {"regions": "지역", "sex": "성별", "ages": "연령", "nationality": "국적"}   # 나머지 분류 = '분류'


def _meta(path):
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def footnotes_of(meta):
    """메타 CMMT → [{type, target, text}] (통계표·분류·항목 주석 모두)"""
    out = []
    for c in meta.get("CMMT") or []:
        if not isinstance(c, dict) or not norm_space(c.get("CMMT_DC")):
            continue
        target = next((norm_space(c.get(k)) for k in ("ITM_NM", "OBJ_NM", "C1_NM", "CHAR_ITM_NM") if norm_space(c.get(k))), "")
        out.append({"type": norm_space(c.get("CMMT_NM")) or "주석", "target": target, "text": norm_space(c.get("CMMT_DC"))})
    return out


def survey_of(meta, fallback):
    src = meta.get("SOURCE") or []
    nm = norm_space((src[0] if src and isinstance(src[0], dict) else {}).get("JOSA_NM"))
    return nm.strip("「」") or fallback


def scan_kosis_csv(con, ref):
    raw = Path(ref.raw_path)
    src = f"read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)"
    cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
    meta = _meta(ref.meta_path)
    lv = [i for i in range(1, 9) if f"C{i}" in cols]
    n_rows = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]

    dims = []
    for i in lv:
        nm_col = f"C{i}_NM" if f"C{i}_NM" in cols else f"C{i}"
        obj = (con.execute(f"SELECT any_value(C{i}_OBJ_NM) FROM {src}").fetchone()[0]
               if f"C{i}_OBJ_NM" in cols else None) or f"분류{i}"
        rows = con.execute(f"SELECT C{i}, any_value({nm_col}), count(*), count({NUM}) FROM {src} "
                           f"GROUP BY 1 ORDER BY 1").fetchall()
        names = [norm_space(r[1]) for r in rows]
        kind = level_kind(obj, names)
        values = []
        for code, name, n, nv in rows:
            name = norm_space(name)
            v = {"code": str(code), "name": name, "n": int(n), "n_value": int(nv)}
            if kind == "regions":
                std = std_geo_name(name)
                v.update(std=std, geo=geo_type_of(name, std, name in STRONG_TOTAL))
            elif kind == "ages":
                a, b = parse_age(name)
                v.update(age_from=a, age_to=b)
            values.append(v)
        dims.append({"level": i, "obj_nm": norm_space(obj), "kind": kind, "slot": KIND_SLOT.get(kind, "분류"),
                     "n_values": len(values), "values": values})

    unit_meta = norm_space(next((u.get("UNIT_NM") for u in meta.get("UNIT") or [] if isinstance(u, dict)), "")) \
        if isinstance(meta.get("UNIT"), list) else ""
    unit_col = "any_value(UNIT_NM)" if "UNIT_NM" in cols else "NULL"
    items = []
    if "ITM_ID" in cols:
        nm_col = "ITM_NM" if "ITM_NM" in cols else "ITM_ID"
        for itm, name, unit, n, nv in con.execute(
                f"SELECT ITM_ID, any_value({nm_col}), {unit_col}, count(*), count({NUM}) FROM {src} GROUP BY 1 ORDER BY 1"
        ).fetchall():
            items.append({"itm_id": str(itm), "name": norm_space(name), "unit": norm_space(unit) or unit_meta,
                          "n": int(n), "n_value": int(nv)})

    periods, years = {}, set()
    if "PRD_DE" in cols:
        se = "coalesce(nullif(trim(PRD_SE), ''), 'Y')" if "PRD_SE" in cols else "'Y'"
        for s, d in con.execute(f"SELECT DISTINCT {se}, PRD_DE FROM {src} WHERE {NUM} IS NOT NULL ORDER BY 1, 2").fetchall():
            d = re.sub(r"\D", "", str(d))
            periods.setdefault(str(s), []).append(d)
            if len(d) >= 4:
                years.add(int(d[:4]))
    return {"tbl_id": ref.tbl_id, "tbl_nm": ref.tbl_nm, "org_id": ref.org_id, "category": ref.category,
            "survey_nm": survey_of(meta, ref.category), "menu_path": ref.menu_path, "selected": ref.selected,
            "raw_path": ref.raw_path, "n_rows": int(n_rows), "columns": cols,
            "dims": [{**d, "values": d["values"][:MAX_VALUES_PER_DIM]} for d in dims], "items": items,
            "periods": periods, "years": sorted(years), "footnotes": footnotes_of(meta),
            "_all_dim_values": dims}
