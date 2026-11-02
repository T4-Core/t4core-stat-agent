"""
[엔드포인트 1] normalize — 원본 CSV + 메타 JSON → 정제 parquet + 표 프로필 + 표기 통일 사전

입력  kosis_data/catalog.csv, kosis_data/raw/<조사>/<기관_표>.csv, kosis_data/meta/<기관_표>.json   (읽기 전용)
출력  view_model/output/processed/<기관_표>.parquet   tidy 데이터 (View 생성의 유일한 입력)
      view_model/output/profiles/<기관_표>.json       표 구조 요약 (분류 종류·합계·지역 유형·항목·시점·부호·주석)
      view_model/output/dict/*.json                   쿼리·RAG 모듈과 공유할 표기 사전

실행  API : POST /normalize/{tbl_id}  (routers/normalize.py)
      CLI : cd view_model 후 (표를 반드시 지정, 기본 목록 없음)
            ../.venv/Scripts/python.exe -m services.normalize --tables DT_1B040A3           # 특정 표 정규화
            ../.venv/Scripts/python.exe -m services.normalize --tables DT_1B040A3 --force   # 원본이 그대로여도 다시

지연 정규화  다른 엔드포인트는 ensure_normalized(con, tbl_id) 를 부른다.
            이미 정규화돼 있으면 프로필만 읽고, 없으면 그때 정규화한다 (표를 미리 정하지 않기 위함)

규칙 출처: ys_work/view_model.ipynb 2단계(0~9장). 규칙은 바꾸지 않고 옮김 (설명은 normalize.md)
"""
import argparse
import json
import re
import sys

import pandas as pd

from config import DATA, OUT, connect, norm_space, one, safe, sql_str

# ── 4-1. 시점 정규화 ─────────────────────────────────────────────
# 원본/메타의 시점 구분 표기 → 표준 코드
PRD_SE_MAP = {
    "A": "Y", "Y": "Y", "년": "Y", "연": "Y",
    "Q": "Q", "분기": "Q",
    "H": "H", "반기": "H",
    "M": "M", "월": "M",
    "D": "D", "일": "D",
    "IR": "IR", "부정기": "IR",
    "F": "F",
}
PRD_SE_NAME = {"Y": "연간", "Q": "분기", "H": "반기", "M": "월간", "D": "일간", "IR": "부정기", "F": "다년주기"}


def se_case_sql(col):
    # SQL CASE 식: 매핑에 없는 값 중 'N년' 형태는 F, 그 외는 원본 유지 (조용히 버리지 않고 눈에 띄게 남김)
    whens = " ".join(f"WHEN {col} = {sql_str(k)} THEN {sql_str(v)}" for k, v in PRD_SE_MAP.items())
    return f"CASE {whens} WHEN {col} LIKE '%년' THEN 'F' ELSE coalesce(nullif({col}, ''), 'Y') END"


# y(연), s(월·분기·반기 번호), d(일) 은 PRD_DE 의 숫자만 뽑아 자리수로 자른다
PERIOD_DATE_SQL = '''
    CASE
      WHEN se = 'M' THEN make_date(y, greatest(1, least(12, s)), 1)
      WHEN se = 'Q' THEN make_date(y, (greatest(1, least(4, s)) - 1) * 3 + 1, 1)
      WHEN se = 'H' THEN make_date(y, (greatest(1, least(2, s)) - 1) * 6 + 1, 1)
      WHEN se = 'D' THEN make_date(y, greatest(1, least(12, s)), greatest(1, least(28, d)))
      ELSE make_date(y, 1, 1)
    END'''
PERIOD_LABEL_SQL = '''
    CASE
      WHEN se = 'M' THEN y::VARCHAR || '.' || lpad(s::VARCHAR, 2, '0')
      WHEN se = 'Q' THEN y::VARCHAR || ' ' || s::VARCHAR || '분기'
      WHEN se = 'H' THEN y::VARCHAR || CASE WHEN s = 1 THEN ' 상반기' ELSE ' 하반기' END
      WHEN se = 'D' THEN y::VARCHAR || '.' || lpad(s::VARCHAR, 2, '0') || '.' || lpad(d::VARCHAR, 2, '0')
      ELSE y::VARCHAR
    END'''

# ── 4-2. 값 정규화와 통계부호 ────────────────────────────────────
# KOSIS 통계표 일반 부호 의미 (표 주석에 설명이 있으면 그쪽을 우선)
DEFAULT_SYMBOL_MEANING = {
    "-": "해당 숫자 없음",
    "X": "비밀보호를 위해 공표하지 않음",
    "x": "비밀보호를 위해 공표하지 않음",
    "*": "공표 기준 미만 등으로 공표하지 않음",
    "***": "공표 기준 미만 등으로 공표하지 않음",
    "...": "자료 미상",
    "…": "자료 미상",
    "p": "잠정치",
    "e": "추정치",
}


def symbol_meanings(symbols, meta):
    # 표 주석(CMMT) 문장 중 해당 부호를 언급한 문장을 찾아 의미로 사용
    texts = [str(c.get("CMMT_DC") or "").strip() for c in (meta.get("CMMT") or []) if isinstance(c, dict)]
    sentences = [s.strip() for t in texts for s in re.split(r"[\n.]", t) if s.strip()]
    out = {}
    for sym in symbols:
        hit = next((s for s in sentences if re.search(rf"(^|[\s\"'‘“(]){re.escape(sym)}(?=[\s\"'’”)]|은|는|:|=|$)", s)), None)
        out[sym] = {"meaning": hit or DEFAULT_SYMBOL_MEANING.get(sym, "의미 미상 (원본 확인 필요)"),
                    "from": "CMMT" if hit else "default"}
    return out


# ── 4-3. 분류(차원) 정규화 ──────────────────────────────────────
# 합계 판별: 강한 합계 > 약한 합계 > 0으로만 된 코드
STRONG_TOTAL = {"계", "합계", "총계", "전체", "전국", "남녀계", "성별계", "연령계", "전연령", "전 연령", "Total", "total"}
WEAK_TOTAL = {"총인구", "총수"}

# 분류 종류 = 쿼리 모듈 conditions 의 조건 이름 (regions, sex, ages, nationality, scenario, cohort) + other
GEO_RE = re.compile(r"행정구역|시도|시군구|읍면동|지역|시·도|시군|권역")
SEX_RE = re.compile(r"^성별?$|^성$|^성별|성별$")
AGE_RE = re.compile(r"연령|나이|세별")
NOT_AGE_RE = re.compile(r"연령차")                       # 부부 연령차(남자연상 …)는 연령이 아님
AGE_NAME_RE = re.compile(r"\d+\s*[~\-]\s*\d+\s*세|\d+\s*세\s*(이상|미만|이하)|^\d+\s*세$")
NATION_RE = re.compile(r"국적|내외국인|내·외국인")
NOT_NATION_RE = re.compile(r"취득")                      # 국적취득연도별 (코드가 연도) 은 국적이 아님
SCENARIO_RE = re.compile(r"시나리오|가정별")
COHORT_RE = re.compile(r"년생|코호트")
ROLE_RE = re.compile(r"^(.+?)\s*의\s*(?:연령|국적|성)|^(가구주|남편|아내|모|부|처)\s*(?:연령|국적|성)")
SCENARIO_DEFAULT_RE = re.compile(r"기본\s*추계|^중위")
SEX_CODES = {"남자", "여자", "남", "여", "남성", "여성"}
URBAN_RURAL = {"동부", "읍부", "면부"}

# 표준 시도 사전: (행정구역 코드, 현재 공식 명칭, 별칭들)
# 현재 명칭을 표준으로 쓰고, 옛 명칭(강원도·전라북도)은 별칭으로 받는다
SIDO = [
    ("11", "서울특별시", ["서울", "서울시"]),
    ("21", "부산광역시", ["부산", "부산시"]),
    ("22", "대구광역시", ["대구", "대구시"]),
    ("23", "인천광역시", ["인천", "인천시"]),
    ("24", "광주광역시", ["광주"]),               # '광주시'는 경기도 광주시와 겹치므로 별칭에서 제외
    ("25", "대전광역시", ["대전", "대전시"]),
    ("26", "울산광역시", ["울산", "울산시"]),
    ("29", "세종특별자치시", ["세종", "세종시"]),
    ("31", "경기도", ["경기"]),
    ("32", "강원특별자치도", ["강원", "강원도"]),   # 2023.6 명칭 변경
    ("33", "충청북도", ["충북"]),
    ("34", "충청남도", ["충남"]),
    ("35", "전북특별자치도", ["전북", "전라북도"]), # 2024.1 명칭 변경
    ("36", "전라남도", ["전남"]),
    ("37", "경상북도", ["경북"]),
    ("38", "경상남도", ["경남"]),
    ("39", "제주특별자치도", ["제주", "제주도"]),
]
SIDO_ALIAS = {a: canon for _, canon, aliases in SIDO for a in [canon, *aliases]}
SIDO_CANON = {canon for _, canon, _ in SIDO}
GEO_DEPTH = {"전국": 0, "시도": 1, "동읍면부": 1, "기타": 1, "시군구": 2, "읍면동": 3}


def std_geo_name(name):
    n = norm_space(name)
    return SIDO_ALIAS.get(n.replace(" ", ""), SIDO_ALIAS.get(n, n))


def geo_type_of(name, std, is_total, tree_depth=None):
    n = norm_space(name)
    if is_total:
        return "전국"
    if n in URBAN_RURAL:
        return "동읍면부"
    if std in SIDO_CANON:
        return "시도"
    if tree_depth and tree_depth >= 2:
        return {2: "시군구"}.get(tree_depth, "읍면동")
    if re.search(r"(시|군|구)$", n):
        return "시군구"
    if re.search(r"(읍|면|동|가|리)$", n):
        return "읍면동"
    return "기타"


def level_kind(obj_nm, names):
    # 판정 순서가 중요: '국적(지역)별' 은 지역보다 국적을 먼저 봐야 함
    nm = str(obj_nm)
    s = {norm_space(n) for n in names} - STRONG_TOTAL
    if NATION_RE.search(nm) and not NOT_NATION_RE.search(nm):
        return "nationality"
    if GEO_RE.search(nm):
        return "regions"
    # 장래추계 표의 가정별: 코드가 '중위 추계(…)' 처럼 길거나, 그냥 '중위/고위/저위'
    if SCENARIO_RE.search(nm) and (nm.startswith("시나리오") or any("추계" in n for n in s) or s & {"중위", "고위", "저위"}):
        return "scenario"
    if COHORT_RE.search(nm):
        return "cohort"
    if SEX_RE.search(nm) or (s and s <= SEX_CODES):
        return "sex"
    if not NOT_AGE_RE.search(nm) and (AGE_RE.search(nm) or (
            len(s) >= 3 and sum(bool(AGE_NAME_RE.search(n)) for n in s) / len(s) >= 0.6)):
        return "ages"
    return "other"


def level_role(obj_nm):
    # 누구의 연령·국적·성별인가 ('가구주의 연령별' → 가구주). 본인이면 ''
    m = ROLE_RE.search(norm_space(obj_nm))
    return (m.group(1) or m.group(2)).strip() if m else ""


def parse_age(name):
    # '0 - 4세' '20~24세' '15세미만' '19세이하' '75세 이상' '0세' → (from, to). 상한 없음은 None
    n = norm_space(name).replace(" ", "")
    for pat, f in [(r"(\d+)[~\-](\d+)세", lambda m: (int(m[1]), int(m[2]))),
                   (r"(\d+)세(이상|이후)", lambda m: (int(m[1]), None)),
                   (r"(\d+)세미만", lambda m: (0, int(m[1]) - 1)),
                   (r"(\d+)세이하", lambda m: (0, int(m[1]))),
                   (r"(\d+)세", lambda m: (int(m[1]), int(m[1])))]:
        m = re.fullmatch(pat, n)
        if m:
            return f(m)
    return None, None


def parse_cohort(name):
    # '1985' '1985년생' '1983~1995년생' → (출생연도 from, to)
    m = re.search(r"(\d{4})(?:년생)?(?:\s*[~\-]\s*(\d{4}))?", str(name))
    return (int(m[1]), int(m[2] or m[1])) if m else (None, None)


def scenario_std(name):
    # '중위 추계(기본 추계: 출산율-중위 …)' → '중위'
    m = re.match(r"^(.+?)\s*추계", norm_space(name))
    return m.group(1).strip() if m else norm_space(name)


def pick_totals(codes):
    # codes: [{"code","name"}] → 합계로 볼 코드 집합
    strong = {c["code"] for c in codes if norm_space(c["name"]) in STRONG_TOTAL}
    if strong:
        return strong
    weak = {c["code"] for c in codes if norm_space(c["name"]) in WEAK_TOTAL}
    if weak:
        return weak
    return {c["code"] for c in codes if c["code"].strip("0") == "" and c["code"] != ""}


# ── 4-4. 메타 → 코드 사전 ───────────────────────────────────────
def raw_path(row):
    return DATA / "raw" / safe(row.category) / f"{row.org_id}_{row.tbl_id}.csv"


def meta_path(row):
    return DATA / "meta" / f"{row.org_id}_{row.tbl_id}.json"


def load_meta(row):
    p = meta_path(row)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def raw_obj_names(con, raw, cols, lv):
    # 원본의 C{i}_OBJ_NM (분류 이름) 을 읽어 {i: 이름}
    q = [f"any_value(C{i}_OBJ_NM)" if f"C{i}_OBJ_NM" in cols else "NULL" for i in lv]
    if not q:
        return {}
    vals = one(con, f"SELECT {', '.join(q)} FROM read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)")
    return {i: norm_space(v) for i, v in zip(lv, vals) if v}


def parse_meta(meta):
    # 메타 ITM → (분류 리스트, 항목 리스트)
    levels, items = {}, []
    for r in meta.get("ITM") or []:
        if not isinstance(r, dict) or "_error" in r:
            continue
        if r.get("OBJ_ID") == "ITEM":
            items.append({"itm_id": str(r.get("ITM_ID")), "name": norm_space(r.get("ITM_NM")),
                          "unit": norm_space(r.get("UNIT_NM")), "parent": str(r.get("UP_ITM_ID") or "")})
            continue
        k = r.get("OBJ_ID")
        if k not in levels:
            levels[k] = {"obj_id": k, "obj_nm": norm_space(r.get("OBJ_NM") or k),
                         "sn": int(r.get("OBJ_ID_SN") or len(levels) + 1), "codes": []}
        levels[k]["codes"].append({"code": str(r.get("ITM_ID")), "name": norm_space(r.get("ITM_NM")),
                                   "parent": str(r.get("UP_ITM_ID") or "")})
    return sorted(levels.values(), key=lambda x: x["sn"]), items


def match_levels(levels, lv, obj_names):
    # 원본 컬럼 번호 i → 메타 분류. 이름 우선, 남는 것은 순서대로
    by_name = {l["obj_nm"]: l for l in levels}
    out, used = {}, set()
    for i in lv:
        l = by_name.get(obj_names.get(i, ""))
        if l and l["obj_id"] not in used:
            out[i] = l
            used.add(l["obj_id"])
    rest = [l for l in levels if l["obj_id"] not in used]
    for i in lv:
        if i not in out and rest:
            out[i] = rest.pop(0)
    return out


def tree_depths(codes):
    parent = {c["code"]: c["parent"] for c in codes}

    def depth(c, seen=()):
        p = parent.get(c)
        return 0 if not p or p not in parent or c in seen else 1 + depth(p, seen + (c,))
    return {c["code"]: depth(c["code"]) for c in codes}


def infer_prefix_parent(codes):
    # 상위코드가 전혀 없을 때: 자기 코드의 가장 긴 접두어인 다른 코드를 부모로 (지역 코드 11 → 11320)
    if any(c["parent"] for c in codes):
        return codes
    keys = sorted({c["code"] for c in codes}, key=len)
    for c in codes:
        cand = [k for k in keys if len(k) < len(c["code"]) and c["code"].startswith(k) and k.strip("0")]
        c["parent"] = cand[-1] if cand else ""
    return codes


def infer_age_parent(codes, totals):
    # 연령 코드끼리 숫자 범위 포함 관계로 상위를 추정 ('80세이상' ⊃ '80 - 84세' ⊃ …)
    # 상위코드가 없거나 합계를 가리키는 코드만 대상. 자기를 포함하는 가장 좁은 범위의 코드를 상위로
    rng = {c["code"]: parse_age(c["name"]) for c in codes}
    for c in codes:
        f, t = rng[c["code"]]
        if c["code"] in totals or f is None or (c["parent"] and c["parent"] not in totals):
            continue
        cands = []
        for o in codes:
            of, ot = rng[o["code"]]
            if o["code"] in totals or of is None or (of, ot) == (f, t):
                continue
            if of <= f and (ot is None or (t is not None and t <= ot)):
                cands.append(((999 if ot is None else ot) - of, o["code"]))
        if cands:
            c["parent"] = min(cands)[1]
    return codes


def build_level_dims(level_no, lv_meta, obj_nm_raw=None):
    obj_nm = lv_meta["obj_nm"] if lv_meta else (obj_nm_raw or f"분류{level_no}")
    codes = [dict(c) for c in (lv_meta["codes"] if lv_meta else [])]
    names = [c["name"] for c in codes]
    kind = level_kind(obj_nm, names)
    if kind == "regions":
        codes = infer_prefix_parent(codes)
    totals = pick_totals(codes)
    if kind == "ages":
        codes = infer_age_parent(codes, totals)
    tdep = tree_depths(codes)
    name_of = {c["code"]: c["name"] for c in codes}
    dup = pd.Series(names).value_counts() if names else pd.Series(dtype=int)
    rows = []
    for o, c in enumerate(codes):
        is_total = c["code"] in totals
        if kind == "regions":
            std = "전국" if is_total else std_geo_name(c["name"])
            gtype = geo_type_of(c["name"], std, is_total, tdep[c["code"]] if c["parent"] else None)
            depth = GEO_DEPTH[gtype]
        else:
            std = scenario_std(c["name"]) if kind == "scenario" else c["name"]
            gtype = None
            depth = 0 if is_total else tdep[c["code"]] + (1 if totals else 0)
        label = c["name"]
        if dup.get(c["name"], 0) > 1:
            pn = name_of.get(c["parent"])
            label = f"{std_geo_name(pn) if kind == 'regions' and pn else (pn or c['code'])} {c['name']}"
        a_from, a_to = parse_age(c["name"]) if kind == "ages" and not is_total else (None, None)
        c_from, c_to = parse_cohort(c["name"]) if kind == "cohort" and not is_total else (None, None)
        rows.append({"level": level_no, "code": c["code"], "name": c["name"], "label": label, "std": std,
                     "ord": o, "depth": depth, "parent": c["parent"], "is_total": is_total, "geo_type": gtype,
                     "age_from": a_from, "age_to": a_to, "cohort_from": c_from, "cohort_to": c_to,
                     "is_default": kind == "scenario" and bool(SCENARIO_DEFAULT_RE.search(c["name"]))})
    total_code = next((r["code"] for r in rows if r["is_total"]), None)
    scen_default = next((r["code"] for r in rows if r["is_default"]), None)
    default_code, reason = ((total_code, "합계") if total_code else (scen_default, "기본 추계(중위)") if scen_default
                            else (rows[0]["code"], "첫 코드") if rows else (None, None))
    info = {"level": level_no, "obj_id": lv_meta["obj_id"] if lv_meta else None, "obj_nm": obj_nm, "kind": kind,
            "role": level_role(obj_nm), "n_codes": len(codes), "total_code": total_code,
            "default_code": default_code, "default_reason": reason}
    return info, rows


def build_item_dims(items):
    # 항목(ITEM): 연령이 항목으로 들어온 표(DT_1JA1502 등) 처리
    names = [i["name"] for i in items]
    n_age = sum(bool(AGE_NAME_RE.search(n)) for n in names)
    totals = pick_totals([{"code": i["itm_id"], "name": i["name"]} for i in items])
    rows = []
    for o, it in enumerate(items):
        is_age = bool(AGE_NAME_RE.search(it["name"]))
        # 연령 항목이 3개 이상인데 연령이 아닌 첫 항목(예: '외국인') → 연령 합계 역할
        is_total = it["itm_id"] in totals or (n_age >= 3 and not is_age and o == 0)
        a_from, a_to = parse_age(it["name"]) if is_age else (None, None)
        rows.append({"itm_id": it["itm_id"], "itm_ord": o, "unit_meta": it["unit"],
                     "itm_kind": "ages" if is_age else "other", "itm_total": is_total, "age_from": a_from, "age_to": a_to})
    return pd.DataFrame(rows, columns=["itm_id", "itm_ord", "unit_meta", "itm_kind", "itm_total", "age_from", "age_to"])


# ── 5. 표 하나 정규화 ───────────────────────────────────────────
def normalize_table(con, row, force=False):
    key = f"{row.org_id}_{row.tbl_id}"
    raw = raw_path(row)
    pq = OUT / "processed" / f"{key}.parquet"
    prof_p = OUT / "profiles" / f"{key}.json"
    if not raw.exists():
        print(f"  (원본 없음) {raw}")
        return None
    # 원본보다 새 결과가 있으면 재사용 (증분 처리)
    if pq.exists() and prof_p.exists() and not force and pq.stat().st_mtime >= raw.stat().st_mtime:
        return json.loads(prof_p.read_text(encoding="utf-8"))

    meta = load_meta(row)
    src = f"read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)"
    cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
    lv = [i for i in range(1, 9) if f"C{i}" in cols]

    # 1) 코드 사전
    levels_meta, items_meta = parse_meta(meta)
    obj_names = raw_obj_names(con, raw, cols, lv)
    matched = match_levels(levels_meta, lv, obj_names)
    level_info, dim_rows = [], []
    for i in lv:
        info, rows = build_level_dims(i, matched.get(i), obj_names.get(i))
        level_info.append(info)
        dim_rows += rows
    dims = pd.DataFrame(dim_rows, columns=["level", "code", "name", "label", "std", "ord", "depth",
                                           "parent", "is_total", "geo_type"]).drop_duplicates(["level", "code"])
    items = build_item_dims(items_meta)
    con.register("dims_df", dims)
    con.register("items_df", items)

    # 2) 정규화 SQL
    sel, joins = [], []
    for i in lv:
        nm = f"nullif(trim(r.C{i}_NM), '')" if f"C{i}_NM" in cols else "NULL"
        sel.append(f'''r.C{i} AS c{i}_code,
            coalesce({nm}, d{i}.name, r.C{i}) AS c{i}_name,
            coalesce(d{i}.label, {nm}, r.C{i}) AS c{i}_label,
            coalesce(d{i}.std, {nm}, r.C{i}) AS c{i}_std,
            coalesce(d{i}.ord, 99999) AS c{i}_ord,
            coalesce(d{i}.depth, 0) AS c{i}_depth,
            coalesce(d{i}.is_total, false) AS c{i}_total,
            d{i}.geo_type AS c{i}_geo_type,
            nullif(d{i}.parent, '') AS c{i}_parent''')
        joins.append(f"LEFT JOIN dims_df d{i} ON d{i}.level = {i} AND d{i}.code = r.C{i}")
    # 단위: 원본 → (비었으면) 같은 항목의 최빈 단위 → 메타 단위. 원본이 비어 채운 경우 unit_inferred 표시
    if "UNIT_NM" in cols:
        unit = "coalesce(nullif(trim(r.UNIT_NM), ''), um.unit_mode, it.unit_meta, '')"
        unit_inf = "(nullif(trim(r.UNIT_NM), '') IS NULL AND coalesce(um.unit_mode, it.unit_meta, '') <> '')"
        um_cte = ", um AS (SELECT ITM_ID AS um_itm, mode(nullif(trim(UNIT_NM), '')) AS unit_mode FROM r0 GROUP BY ITM_ID)"
        um_join = "LEFT JOIN um ON um.um_itm = r.ITM_ID"
    else:
        unit, unit_inf, um_cte, um_join = "coalesce(it.unit_meta, '')", "false", "", ""
    se_col = "trim(coalesce(PRD_SE, ''))" if "PRD_SE" in cols else "'Y'"
    order = ", ".join(["prd_se", "period_date"] + [f"c{i}_ord" for i in lv] + ["itm_ord"])
    sql = f'''
    COPY (
      WITH r0 AS (
        SELECT *, {se_case_sql(se_col)} AS se,
               regexp_replace(coalesce(PRD_DE, ''), '[^0-9]', '', 'g') AS pd,
               nullif(trim(DT), '') AS dt
        FROM {src}
      ), r AS (
        SELECT *, try_cast(substr(pd, 1, 4) AS INTEGER) AS y,
               coalesce(try_cast(nullif(substr(pd, 5, 2), '') AS INTEGER), 1) AS s,
               coalesce(try_cast(nullif(substr(pd, 7, 2), '') AS INTEGER), 1) AS d,
               try_cast(replace(dt, ',', '') AS DOUBLE) AS v
        FROM r0
      ){um_cte}
      SELECT {sql_str(key)} AS table_key, {sql_str(row.org_id)} AS org_id, {sql_str(row.tbl_id)} AS tbl_id,
             r.se AS prd_se, r.PRD_DE AS prd_de, r.y AS year,
             {PERIOD_LABEL_SQL} AS period_label, {PERIOD_DATE_SQL} AS period_date,
             {', '.join(sel) + ',' if sel else ''}
             r.ITM_ID AS itm_id, coalesce(nullif(trim(r.ITM_NM), ''), r.ITM_ID) AS itm_nm,
             coalesce(it.itm_ord, 99999) AS itm_ord, coalesce(it.itm_kind, 'other') AS itm_kind,
             coalesce(it.itm_total, false) AS itm_total, {unit} AS unit, {unit_inf} AS unit_inferred,
             r.v AS value, r.DT AS value_raw,
             CASE WHEN r.v IS NULL THEN r.dt END AS symbol
      FROM r {' '.join(joins)}
      LEFT JOIN items_df it ON it.itm_id = r.ITM_ID
      {um_join}
      WHERE r.y IS NOT NULL
      ORDER BY {order}
    ) TO {sql_str(pq.as_posix())} (FORMAT PARQUET)'''
    pq.parent.mkdir(parents=True, exist_ok=True)
    con.execute(sql)
    con.unregister("dims_df")
    con.unregister("items_df")

    # 3) 프로필 (분류 종류별 속성: 연령·코호트 범위, 시나리오 기본값 등은 코드 사전에서 가져와 붙임)
    extra = {(r["level"], r["code"]): {k: r[k] for k in ("age_from", "age_to", "cohort_from", "cohort_to", "is_default")}
             for r in dim_rows}
    as_int = lambda x: None if x is None or pd.isna(x) else int(x)   # noqa: E731  (NaN 은 JSON 표준이 아니므로 None 으로)
    item_extra = {r.itm_id: {"age_from": as_int(r.age_from), "age_to": as_int(r.age_to)} for r in items.itertuples()}
    prof = build_profile(con, row, key, pq, raw, lv, level_info, meta, extra, item_extra)
    prof_p.parent.mkdir(parents=True, exist_ok=True)
    prof_p.write_text(json.dumps(prof, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return prof


def build_profile(con, row, key, pq, raw, lv, level_info, meta, extra=None, item_extra=None):
    # 프로필 값은 메타가 아니라 방금 만든 parquet 에서 다시 집계 ("실제로 조회 가능한 것" 만 기록)
    extra, item_extra = extra or {}, item_extra or {}
    src = f"read_parquet({sql_str(pq.as_posix())})"
    n_raw = one(con, f"SELECT count(*) FROM read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)")[0]
    n_rows, n_num = one(con, f"SELECT count(*), count(value) FROM {src}")

    periods = {}
    for se, prd, lab, yr, _ in con.execute(
            f"SELECT DISTINCT prd_se, prd_de, period_label, year, period_date FROM {src} ORDER BY prd_se, period_date").fetchall():
        periods.setdefault(se, []).append({"prd_de": prd, "label": lab, "year": yr})

    levels = []
    for info in level_info:
        i = info["level"]
        codes = [{"code": a, "name": b, "label": c, "std": d, "ord": e, "depth": f, "is_total": bool(g), "geo_type": h,
                  "parent": k, **extra.get((i, a), {})}
                 for a, b, c, d, e, f, g, h, k in con.execute(f'''
                    SELECT c{i}_code, any_value(c{i}_name), any_value(c{i}_label), any_value(c{i}_std),
                           min(c{i}_ord), min(c{i}_depth), bool_or(c{i}_total), any_value(c{i}_geo_type),
                           any_value(c{i}_parent)
                    FROM {src} GROUP BY c{i}_code ORDER BY min(c{i}_ord), c{i}_code''').fetchall()]
        totals = [c for c in codes if c["is_total"]]
        # 기본값 코드가 실제 데이터에 없으면(메타에만 정의) 데이터 기준으로 다시 고름
        dflt = info.get("default_code")
        if not any(c["code"] == dflt for c in codes):
            dflt, info = (totals[0]["code"] if totals else codes[0]["code"] if codes else None), \
                {**info, "default_reason": "합계" if totals else "첫 코드"}
        levels.append({**info, "n_codes": len(codes), "total_code": totals[0]["code"] if totals else None,
                       "default_code": dflt,
                       "geo_types": sorted({c["geo_type"] for c in codes if c["geo_type"]}), "codes": codes})

    items = [{"itm_id": a, "name": b, "unit": c, "kind": d, "is_total": bool(e), "n_rows": n, **item_extra.get(a, {})}
             for a, b, c, d, e, n in con.execute(f'''
                SELECT itm_id, any_value(itm_nm), any_value(unit), any_value(itm_kind), bool_or(itm_total), count(*)
                FROM {src} GROUP BY itm_id ORDER BY min(itm_ord), itm_id''').fetchall()]

    sym_cnt = dict(con.execute(f"SELECT symbol, count(*) FROM {src} WHERE symbol IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
    sym_mean = symbol_meanings(list(sym_cnt), meta)
    cycles = sorted({norm_space(p.get("PRD_SE")) for p in (meta.get("PRD") or []) if isinstance(p, dict) and p.get("PRD_SE")})
    notes = [norm_space(c.get("CMMT_DC")) for c in (meta.get("CMMT") or []) if isinstance(c, dict) and norm_space(c.get("CMMT_DC"))]
    source = next((s for s in (meta.get("SOURCE") or []) if isinstance(s, dict)), {})

    return {
        "table_key": key, "org_id": row.org_id, "tbl_id": row.tbl_id, "tbl_nm": row.tbl_nm,
        "category": row.category, "path": row.path,
        "survey_nm": norm_space(source.get("JOSA_NM", "")).strip("「」") or row.category,
        "dept_nm": norm_space(source.get("DEPT_NM", "")),
        "file": f"processed/{key}.parquet",
        "row_check": {"raw": n_raw, "processed": n_rows, "dropped": n_raw - n_rows},
        "n_numeric": n_num,
        "periods": periods, "cycles": cycles,
        "latest": {se: ps[-1] for se, ps in periods.items()},
        "levels": levels, "items": items,
        "symbols": {s: {"count": sym_cnt[s], **sym_mean[s]} for s in sym_cnt},
        "notes": list(dict.fromkeys(notes)),
    }


# ── 6. 검증: 합계 정합성 ("하위 코드 합 ≈ 합계 코드 값") ──────────
def check_total(con, prof, level_no, include_urban_rural=False):
    pq = (OUT / prof["file"]).as_posix()
    lvl = next(l for l in prof["levels"] if l["level"] == level_no)
    if not lvl["total_code"]:
        return None
    se = "Y" if "Y" in prof["periods"] else next(iter(prof["periods"]))
    latest = prof["latest"][se]["prd_de"]
    item = next((i for i in prof["items"] if i["is_total"]), prof["items"][0])
    base = {"tbl_id": prof["tbl_id"], "분류": lvl["obj_nm"], "동읍면부포함": include_urban_rural, "시점": latest, "항목": item["name"]}
    if re.search(r"%|‰|율|비$", item["unit"] or ""):
        return {**base, "비고": f"단위가 비율({item['unit']})이라 합산 검증 제외"}
    # 다른 분류는 합계로, 합계가 없는 분류(시나리오 등)는 기본값(중위)으로 고정 — 고정하지 않으면 시나리오 3개가 함께 더해짐
    fixed = [f"c{l['level']}_total" if l["total_code"] else f"c{l['level']}_code = {sql_str(l['default_code'])}"
             for l in prof["levels"] if l["level"] != level_no and l["default_code"]]
    where = " AND ".join([f"prd_se = '{se}'", f"prd_de = {sql_str(latest)}", f"itm_id = {sql_str(item['itm_id'])}"] + fixed)
    ur = "" if include_urban_rural else f"AND coalesce(c{level_no}_geo_type, '') <> '동읍면부'"
    total, child_sum, n_child, n_sym = one(con, f'''
        SELECT max(value) FILTER (WHERE c{level_no}_total),
               sum(value) FILTER (WHERE NOT c{level_no}_total AND c{level_no}_depth = 1 {ur}),
               count(*) FILTER (WHERE NOT c{level_no}_total AND c{level_no}_depth = 1 {ur}),
               count(symbol) FILTER (WHERE NOT c{level_no}_total AND c{level_no}_depth = 1 {ur})
        FROM read_parquet({sql_str(pq)}) WHERE {where}''')
    ratio = child_sum / total if total and child_sum else None
    return {**base, "합계값": total, "하위합": child_sum, "하위코드수": n_child, "하위부호수": n_sym,
            "비율": round(ratio, 4) if ratio else None, "비고": ""}


# ── 7. 표기 통일 사전 내보내기 (쿼리·RAG 모듈 공유용) ─────────────
def export_dicts():
    d = OUT / "dict"
    d.mkdir(parents=True, exist_ok=True)
    region_dict = {
        "version": 1,
        "standard": "현재 공식 명칭 (옛 명칭은 aliases)",
        "national": {"std": "전국", "aliases": ["전국", "합계", "계", "총계"]},
        "sido": [{"code": c, "std": s, "aliases": a} for c, s, a in SIDO],
        "geo_types": {"전국": 0, "시도": 1, "시군구": 2, "읍면동": 3,
                      "동읍면부": "전국을 동부/읍부/면부로 나눈 것 (시도와 합산 금지)", "기타": "권역 등"},
    }
    period_rules = {
        "version": 1,
        "prd_se": {k: {"name": PRD_SE_NAME[k]} for k in PRD_SE_NAME},
        "raw_to_std": PRD_SE_MAP,
        "label_format": {"Y": "YYYY", "F": "YYYY", "IR": "YYYY", "Q": "YYYY N/4분기", "H": "YYYY 상반기|하반기",
                         "M": "YYYY.MM", "D": "YYYY.MM.DD"},
    }
    dim_kinds = {
        "version": 1,
        "note": "분류 종류 이름 = 쿼리 모듈 conditions 의 조건 이름. View 모듈이 분류(C1~C8)를 이 이름으로 판정",
        "kinds": {
            "regions": {"detect": GEO_RE.pattern, "value": "std(표준명) + geo_type(전국/시도/시군구/읍면동)", "default": "합계(전국)"},
            "sex": {"detect": SEX_RE.pattern, "value": "남자 / 여자", "default": "합계(계·전체)"},
            "ages": {"detect": AGE_RE.pattern, "exclude": NOT_AGE_RE.pattern,
                     "value": "age_from, age_to (숫자 범위, 상한 없음 = null) ← 쿼리 {from, to} 와 비교", "default": "합계"},
            "nationality": {"detect": NATION_RE.pattern, "exclude": NOT_NATION_RE.pattern, "value": "국가명 / 내국인·외국인",
                            "default": "합계"},
            "scenario": {"detect": SCENARIO_RE.pattern + " (코드에 '추계' 포함)", "value": "std = 짧은 이름 (중위/고위/저위/…)",
                         "default": "기본 추계(중위) — 합계 없음"},
            "cohort": {"detect": COHORT_RE.pattern, "value": "cohort_from, cohort_to (출생연도)", "default": "합계 또는 첫 코드"},
            "other": {"detect": "위에 해당하지 않음", "value": "범주 이름으로 매칭", "default": "합계 또는 첫 코드"},
        },
        "detect_order": ["nationality", "regions", "scenario", "cohort", "sex", "ages"],
        "role": {"detect": ROLE_RE.pattern, "note": "누구의 연령·국적·성별인가 (가구주, 모, 외국인 아내 …). 쿼리 모듈에 아직 없는 개념 — 협의 필요"},
    }
    for name, obj in [("region_dict", region_dict), ("period_rules", period_rules), ("symbol_dict", DEFAULT_SYMBOL_MEANING),
                      ("dim_kinds", dim_kinds)]:
        (d / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return sorted(p.name for p in d.iterdir())


def load_targets(tables):
    catalog = pd.read_csv(DATA / "catalog.csv", dtype=str)
    catalog = catalog[catalog["selected"] == "True"]
    missing = [t for t in tables if t not in set(catalog["tbl_id"])]
    if missing:
        raise ValueError(f"catalog.csv(selected) 에 없는 표: {missing}")
    return catalog.set_index("tbl_id").loc[tables].reset_index()


def ensure_normalized(con, tbl_id, force=False):
    # 지연 정규화: resolve 가 고른 표만 이 시점에 정규화. 캐시(원본보다 새 parquet)가 있으면 프로필만 읽음
    row = next(load_targets([tbl_id]).itertuples())
    return normalize_table(con, row, force=force)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="원본 CSV → 정제 parquet + 프로필")
    ap.add_argument("--tables", nargs="+", required=True, help="정규화할 tbl_id (예: DT_1B040A3)")
    ap.add_argument("--force", action="store_true", help="원본이 그대로여도 다시 정규화")
    args = ap.parse_args()

    con = connect()
    profiles = {}
    for r in load_targets(args.tables).itertuples():
        p = normalize_table(con, r, force=args.force)
        if p is None:
            continue
        profiles[r.tbl_id] = p
        print(f"[정규화] {r.tbl_id:16s} 행 {p['row_check']} | 숫자 {p['n_numeric']:,} | 부호 {list(p['symbols'])} | 주기 {p['cycles']}")

    print("\n[분류 판정]")
    for t, p in profiles.items():
        for l in p["levels"]:
            dflt = next((c["std"] for c in l["codes"] if c["code"] == l["default_code"]), None)
            print(f"  {t:16s} c{l['level']} {l['obj_nm'][:20]:20s} kind={l['kind']:11s} 코드 {l['n_codes']:5d} "
                  f"기본값={str(dflt)[:15]}({l['default_reason']}) 지역유형={','.join(l['geo_types'])}")
        units = sorted({i["unit"] for i in p["items"] if i["unit"]})
        print(f"  {t:16s} 항목 {len(p['items'])}개, 단위 {units or '(없음)'}")

    print("\n[합계 정합성] 비율 ≈ 1.0 이면 합계 판별·계층 정상")
    for p in profiles.values():
        for l in p["levels"]:
            for ur in ([False, True] if "동읍면부" in l["geo_types"] else [False]):
                c = check_total(con, p, l["level"], include_urban_rural=ur)
                if c:
                    print(f"  {c['tbl_id']:16s} {c['분류'][:16]:16s} 동읍면부포함={c['동읍면부포함']!s:5s} "
                          f"비율={c.get('비율')} {c['비고']}")

    print("\n[사전]", export_dicts())


if __name__ == "__main__":
    main()
