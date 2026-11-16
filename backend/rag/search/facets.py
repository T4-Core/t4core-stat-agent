"""표 단면(Facet) — 표 하나가 '무엇을 · 언제 · 어느 지역 수준으로' 담는지

읽는 곳 (위에서부터 있는 것을 씀)
  1) CSV 값 사전 (backend.rag.csv_index: tables.jsonl + values.parquet) — 원본 CSV 에 실제로 있는 값
       · 연도 = 실제 수록 연도 (5년 주기 표는 2015·2020 만)  · 분류 값 전부 (메타 프로필은 분류마다 300개까지)
       · 시군구·읍면동 이름 전부 → '화성군'·'부산진구' 가 그 표에 있는지 정확히 확인
  2) 메타 프로필 (meta_profiles.jsonl) — 정의된 기간(범위) · 분류 값 300개까지 · 지역은 수준과 시도 이름만
  3) 문서의 meta.profile — 2) 와 같은 모양. 있으면 2) 보다 먼저 씀 (코퍼스가 직접 준 구조가 우선)

값 사전이 없어도 돌아가지만, 시점·시군구 확인의 정확도는 1) 이 있을 때 가장 좋다
  python -m backend.rag.csv_index build
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.rag.search.text import TOTALS, norm

SUB_SUFFIX = re.compile(r"(시|군|구)$")
EMD_SUFFIX = re.compile(r"(읍|면|동|가|리)$")
URBAN = {"동부", "읍부", "면부", "시부", "군부", "읍면부"}
AGE_NAME = re.compile(r"\d+\s*세|\d+\s*[~\-]\s*\d+")
SEX_NAME = re.compile(r"남자|여자|남성|여성|^남$|^여$|\(남\)|\(여\)|_남$|_여$")
CYCLE = {"A": "Y", "Y": "Y", "F": "Y", "M": "M", "Q": "Q", "H": "H", "년": "Y", "월": "M", "분기": "Q", "반기": "H"}


@dataclass
class Facet:
    tbl_id: str
    tbl_nm: str = ""
    survey_nm: str = ""
    path: str = ""
    items: list = field(default_factory=list)            # 항목 이름
    dims: list = field(default_factory=list)             # [(분류 이름, 종류, [값 이름…])] — 지역 분류 제외
    units: list = field(default_factory=list)
    years: frozenset | None = None                       # 실제 수록 연도 (값 사전이 있을 때)
    spans: list = field(default_factory=list)            # [(시작, 끝)] 정의된 기간
    cycles: set = field(default_factory=set)             # {"Y", "M", "Q", "H"}
    geo: set = field(default_factory=set)                # {"시도", "시군구", "읍면동", "동읍면부"}
    sido: set = field(default_factory=set)               # 시도 짧은 이름 ('서울', '경기')
    regions: set = field(default_factory=set)            # 시도 아래 지역 이름 (norm)
    regions_full: bool = False                           # regions 가 그 표의 지역 전부인가
    source: str = "none"
    has_age: bool = False                                # 연령 분류(또는 연령이 이름에 든 항목)가 있는가
    has_sex: bool = False                                # 성별 분류(또는 남·여가 이름에 든 항목)가 있는가

    def finish(self):
        """분류·항목에서 구조 표시 계산 (만든 뒤 한 번)"""
        names = list(self.items) + [n for _, _, ns in self.dims for n in ns[:200]]
        self.has_age = any(k == "ages" for _, k, _ in self.dims) or sum(bool(AGE_NAME.search(str(n))) for n in names) >= 3
        self.has_sex = any(k == "sex" for _, k, _ in self.dims) or any(SEX_NAME.search(str(n)) for n in names) \
            or bool(re.search(r"\((?:남|여|남자|여자)\)", self.tbl_nm or ""))   # [NEW 11-16] '…(여)' 처럼 성별로 나눈 형제 표
        return self

    def year_cover(self, want) -> float:
        if not want:
            return 1.0
        if self.years is not None:
            return sum(y in self.years for y in want) / len(want)
        return sum(any(a <= y <= b for a, b in self.spans) for y in want) / len(want)

    def last_year(self):
        if self.years:
            return max(self.years)
        return max((b for _, b in self.spans), default=None)


def sido_short(name):
    from backend.rag.ingestion.resolve import short
    return short(name)


def _is_sido(name):
    from backend.rag.ingestion.normalize import SIDO_ALIAS
    from backend.rag.ingestion.resolve import OLD_SIDO_RE
    n = norm(name)
    return bool(SIDO_ALIAS.get(n) or OLD_SIDO_RE.search(n))


def _add_region(f: Facet, name):
    n = norm(name)
    if not n or n in TOTALS:
        return
    if _is_sido(name):
        f.sido.add(sido_short(name))
        f.geo.add("시도")
        return
    last = norm(str(name).split()[-1])                    # '수원시 권선구' → 권선구 (앞의 시도·시는 따로 등록)
    for part in {n, last}:
        f.regions.add(part)
    if last in URBAN:
        f.geo.add("동읍면부")
    elif SUB_SUFFIX.search(last):
        f.geo.add("시군구")
    elif EMD_SUFFIX.search(last):
        f.geo.add("읍면동")


def from_profile(p: dict) -> Facet:
    """메타 프로필(또는 카드 프로필) → Facet"""
    from backend.rag.ingestion.build_view import full_names
    f = Facet(p["tbl_id"], p.get("tbl_nm") or "", p.get("survey_nm") or "", p.get("path") or "", source="meta")
    f.items = full_names([i["name"] for i in p.get("items") or []])
    f.units = list(p.get("units") or [])
    for x in p.get("periods") or []:
        if x.get("year_to"):
            f.spans.append((x.get("year_from") or x["year_to"], x["year_to"]))
        f.cycles.add(CYCLE.get(str(x.get("se") or "Y"), "Y"))
    for lv in p.get("levels") or []:
        names = list(lv.get("names") or [])
        if lv.get("kind") == "regions":
            for g, n in (lv.get("geo_types") or {}).items():
                if n and g != "전국":
                    f.geo.add("동읍면부" if g == "동읍면부" else g)
            for n in list(lv.get("sido") or []) + names:
                _add_region(f, n)
        else:
            f.dims.append((lv.get("obj_nm") or "", lv.get("kind") or "other", full_names(names)))
            if sum(_is_sido(n) for n in names) >= 3:      # 지역으로 판정되지 않은 옛 표의 시도 목록
                for n in names:
                    _add_region(f, n)
    return f


def from_csv_scan(t: dict, region_names=None) -> Facet:
    """CSV 값 사전의 표 하나(tables.jsonl) → Facet. region_names = values.parquet 에서 뽑은 그 표의 지역 값 전부"""
    f = Facet(t["tbl_id"], t.get("tbl_nm") or "", t.get("survey_nm") or "", t.get("menu_path") or "", source="csv")
    f.items = [i["name"] for i in t.get("items") or []]
    f.units = sorted({i.get("unit") for i in t.get("items") or [] if i.get("unit")})
    f.years = frozenset(int(y) for y in t.get("years") or [])
    f.spans = [(min(f.years), max(f.years))] if f.years else []
    f.cycles = {CYCLE.get(str(k), "Y") for k in (t.get("periods") or {})} or {"Y"}
    for d in t.get("dims") or []:
        names = [v["name"] for v in d.get("values") or []]
        if d.get("kind") == "regions":
            for n in (region_names if region_names is not None else names):
                _add_region(f, n)
            f.regions_full = region_names is not None or d.get("n_values", len(names)) <= len(names)
        else:
            f.dims.append((d.get("obj_nm") or "", d.get("kind") or "other", names))
    return f


def build_facets(docs, source="auto", log=None) -> dict:
    """코퍼스 문서 목록 → {tbl_id: Facet}. source: auto | csv | meta"""
    out, want = {}, {d.id for d in docs}
    if source in ("auto", "csv"):
        try:
            from backend.rag.csv_index import load_index
            idx = load_index()
            reg = idx.v[(idx.v["slot"] == "지역") & (idx.v["kind"] == "dim") & idx.v["tbl_id"].isin(want)]
            by_tbl = reg.groupby("tbl_id")["name"].agg(list).to_dict()
            for tid in want:
                t = idx.table(tid)
                if t:
                    out[tid] = from_csv_scan(t, by_tbl.get(tid))
            # 값 사전의 분류 값은 표마다 상한이 있을 수 있어, 역색인의 분류 값 전부로 채움
            dv = idx.v[(idx.v["kind"] == "dim") & (idx.v["slot"] != "지역") & idx.v["tbl_id"].isin(set(out))]
            for (tid, obj), names in dv.groupby(["tbl_id", "obj_nm"])["name"].agg(list).items():
                f = out[tid]
                f.dims = [(o, k, names if o == obj else n) for o, k, n in f.dims]
        except FileNotFoundError:
            if source == "csv":
                raise
        except Exception as e:  # noqa: BLE001  (값 사전이 깨져 있어도 메타로 계속)
            if log:
                log(f"[v5] CSV 값 사전을 읽지 못해 메타 프로필만 씀: {e.__class__.__name__}: {e}")
    rest = want - set(out)
    if rest:
        try:
            from backend.rag.ingestion.meta_profile import load_meta_profiles
            prof = {p["tbl_id"]: p for p in load_meta_profiles() if p["tbl_id"] in rest}
        except FileNotFoundError:
            prof = {}
        for d in docs:
            if d.id in rest:
                p = d.meta.get("profile") or prof.get(d.id)   # 문서가 직접 들고 온 프로필이 먼저 (같은 tbl_id 의 메타 파일보다)
                out[d.id] = from_profile(p) if p else Facet(d.id, d.meta.get("tbl_nm", ""), d.meta.get("survey_nm", ""))
    for f in out.values():
        f.finish()
    if log:
        from collections import Counter
        log(f"[v5] 표 단면 {len(out)}개 · 출처 {dict(Counter(f.source for f in out.values()))}")
    return out


def facet_text(f: Facet, small=30) -> str:
    """글자 n-gram 채널용 글: 표 이름(두 번) · 조사명 · 항목 · 분류 이름 · 값이 적은 분류의 값"""
    parts = [f.tbl_nm, f.tbl_nm, f.survey_nm, " ".join(f.items[:60])]
    for obj, _, names in f.dims:
        parts.append(obj)
        parts.append(" ".join(names[:small]))
    return " ".join(x for x in parts if x)
