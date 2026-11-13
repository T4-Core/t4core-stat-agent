"""KOSIS RAW CSV + meta JSON Adapter, 그리고 방식 B(RAW 기반) View 생성기.

입력 (collector.py 출력 구조, 읽기 전용):
  <data_root>/catalog.csv                 (선택) category=조사명, org_id, tbl_id, tbl_nm, path, survey_type …
  <data_root>/meta/<ORG>_<TBL>.json       (선택) {"TBL": [...], "ITM": [...], "PRD": [...], "CMMT": [...], "SOURCE": [...]}
  <data_root>/raw/<조사명>/<ORG>_<TBL>.csv  원본: ORG_ID, TBL_ID, TBL_NM, C1~C8(+_NM, _OBJ_NM), ITM_ID, ITM_NM, UNIT_NM,
                                          PRD_SE, PRD_DE, DT
  <data_root>/store/data/<ORG>_<TBL>.parquet (선택, raw 가 없을 때) tidy: prd_se, prd_de, cN_code, cN_name, itm_id …

원칙
  - C1 이 지역, C2 가 성별이라고 가정하지 않는다: OBJ_NM 키워드 + 메타 ITM(OBJ_ID_SN)로 분류 의미를 정한다.
  - 표 ID 는 DT_ 뿐 아니라 INH_ 등 모든 형태를 허용한다 (파일명 첫 '_' 앞 = 기관 ID).
  - 원본 행 번호(_src_row)는 1부터, 헤더 제외.
  - 생성된 View 는 출력 폴더(outputs/generated_views/)에만 쓴다. 원본 폴더에는 쓰지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from synthetic_gold_pipeline.schemas.metadata import (DimensionCode, DimensionDefinition, DimensionType,
                                                       IndicatorDefinition, InputMode, MetadataCompleteness,
                                                       ObservationType, TableMetadata, ViewMetadata, ViewSelector)
from synthetic_gold_pipeline.tools.units import unit_info
from synthetic_gold_pipeline.utils import (display_path, ensure_inside, normalize_frequency, norm_text,
                                           safe_name, sha256_file, sha256_text, period_sort_key)

log = logging.getLogger(__name__)

LEVELS = [f"C{i}" for i in range(1, 9)]
CANON_COLS = (["ORG_ID", "TBL_ID", "TBL_NM"]
              + [f"{lv}{s}" for lv in LEVELS for s in ("", "_NM", "_OBJ_NM")]
              + ["ITM_ID", "ITM_NM", "UNIT_NM", "PRD_SE", "PRD_DE", "DT"])
PROV_COLS = ["_src_row"]
KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}"

DEFAULT_DIM_KEYWORDS: dict[str, list[str]] = {
    "SCENARIO": [r"시나리오", r"가정별", r"추계\s*구분", r"전망\s*구분"],
    "REGION": [r"행정구역", r"시도", r"시군구", r"지역", r"읍면동", r"권역"],
    "SEX": [r"성별", r"^성$", r"남녀"],
    "AGE": [r"연령", r"나이", r"\d+세별"],
    "NATIONALITY": [r"국적", r"국가별"],
    "INDUSTRY": [r"산업", r"업종"],
    "HOUSEHOLD": [r"가구"],
}
DEFAULT_TOTAL_PATTERN = r"^(계|합계|총계|소계|전체|전국|총인구|총수|Total|전\s?연령|남녀\s?전체)$"
DEFAULT_SYMBOL_MEANINGS = {"-": "해당 숫자 없음", "X": "비밀보호를 위해 공표하지 않음", "x": "비밀보호를 위해 공표하지 않음",
                           "*": "자료 신뢰도 낮음 또는 비공개", "…": "미상", "": "값 없음(빈 칸)"}


class AdapterError(Exception):
    pass


@dataclass
class TableRef:
    org_id: str
    tbl_id: str
    key: str
    data_path: Path
    data_kind: str                 # raw_csv | store_parquet
    meta_path: Path | None
    catalog: dict[str, Any] = field(default_factory=dict)
    survey_hint: str = ""


@dataclass
class LoadedTable:
    meta: TableMetadata
    df: pd.DataFrame                # 표준 컬럼(CANON_COLS 중 존재하는 것) + _src_row, 모두 문자열


def as_string_frame(df: pd.DataFrame) -> pd.DataFrame:
    """모든 컬럼을 문자열로 (결측은 빈 문자열). 이미 문자열이고 결측이 없는 컬럼(CSV dtype=str)은 그대로 둔다.
    셀마다 Python 함수를 부르지 않도록 컬럼 단위로만 변환한다."""
    df = df.copy()
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_string_dtype(col) and not col.isna().any():
            continue
        df[c] = col.astype(str).where(col.notna(), "")
    return df


def _arrow_str(values: pd.Series, null_as: str | None = None):
    """pandas Series → pyarrow 문자열 배열 (컬럼 단위, 복사 최소화)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    arr = pa.array(values, from_pandas=True)
    if not pa.types.is_large_string(arr.type):
        arr = pc.cast(arr, pa.large_string())           # 컬럼마다 string/large_string 이 섞이지 않게 통일
    return pc.fill_null(arr, null_as) if null_as is not None else arr


def numeric_mask(values: pd.Series) -> np.ndarray:
    """parse_value(v).ok 의 벡터화 판 (결측 기호·NaN 문자열·빈 값은 False, 0 으로 바꾸지 않음)."""
    from synthetic_gold_pipeline.tools.units import _NUM, MISSING_SYMBOLS, NAN_STRINGS
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        t = pc.utf8_trim_whitespace(_arrow_str(values, ""))
        bad = pc.or_(pc.is_in(t, value_set=pa.array(sorted(MISSING_SYMBOLS | NAN_STRINGS | {""}))), pc.equal(t, ""))
        ok = pc.match_substring_regex(pc.replace_substring(t, " ", ""), _NUM.pattern)
        return pc.and_(ok, pc.invert(bad)).to_numpy(zero_copy_only=False).astype(bool)
    except ImportError:  # pragma: no cover - pyarrow 없을 때
        t = values.astype(str).where(values.notna(), "").str.strip()
        bad = t.isin(MISSING_SYMBOLS | NAN_STRINGS) | (t == "")
        ok = t.str.replace(" ", "", regex=False).str.match(_NUM.pattern)
        return (ok.fillna(False).astype(bool) & ~bad).to_numpy(dtype=bool)


def row_strings(df: pd.DataFrame) -> np.ndarray:
    """행마다 표준 컬럼 값을 이어 붙인 문자열 배열 (스냅샷 해시용, pyarrow 벡터 연산). 결측은 \\x00."""
    cols = [c for c in CANON_COLS if c in df.columns] + ["_src_row"]
    try:
        import pyarrow.compute as pc
        import pyarrow as pa
        joined = pc.binary_join_element_wise(*[_arrow_str(df[c], "\x00") for c in cols],
                                             pa.scalar("\x1f", pa.large_string()))
        return np.asarray(joined.to_pylist(), dtype=object)
    except ImportError:  # pragma: no cover
        parts = [df[c].astype(str).where(df[c].notna(), "\x00") for c in cols]
        return (parts[0].str.cat(parts[1:], sep="\x1f") if len(parts) > 1 else parts[0]).to_numpy(dtype=object)


def split_table_key(stem: str) -> tuple[str, str]:
    """'101_DT_1B040A3' → ('101', 'DT_1B040A3'), '101_INH_1B04005' → ('101', 'INH_1B04005')."""
    if "_" not in stem:
        raise AdapterError(f"기관ID_통계표ID 형식이 아님: {stem}")
    org, tbl = stem.split("_", 1)
    if not org or not tbl:
        raise AdapterError(f"기관ID_통계표ID 형식이 아님: {stem}")
    return org, tbl


def flatten_meta_text(rows: Any) -> list[str]:
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            if "_error" in r:
                continue
            txt = " ".join(str(v) for k, v in r.items() if v not in (None, "") and not str(k).endswith("_ID"))
            if txt.strip():
                out.append(norm_text(txt))
        elif r:
            out.append(norm_text(r))
    return out


class KosisRawAdapter:
    def __init__(self, data_root: str | Path, cfg: dict | None = None):
        self.root = Path(data_root).resolve()
        cfg = cfg or {}
        self.dim_keywords = cfg.get("dimension_keywords") or DEFAULT_DIM_KEYWORDS
        self.total_re = re.compile(cfg.get("total_name_pattern") or DEFAULT_TOTAL_PATTERN)
        self.population_rules = cfg.get("population_scope_rules") or []
        self.projection_re = re.compile(cfg.get("projection_pattern") or r"추계|전망|projection")
        self.max_rows = int(cfg.get("max_rows_per_table") or 2_000_000)
        self._catalog = self._read_catalog()

    # ── 탐색 ──────────────────────────────────────────────────────
    def _read_catalog(self) -> dict[tuple[str, str], dict]:
        p = self.root / "catalog.csv"
        if not p.exists():
            return {}
        cat = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        out = {}
        for r in cat.to_dict("records"):
            if r.get("org_id") and r.get("tbl_id"):
                out.setdefault((r["org_id"], r["tbl_id"]), r)
        return out

    def discover(self, only_selected: bool = False, include_tables: Iterable[str] | None = None) -> list[TableRef]:
        refs: dict[str, TableRef] = {}
        inc = set(include_tables or [])
        raw_root = self.root / "raw"
        for p in sorted(raw_root.rglob("*.csv")) if raw_root.exists() else []:
            try:
                org, tbl = split_table_key(p.stem)
            except AdapterError:
                log.warning("표 ID 를 해석할 수 없는 파일 건너뜀: %s", p)
                continue
            key = f"{org}_{tbl}"
            refs[key] = TableRef(org, tbl, key, p, "raw_csv", self._meta_path(key),
                                 self._catalog.get((org, tbl), {}), survey_hint=p.parent.name)
        store = self.root / "store" / "data"
        for p in sorted(store.glob("*.parquet")) if store.exists() else []:
            try:
                org, tbl = split_table_key(p.stem)
            except AdapterError:
                continue
            key = f"{org}_{tbl}"
            if key not in refs:
                refs[key] = TableRef(org, tbl, key, p, "store_parquet", self._meta_path(key),
                                     self._catalog.get((org, tbl), {}))
        out = []
        for key, ref in sorted(refs.items()):
            if inc and key not in inc and ref.tbl_id not in inc:
                continue
            if only_selected and ref.catalog and str(ref.catalog.get("selected", "True")).lower() == "false":
                continue
            out.append(ref)
        return out

    def _meta_path(self, key: str) -> Path | None:
        p = self.root / "meta" / f"{key}.json"
        return p if p.exists() else None

    # ── 로딩 ──────────────────────────────────────────────────────
    def read_frame(self, ref: TableRef) -> pd.DataFrame:
        if ref.data_kind == "raw_csv":
            df = pd.read_csv(ref.data_path, dtype=str, keep_default_na=False, encoding="utf-8-sig",
                             nrows=self.max_rows + 1)
        else:
            t = pd.read_parquet(ref.data_path)
            df = tidy_to_canonical(t, ref.org_id, ref.tbl_id)
        if len(df) > self.max_rows:
            raise AdapterError(f"{ref.key}: 행 수가 상한({self.max_rows})을 넘음")
        missing = [c for c in ("PRD_DE", "ITM_ID", "DT") if c not in df.columns]
        if missing:
            raise AdapterError(f"{ref.key}: 필수 컬럼 없음 {missing}")
        df = as_string_frame(df)
        df["_src_row"] = range(1, len(df) + 1)
        if "ORG_ID" not in df.columns or (df["ORG_ID"].fillna("") == "").all():
            df["ORG_ID"] = ref.org_id
        if "TBL_ID" not in df.columns or (df["TBL_ID"].fillna("") == "").all():
            df["TBL_ID"] = ref.tbl_id
        if "PRD_SE" not in df.columns:
            df["PRD_SE"] = ""
        for c in ("ITM_NM", "UNIT_NM", "TBL_NM"):
            if c not in df.columns:
                df[c] = ""
        return df

    def load(self, ref: TableRef) -> LoadedTable:
        df = self.read_frame(ref)
        meta_json = {}
        if ref.meta_path:
            try:
                meta_json = json.loads(ref.meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                log.warning("메타 JSON 읽기 실패 %s: %s", ref.meta_path, e)
        meta = self.build_table_metadata(ref, df, meta_json)
        return LoadedTable(meta, df)

    # ── 메타데이터 ────────────────────────────────────────────────
    def classify_dimension(self, obj_nm: str) -> tuple[DimensionType, str]:
        s = norm_text(obj_nm)
        for typ, pats in self.dim_keywords.items():
            for p in pats:
                if re.search(p, s):
                    return DimensionType(typ), f"OBJ_NM '{s}' ~ /{p}/"
        return DimensionType.OTHER, f"OBJ_NM '{s}' 키워드 없음"

    def _meta_levels(self, meta_json: dict) -> list[dict]:
        levels: dict[str, dict] = {}
        for r in meta_json.get("ITM") or []:
            if not isinstance(r, dict) or "_error" in r or r.get("OBJ_ID") == "ITEM":
                continue
            k = r.get("OBJ_ID")
            if k not in levels:
                levels[k] = {"obj_id": k, "obj_nm": r.get("OBJ_NM") or "", "sn": int(r.get("OBJ_ID_SN") or len(levels) + 1),
                             "codes": {}}
            levels[k]["codes"][str(r.get("ITM_ID"))] = {"nm": r.get("ITM_NM") or "", "up": r.get("UP_ITM_ID") or None}
        return sorted(levels.values(), key=lambda x: x["sn"])

    def build_table_metadata(self, ref: TableRef, df: pd.DataFrame, meta_json: dict) -> TableMetadata:
        cat = ref.catalog or {}
        notes: list[str] = []
        meta_levels = self._meta_levels(meta_json)
        csv_levels = [lv for lv in LEVELS if lv in df.columns and (df[lv].fillna("") != "").any()]
        # 메타 레벨 ↔ CSV 레벨 매핑: OBJ_NM 이 같으면 이름으로, 아니면 순서(OBJ_ID_SN)로
        by_name = {norm_text(m["obj_nm"]): m for m in meta_levels}
        dims: list[DimensionDefinition] = []
        codes: dict[str, list[DimensionCode]] = {}
        for i, lv in enumerate(csv_levels):
            obj_col = f"{lv}_OBJ_NM"
            obj_nm = ""
            if obj_col in df.columns:
                vals = [v for v in df[obj_col].dropna().unique() if v]
                obj_nm = vals[0] if vals else ""
                if len(vals) > 1:
                    notes.append(f"{lv}_OBJ_NM 값이 여러 개: {vals[:3]}")
            m = by_name.get(norm_text(obj_nm)) if obj_nm else None
            if m is None and i < len(meta_levels):
                m = meta_levels[i]
                if obj_nm and norm_text(m["obj_nm"]) != norm_text(obj_nm):
                    notes.append(f"{lv}: CSV OBJ_NM '{obj_nm}' ≠ 메타 '{m['obj_nm']}' (순서로 매핑)")
            obj_nm = obj_nm or (m["obj_nm"] if m else lv)
            dtype, basis = self.classify_dimension(obj_nm)
            meta_codes = (m or {}).get("codes", {})
            name_col = f"{lv}_NM"
            pairs = df[[lv] + ([name_col] if name_col in df.columns else [])].drop_duplicates()
            present: dict[str, str] = {}
            for r in pairs.itertuples(index=False):
                c = r[0]
                if c is None or c == "":
                    continue
                present.setdefault(str(c), str(r[1]) if len(r) > 1 and r[1] is not None else
                                   meta_codes.get(str(c), {}).get("nm", str(c)))
            parent = {c: (meta_codes.get(c, {}).get("up") or None) for c in present}
            all_parent = {c: v.get("up") for c, v in meta_codes.items()}
            all_parent.update({c: p for c, p in parent.items() if c not in all_parent})
            children = {p for p in all_parent.values() if p}

            def depth(c, seen=()):
                up = all_parent.get(c)
                if not up or up not in all_parent or c in seen or len(seen) > 20:
                    return 0
                return 1 + depth(up, seen + (c,))
            dcodes = []
            for c, nm in present.items():
                is_total = bool(self.total_re.match(norm_text(nm))) or (not all_parent.get(c) and c in children
                                                                        and bool(meta_codes))
                dcodes.append(DimensionCode(code=c, name=nm, parent_code=all_parent.get(c), depth=depth(c),
                                            is_total=is_total, has_children=c in children))
            names = [d.name for d in dcodes]
            dims.append(DimensionDefinition(level=lv, obj_id=(m or {}).get("obj_id"), obj_nm=obj_nm, dim_type=dtype,
                                            dim_type_basis=basis, n_codes=len(dcodes),
                                            total_codes=[d.code for d in dcodes if d.is_total],
                                            code_name_unique=len(set(names)) == len(names)))
            codes[lv] = dcodes
        # 항목
        inds = []
        for r in df[["ITM_ID", "ITM_NM", "UNIT_NM"]].drop_duplicates().itertuples(index=False):
            ui = unit_info(r.UNIT_NM)
            inds.append(IndicatorDefinition(itm_id=str(r.ITM_ID), itm_nm=str(r.ITM_NM or r.ITM_ID),
                                            unit_nm=r.UNIT_NM or None, unit_family=ui.family,
                                            unit_multiplier=float(ui.multiplier) if ui.multiplier is not None else None,
                                            value_kind=ui.kind, additive=ui.additive))
        multi_unit = {i.itm_id for i in inds if sum(1 for j in inds if j.itm_id == i.itm_id) > 1}
        if multi_unit:
            notes.append(f"항목별 단위가 여러 개: {sorted(multi_unit)}")
        # 시점 (실제 데이터)
        periods: dict[str, list[str]] = {}
        for se, grp in df.groupby(df["PRD_SE"].fillna(""), sort=False):
            periods[str(se)] = sorted({str(p) for p in grp["PRD_DE"].dropna()}, key=period_sort_key)
        meta_periods = {}
        for p in meta_json.get("PRD") or []:
            if isinstance(p, dict) and "_error" not in p:
                se = normalize_frequency(p.get("PRD_SE"))
                rng = [str(p.get(k)) for k in ("STRT_PRD_DE", "END_PRD_DE", "PRD_DE") if p.get(k)]
                meta_periods.setdefault(se, []).extend(rng)
        comments = flatten_meta_text(meta_json.get("CMMT"))
        source_txt = " ".join(flatten_meta_text(meta_json.get("SOURCE")))
        survey = (cat.get("category") or ref.survey_hint or re.sub(r"[「」]", "", source_txt.split(" ")[0] if source_txt else "")
                  or "")
        title = (cat.get("tbl_nm") or next((v for v in df["TBL_NM"].dropna().unique() if v), "")
                 or next((r.get("TBL_NM") for r in meta_json.get("TBL") or [] if isinstance(r, dict) and r.get("TBL_NM")), ""))
        path = cat.get("path") or ""
        scope, scope_basis = self._population_scope(" ".join([survey, title, path]))
        has_scenario = any(d.dim_type == DimensionType.SCENARIO for d in dims)
        proj_txt = " ".join([survey, title, path])
        if has_scenario or self.projection_re.search(proj_txt):
            obs, obs_basis = ObservationType.PROJECTED, ("시나리오 분류 존재" if has_scenario else f"'{proj_txt}' ~ 추계/전망")
        else:
            obs, obs_basis = ObservationType.OBSERVED, "추계·전망 키워드와 시나리오 분류가 없어 실측으로 간주 (기본값)"
        level_cols = [lv for lv in csv_levels]
        dup = int(df.duplicated(subset=["ITM_ID", "PRD_SE", "PRD_DE"] + level_cols, keep=False).sum())
        return TableMetadata(
            parent_table_id=ref.key, org_id=ref.org_id, tbl_id=ref.tbl_id, survey_name=survey, table_title=title,
            section=cat.get("section") or "", path=path, source_path=display_path(ref.data_path),
            source_file_hash=sha256_file(ref.data_path), source_url=KOSIS_URL.format(org=ref.org_id, tbl=ref.tbl_id),
            meta_path=display_path(ref.meta_path) if ref.meta_path else None,
            metadata_source="meta_json" if meta_json else ("store_parquet" if ref.data_kind == "store_parquet" else "raw_only"),
            dimension_definitions=dims, dimension_codes=codes, indicator_definitions=inds, periods=periods,
            meta_periods=meta_periods, comments=comments, symbol_meanings=self._symbol_meanings(comments),
            population_scope=scope, population_scope_basis=scope_basis,
            reference_time=self._reference_time(comments), aggregation_basis=self._aggregation_basis(cat, path),
            observed_or_projected=obs, observation_basis=obs_basis, duplicate_coordinate_rows=dup, n_rows=len(df),
            adapter_notes=notes)

    def _population_scope(self, text: str) -> tuple[str, str]:
        for rule in self.population_rules:
            if re.search(rule["pattern"], text):
                return rule["scope"], f"/{rule['pattern']}/ 일치"
        return "UNSPECIFIED", "규칙 일치 없음"

    @staticmethod
    def _symbol_meanings(comments: list[str]) -> dict[str, str]:
        out = dict(DEFAULT_SYMBOL_MEANINGS)
        for c in comments:
            for m in re.finditer(r"[\"'“‘]?([\-\*Xx…])[\"'”’]?\s*[:：=]\s*([^,;\n]+)", c):
                out[m.group(1)] = norm_text(m.group(2))[:80]
        return out

    @staticmethod
    def _reference_time(comments: list[str]) -> str | None:
        for c in comments:
            m = re.search(r"([^.。\n]{0,24}기준)", c)
            if m:
                return norm_text(m.group(1))
        return None

    @staticmethod
    def _aggregation_basis(cat: dict, path: str) -> str | None:
        st = cat.get("survey_type") or ""
        bits = [b for b in (st, "등록센서스" if "등록센서스" in path else "", "전수" if "전수" in path else "") if b]
        return " / ".join(dict.fromkeys(bits)) or None


def tidy_to_canonical(t: pd.DataFrame, org: str, tbl: str) -> pd.DataFrame:
    """collector store/data/*.parquet (tidy) → KOSIS 표준 컬럼."""
    out = pd.DataFrame({"ORG_ID": org, "TBL_ID": tbl, "TBL_NM": ""}, index=t.index)
    for i in range(1, 9):
        if f"c{i}_code" in t.columns:
            out[f"C{i}"] = t[f"c{i}_code"]
            out[f"C{i}_NM"] = t.get(f"c{i}_name")
            out[f"C{i}_OBJ_NM"] = t.get(f"c{i}_obj_nm", f"C{i}")
    out["ITM_ID"], out["ITM_NM"], out["UNIT_NM"] = t.get("itm_id"), t.get("itm_nm"), t.get("unit")
    out["PRD_SE"], out["PRD_DE"] = t.get("prd_se"), t.get("prd_de")
    out["DT"] = t["value_raw"] if "value_raw" in t.columns else t.get("value")
    return out.reset_index(drop=True)


# ── 방식 B: View 생성 ───────────────────────────────────────────────

def frame_snapshot_hash(df: pd.DataFrame, rows: np.ndarray | None = None) -> str:
    """View 에 담긴 원본 행들의 해시 (원본 행 번호 순). rows: 미리 계산한 row_strings 의 해당 부분."""
    order = np.argsort(pd.to_numeric(df["_src_row"]).to_numpy(), kind="stable")
    rs = (rows if rows is not None else row_strings(df))[order]
    return sha256_text("\n".join(rs.tolist()))


def completeness_of(tm: TableMetadata) -> MetadataCompleteness:
    checks = {
        "survey_name": bool(tm.survey_name), "table_title": bool(tm.table_title),
        "meta_json": tm.metadata_source == "meta_json",
        "units": all(i.unit_nm for i in tm.indicator_definitions),
        "known_units": all(i.unit_family for i in tm.indicator_definitions),
        "hierarchy": any(c.parent_code for cs in tm.dimension_codes.values() for c in cs) or not tm.dimension_codes,
        "comments": bool(tm.comments), "reference_time": bool(tm.reference_time),
        "population_scope": tm.population_scope != "UNSPECIFIED",
    }
    present = [k for k, v in checks.items() if v]
    missing = [k for k, v in checks.items() if not v]
    return MetadataCompleteness(score=round(len(present) / len(checks), 3), present=present, missing=missing,
                                notes=list(getattr(tm, "adapter_notes", []) or []) + [tm.observation_basis])


class RawViewGenerator:
    """원본 표 → Golden Set 전용 View 들 (기본: 항목 × 시점, 시나리오·설정된 분류는 코드별로 추가 분할)."""

    def __init__(self, out_dir: str | Path, allowed_root: str | Path, cfg: dict | None = None):
        cfg = cfg or {}
        self.out_dir = Path(out_dir)
        self.allowed_root = Path(allowed_root)
        self.split_types = {DimensionType(t) for t in (cfg.get("split_dimension_types") or [])} | {DimensionType.SCENARIO}
        self.split_max_codes = int(cfg.get("split_dimension_max_codes") or 4)
        self.file_format = cfg.get("view_file_format") or "parquet"
        self.min_numeric = int(cfg.get("min_numeric_values_per_view") or 1)

    def _write(self, df: pd.DataFrame, path: Path) -> Path:
        ensure_inside(path, self.allowed_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.file_format == "parquet":
            try:
                df.to_parquet(path.with_suffix(".parquet"), index=False)
                return path.with_suffix(".parquet")
            except (ImportError, ValueError):  # pyarrow 없음 → CSV
                pass
        p = path.with_suffix(".csv")
        df.to_csv(p, index=False, encoding="utf-8-sig")
        return p

    def generate(self, lt: LoadedTable, max_views: int = 0) -> list[ViewMetadata]:
        """max_views > 0 이면 남길 View 만 골라서 만든다 (최근 시점 우선, 항목은 번갈아) — 버릴 View 는 계산·저장하지 않음."""
        tm, df = lt.meta, lt.df
        split_dims = [d for d in tm.dimension_definitions
                      if d.dim_type in self.split_types and 1 < d.n_codes <= max(self.split_max_codes, 50 if d.dim_type == DimensionType.SCENARIO else 0)]
        group_cols = ["ITM_ID", "PRD_SE", "PRD_DE"] + [d.level for d in split_dims]
        ok = numeric_mask(df["DT"])
        keys_df = as_string_frame(df[group_cols]) if any(df[c].isna().any() or not pd.api.types.is_string_dtype(df[c])
                                                         for c in group_cols) else df[group_cols]
        # 그룹 번호(키 정렬 순) → 표를 한 번만 재정렬해 View 마다 연속 구간(복사 없는 slice)으로 자른다
        gid = keys_df.groupby(group_cols, sort=True).ngroup().to_numpy()
        order = np.argsort(gid, kind="stable")          # 같은 그룹 안에서는 원본 행 순서 유지
        bounds = np.flatnonzero(np.diff(gid[order])) + 1
        starts = np.concatenate([[0], bounds]) if len(order) else np.array([], dtype=int)
        ends = np.concatenate([bounds, [len(order)]]) if len(order) else np.array([], dtype=int)
        ok_sorted = ok[order]
        key_rows = keys_df.iloc[order[starts]] if len(order) else keys_df.iloc[:0]
        cand = []
        for (st, en), keys in zip(zip(starts, ends), key_rows.itertuples(index=False, name=None)):
            n_num = int(ok_sorted[st:en].sum())
            if n_num >= self.min_numeric:
                cand.append((tuple(str(k) for k in keys), (int(st), int(en)), n_num))
        if max_views and len(cand) > max_views:
            cand = select_recent(cand, max_views)
        sdf = df.take(order) if cand else df
        rows = row_strings(sdf) if cand else None
        views: list[ViewMetadata] = []
        comp = completeness_of(tm)
        for keys, (st, en), n_num in cand:
            itm, se, prd = keys[:3]
            split_sel = {d.level: k for d, k in zip(split_dims, keys[3:])}
            part = sdf.iloc[st:en]
            snap = frame_snapshot_hash(part, rows[st:en])
            freq = normalize_frequency(se)
            split_txt = "".join(f"::{lv}={c}" for lv, c in split_sel.items())
            view_id = f"sgv::{tm.parent_table_id}::{itm}::{freq}{prd}{split_txt}::{snap[:8]}"
            path = self.out_dir / safe_name(tm.parent_table_id) / safe_name(view_id.replace("::", "__"), 180)
            existing = [p for p in (path.with_suffix(".parquet"), path.with_suffix(".csv")) if p.exists()]
            vfile = existing[0] if existing else self._write(part.reset_index(drop=True), path)
            views.append(build_view_metadata(tm, part, view_id, vfile, InputMode.GENERATED_FROM_RAW, snap, comp,
                                             split_sel, n_num))
        return views


def select_recent(cand: list[tuple], n: int) -> list[tuple]:
    """(keys, idx, n_num) 후보 중 n 개: 항목(keys[0])별로 최근 시점(keys[2]) 우선, 항목을 번갈아 고른다."""
    by_item: dict[str, list] = {}
    for c in cand:
        by_item.setdefault(c[0][0], []).append(c)
    for k in by_item:
        by_item[k].sort(key=lambda c: c[0][2], reverse=True)
    out, i = [], 0
    while len(out) < n and any(i < len(x) for x in by_item.values()):
        for k in sorted(by_item):
            if i < len(by_item[k]) and len(out) < n:
                out.append(by_item[k][i])
        i += 1
    return out


def build_view_metadata(tm: TableMetadata, part: pd.DataFrame, view_id: str, vfile: Path, mode: InputMode,
                        snap: str, comp: MetadataCompleteness, split_sel: dict[str, str] | None = None,
                        n_numeric: int | None = None) -> ViewMetadata:
    split_sel = split_sel or {}

    def uniq(col: str) -> list[str]:                 # 컬럼 단위 고유값 (행마다 Python 반복하지 않음)
        return [str(x) for x in part[col].dropna().unique()] if col in part.columns else []
    dcodes: dict[str, list[DimensionCode]] = {}
    for d in tm.dimension_definitions:
        present = set(uniq(d.level))
        dcodes[d.level] = [c for c in tm.dimension_codes.get(d.level, []) if c.code in present]
    itm_ids = sorted(set(uniq("ITM_ID")))
    unit_vals = set(uniq("UNIT_NM"))
    inds = [i for i in tm.indicator_definitions if i.itm_id in itm_ids and (i.unit_nm or "") in unit_vals]
    units = sorted(u for u in unit_vals if u)
    ses = sorted(set(uniq("PRD_SE"))) or [""]
    freq_raw = ses[0] if ses else ""
    scen_dim = next((d for d in tm.dimension_definitions if d.dim_type == DimensionType.SCENARIO), None)
    scenario = None
    if scen_dim and dcodes.get(scen_dim.level) and len(dcodes[scen_dim.level]) == 1:
        scenario = dcodes[scen_dim.level][0].name
    level_cols = [d.level for d in tm.dimension_definitions if d.level in part.columns]
    dup = int(part.duplicated(subset=["ITM_ID", "PRD_SE", "PRD_DE"] + level_cols, keep=False).sum())
    if n_numeric is None:
        n_numeric = int(numeric_mask(part["DT"]).sum())
    return ViewMetadata(
        view_id=view_id, parent_table_id=tm.parent_table_id, org_id=tm.org_id, tbl_id=tm.tbl_id,
        survey_name=tm.survey_name, table_title=tm.table_title, source_path=tm.source_path,
        source_file_hash=tm.source_file_hash, source_url=tm.source_url, view_file=display_path(vfile),
        view_file_hash=sha256_file(vfile), input_mode=mode,
        column_schema=[c for c in part.columns], dimension_definitions=tm.dimension_definitions,
        dimension_codes=dcodes,
        available_periods=sorted(set(uniq("PRD_DE")), key=period_sort_key),
        period_frequency=normalize_frequency(freq_raw), period_frequency_raw=freq_raw,
        indicator_definitions=inds, units=units,
        unit_multiplier={u: (float(unit_info(u).multiplier) if unit_info(u).multiplier is not None else None) for u in units},
        population_scope=tm.population_scope, reference_time=tm.reference_time, aggregation_basis=tm.aggregation_basis,
        observed_or_projected=tm.observed_or_projected, scenario=scenario,
        hierarchy_information={lv: {c.code: c.parent_code for c in cs} for lv, cs in dcodes.items()},
        total_and_subtotal_codes={lv: [c.code for c in cs if c.is_total or c.has_children] for lv, cs in dcodes.items()},
        source_coordinates=ViewSelector(itm_ids=itm_ids, prd_se=freq_raw,
                                        prd_de=sorted(set(uniq("PRD_DE")), key=period_sort_key),
                                        dim_filters={lv: [c] for lv, c in split_sel.items()}),
        metadata_completeness=comp, data_snapshot_hash=snap, n_rows=len(part), n_numeric=n_numeric,
        duplicate_coordinate_rows=dup, symbol_meanings=tm.symbol_meanings, comments=tm.comments[:5],
    )
