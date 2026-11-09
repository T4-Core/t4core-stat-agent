"""[NEW v4] 2-3 View(Record) → Point 목록 — 표가 달라도 같은 '교차점' 이면 같은 key

  key  = 시점 + 지역 + 성별 + 연령 + 지표 + 기본 단위 (+ 질문에 없던 분류가 합계가 아니면 그 분류 값)
  value = 기본 단위로 바꾼 값 (천명 → 명 ×1000)

  - 시점: 라벨의 숫자만 ('2025' · '2025.01' → '202501'). 주기가 다르면 key 가 달라 비교되지 않음
  - 지역: 표준 이름 (judge.extract.region_std — View 라벨을 만든 규칙과 같음)
  - 성별·연령: 분류 열에 있거나, 성별은 항목 이름에 있을 때 ('남자인구수' → 성별 남자, 지표 인구수)
              합계 라벨(계·연령계)은 '구분 없음' 과 같게 봄 → 성별 분류가 없는 표의 값과 비교됨
  - 지표: 항목의 핵심 이름(괄호·성별·'총' 을 뗀 것)이 질문의 지표·대상 단어와 같으면 그 단어로
          ('총인구수' · '인구' → '인구수'), 아니면 항목 이름 — '다문화출생아수'·'추계인구' 는 다른 지표
  - 질문에 없던 분류(가구원수별 …): 합계 행만 key 에서 빠지고, 나머지 값은 '분류=값' 으로 key 에 남음
    → 그런 표끼리만 비교됨 (다른 구분의 값을 같은 값으로 오인하지 않게)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from backend.core.utils import norm_space
from backend.rag.ingestion.build_view import has_sex, squash, term_stems
from backend.rag.ingestion.normalize import level_kind, parse_age
from backend.rag.judge.extract import ITEM_COL, PERIOD_COL, VALUE_COL, is_total, region_std

KEY_ORDER = ("시점", "지역", "성별", "연령", "지표", "단위")

# 단위 배수: 앞머리 → 배수. '천명' = 1000 × '명'
SCALE = [("십억", 1e9), ("백만", 1e6), ("천만", 1e7), ("억", 1e8), ("만", 1e4), ("천", 1e3), ("백", 1e2)]
NO_SCALE_UNITS = {"만나이", "백분율"}


def unit_base(unit):
    """'천명' → ('명', 1000), '%' → ('%', 1), '' → ('', 1)"""
    u = squash(unit or "")
    if not u or u in NO_SCALE_UNITS:
        return u, 1.0
    for pre, k in SCALE:
        if u.startswith(pre) and len(u) > len(pre):
            return u[len(pre):], k
    return u, 1.0


def period_key(label):
    d = re.sub(r"\D", "", str(label or ""))
    return d or norm_space(label)


def sex_of(label):
    n = squash(label)
    if n in ("남", "남자", "남성"):
        return "남자"
    if n in ("여", "여자", "여성"):
        return "여자"
    return None


def age_key(label):
    lo, hi = parse_age(label)
    if lo is None:
        return None
    return f"{lo}-{'' if hi is None else hi}"


@dataclass
class Point:
    key: dict
    value: float | None               # 기본 단위로 바꾼 값
    raw_value: float | None
    unit: str                         # 표의 단위 (바꾸기 전)
    record_id: str
    tbl_id: str
    row: int                          # View 표의 몇 번째 행인지 (0부터)
    labels: dict = field(default_factory=dict)   # 원래 라벨 (사람이 읽기용)

    def key_str(self):
        return key_str(self.key)

    def as_dict(self):
        return {**asdict(self), "key_str": self.key_str()}


def key_str(key):
    head = [f"{k}={key[k]}" for k in KEY_ORDER if key.get(k) not in (None, "")]
    rest = [f"{k}={v}" for k, v in sorted(key.items()) if k not in KEY_ORDER and v not in (None, "")]
    return " | ".join(head + rest)


def _as_dict(record):
    return record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)


GENERIC_PREFIX = ("총", "전체")
SEX_WORDS = ("남자", "여자", "남성", "여성")


def item_core(item):
    """항목 이름의 핵심: 괄호 내용·성별 단어·'총/전체' 앞머리를 뗌 ('총인구수' → '인구수', '남자인구수(명)' → '인구수')"""
    n = squash(re.sub(r"\(.*?\)|（.*?）", "", str(item or "")))
    for w in SEX_WORDS:
        n = n.replace(w, "")
    for pre in GENERIC_PREFIX:
        if n.startswith(pre) and len(n) > len(pre) + 1:
            n = n[len(pre):]
    return n


def _term_of(item, terms):
    """항목 이름 → 질문의 지표·대상 단어 (핵심 이름이 그 단어(또는 '수' 를 뗀 것)와 같을 때만), 아니면 None
    포함만으로는 같은 지표로 보지 않음: '다문화출생아수' ≠ '출생아수', '추계인구' ≠ '인구' (다른 값이 정상)"""
    core = item_core(item)
    for t in sorted(terms, key=lambda x: -len(squash(x))):
        if core and core in term_stems([t]):
            return t
    return None


def record_points(record, filters=None):
    """Record 하나 → (Point 목록, 메모). 값이 None 인 칸도 Point 로 (비교에서는 빠짐)"""
    r = _as_dict(record)
    f = filters or {}
    table = r.get("table") or {}
    cols = list(table.get("columns") or [])
    rows = table.get("rows") or []
    meta, src = r.get("metadata") or {}, r.get("source") or {}
    rid, tbl = str(r.get("id") or ""), str(src.get("tbl_id") or "")
    notes = []
    units = [u for u in str(meta.get("unit") or "").split() if u]
    unit = units[0] if len(units) == 1 else ""
    if len(units) > 1:
        notes.append(f"단위가 여러 개 ({' '.join(units)}) → 단위는 key 에 넣지 않고 항목 이름으로 구분")
    base, scale = unit_base(unit)
    terms = [t for t in (f.get("지표") or []) + (f.get("대상") or []) if t]
    ci = {c: i for i, c in enumerate(cols)}
    dim_cols = [c for c in cols if c not in (PERIOD_COL, ITEM_COL, VALUE_COL)]
    kinds = {c: level_kind(c, list(dict.fromkeys(str(row[ci[c]]) for row in rows if row[ci[c]] is not None)))
             for c in dim_cols}
    has_sex_dim = any(k == "sex" for k in kinds.values())
    pts = []
    for n, row in enumerate(rows):
        key, labels = {}, {}
        if PERIOD_COL in ci:
            key["시점"] = period_key(row[ci[PERIOD_COL]])
            labels["시점"] = row[ci[PERIOD_COL]]
        for c in dim_cols:
            lb = row[ci[c]]
            if lb is None:
                continue
            labels[c] = lb
            k = kinds[c]
            if k == "regions":
                key["지역"] = region_std(str(lb))
            elif is_total(str(lb)):
                continue                                        # 합계 = 구분 없음
            elif k == "sex":
                key["성별"] = sex_of(lb) or norm_space(lb)
            elif k == "ages":
                key["연령"] = age_key(lb) or norm_space(lb)
            else:
                key[norm_space(c)] = norm_space(lb)
        item = str(row[ci[ITEM_COL]]) if ITEM_COL in ci and row[ci[ITEM_COL]] is not None else ""
        labels["항목"] = item
        if not has_sex_dim and "성별" not in key and item:
            s = next((x for x in ("남자", "여자") if has_sex(item, x)), None)
            if s:
                key["성별"] = s
        key["지표"] = _term_of(item, terms) or squash(item)
        if base:
            key["단위"] = base
        raw = row[ci[VALUE_COL]] if VALUE_COL in ci else None
        try:
            raw = None if raw is None else float(raw)
        except (TypeError, ValueError):
            raw = None
        pts.append(Point(key=key, value=None if raw is None else raw * scale, raw_value=raw, unit=unit,
                         record_id=rid, tbl_id=tbl, row=n, labels=labels))
    # 한 표 안에서 key 가 겹치면 (같은 지표 단어에 항목 두 개) 그 점들은 항목 이름 그대로
    seen = {}
    for p in pts:
        seen.setdefault(p.key_str(), []).append(p)
    for ps in seen.values():
        if len(ps) > 1 and len({p.labels.get("항목") for p in ps}) > 1:
            for p in ps:
                p.key["지표"] = squash(p.labels.get("항목"))
            notes.append(f"항목 {sorted({p.labels.get('항목') for p in ps})} 이 같은 지표로 묶여 항목 이름으로 구분")
    return pts, notes
