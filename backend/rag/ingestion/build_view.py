"""
[엔드포인트 4] build_view — 검색으로 찾은 표(메타데이터) + 슬롯 dict → View 카드(Record, doc_type="view")

  1) 표 지연 정규화 (normalize.ensure_normalized): raw CSV → 정제 parquet + 실제 프로필
  2) 슬롯 → 그 표의 실제 코드 조건 (시점·지역·성별·연령·지표/대상)
  3) parquet 에서 조건대로 잘라 View 데이터 → output/views/<id>.csv
  4) 카드: id · lexical_text · table{columns, rows} · doc_type=view · parent_id · metadata · source
     (판단·RAG 모듈이 받기로 한 예시 모양. dense_vectors 는 넣지 않음)

원칙
  - 표에 없는 조건은 억지로 맞추지 않고 notes 에 남긴다 → 판단 모듈이 "조건을 못 맞춘 View" 를 알 수 있게
  - 숫자는 parquet 에서만 꺼낸다 (설명문·요약에 숫자를 지어 넣지 않음)
  - 슬롯 → 코드 매칭 규칙은 메타데이터 초안 기준이라 바뀔 수 있음 (규칙은 이 파일의 match_* 함수에만 둠)
"""
import re

import pandas as pd

from backend.core.config import OUT
from backend.core.utils import sql_str
from backend.data_engine.duckdb_client import connect
from backend.rag.ingestion.normalize import ensure_normalized
# [CHANGED] 이전: from config import OUT, connect, sql_str
#                from services.normalize import ensure_normalized

MAX_ROWS = 5000          # View 하나의 최대 행 수 (넘으면 잘라내고 notes)
SEX_ALIAS = {"남": "남자", "남성": "남자", "여": "여자", "여성": "여자"}
SE_PREF = ["Y", "F", "IR", "H", "Q", "M", "D"]


def squash(s):
    return re.sub(r"[\s_·\-()（）\[\]:,]", "", str(s or ""))


def sex_name(name):
    # '남자(A)' · '여성' → '남자' · '여자' (끝의 괄호 표기를 떼고 별칭을 표준으로)
    n = re.sub(r"\s*\(.*\)\s*$", "", str(name or "")).strip()
    return SEX_ALIAS.get(n, n)


def term_stems(terms):
    # '인구수' → {'인구수', '인구'}  ('수' 로 끝나는 지표는 앞부분으로도 찾음)
    out = set()
    for t in terms or []:
        t = squash(t)
        if t:
            out.add(t)
            if t.endswith("수") and len(t) > 2:
                out.add(t[:-1])
    return out


def match_name(name, stems):
    n = squash(name)
    return any(s in n for s in stems)


# ── 시점 ────────────────────────────────────────────────────────
def match_period(prof, f, notes):
    se = next((s for s in SE_PREF if s in prof["periods"]), next(iter(prof["periods"])))
    avail = sorted({p["year"] for p in prof["periods"][se]})
    want = f.get("시점")
    if want:
        use = [y for y in want if y in avail]
        miss = [y for y in want if y not in avail]
        if miss:
            notes.append(f"시점 {miss} 은 이 표에 없음 (수록 {avail[0]}~{avail[-1]})")
        if not use:
            use = [avail[-1]]
            notes.append(f"요청 시점이 모두 없어 최신 {avail[-1]} 사용")
    elif f.get("의도") == "추이":
        use = avail
    else:
        use = [avail[-1]]
    return se, use


# ── 분류 ────────────────────────────────────────────────────────
def leaves(codes):
    # 범위가 겹치면 가장 잘게 나뉜 것만 (예: '20~29세' 와 '20~24세','25~29세' 가 같이 있으면 뒤의 둘)
    def inside(a, b):
        return a is not b and b["age_from"] <= a["age_from"] and (
            b["age_to"] is None or (a["age_to"] is not None and a["age_to"] <= b["age_to"]))
    return [c for c in codes if not any(inside(o, c) for o in codes)]


def age_codes(codes, rng, notes, what):
    lo, hi = rng.get("from"), rng.get("to")
    sel = [c for c in codes if c.get("age_from") is not None and c["age_from"] >= lo
           and (hi is None or (c.get("age_to") is not None and c["age_to"] <= hi))]
    sel = leaves(sel)
    covered = sorted((c["age_from"], c["age_to"]) for c in sel)
    ok, cur = bool(covered), lo
    for f, t in covered:
        if f > cur:
            ok = False
        cur = max(cur, (t if t is not None else 10**6) + 1)
    if hi is not None and cur <= hi:
        ok = False
    if not ok:
        notes.append(f"{what}: 연령 {lo}~{hi if hi is not None else ''} 을 정확히 덮는 코드 없음"
                     + (f" (가까운 코드 {len(sel)}개 사용)" if sel else ""))
    return sel


def match_level(l, f, stems, notes):
    kind, codes = l["kind"], l["codes"]
    default = [c for c in codes if c["code"] == l["default_code"]]
    name = l["obj_nm"]

    def fallback(why):
        if default:
            notes.append(f"{name}: {why} → 기본값 '{default[0]['std']}'({l['default_reason']})")
        return default

    if kind == "regions":
        regions, axis = f.get("지역"), f.get("비교축")
        if regions:
            sel = {}
            for c in codes:                                   # 같은 표준명이 여럿이면 상위(depth 작은) 하나만
                if c["std"] in regions and c.get("geo_type") != "동읍면부":
                    if c["std"] not in sel or c["depth"] < sel[c["std"]]["depth"]:
                        sel[c["std"]] = c
            miss = [r for r in regions if r not in sel]
            if miss:
                notes.append(f"{name}: 지역 {miss} 없음")
            return list(sel.values()) or fallback("요청 지역 없음")
        if axis in ("시도", "지역", "시군구"):
            gt = "시군구" if axis == "시군구" else "시도"
            sel = {}
            for c in codes:
                if c.get("geo_type") == gt and c["std"] not in sel:
                    sel[c["std"]] = c
            return list(sel.values()) or fallback(f"{gt} 코드 없음")
        return [c for c in codes if c["is_total"]] or fallback("전국 합계 없음")
    if kind == "sex":
        want = {SEX_ALIAS.get(s, s) for s in (f.get("성별") or [])}
        if want:
            sel = [c for c in codes if sex_name(c["name"]) in want]
            return sel or fallback(f"성별 {sorted(want)} 코드 없음")
        return [c for c in codes if c["is_total"]] or default
    if kind == "ages":
        if f.get("연령"):
            return age_codes(codes, f["연령"], notes, name) or fallback("연령 범위 코드 없음")
        return [c for c in codes if c["is_total"]] or default
    if kind == "scenario":
        # 시나리오는 지표 단어로 고르지 않는다: 이름이 '높은 출산율 추계(… 기대수명-중위 …)' 처럼 길어서
        # 지표 '기대수명' 이 모든 시나리오에 걸림. 슬롯에 시나리오가 없으므로 기본값(중위) 하나
        if default and l["default_reason"] != "기본 추계(중위)":
            notes.append(f"{name}: 중위(기본) 시나리오가 없어 '{default[0]['std']}'({l['default_reason']}) 사용")
        return default
    sel = [c for c in codes if not c["is_total"] and match_name(c["name"], stems)]    # 지표·대상 단어로
    if sel:
        return sel
    return [c for c in codes if c["is_total"]] or fallback("지표·대상과 맞는 코드 없음")


def has_sex(name, sex):
    # '남자인구수' 처럼 성별 단어가 들어 있거나, '기대수명 - 남' 처럼 이름 끝이 '남'/'여'
    n = squash(name)
    return sex in n or n.endswith(sex[0])


def is_sexed(name):
    return has_sex(name, "남자") or has_sex(name, "여자")


def pick_sex(rows, sexes):
    # 성별을 물었으면 그 성별 이름이 붙은 것만, 묻지 않았으면 성별로 나뉜 것을 빼고 (남아 있으면) 합계 쪽만
    if sexes:
        return [r for r in rows if any(has_sex(r["name"], s) for s in sexes)]
    plain = [r for r in rows if not is_sexed(r["name"])]
    return plain or rows


def match_items(prof, f, stems, sex_done, notes):
    items = prof["items"]
    sel = [i for i in items if match_name(i["name"], stems)]
    sexes = {SEX_ALIAS.get(s, s) for s in (f.get("성별") or [])}
    if sexes and not sex_done:                              # 성별이 항목 이름에 있는 표 (남자인구수 …)
        by_sex = pick_sex(sel or items, sexes)
        if by_sex:
            sel = by_sex
        else:
            notes.append(f"성별 {sorted(sexes)}: 이 표에 성별 구분 없음")
    elif not sexes and sel:
        sel = pick_sex(sel, None)
    if f.get("연령") and any(i.get("kind") == "ages" for i in items):
        ages = age_codes([i for i in items if i.get("kind") == "ages"], f["연령"], notes, "항목")
        if ages:
            sel = ages
    if sel:
        return sel
    if len(items) == 1:                                     # 고를 것이 없음 (notes 를 남기면 잡음)
        return items
    if len(items) <= 12:
        notes.append("항목: 지표·대상과 맞는 항목 없음 → 항목 전체")
        return items
    tot = [i for i in items if i["is_total"]] or items[:1]
    notes.append(f"항목: 지표·대상과 맞는 항목 없음 → '{tot[0]['name']}'")
    return tot


# ── View 만들기 ─────────────────────────────────────────────────
def build_view(tbl_id, f, num, con=None):
    # f = 슬롯 dict (연령은 {"from","to"}), num = id 번호 자리 ('질문ID-순위', 예: '12-1')
    # 반환: (record dict = 카드, notes = 못 맞춘 조건 메모)
    # id = view::표key::주기::번호::종류 (예: view::101_DT_1B040A3::Y::12-1::trend)
    own = con is None
    con = con or connect()
    notes = []
    try:
        prof = ensure_normalized(con, tbl_id)
        if prof is None:
            raise FileNotFoundError(f"원본 CSV 없음: {tbl_id}")
        stems = term_stems((f.get("지표") or []) + (f.get("대상") or []))
        se, years = match_period(prof, f, notes)
        dims = {}
        for l in prof["levels"]:
            sel = match_level(l, f, stems, notes)
            dims[l["level"]] = (l, sel)
        # [NEW] 지역을 물었는데 이 표에 지역 분류가 없으면 메모 (이전: 아무 메모 없이 전국 값이 '조건을 다 맞춘 표'로 쓰임
        #       → 답변이 전국 값을 요청 지역 값처럼 말함). 메모가 있으면 답변 문맥 정렬에서 뒤로 가고, LLM 에도 경고로 전달됨
        want_geo = [r for r in (f.get("지역") or []) if r not in ("전국", "전체")]
        if want_geo and not any(l["kind"] == "regions" for l in prof["levels"]):
            notes.append(f"지역 {want_geo}: 이 표에는 지역 구분이 없음 → 전국 값")
        # 성별 분류가 없는 표: 성별이 다른 분류의 코드 이름 끝에 있을 수 있음 ('기대수명 - 남')
        sexes = {SEX_ALIAS.get(s, s) for s in (f.get("성별") or [])}
        sex_done = any(l["kind"] == "sex" for l in prof["levels"])
        for i, (l, sel) in dims.items():
            if sex_done or l["kind"] in ("regions", "ages") or len(sel) < 2:
                continue
            picked = pick_sex(sel, sexes or None)
            if picked and len(picked) < len(sel):
                dims[i] = (l, picked)
                sex_done = sex_done or bool(sexes)
        items = match_items(prof, f, stems, sex_done, notes)

        where = [f"prd_se = {sql_str(se)}", f"itm_id IN ({', '.join(sql_str(i['itm_id']) for i in items)})"]
        for i, (l, sel) in dims.items():
            if sel:
                where.append(f"c{i}_code IN ({', '.join(sql_str(c['code']) for c in sel)})")
        pq = (OUT / prof["file"]).as_posix()
        if not f.get("시점") and f.get("의도") != "추이":
            # "최신" = 이 조건에 실제 값이 있는 가장 최근 연도 (최신 연도가 '-' 로만 채워진 표가 있음)
            y = con.execute(f"SELECT max(year) FROM read_parquet({sql_str(pq)}) "
                            f"WHERE {' AND '.join(where)} AND value IS NOT NULL").fetchone()[0]
            if y is not None and y != years[-1]:
                notes.append(f"최신 {years[-1]} 은 값이 없어 값이 있는 최신 {y} 사용")
                years = [int(y)]
        where.append(f"year IN ({', '.join(map(str, years))})")
        label_cols = [f"c{i}_label AS \"{l['obj_nm']}\"" for i, (l, _) in dims.items()]
        order = ["period_date"] + [f"c{i}_ord" for i in dims] + ["itm_ord"]
        df = con.execute(f'''
            SELECT period_label AS 시점, {', '.join(label_cols) + ',' if label_cols else ''}
                   itm_nm AS 항목, value AS 값, unit AS 단위, symbol AS 부호
            FROM read_parquet({sql_str(pq)}) WHERE {' AND '.join(where)}
            ORDER BY {', '.join(order)} LIMIT {MAX_ROWS + 1}''').df()
    finally:
        if own:
            con.close()
    if len(df) > MAX_ROWS:
        df = df.head(MAX_ROWS)
        notes.append(f"행이 {MAX_ROWS}개를 넘어 앞부분만 사용")
    if df.empty:
        notes.append("조건에 맞는 값이 없음 (빈 View)")

    view_id = f"view::{prof['table_key']}::{se}::{num}::{view_type_of(f)}"
    vdir = OUT / "views"
    vdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(vdir / (re.sub(r"[^\w\-]+", "_", view_id) + ".csv"), index=False, encoding="utf-8-sig")

    applied = {"시점": f"{years[0]}~{years[-1]}" if len(years) > 1 else str(years[0])}
    for i, (l, sel) in dims.items():
        applied[l["obj_nm"]] = [c["std"] for c in sel][:30]
    item_names = [i["name"] for i in items]
    units = sorted({u for u in df["단위"].dropna().unique() if u}) if not df.empty else []
    cond_txt = " ".join(f"{k} {' '.join(v[:5]) if isinstance(v, list) else v}" for k, v in applied.items() if v)
    meta = meta_profile_of(prof["tbl_id"])
    geo = sorted({c.get("geo_type") for l, sel in dims.values() if l["kind"] == "regions" for c in sel if c.get("geo_type")})
    latest = (prof.get("latest") or {}).get(se, {}).get("year")
    table = df.drop(columns=["단위", "부호"])
    record = {                                                  # 판단·RAG 모듈이 받기로 한 카드 모양 (2026-11-02 예시)
        "id": view_id,
        "lexical_text": " ".join([prof["tbl_nm"], prof["survey_nm"], cond_txt, " ".join(item_names), " ".join(units)]),
        "table": {"columns": list(table.columns),
                  "rows": table.astype(object).where(pd.notna(table), None).values.tolist()},
        "doc_type": "view",
        "parent_id": f"table::{prof['table_key']}",
        "metadata": {"survey_nm": prof["survey_nm"], "category": meta.get("category"),
                     "survey_type": meta.get("survey_type"), "view_type": view_type_of(f),
                     "prd_se": se, "prd_from": str(years[0]), "prd_to": str(years[-1]),
                     "is_latest": latest is not None and years[-1] == latest,
                     "unit": " ".join(units), "geo_level": geo[0] if len(geo) == 1 else (geo or None),
                     "n_points": int(df["값"].notna().sum()) if not df.empty else 0,
                     "items": item_names,
                     "dims": [l["obj_nm"] for l, sel in dims.values() if len(sel) > 1]},
        "source": {"table_key": prof["table_key"], "file": prof["file"], "org_id": prof["org_id"],
                   "tbl_id": prof["tbl_id"], "prd_se": se, "itm_id": [i["itm_id"] for i in items],
                   "dims": {f"c{i}": {"codes": [c["code"] for c in sel]} for i, (l, sel) in dims.items()},
                   "period": {} if f.get("의도") == "추이" and not f.get("시점") else {"in": [str(y) for y in years]},
                   "kosis_url": KOSIS_URL.format(org=prof["org_id"], tbl=prof["tbl_id"])},
    }
    return record, notes


VIEW_TYPE = {"추이": "trend", "비교": "breakdown", "순위": "breakdown", "값 조회": "value"}
KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}"
_meta = {}


def view_type_of(f):
    # 의도 슬롯 → View 종류 (id 끝자리와 metadata.view_type)
    return VIEW_TYPE.get((f or {}).get("의도"), "value")


def meta_profile_of(tbl_id):
    # 카탈로그 정보(category, survey_type)는 메타 프로필에서
    if not _meta:
        from backend.rag.ingestion.meta_profile import load_meta_profiles   # [CHANGED] 이전: from services.meta_profile import load_meta_profiles
        _meta.update({p["tbl_id"]: p for p in load_meta_profiles()})
    return _meta.get(tbl_id, {})
