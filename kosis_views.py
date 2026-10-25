"""
KOSIS 수집 결과(raw/meta/catalog) → 그래프용 정제 데이터 + 좌표 + RAG 검색용 JSON

입력 (kosis_rag_builder.py 수집 결과, API 재호출 없음)
  kosis_data/catalog.csv, kosis_data/meta/*.json, kosis_data/raw/<조사>/<기관_표>.csv

단계
  python kosis_views.py prepare   # 1) 표별 정제 parquet: 시점 파싱·정렬, 값 숫자화, 코드 순서·계층·합계 표시
  python kosis_views.py views     # 2) 표 레코드 + 뷰(그래프 1개 단위) 레코드 JSONL 생성
  python kosis_views.py enrich    # 3) (선택) LLM으로 질문·동의어·요약 보강 (숫자 검증 포함)
  python kosis_views.py render --id "view::..."   # 좌표로 데이터를 다시 불러 차트 HTML 생성 (검증용)
  python kosis_views.py all       # prepare + views
  python kosis_views.py audit --catalog data/population_table_catalog.jsonl   # 누락·최신성 점검

  --catalog <population_table_catalog.jsonl> 를 views 에 주면 XLS 카탈로그(preprocess_population.py 결과)의
  조사명·작성기관·출처 문구·전체 메뉴 경로·KOSIS 링크·수록기간(최신성)을 RAG 레코드에 결합합니다.

옵션
  --data kosis_data      수집 폴더
  --out  kosis_data/rag_views
  --surveys 인구총조사 ...   특정 조사만,  --max-tables 20  테스트용
  --kiwi                 BM25용 한국어 형태소 토큰(bm25_tokens) 생성 (pip install kiwipiepy)

출력 (--out 아래)
  processed/<기관_표>.parquet  그래프용 tidy 데이터 (정렬 완료)
  profiles/<기관_표>.json      표 구조 요약 (분류·코드·항목·시점)
  tables.jsonl / views.jsonl / records.jsonl(둘 합침)   RAG 인덱싱 대상
  survey_map_template.csv      stat_id → 조사명 매핑 작성용 (채워서 data 폴더에 survey_map.csv 로 저장)

필요 패키지: pip install duckdb pyarrow pandas   (선택: plotly, kiwipiepy, openai)
"""
import argparse
import json
import math
import os
import re
from pathlib import Path

import duckdb
import pandas as pd

# config , 설정내용
MAX_ITEMS = 5            # 표당 뷰를 만들 대표 항목 수 (항목 순서상 앞쪽)
MAX_BREAKDOWN_ITEMS = 3  # 분류별 비교 뷰를 만들 항목 수
MAX_VIEWS = 40           # 표당 뷰 상한
MAX_LINES = 8            # 다중 시계열 뷰의 최대 시리즈 수
TOP_N = 20               # 범주가 많을 때 차트 표시 개수
CODE_LIST_LIMIT = 300    # 좌표에 코드를 직접 나열하는 상한 (넘으면 depth 선택자 사용)
PREVIEW_ROWS = 60

TOTAL_RE = re.compile(r"^(계|합계|총계|소계|전체|전국|총인구|총수|Total|전 ?연령|연령계|남녀계|성별계)$")
GEO_RE = re.compile(r"행정구역|시도|시군구|읍면동|지역|시·도|시군|권역")
SEX_RE = re.compile(r"^성별?$|^성$|^성별")
AGE_RE = re.compile(r"연령|나이")
SEX_CODES = {"남자", "여자", "남", "여", "남성", "여성"}
GEO_LEVEL = {0: "전국", 1: "시도", 2: "시군구", 3: "읍면동"}
COUNT_UNITS = {"명", "가구", "건", "호", "개", "천명", "세대", "개소", "천가구"}

KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}"

# 동의어/구어 표현 (aliases). data 폴더에 aliases.json({"용어": ["동의어", ...]})을 두면 병합
ALIASES = {
    "총인구": ["인구", "인구수", "사람 수", "주민 수"], "인구": ["인구수", "사람 수"],
    "65세 이상": ["노인", "고령자", "노년층", "어르신"], "고령": ["노인", "고령자"],
    "합계출산율": ["출산율", "TFR", "아이 낳는 수"], "출생": ["출산", "태어난 아이", "신생아"],
    "출생아": ["신생아", "태어난 아이", "출산아"], "사망": ["사망자", "죽은 사람"],
    "혼인": ["결혼", "결혼 건수"], "이혼": ["이혼 건수", "갈라섬"], "가구": ["세대", "가정", "집"],
    "1인가구": ["1인 가구", "혼자 사는 가구", "나홀로 가구", "독거"], "외국인": ["외국 사람", "이주민"],
    "체류외국인": ["외국인 체류자", "국내 거주 외국인"], "전입": ["이사 온", "전입자", "유입"],
    "전출": ["이사 간", "전출자", "유출"], "순이동": ["순유입", "인구 유입", "순유출"],
    "생산연령인구": ["15~64세", "일하는 나이 인구"], "유소년인구": ["0~14세", "어린이 인구"],
    "고령인구": ["노인 인구", "65세 이상 인구"], "추계": ["전망", "예측", "미래"],
    "장래인구": ["인구 전망", "미래 인구"], "행정구역": ["지역", "지역별"], "시도": ["광역시도", "광역자치단체"],
    "시군구": ["기초자치단체", "시군구별"], "성별": ["남녀", "성"], "남자": ["남성"], "여자": ["여성"],
    "다문화": ["다문화가정", "다문화가족"], "평균연령": ["평균 나이"], "중위연령": ["중간 나이"],
    "인구밀도": ["밀집도", "인구 밀집"], "기대수명": ["평균수명", "수명"], "귀국": ["영주귀국"],
    "출입국": ["입국", "출국", "해외 이동"], "인구이동": ["이사", "이주", "이동자"],
}


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


# 한국어 조사
_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False,
                  "5": False, "6": True, "7": True, "8": True, "9": False}


def josa(word, pair):
    """josa('서울', '은/는') → '서울은'"""
    a, b = pair.split("/")
    w = re.sub(r"[\s\)\]\}\"'%·.,]+$", "", str(word))
    if not w:
        return f"{word}{b}"
    ch = w[-1]
    if "가" <= ch <= "힣":
        bat = (ord(ch) - 0xAC00) % 28 != 0
        if pair == "으로/로" and (ord(ch) - 0xAC00) % 28 == 8:   # ㄹ 받침
            bat = False
    elif ch.isdigit():
        bat = _DIGIT_BATCHIM[ch]
    else:
        bat = ch.lower() in "lmnr"
    return f"{word}{a if bat else b}"


# 숫자 표기
def fmt_num(v, unit=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "자료없음"
    u = str(unit or "")
    if "%" in u or "율" in u or "비" in u or abs(v - round(v)) > 1e-9:
        s = f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.1f}"
    else:
        s = f"{int(round(v)):,}"
    return f"{s}{u if u and u != 'nan' else ''}".strip()


def fmt_pct(p):
    return f"{p:+.1f}%"


# 메타 해석
def meta_levels(meta):
    """ITM 메타 → 분류 레벨(코드·순서·상위코드) 리스트, 항목 리스트"""
    levels, items = {}, []
    for r in meta.get("ITM") or []:
        if not isinstance(r, dict) or "_error" in r:
            continue
        if r.get("OBJ_ID") == "ITEM":
            items.append({"itm_id": str(r.get("ITM_ID")), "nm": r.get("ITM_NM"), "unit": r.get("UNIT_NM") or ""})
            continue
        k = r.get("OBJ_ID")
        if k not in levels:
            levels[k] = {"obj_id": k, "obj_nm": r.get("OBJ_NM") or k,
                         "sn": int(r.get("OBJ_ID_SN") or len(levels) + 1), "codes": []}
        levels[k]["codes"].append({"code": str(r.get("ITM_ID")), "name": str(r.get("ITM_NM") or "").strip(),
                                   "parent": str(r.get("UP_ITM_ID") or "")})
    return sorted(levels.values(), key=lambda x: x["sn"]), items


def dims_frame(levels):
    """레벨별 코드 사전: 순서(ord), 깊이(depth), 합계 여부(is_total)"""
    rows = []
    for li, l in enumerate(levels, 1):
        codes = l["codes"]
        parent = {c["code"]: c["parent"] for c in codes}
        has_child = {c["parent"] for c in codes if c["parent"]}

        def depth(c, seen=()):
            p = parent.get(c)
            return 0 if not p or p not in parent or c in seen else 1 + depth(p, seen + (c,))
        depths = {c["code"]: depth(c["code"]) for c in codes}
        roots = [c for c in codes if depths[c["code"]] == 0]
        geo = bool(GEO_RE.search(str(l["obj_nm"])))
        # 상위코드 정보가 없고 지역 분류면 코드 길이로 계층 추정 (00 전국 / 2자리 시도 / 5자리 시군구 / 7자리↑ 읍면동)
        if geo and len(roots) == len(codes) and len({len(c["code"]) for c in codes}) > 1:
            tot = {c["code"] for c in codes if c["code"].strip("0") == "" or TOTAL_RE.match(c["name"])}
            lens = sorted({len(c["code"]) for c in codes if c["code"] not in tot})
            for c in codes:   # 합계=0, 가장 짧은 코드=1(시도), 그다음=2(시군구) ...
                depths[c["code"]] = 0 if c["code"] in tot else lens.index(len(c["code"])) + 1
        name_of = {c["code"]: c["name"] for c in codes}
        cnt = pd.Series([c["name"] for c in codes]).value_counts()
        for o, c in enumerate(codes):
            is_total = bool(TOTAL_RE.match(c["name"])) or (
                depths[c["code"]] == 0 and c["code"] in has_child and len(roots) == 1)
            # 같은 분류 안에서 이름이 겹치면(서울 중구 / 부산 중구) 상위 이름을 붙여 구분
            label = c["name"]
            if cnt.get(c["name"], 0) > 1:
                pn = name_of.get(c["parent"]) or (c["parent"] or c["code"])
                label = f"{pn} {c['name']}"
            rows.append({"level": li, "code": c["code"], "name": c["name"], "label": label, "ord": o,
                         "depth": depths[c["code"]], "parent": c["parent"], "is_total": is_total,
                         "dup": label != c["name"]})
    df = pd.DataFrame(rows, columns=["level", "code", "name", "label", "ord", "depth", "parent",
                                     "is_total", "dup"])
    return df.drop_duplicates(["level", "code"])          # 같은 코드 중복 정의 시 조인 행 복제 방지


def level_kind(obj_nm, names):
    nm = str(obj_nm)
    s = {str(n).strip() for n in names}
    if GEO_RE.search(nm):
        return "geo"
    if SEX_RE.search(nm) or (s - {"계", "합계", "전체"}) and (s - {"계", "합계", "전체"}) <= SEX_CODES:
        return "sex"
    if AGE_RE.search(nm):
        return "age"
    return "other"


def is_ordinal(names):
    ns = [n for n in names if not TOTAL_RE.match(str(n))]
    return len(ns) >= 3 and sum(bool(re.search(r"\d", str(n))) for n in ns) / len(ns) >= 0.6


# 1) prepare
PERIOD_SQL = """
    CASE
      WHEN se IN ('M') THEN make_date(y, greatest(1, least(12, s)), 1)
      WHEN se IN ('Q') THEN make_date(y, (greatest(1, least(4, s)) - 1) * 3 + 1, 1)
      WHEN se IN ('H') THEN make_date(y, (greatest(1, least(2, s)) - 1) * 6 + 1, 1)
      WHEN se IN ('D') THEN make_date(y, greatest(1, least(12, s)), greatest(1, least(28, d)))
      ELSE make_date(y, 1, 1)
    END"""
LABEL_SQL = """
    CASE
      WHEN se = 'M' THEN y::VARCHAR || '.' || lpad(s::VARCHAR, 2, '0')
      WHEN se = 'Q' THEN y::VARCHAR || ' ' || s::VARCHAR || '/4분기'
      WHEN se = 'H' THEN y::VARCHAR || CASE WHEN s = 1 THEN ' 상반기' ELSE ' 하반기' END
      WHEN se = 'D' THEN y::VARCHAR || '.' || lpad(s::VARCHAR, 2, '0') || '.' || lpad(d::VARCHAR, 2, '0')
      ELSE y::VARCHAR
    END"""
SE_NORM = """
    CASE WHEN p IN ('M', '월') THEN 'M' WHEN p IN ('Q', '분기') THEN 'Q' WHEN p IN ('H', '반기') THEN 'H'
         WHEN p IN ('D', '일') THEN 'D' WHEN p IN ('Y', '년', '연') THEN 'Y'
         WHEN p LIKE '%년' OR p = 'F' THEN 'F' ELSE coalesce(nullif(p, ''), 'Y') END"""


def prepare_table(con, row, data_dir, out_dir, force=False):
    key = f"{row.org_id}_{row.tbl_id}"
    raw = data_dir / "raw" / safe(row.category) / f"{key}.csv"
    pq = out_dir / "processed" / f"{key}.parquet"
    prof_p = out_dir / "profiles" / f"{key}.json"
    if not raw.exists():
        return None
    if pq.exists() and prof_p.exists() and not force and pq.stat().st_mtime >= raw.stat().st_mtime:
        return json.loads(prof_p.read_text(encoding="utf-8"))

    mp = data_dir / "meta" / f"{key}.json"
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    levels, items_meta = meta_levels(meta)
    dims = dims_frame(levels)
    cols = [c[0] for c in con.execute(
        f"DESCRIBE SELECT * FROM read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)").fetchall()]
    lv = [i for i in range(1, 9) if f"C{i}" in cols]

    con.register("dims_df", dims)
    items_df = pd.DataFrame([{"itm_id": it["itm_id"], "itm_ord": o, "unit_meta": it["unit"]}
                             for o, it in enumerate(items_meta)], columns=["itm_id", "itm_ord", "unit_meta"])
    con.register("items_df", items_df)

    sel, joins = [], []
    for i in lv:
        nm = f"r.C{i}_NM" if f"C{i}_NM" in cols else "NULL"
        sel.append(f"""r.C{i} AS c{i}_code,
            CASE WHEN coalesce(d{i}.dup, false) THEN d{i}.label ELSE coalesce({nm}, d{i}.name, r.C{i}) END AS c{i}_name,
            coalesce(d{i}.ord, 99999) AS c{i}_ord, coalesce(d{i}.depth, 0) AS c{i}_depth,
            coalesce(d{i}.is_total, false) AS c{i}_total""")
        joins.append(f"LEFT JOIN dims_df d{i} ON d{i}.level = {i} AND d{i}.code = r.C{i}")
    has = lambda c: c in cols  # noqa: E731
    unit_expr = "coalesce(nullif(r.UNIT_NM, ''), it.unit_meta, '')" if has("UNIT_NM") else "coalesce(it.unit_meta, '')"
    order = ", ".join(["prd_se", "period_date"] + [f"c{i}_ord" for i in lv] + ["itm_ord"])
    sql = f"""
    COPY (
      WITH r0 AS (
        SELECT *, trim(coalesce({'PRD_SE' if has('PRD_SE') else "'Y'"}, '')) AS p,
               regexp_replace(coalesce(PRD_DE, ''), '[^0-9]', '', 'g') AS pd
        FROM read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)
      ), r AS (
        SELECT *, {SE_NORM} AS se,
               try_cast(substr(pd, 1, 4) AS INTEGER) AS y,
               coalesce(try_cast(nullif(substr(pd, 5, 2), '') AS INTEGER), 1) AS s,
               coalesce(try_cast(nullif(substr(pd, 7, 2), '') AS INTEGER), 1) AS d
        FROM r0
      )
      SELECT {sql_str(key)} AS table_key, r.se AS prd_se, r.PRD_DE AS prd_de,
             {LABEL_SQL} AS period_label, {PERIOD_SQL} AS period_date,
             {', '.join(sel) + ',' if sel else ''}
             r.ITM_ID AS itm_id, coalesce(r.ITM_NM, r.ITM_ID) AS itm_nm,
             coalesce(it.itm_ord, 99999) AS itm_ord, {unit_expr} AS unit,
             try_cast(replace(r.DT, ',', '') AS DOUBLE) AS value, r.DT AS value_raw,
             CASE WHEN try_cast(replace(r.DT, ',', '') AS DOUBLE) IS NULL THEN nullif(trim(r.DT), '') END AS symbol
      FROM r {' '.join(joins)}
      LEFT JOIN items_df it ON it.itm_id = r.ITM_ID
      WHERE r.y IS NOT NULL
      ORDER BY {order}
    ) TO {sql_str(pq.as_posix())} (FORMAT PARQUET)"""
    pq.parent.mkdir(parents=True, exist_ok=True)
    con.execute(sql)
    con.unregister("dims_df")
    con.unregister("items_df")

    prof = profile_table(con, row, key, pq, lv, levels, cols, raw)
    prof_p.parent.mkdir(parents=True, exist_ok=True)
    prof_p.write_text(json.dumps(prof, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return prof


def profile_table(con, row, key, pq, lv, levels, cols, raw):
    src = f"read_parquet({sql_str(pq.as_posix())})"
    periods = {}
    for se, prd, lab in con.execute(
            f"SELECT prd_se, prd_de, period_label FROM (SELECT DISTINCT prd_se, prd_de, period_label, period_date "
            f"FROM {src}) ORDER BY prd_se, period_date").fetchall():
        periods.setdefault(se, []).append({"prd_de": prd, "label": lab})
    items = [{"itm_id": a, "nm": str(b).strip(), "unit": c or "", "n": n} for a, b, c, n in con.execute(
        f"SELECT itm_id, any_value(itm_nm), any_value(unit), count(*) FROM {src} GROUP BY itm_id "
        f"ORDER BY min(itm_ord), itm_id").fetchall()]
    obj_names = {}
    if any(f"C{i}_OBJ_NM" in cols for i in lv):
        q = ", ".join(f"any_value(C{i}_OBJ_NM)" if f"C{i}_OBJ_NM" in cols else "NULL" for i in lv)
        obj_names = dict(zip(lv, con.execute(
            f"SELECT {q} FROM read_csv({sql_str(raw.as_posix())}, all_varchar=true, header=true)").fetchone()))
    lvls = []
    for i in lv:
        codes = [{"code": a, "name": str(b).strip(), "ord": c, "depth": d, "is_total": bool(t)}
                 for a, b, c, d, t in con.execute(
                     f"SELECT c{i}_code, any_value(c{i}_name), min(c{i}_ord), min(c{i}_depth), bool_or(c{i}_total) "
                     f"FROM {src} GROUP BY c{i}_code ORDER BY min(c{i}_ord), c{i}_code").fetchall()]
        obj_nm = (levels[i - 1]["obj_nm"] if i - 1 < len(levels) else None) or obj_names.get(i) or f"분류{i}"
        names = [c["name"] for c in codes]
        totals = [c for c in codes if c["is_total"]]
        lvls.append({"level": i, "obj_nm": str(obj_nm).strip(), "kind": level_kind(obj_nm, names),
                     "ordinal": is_ordinal(names), "n_codes": len(codes),
                     "total_code": totals[0]["code"] if totals else None, "codes": codes})
    n_rows, n_sym = con.execute(f"SELECT count(*), count(symbol) FROM {src}").fetchone()
    return {"table_key": key, "org_id": row.org_id, "tbl_id": row.tbl_id, "tbl_nm": row.tbl_nm,
            "file": f"processed/{key}.parquet", "levels": lvls, "items": items, "periods": periods,
            "n_rows": n_rows, "n_symbols": n_sym}


# 좌표 → 데이터
def load_view(source, base_dir, con=None):
    """좌표(source)로 정제 데이터를 다시 조회 → 정렬된 DataFrame.
    에이전트가 답변·차트용 수치를 가져올 때 쓰는 함수.
    source = {"file", "prd_se", "itm_id": [...], "dims": {"c1": {"codes": [...]} | {"depth": d, "exclude_total": true}},
              "period": {"in": [...]} | {"from": .., "to": ..}}"""
    con = con or duckdb.connect()
    w = [f"prd_se = {sql_str(source['prd_se'])}"]
    if source.get("itm_id"):
        w.append(f"itm_id IN ({', '.join(map(sql_str, source['itm_id']))})")
    for c, s in (source.get("dims") or {}).items():
        if "codes" in s:
            w.append(f"{c}_code IN ({', '.join(map(sql_str, s['codes']))})")
        if "depth" in s:
            w.append(f"{c}_depth = {int(s['depth'])}")
        if s.get("exclude_total"):
            w.append(f"NOT {c}_total")
    p = source.get("period") or {}
    if "in" in p:
        w.append(f"prd_de IN ({', '.join(map(sql_str, p['in']))})")
    if "from" in p:
        w.append(f"prd_de >= {sql_str(p['from'])}")
    if "to" in p:
        w.append(f"prd_de <= {sql_str(p['to'])}")
    path = (Path(base_dir) / source["file"]).as_posix()
    df = con.execute(f"SELECT * FROM read_parquet({sql_str(path)}) WHERE {' AND '.join(w)}").df()
    sort = ["period_date"] + sorted([c for c in df.columns if re.fullmatch(r"c\d_ord", c)]) + ["itm_ord"]
    return df.sort_values(sort, kind="stable").reset_index(drop=True)


# 2) views
def dim_label(lv, depth=None):
    nm = re.sub(r"별$", "", lv["obj_nm"]).strip() or lv["obj_nm"]
    if lv["kind"] == "geo" and depth is not None and depth in GEO_LEVEL and depth > 0:
        return GEO_LEVEL[depth]
    return nm


def base_code(lv):
    """다른 분류를 볼 때 이 분류를 고정할 코드: 합계 코드, 없으면 첫 코드"""
    return lv["total_code"] or lv["codes"][0]["code"]


def code_name(lv, code):
    return next((c["name"] for c in lv["codes"] if c["code"] == code), code)


def selector(codes, depth):
    if len(codes) <= CODE_LIST_LIMIT:
        return {"codes": [c["code"] for c in codes]}
    return {"depth": depth, "exclude_total": True}


def cond_text(prof, fixed):
    """고정 조건 중 '합계'가 아닌 것만 문장에 표시 (예: '서울특별시, 여자')"""
    out = []
    for lv in prof["levels"]:
        code = fixed.get(lv["level"])
        if code and code != lv["total_code"] and lv["n_codes"] > 1:
            out.append(code_name(lv, code))
    return ", ".join(out)


def fixed_desc(prof, fixed):
    return "; ".join(f"{lv['obj_nm']}: {code_name(lv, fixed[lv['level']])}"
                     for lv in prof["levels"] if lv["level"] in fixed and lv["n_codes"] > 1)


def make_source(prof, se, itm_ids, fixed, var=None, period=None):
    dims = {f"c{l}": {"codes": [c]} for l, c in fixed.items()}
    for l, s in (var or {}).items():
        dims[f"c{l}"] = s
    return {"table_key": prof["table_key"], "file": prof["file"], "org_id": prof["org_id"], "tbl_id": prof["tbl_id"],
            "prd_se": se, "itm_id": list(itm_ids), "dims": dict(sorted(dims.items())), "period": period or {},
            "kosis_url": KOSIS_URL.format(org=prof["org_id"], tbl=prof["tbl_id"])}


def preview_rows(df, x, series=None):
    cols = [x] + ([series] if series else []) + ["value"]
    d = df[cols].head(PREVIEW_ROWS)
    return [[None if (isinstance(v, float) and math.isnan(v)) else (str(v) if not isinstance(v, (int, float)) else v)
             for v in r] for r in d.itertuples(index=False)]


def fact(label, value, unit, text):
    return {"label": label, "value": None if value is None or (isinstance(value, float) and math.isnan(value))
            else round(float(value), 4), "unit": unit, "text": text}


def facts_trend(df, unit):
    d = df.dropna(subset=["value"])
    if d.empty:
        return []
    a, b = d.iloc[0], d.iloc[-1]
    f = [fact("시작", a.value, unit, f"{a.period_label} {fmt_num(a.value, unit)}"),
         fact("최근", b.value, unit, f"{b.period_label} {fmt_num(b.value, unit)}")]
    if len(d) >= 2:
        diff = b.value - a.value
        f.append(fact("변화량", diff, unit, f"{a.period_label} 대비 {b.period_label} {fmt_num(diff, unit)} "
                                           f"{'증가' if diff > 0 else '감소' if diff < 0 else '변화 없음'}"))
        if a.value:
            pct = diff / abs(a.value) * 100
            f.append(fact("변화율", pct, "%", f"변화율 {fmt_pct(pct)}"))
        mx, mn = d.loc[d.value.idxmax()], d.loc[d.value.idxmin()]
        f.append(fact("최대", mx.value, unit, f"최대 {mx.period_label} {fmt_num(mx.value, unit)}"))
        f.append(fact("최소", mn.value, unit, f"최소 {mn.period_label} {fmt_num(mn.value, unit)}"))
        if len(d) >= 3:
            prev = d.iloc[-2]
            if prev.value:
                p2 = (b.value - prev.value) / abs(prev.value) * 100
                f.append(fact("직전대비", p2, "%", f"직전 시점({prev.period_label}) 대비 {fmt_pct(p2)}"))
    return f


def facts_breakdown(df, unit, xcol, total_value=None, ordinal=False):
    d = df.dropna(subset=["value"])
    if d.empty:
        return []
    s = d.sort_values("value", ascending=False)
    f = [fact("범주수", len(d), "", f"{len(d)}개 범주")]
    for k, r in enumerate(s.head(3).itertuples(), 1):
        f.append(fact(f"{k}위", r.value, unit, f"{k}위 {getattr(r, xcol)} {fmt_num(r.value, unit)}"))
    lo = s.iloc[-1]
    if len(s) > 3:
        f.append(fact("최하위", lo.value, unit, f"최하위 {lo[xcol]} {fmt_num(lo.value, unit)}"))
    if total_value and unit in COUNT_UNITS and abs(s.value.sum() - total_value) <= 0.05 * abs(total_value):
        top = s.iloc[0]
        sh = top.value / total_value * 100
        f.append(fact("1위비중", sh, "%", f"{top[xcol]} 비중 {sh:.1f}%"))
    if ordinal:
        f.append(fact("최빈구간", s.iloc[0].value, unit, f"가장 큰 구간은 {s.iloc[0][xcol]}"))
    return f


def josa_q(t):
    return t


def view_questions(vt, item, dim, cond, ctx):
    """뷰가 답할 수 있는 원자적 질문 (템플릿). LLM 보강(enrich) 시 추가됨"""
    c = f"{cond} " if cond else ""
    it = item
    q = []
    if vt == "trend":
        q += [f"{c}{josa(it, '은/는')} 어떻게 변해왔나요?", f"{c}{it} 추이",
              f"{ctx['last']} {c}{josa(it, '은/는')} 얼마인가요?",
              f"{ctx['first']}년부터 {ctx['last']}까지 {c}{it} 변화", f"{c}{josa(it, '이/가')} 가장 많았던 시기는?",
              f"최근 {c}{it} 증감률은?"]
    elif vt == "breakdown":
        q += [f"{ctx['last']} {dim}별 {c}{it}", f"{c}{josa(it, '이/가')} 가장 많은 {josa(dim, '은/는')}?",
              f"{c}{josa(it, '이/가')} 가장 적은 {josa(dim, '은/는')}?", f"{dim}별 {c}{it} 순위",
              f"{dim}별 {c}{it} 비교"]
        if ctx.get("top"):
            t1 = ctx["top"][0]
            q.append(f"{t1}의 {c}{josa(it, '은/는')} 얼마인가요?")
            if len(ctx["top"]) > 1:
                q.append(f"{josa(t1, '과/와')} {ctx['top'][1]}의 {c}{it} 비교")
    elif vt == "breakdown_trend":
        q += [f"{dim}별 {c}{it} 추이 비교", f"{dim}별 {c}{it} 변화"]
        if len(ctx.get("top", [])) > 1:
            q.append(f"{josa(ctx['top'][0], '과/와')} {ctx['top'][1]}의 {c}{it} 추이")
    elif vt == "pyramid":
        q += [f"{ctx['last']} {c}인구 피라미드", f"성별 연령별 {c}{it} 구조", f"남녀 연령대별 {c}{it} 차이",
              f"{c}{it} 연령 분포"]
    elif vt == "items_trend":
        q += [f"{ctx['tbl_nm']} 항목별 추이", f"{' '.join(ctx.get('items', [])[:3])} 비교 추이"]
    return list(dict.fromkeys(q))


def find_aliases(text, extra):
    out = []
    for k, vs in {**ALIASES, **extra}.items():
        if k in text:
            out += [v for v in vs if v not in text]
    return list(dict.fromkeys(out))[:15]


def summarize(title, facts):
    if not facts:
        return f"{title} 자료입니다."
    txt = ", ".join(f["text"] for f in facts[:5])
    return f"{title}: {txt}입니다."


def chart_spec(vt, x, series=None, ordinal=False, n=0, unit="", geo=False):
    spec = {"type": {"trend": "line", "items_trend": "line", "breakdown_trend": "line",
                     "breakdown": "bar", "pyramid": "pyramid"}[vt],
            "x": x, "y": "value", "series": series, "unit": unit,
            "x_type": "time" if x == "period_date" else ("ordinal" if ordinal else "category"),
            "x_label": "period_label" if x == "period_date" else x,
            "sort": "time" if x == "period_date" else ("code_order" if ordinal else "value_desc")}
    alts = []
    if vt == "breakdown":
        if n > TOP_N and not ordinal:
            spec["top_n"] = TOP_N
        if geo:
            alts.append("choropleth")
        if unit in COUNT_UNITS and n <= 12:
            alts += ["pie", "treemap"]
        if ordinal:
            alts.append("column_ordered")
    if vt == "breakdown_trend":
        alts += ["small_multiples", "stacked_area" if unit in COUNT_UNITS else "heatmap"]
    if vt == "trend":
        alts.append("bar")
    spec["alternatives"] = alts
    return spec


def caveats_for(prof, meta, row, df_periods, survey_nm, symbols):
    cv = []
    cmmt = []
    for r in (meta.get("CMMT") or []):
        if isinstance(r, dict):
            for k, v in r.items():
                if v and k not in ("_error",) and isinstance(v, str) and len(v) > 4:
                    cmmt.append(v.strip())
    if cmmt:
        cv.append(" ".join(dict.fromkeys(cmmt))[:500])
    yrs = sorted({int(p["prd_de"][:4]) for ps in prof["periods"].values() for p in ps if p["prd_de"][:4].isdigit()})
    if "인구총조사" in f"{survey_nm}{row.category}" and yrs and yrs[0] < 2015 <= yrs[-1]:
        cv.append("2015년부터 등록센서스(행정자료 기반) 방식으로 바뀌어 이전 시점과 직접 비교에 주의")
    if "주민등록" in f"{survey_nm}{row.category}":
        cv.append("주민등록 기준 인구로, 실제 거주(상주) 기준인 인구총조사와 수치가 다를 수 있음")
    if any(lv["kind"] == "geo" for lv in prof["levels"]) and len(yrs) > 1:
        cv.append("행정구역 개편(예: 세종시 신설 2012, 군위군 대구 편입 2023)으로 시점별 지역 범위가 다를 수 있음")
    if "추계" in f"{survey_nm}{row.tbl_nm}":
        cv.append("추계(전망)값으로 실측치가 아님")
    if symbols:
        cv.append("일부 값은 통계부호(-, X, … 등)로 결측 처리됨 (0이 아님)")
    if str(row.survey_type) == "구분없음(전체집계)":
        cv.append("전수/표본 구분 표기가 없는 표")
    return cv


def build_views(con, prof, row, meta, base_dir, survey_nm, extra_alias):
    views = []
    lvls = prof["levels"]
    multi = [lv for lv in lvls if lv["n_codes"] > 1]
    for se, plist in prof["periods"].items():
        prds = [p["prd_de"] for p in plist]
        labels = {p["prd_de"]: p["label"] for p in plist}
        latest = prds[-1]
        base = {lv["level"]: base_code(lv) for lv in lvls}
        items = [it for it in prof["items"]][:MAX_ITEMS]
        ctx0 = {"first": labels[prds[0]][:4], "last": labels[latest], "tbl_nm": prof["tbl_nm"]}

        def add(vt, title, src, x, series, items_used, dim=None, ordinal=False, geo=False, cond="", extra_ctx=None,
                fixed=None, var_desc=""):
            if len(views) >= MAX_VIEWS:
                return
            df = load_view(src, base_dir, con)
            if df.empty or df["value"].notna().sum() == 0:
                return
            unit = str(df["unit"].dropna().iloc[0]) if df["unit"].notna().any() else ""
            if vt in ("trend",):
                facts = facts_trend(df, unit)
            elif vt == "breakdown":
                tv = None
                if extra_ctx and extra_ctx.get("total_src"):
                    t = load_view(extra_ctx["total_src"], base_dir, con)
                    tv = t["value"].iloc[0] if len(t) and pd.notna(t["value"].iloc[0]) else None
                facts = facts_breakdown(df, unit, x, tv, ordinal)
            elif vt == "breakdown_trend":
                last = df[df["prd_de"] == df["prd_de"].max()]
                facts = facts_breakdown(last, unit, series, None, False)
                if not facts:
                    facts = []
                first = df[df["prd_de"] == df["prd_de"].min()].set_index(series)["value"]
                ch = (last.set_index(series)["value"] - first).dropna()
                if len(ch):
                    k = ch.idxmax()
                    facts.append(fact("최대증가", ch[k], unit, f"가장 많이 늘어난 {k} {fmt_num(ch[k], unit)}"))
            elif vt == "pyramid":
                facts = []
                g = df.groupby(series)["value"].sum()
                for k, v in g.items():
                    facts.append(fact(f"{k}합계", v, unit, f"{k} {fmt_num(v, unit)}"))
                for k, sub in df.dropna(subset=["value"]).groupby(series):
                    r = sub.loc[sub.value.idxmax()]
                    facts.append(fact(f"{k}최다연령", r.value, unit, f"{k} 최다 {r[x]} {fmt_num(r.value, unit)}"))
            else:  # items_trend
                facts = []
                for nm, sub in df.groupby("itm_nm", sort=False):
                    ft = facts_trend(sub, str(sub["unit"].iloc[0]))
                    facts += [dict(f, label=f"{nm} {f['label']}", text=f"{nm} {f['text']}")
                              for f in ft if f["label"] in ("최근", "변화율")]
            item_nm = items_used[0]["nm"] if items_used else ""
            top = []
            if vt == "breakdown":
                top = df.dropna(subset=["value"]).sort_values("value", ascending=False)[x].astype(str).head(3).tolist()
            if vt == "breakdown_trend":
                top = df[df["prd_de"] == df["prd_de"].max()].sort_values("value", ascending=False)[series] \
                    .astype(str).head(3).tolist()
            ctx = {**ctx0, "top": top, "items": [i["nm"] for i in items_used]}
            p_from, p_to = df["period_label"].iloc[0], df["period_label"].iloc[-1]
            period_phrase = p_to if p_from == p_to else f"{p_from}~{p_to}"
            fd = fixed_desc(prof, fixed or {})
            phrase = f"{(cond + '의 ') if cond else ''}{item_nm}({unit or '단위 없음'}){var_desc}"
            desc = (f"{survey_nm}의 「{prof['tbl_nm']}」 통계표에서 {josa(phrase, '을/를')} "
                    f"{period_phrase} 기준으로 정리한 자료입니다."
                    + (f" 고정 조건: {fd}." if fd else ""))
            questions = view_questions(vt, item_nm, dim, cond, ctx)
            names_in_view = []
            for c in [x, series]:
                if c and c in df.columns and c not in ("period_date", "itm_nm"):
                    names_in_view += df[c].dropna().astype(str).unique().tolist()[:300]
            names_in_view += [code_name(lv, (fixed or {})[lv["level"]]) for lv in lvls if lv["level"] in (fixed or {})]
            names_in_view = list(dict.fromkeys(names_in_view))
            alias = find_aliases(" ".join([title, prof["tbl_nm"], item_nm, dim or "", cond]), extra_alias)
            vid = f"view::{prof['table_key']}::{se}::{len(views):02d}::{vt}"
            spec = chart_spec(vt, x, series, ordinal, df[x].nunique() if x in df else 0, unit, geo)
            geo_lv = next((lv for lv in lvls if lv["kind"] == "geo"), None)
            geo_level = None
            if geo_lv:
                dsel = src["dims"].get(f"c{geo_lv['level']}", {})
                codes = dsel.get("codes", [])
                if "depth" in dsel:
                    geo_level = GEO_LEVEL.get(dsel["depth"])
                elif codes:
                    dd = {c["code"]: c["depth"] for c in geo_lv["codes"]}
                    geo_level = GEO_LEVEL.get(min(dd.get(c, 0) for c in codes))
            rec = {
                "id": vid, "doc_type": "view", "parent_id": f"table::{prof['table_key']}",
                "view_type": vt, "title": title,
                "survey_nm": survey_nm, "category": row.category, "path": row.path,
                "also_in": "" if str(getattr(row, "also_in", "nan")) == "nan" else row.also_in,
                "tbl_nm": prof["tbl_nm"],
                "description": desc,
                "facts": facts,
                "summary": summarize(title, facts),
                "questions": questions,
                "aliases": alias,
                "filters": {"survey_nm": survey_nm, "category": row.category, "survey_type": row.survey_type,
                            "view_type": vt, "prd_se": se, "prd_from": df["prd_de"].iloc[0],
                            "prd_to": df["prd_de"].iloc[-1], "is_latest": df["prd_de"].iloc[-1] == latest,
                            "unit": unit, "geo_level": geo_level, "n_points": int(df["value"].notna().sum()),
                            "items": [i["nm"] for i in items_used],
                            "dims": [dim] if dim else []},
                "source": src,
                "chart": spec,
                "preview": {"columns": [spec["x_label"] if x == "period_date" else x] + ([series] if series else [])
                            + ["value"],
                            "rows": preview_rows(df, spec["x_label"] if x == "period_date" else x, series)},
                "caveats": [],
                "_names": names_in_view,
            }
            views.append(rec)

        # A) 항목별 시계열 (모든 분류 = 합계/대표값)
        if len(prds) >= 2:
            for it in items:
                cond = cond_text(prof, base)
                src = make_source(prof, se, [it["itm_id"]], base)
                add("trend", f"{(cond + ' ') if cond else ''}{it['nm']} 추이 ({labels[prds[0]]}~{labels[latest]})",
                    src, "period_date", None, [it], cond=cond, fixed=base, var_desc="의 시점별 추이")
            same_unit = [it for it in items if it["unit"] == items[0]["unit"]]
            if 2 <= len(same_unit) <= 6:
                src = make_source(prof, se, [i["itm_id"] for i in same_unit], base)
                add("items_trend", f"{prof['tbl_nm']}: 항목별 추이", src, "period_date", "itm_nm", same_unit,
                    fixed=base, var_desc=" 등 항목별 추이")

        # B) 분류별 비교 (최신 시점, 다른 분류 = 합계)
        for lv in multi:
            others = {l: c for l, c in base.items() if l != lv["level"]}
            cand = [c for c in lv["codes"] if not c["is_total"]] or lv["codes"]
            depths = sorted({c["depth"] for c in cand})
            for dpt in depths[:2]:
                codes = [c for c in cand if c["depth"] == dpt]
                if len(codes) < 2:
                    continue
                dim = dim_label(lv, dpt)
                for it in items[:MAX_BREAKDOWN_ITEMS]:
                    cond = cond_text(prof, others)
                    src = make_source(prof, se, [it["itm_id"]], others,
                                      {lv["level"]: selector(codes, dpt)}, {"in": [latest]})
                    tsrc = make_source(prof, se, [it["itm_id"]], {**others, lv["level"]: lv["total_code"]},
                                       None, {"in": [latest]}) if lv["total_code"] else None
                    add("breakdown", f"{labels[latest]} {dim}별 {(cond + ' ') if cond else ''}{it['nm']}",
                        src, f"c{lv['level']}_name", None, [it], dim=dim, ordinal=lv["ordinal"],
                        geo=lv["kind"] == "geo", cond=cond, extra_ctx={"total_src": tsrc}, fixed=others,
                        var_desc=f"의 {dim}별 분포")
                # C) 분류별 시계열 (범주가 적을 때)
                if len(prds) >= 3 and 2 <= len(codes) <= MAX_LINES and items:
                    it = items[0]
                    cond = cond_text(prof, others)
                    src = make_source(prof, se, [it["itm_id"]], others, {lv["level"]: selector(codes, dpt)})
                    add("breakdown_trend", f"{dim}별 {(cond + ' ') if cond else ''}{it['nm']} 추이",
                        src, "period_date", f"c{lv['level']}_name", [it], dim=dim, cond=cond, fixed=others,
                        var_desc=f"의 {dim}별 시계열")

        # D) 인구 피라미드 (성 × 연령)
        sex = next((lv for lv in lvls if lv["kind"] == "sex"), None)
        age = next((lv for lv in lvls if lv["kind"] == "age" and lv["ordinal"]), None)
        if sex and age and items:
            sx = [c for c in sex["codes"] if c["name"] in SEX_CODES]
            ag = [c for c in age["codes"] if not c["is_total"]]
            if ag:
                d0 = min(c["depth"] for c in ag)
                ag = [c for c in ag if c["depth"] == d0]
            if len(sx) == 2 and len(ag) >= 5:
                others = {l: c for l, c in base.items() if l not in (sex["level"], age["level"])}
                cond = cond_text(prof, others)
                src = make_source(prof, se, [items[0]["itm_id"]], others,
                                  {sex["level"]: {"codes": [c["code"] for c in sx]},
                                   age["level"]: selector(ag, d0)}, {"in": [latest]})
                add("pyramid", f"{labels[latest]} {(cond + ' ') if cond else ''}성·연령별 {items[0]['nm']} (인구 피라미드)",
                    src, f"c{age['level']}_name", f"c{sex['level']}_name", [items[0]],
                    dim="연령", cond=cond, fixed=others, var_desc="의 성·연령 구조")
    return views


def text_fields(rec, kiwi=None):
    """BM25용 텍스트/토큰과 임베딩용 텍스트 (임베딩에는 수치를 넣지 않음)"""
    if "_names" in rec:                      # 뷰에 등장하는 범주명(지역·연령 등) → 영구 필드로 보관
        rec["entities"] = rec.pop("_names")[:300]
    names = rec.get("entities", [])
    parts = [rec["title"], rec.get("tbl_nm", ""), rec.get("survey_nm", ""), rec.get("organization", ""),
             " ".join(rec.get("menu_paths", [])), rec.get("path", ""),
             rec.get("also_in", ""), " ".join(rec["filters"].get("items", [])),
             " ".join(rec["filters"].get("dims", [])), rec["filters"].get("unit") or "",
             " ".join(names), " ".join(rec.get("aliases", [])), " ".join(rec.get("questions", [])),
             " ".join(sorted({str(rec["filters"].get("prd_from", ""))[:4], str(rec["filters"].get("prd_to", ""))[:4]}))]
    bm = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
    rec["bm25_text"] = bm
    if kiwi is not None:
        rec["bm25_tokens"] = [t.form for t in kiwi.tokenize(bm)
                              if t.tag.startswith(("NN", "SL", "SN", "XR", "VV", "VA"))]
    rec["embed_text"] = "\n".join([
        rec["title"], rec["description"],
        "질문 예: " + " | ".join(rec.get("questions", [])[:10]),
        "관련어: " + ", ".join(rec.get("aliases", [])[:15])])
    return rec


def table_record(prof, row, survey_nm, view_ids, caveats, extra_alias, meta):
    lv_txt = []
    for lv in prof["levels"]:
        sample = ", ".join(c["name"] for c in lv["codes"][:12])
        more = f" 외 {lv['n_codes'] - 12}개" if lv["n_codes"] > 12 else ""
        lv_txt.append(f"{lv['obj_nm']}({lv['n_codes']}개: {sample}{more})")
    it_txt = ", ".join(f"{i['nm']}({i['unit']})" if i["unit"] else i["nm"] for i in prof["items"][:30])
    pr_txt = "; ".join(f"{se} {ps[0]['label']}~{ps[-1]['label']} ({len(ps)}개 시점)" for se, ps in prof["periods"].items())
    title = prof["tbl_nm"]
    desc = (f"{survey_nm}의 「{title}」 통계표입니다. 분류: {' / '.join(lv_txt) or '없음'}. "
            f"항목: {it_txt}. 수록기간: {pr_txt}.")
    q = [f"{title} 통계", f"{title} 자료 어디서 보나요?"]
    for i in prof["items"][:3]:
        for lv in prof["levels"][:2]:
            q.append(f"{dim_label(lv)}별 {i['nm']}")
    alias = find_aliases(" ".join([title, it_txt, " ".join(l["obj_nm"] for l in prof["levels"])]), extra_alias)
    yrs = [p["prd_de"] for ps in prof["periods"].values() for p in ps]
    rec = {
        "id": f"table::{prof['table_key']}", "doc_type": "table", "parent_id": None, "view_type": "table",
        "title": title, "survey_nm": survey_nm, "category": row.category, "path": row.path,
        "also_in": "" if str(getattr(row, "also_in", "nan")) == "nan" else row.also_in,
        "tbl_nm": title, "description": desc, "facts": [], "summary": desc,
        "questions": list(dict.fromkeys(q)), "aliases": alias,
        "filters": {"survey_nm": survey_nm, "category": row.category, "survey_type": row.survey_type,
                    "view_type": "table", "prd_se": ",".join(prof["periods"].keys()),
                    "prd_from": min(yrs) if yrs else None, "prd_to": max(yrs) if yrs else None,
                    "unit": ", ".join(sorted({i["unit"] for i in prof["items"] if i["unit"]})),
                    "geo_level": None, "n_points": prof["n_rows"],
                    "items": [i["nm"] for i in prof["items"][:40]], "dims": [lv["obj_nm"] for lv in prof["levels"]]},
        "source": {"table_key": prof["table_key"], "file": prof["file"], "org_id": prof["org_id"],
                   "tbl_id": prof["tbl_id"], "kosis_url": KOSIS_URL.format(org=prof["org_id"], tbl=prof["tbl_id"]),
                   "dims_schema": [{"col": f"c{lv['level']}", "obj_nm": lv["obj_nm"], "kind": lv["kind"],
                                    "ordinal": lv["ordinal"], "total_code": lv["total_code"], "n_codes": lv["n_codes"]}
                                   for lv in prof["levels"]]},
        "chart": None, "preview": None, "caveats": caveats, "view_ids": view_ids,
        "updated": str(meta.get("_updated", "")),
        "_names": [c["name"] for lv in prof["levels"] for c in lv["codes"][:200]],
    }
    return rec


# 실행
def load_catalog(args):
    cat = pd.read_csv(Path(args.data) / "catalog.csv", dtype=str)
    cat = cat[cat["selected"] == "True"]
    if args.surveys:
        cat = cat[cat["category"].isin(args.surveys)]
    if args.tables:
        cat = cat[cat["tbl_id"].isin(args.tables)]
    if args.max_tables:
        cat = cat.head(args.max_tables)
    return cat



# XLS 카탈로그 결합
SAMPLE_RE = re.compile(r"표본|\d+\s*%\s*부문|샘플")
CAT_SE = {"년": "Y", "연": "Y", "월": "M", "분기": "Q", "반기": "H", "일": "D"}


def load_xls_catalog(path):
    """preprocess_population.py 결과(population_table_catalog.jsonl) → {(org_id, tbl_id): 레코드}"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"(카탈로그 없음: {p} → 폴더명 기준으로 진행)")
        return {}
    out = {}
    for line in p.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            out[(str(d["org_id"]), str(d["tbl_id"]))] = d
    print(f"카탈로그 {len(out)}개 표 로드: {p}")
    return out


def cat_se(label):
    label = str(label).strip()
    if label in CAT_SE:
        return CAT_SE[label]
    if label.endswith("년"):
        return "F"
    return label            # IR 등은 그대로


def menu_paths(c):
    """'주제별통계 > 인구 > 인구총조사 > … > 표이름' → '인구총조사 > …' (루트·표이름 제외)"""
    out = []
    for p in c.get("paths", []):
        parts = [x.strip() for x in p["path"].split(" > ")]
        out.append(" > ".join(parts[2:-1]))
    return list(dict.fromkeys(x for x in out if x))


def freshness(c, prof):
    """카탈로그 수록기간 끝 vs 수집 데이터 마지막 시점 (주기별)"""
    cat_end = {}
    for x in (c or {}).get("catalog_periods", []):
        se = cat_se(x["frequency_label"])
        cat_end[se] = max(cat_end.get(se, ""), str(x["end"]))
    data_end = {se: ps[-1]["prd_de"] for se, ps in prof["periods"].items() if ps}
    stale = {se: {"catalog": e, "data": data_end.get(se)} for se, e in cat_end.items()
             if se in data_end and str(data_end[se]) < e}
    return {"catalog_end": cat_end, "data_end": data_end, "is_stale": bool(stale), "stale": stale}


def apply_catalog(rec, c, fresh):
    """RAG 레코드에 카탈로그 정보(기관·출처·메뉴 경로·KOSIS 링크·최신성) 반영"""
    rec["freshness"] = fresh
    if not c:
        rec.setdefault("organization", "")
        rec.setdefault("source_text", f"자료: 「{rec.get('survey_nm', '')}」 (KOSIS)")
        rec.setdefault("menu_paths", [rec.get("path", "")])
        return rec
    mps = menu_paths(c)
    rec["organization"] = c.get("organization", "")
    rec["source_text"] = f"자료: {c.get('source_text') or c.get('organization', '')}"
    rec["menu_paths"] = mps
    others = [m for m in mps if m != rec.get("path")]
    rec["also_in"] = " || ".join(dict.fromkeys([x for x in str(rec.get("also_in") or "").split(" || ") if x] + others))
    url = next((p.get("kosis_table_url") for p in c.get("paths", []) if p.get("kosis_table_url")), None)
    if url and isinstance(rec.get("source"), dict):
        rec["source"]["kosis_url"] = url
    rec["filters"]["organization"] = rec["organization"]
    if fresh.get("is_stale"):
        msg = "; ".join(f"수집 {v['data']} / KOSIS 최신 {v['catalog']}" for v in fresh["stale"].values())
        rec["caveats"] = list(rec.get("caveats") or []) + [f"KOSIS에 더 최근 자료가 있음 ({msg})"]
    return rec


def survey_names(args, cat_all):
    """stat_id → 조사명. data/survey_map.csv(stat_id,survey_nm)가 있으면 사용, 없으면 폴더명(category)"""
    mp = Path(args.data) / "survey_map.csv"
    m = {}
    if mp.exists():
        d = pd.read_csv(mp, dtype=str)
        m = dict(zip(d["stat_id"], d["survey_nm"]))
    # 매핑 작성용 템플릿: 폴더 안에서 다른 조사로 보이는 stat_id 목록
    t = (cat_all.groupby(["stat_id", "category"])
         .agg(n_tables=("tbl_id", "size"), sample_path=("path", "first"), sample_tbl=("tbl_nm", "first"))
         .reset_index())
    t["survey_nm"] = t["stat_id"].map(m).fillna("")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "survey_map_template.csv", index=False, encoding="utf-8-sig")
    return m


def stage_prepare(args):
    cat = load_catalog(args)
    con = duckdb.connect()
    data, out = Path(args.data), Path(args.out)
    ok = 0
    for i, r in enumerate(cat.itertuples(), 1):
        try:
            p = prepare_table(con, r, data, out, force=args.force)
            ok += p is not None
        except Exception as e:  # 표 하나 실패해도 계속
            print(f"  ✗ {r.tbl_id} {r.tbl_nm}: {e}")
        if i % 50 == 0 or i == len(cat):
            print(f"[prepare] {i}/{len(cat)} (완료 {ok})", flush=True)


def stage_views(args):
    data, out = Path(args.data), Path(args.out)
    cat_all = pd.read_csv(data / "catalog.csv", dtype=str)
    cat = load_catalog(args)
    smap = survey_names(args, cat_all)
    extra_alias = {}
    ap = data / "aliases.json"
    if ap.exists():
        extra_alias = json.loads(ap.read_text(encoding="utf-8"))
    kiwi = None
    if args.kiwi:
        from kiwipiepy import Kiwi
        kiwi = Kiwi()
    xcat = load_xls_catalog(args.catalog)
    con = duckdb.connect()
    files = {k: (out / f"{k}.jsonl").open("w", encoding="utf-8") for k in ("tables", "views", "records")}
    n_t = n_v = n_cat = n_stale = 0
    for i, r in enumerate(cat.itertuples(), 1):
        key = f"{r.org_id}_{r.tbl_id}"
        pf = out / "profiles" / f"{key}.json"
        if not pf.exists():
            continue
        prof = json.loads(pf.read_text(encoding="utf-8"))
        mp = data / "meta" / f"{key}.json"
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        c = xcat.get((str(r.org_id), str(r.tbl_id)))
        survey_nm = (c or {}).get("survey_name") or smap.get(str(r.stat_id), r.category)
        fresh = freshness(c, prof)
        caveats = caveats_for(prof, meta, r, None, survey_nm, prof.get("n_symbols", 0))
        try:
            views = build_views(con, prof, r, meta, out, survey_nm, extra_alias)
        except Exception as e:
            print(f"  ✗ views {key} {r.tbl_nm}: {e}")
            views = []
        upd = con.execute(f"SELECT max(prd_de) FROM read_parquet({sql_str((out / prof['file']).as_posix())})").fetchone()[0]
        for v in views:
            v["caveats"] = caveats
            v["updated"] = r.send_de if "send_de" in cat.columns and str(r.send_de) != "nan" else ""
            apply_catalog(v, c, fresh)
            text_fields(v, kiwi)
        meta["_updated"] = r.send_de if "send_de" in cat.columns and str(r.send_de) != "nan" else ""
        trec = table_record(prof, r, survey_nm, [v["id"] for v in views], caveats, extra_alias, meta)
        trec = text_fields(apply_catalog(trec, c, fresh), kiwi)
        n_cat += c is not None
        n_stale += fresh["is_stale"]
        trec["filters"]["latest_prd"] = upd
        for rec, kind in [(trec, "tables")] + [(v, "views") for v in views]:
            line = json.dumps(rec, ensure_ascii=False, default=str)
            files[kind].write(line + "\n")
            files["records"].write(line + "\n")
        n_t += 1
        n_v += len(views)
        if i % 50 == 0 or i == len(cat):
            print(f"[views] {i}/{len(cat)} 표 {n_t}, 뷰 {n_v}", flush=True)
    for f in files.values():
        f.close()
    (out / "manifest.json").write_text(json.dumps(
        {"tables": n_t, "views": n_v, "files": ["tables.jsonl", "views.jsonl", "records.jsonl"],
         "text_fields": {"bm25": "bm25_text / bm25_tokens", "dense": "embed_text"},
         "coordinate_field": "source (load_view 로 재조회)"}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료: 표 {n_t}, 뷰 {n_v} → {out}")
    if xcat:
        print(f"카탈로그 결합 {n_cat}/{n_t}표, 최신 자료 미반영 {n_stale}표 (audit 단계로 목록 확인)")


# 3) enrich (선택, LLM)
ENRICH_SYS = (
    "너는 한국 공식통계 데이터 카탈로그 작성자다. 주어진 facts 의 숫자만 사용하고 새로운 숫자를 만들지 마라. "
    "문체는 '~입니다'체로 통일한다. 반드시 JSON 객체 하나만 출력한다.")
ENRICH_USER = """다음 통계 뷰의 검색용 필드를 만들어라.
{payload}

출력 JSON 키:
- "summary": facts 숫자만 사용한 1~2문장 요약
- "questions": 이 데이터 하나로 바로 답할 수 있는 사용자 질문 8개 (구어체·짧은 키워드형 섞기, 지역/연도 등 구체값 포함)
- "paraphrases": 위 질문과 같은 뜻의 다른 표현 5개 (질의 재작성 대응)
- "aliases": 이 자료 관련 동의어·일상어 8개
- "decomposition": 이 자료가 '일부'로 쓰이는 복합 질문 2개와 그 하위 질문 목록. 형식 [{{"complex": "...", "sub": ["...", "..."]}}]
"""
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(s):
    return {n.replace(",", "").rstrip("0").rstrip(".") for n in NUM_RE.findall(str(s))}


def enrich_one(client, model, rec):
    payload = {k: rec[k] for k in ("title", "description", "view_type", "survey_nm", "tbl_nm")}
    payload["facts"] = [f["text"] for f in rec["facts"]]
    payload["filters"] = {k: rec["filters"].get(k) for k in ("items", "dims", "prd_from", "prd_to", "unit")}
    payload["examples"] = rec["questions"][:5]
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": ENRICH_SYS},
                  {"role": "user", "content": ENRICH_USER.format(payload=json.dumps(payload, ensure_ascii=False))}])
    txt = resp.choices[0].message.content
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0) if m else txt)


def stage_enrich(args):
    """views.jsonl 의 각 뷰에 LLM 질문/재작성/동의어/분해/요약 추가. OpenAI 호환 API 사용
    env: LLM_API_KEY(또는 OPENAI_API_KEY), LLM_BASE_URL(선택), LLM_MODEL"""
    from concurrent.futures import ThreadPoolExecutor
    from openai import OpenAI
    out = Path(args.out)
    client = OpenAI(api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
                    base_url=os.getenv("LLM_BASE_URL") or None)
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    cache_p = out / "enrich_cache.jsonl"
    cache = {}
    if cache_p.exists():
        for line in cache_p.open(encoding="utf-8"):
            d = json.loads(line)
            cache[d["id"]] = d["llm"]
    recs = [json.loads(l) for l in (out / "views.jsonl").open(encoding="utf-8")]
    todo = [r for r in recs if r["id"] not in cache][: args.max_enrich or None]
    print(f"LLM 보강 대상 {len(todo)} / 전체 뷰 {len(recs)} (캐시 {len(cache)})")
    with ThreadPoolExecutor(max_workers=args.workers) as ex, cache_p.open("a", encoding="utf-8") as cf:
        for rec, res in zip(todo, ex.map(lambda r: _safe_enrich(client, model, r), todo)):
            if res:
                cache[rec["id"]] = res
                cf.write(json.dumps({"id": rec["id"], "llm": res}, ensure_ascii=False) + "\n")
    kiwi = None
    if args.kiwi:
        from kiwipiepy import Kiwi
        kiwi = Kiwi()
    rejected = 0
    tables = [json.loads(l) for l in (out / "tables.jsonl").open(encoding="utf-8")]
    with (out / "views.jsonl").open("w", encoding="utf-8") as fv, \
            (out / "records.jsonl").open("w", encoding="utf-8") as fr:
        for t in tables:
            fr.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")
        for r in recs:
            llm = cache.get(r["id"])
            if llm:
                allowed = set().union(*[_nums(f["text"]) for f in r["facts"]] or [set()]) | _nums(r["title"]) \
                    | _nums(r["description"])
                s = llm.get("summary", "")
                if s and _nums(s) <= allowed:
                    r["summary"] = s                      # 숫자 검증 통과 시에만 교체
                elif s:
                    rejected += 1
                r["questions"] = list(dict.fromkeys(r["questions"] + list(llm.get("questions", []))))
                r["paraphrases"] = llm.get("paraphrases", [])
                r["aliases"] = list(dict.fromkeys(r["aliases"] + list(llm.get("aliases", []))))[:20]
                r["decomposition"] = llm.get("decomposition", [])
                text_fields(r, kiwi)
                r["embed_text"] += "\n다른 표현: " + " | ".join(r.get("paraphrases", [])[:5])
            line = json.dumps(r, ensure_ascii=False, default=str)
            fv.write(line + "\n")
            fr.write(line + "\n")
    print(f"보강 반영 완료. 숫자 검증 실패로 요약 미교체 {rejected}건")


def _safe_enrich(client, model, rec):
    for _ in range(3):
        try:
            return enrich_one(client, model, rec)
        except Exception as e:  # noqa: BLE001
            err = e
    print(f"  ✗ enrich {rec['id']}: {err}")
    return None


# render (검증/에이전트용)
def render(rec, base_dir, out_html=None):
    """뷰 레코드의 좌표로 데이터를 다시 불러 chart 스펙대로 그림 (plotly)"""
    import plotly.express as px
    df = load_view(rec["source"], base_dir)
    ch = rec["chart"]
    x, s, unit = ch["x"], ch.get("series"), ch.get("unit") or ""
    title = rec["title"]
    ylab = f"값({unit})" if unit else "값"
    if ch["type"] == "line":
        fig = px.line(df, x=x, y="value", color=s, markers=True, title=title,
                      labels={"value": ylab, x: "시점", s or "": ""},
                      hover_data=["period_label"])
    elif ch["type"] == "pyramid":
        d = df.copy()
        first = d[s].iloc[0]
        d["plot"] = d.apply(lambda r: -r["value"] if r[s] == first else r["value"], axis=1)
        fig = px.bar(d, y=x, x="plot", color=s, orientation="h", title=title,
                     labels={"plot": ylab, x: ""}, category_orders={x: d[x].drop_duplicates().tolist()})
        fig.update_layout(barmode="relative")
    else:
        d = df.dropna(subset=["value"])
        if ch.get("sort") == "value_desc":
            d = d.sort_values("value", ascending=False)
        if ch.get("top_n"):
            d = d.head(ch["top_n"])
        fig = px.bar(d, x=x, y="value", title=title, labels={"value": ylab, x: ""},
                     category_orders={x: d[x].tolist()})
    if out_html:
        Path(out_html).parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(out_html, include_plotlyjs="cdn")
    return fig, df


def stage_render(args):
    out = Path(args.out)
    recs = {}
    for line in (out / "views.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        recs[d["id"]] = d
    ids = args.id or list(recs)[: args.max_tables or 5]
    for vid in ids:
        rec = recs[vid]
        html = out / "charts" / f"{safe(vid)}.html"
        try:
            _, df = render(rec, out, html)
            print(f"{vid} → {html} ({len(df)} rows)")
        except ImportError:
            df = load_view(rec["source"], out)
            print(f"(plotly 미설치) {vid} 데이터 {len(df)}행:\n{df.head(10).to_string()}")


# audit: 카탈로그 vs 수집 결과 대조
def stage_audit(args):
    """XLS 카탈로그 기준으로 수집 상태 점검
    status: ok / stale(KOSIS에 더 최근 자료) / not_downloaded(선택됐지만 raw 없음)
            / missing_in_api(API 목록 탐색에서 못 찾음) / excluded_sample(표본 경로) / not_selected(중복 등)
    --apply : missing_in_api 표를 data/catalog.csv 에 추가 (이후 rag_builder schema·download 로 수집)
    출력    : audit.csv, refresh_tables.txt (다시 받을 tbl_id 목록)"""
    data, out = Path(args.data), Path(args.out)
    xcat = load_xls_catalog(args.catalog)
    if not xcat:
        raise SystemExit("--catalog 로 population_table_catalog.jsonl 경로를 지정하세요.")
    api = pd.read_csv(data / "catalog.csv", dtype=str)
    api_keys = {(r.org_id, r.tbl_id): r for r in api.itertuples()}
    sel_keys = {(r.org_id, r.tbl_id): r for r in api[api["selected"] == "True"].itertuples()}
    rows, add_rows = [], []
    for (org, tbl), c in xcat.items():
        mps = menu_paths(c)
        is_sample = bool(mps) and all(SAMPLE_RE.search(m) for m in mps)
        r = sel_keys.get((org, tbl))
        raw = data / "raw" / safe(r.category) / f"{org}_{tbl}.csv" if r is not None else None
        prof_p = out / "profiles" / f"{org}_{tbl}.json"
        fresh = freshness(c, json.loads(prof_p.read_text(encoding="utf-8"))) if prof_p.exists() else {}
        if is_sample:
            st = "excluded_sample"
        elif (org, tbl) not in api_keys:
            st = "missing_in_api"
            parts = [x.strip() for x in c["paths"][0]["path"].split(" > ")]
            fold = parts[2:-1]
            add_rows.append({"category": fold[0] if fold else c["survey_name"],
                             "section": fold[1] if len(fold) > 1 else "", "path": " > ".join(fold),
                             "depth": len(fold), "org_id": org, "tbl_id": tbl, "tbl_nm": c["table_name"],
                             "stat_id": "", "send_de": "", "is_sample": False, "is_full": "전수" in " ".join(fold),
                             "survey_type": "전수" if "전수" in " ".join(fold) else "구분없음(전체집계)",
                             "selected": True, "dup": False, "also_in": "", "added_from": "xls_catalog"})
        elif r is None:
            st = "not_selected"
        elif not raw.exists():
            st = "not_downloaded"
        elif fresh.get("is_stale"):
            st = "stale"
        else:
            st = "ok"
        rows.append({"status": st, "survey_name": c["survey_name"], "organization": c["organization"],
                     "org_id": org, "tbl_id": tbl, "table_name": c["table_name"], "period": c.get("period"),
                     "data_end": json.dumps(fresh.get("data_end", {}), ensure_ascii=False),
                     "menu_path": mps[0] if mps else ""})
    extra = [k for k in sel_keys if k not in xcat]
    for org, tbl in extra:
        r = sel_keys[(org, tbl)]
        rows.append({"status": "not_in_catalog", "survey_name": r.category, "organization": "", "org_id": org,
                     "tbl_id": tbl, "table_name": r.tbl_nm, "period": "", "data_end": "", "menu_path": r.path})
    rep = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    rep.to_csv(out / "audit.csv", index=False, encoding="utf-8-sig")
    print(rep.pivot_table(index="survey_name", columns="status", values="tbl_id", aggfunc="count", fill_value=0)
          .to_string())
    refresh = rep[rep["status"].isin(["stale", "not_downloaded"])]["tbl_id"].tolist()
    (out / "refresh_tables.txt").write_text("\n".join(refresh), encoding="utf-8")
    print(f"\naudit.csv 저장. 다시 받을 표 {len(refresh)}개 → refresh_tables.txt")
    if add_rows:
        print(f"API 목록에 없는 표 {len(add_rows)}개" + ("" if args.apply else " (--apply 로 catalog.csv 에 추가)"))
        if args.apply:
            api2 = pd.concat([api, pd.DataFrame(add_rows).astype(str)], ignore_index=True)
            api2.to_csv(data / "catalog.csv", index=False, encoding="utf-8-sig")
            (out / "refresh_tables.txt").write_text("\n".join(refresh + [x["tbl_id"] for x in add_rows]),
                                                   encoding="utf-8")
            rf = (out / "refresh_tables.txt").as_posix()
            print("→ catalog.csv 에 추가했습니다. 수집:\n"
                  f"  python kosis_rag_builder.py schema   --tables @{rf}\n"
                  f"  python kosis_rag_builder.py download --tables @{rf} --refresh")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "views", "enrich", "render", "audit", "all"])
    ap.add_argument("--catalog", default=None,
                    help="preprocess_population.py 결과 jsonl (조사명·기관·메뉴 경로·KOSIS 링크·최신성 결합)")
    ap.add_argument("--apply", action="store_true", help="audit: API 목록에 없는 표를 catalog.csv 에 추가")
    ap.add_argument("--data", default="kosis_data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--surveys", nargs="*")
    ap.add_argument("--tables", nargs="*", help="tbl_id 지정")
    ap.add_argument("--max-tables", type=int)
    ap.add_argument("--force", action="store_true", help="prepare 강제 재생성")
    ap.add_argument("--kiwi", action="store_true", help="bm25_tokens 생성 (kiwipiepy)")
    ap.add_argument("--workers", type=int, default=4, help="enrich 동시 요청 수")
    ap.add_argument("--max-enrich", type=int, help="enrich 테스트용 개수 제한")
    ap.add_argument("--id", nargs="*", help="render 할 뷰 id")
    args = ap.parse_args()
    args.out = args.out or str(Path(args.data) / "rag_views")
    auto = Path(args.data) / "population_table_catalog.jsonl"
    if not args.catalog and auto.exists():          # data 폴더에 있으면 자동 사용
        args.catalog = str(auto)
    if args.stage in ("prepare", "all"):
        stage_prepare(args)
    if args.stage in ("views", "all"):
        stage_views(args)
    if args.stage == "enrich":
        stage_enrich(args)
    if args.stage == "render":
        stage_render(args)
    if args.stage == "audit":
        stage_audit(args)


if __name__ == "__main__":
    main()
