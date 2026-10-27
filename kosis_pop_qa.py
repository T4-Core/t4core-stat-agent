"""
population_4group_cleaned.csv 기반 LLM 질의응답: 질문 자동 생성(gen) → 표 선택·조건 추출 → duckdb 조회 → HCX 답변

입력 (이 파일 하나만 사용)
  kosis_data/merged/population_4group_cleaned.csv
  인구총조사·주민등록인구현황·장래가구추계 69개 표, long 포맷 (TBL_ID, C1(지역 등), ITM_ID, PRD_DE, DT ...)

단계
  python kosis_pop_qa.py prepare                          # CSV → parquet + 표 카탈로그 (최초 1회, 이후 캐시)
  python kosis_pop_qa.py gen --n 10                       # 데이터에서 사실을 뽑아 LLM이 질문 작성 → questions.jsonl
  python kosis_pop_qa.py ask "2025년 서울 1인가구는 몇 가구야?"   # 질문 1개 답변
  python kosis_pop_qa.py run --n 5                        # 질문 생성 + 답변 한 번에 (표 선택 정확도 출력)
  python kosis_pop_qa.py run --questions kosis_data/pop_qa/<...>_questions.jsonl

.env (.env.example 참고. .env 에 없는 키는 .env.example 값으로 채움)
  HCX_API_KEY, HCX_BASE_URL, HCX_MODEL
LLM 호출·숫자 검증은 kosis_rag_qa.py 의 chat / verify_numbers / fmt_v 를 그대로 사용합니다.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env")
load_dotenv(Path.cwd() / ".env.example")               # override=False → .env 에 없는 키만 채움

from kosis_rag_qa import (SIDO, chat, embed_many, embed_one, fmt_v, normalize,  # noqa: E402  (env 로드 후 import)
                          short_name, verify_numbers)

DATA = Path(os.getenv("KOSIS_DATA", "kosis_data"))
CSV = DATA / "merged" / "population_4group_cleaned.csv"
PQ = CSV.with_suffix(".parquet")
CATALOG = DATA / "merged" / "population_4group_catalog.json"
OUT = DATA / "pop_qa"

GEO_RE = re.compile(r"행정구역|시도|시군구|읍면동|동읍면|도별")
TOTAL_RE = re.compile(r"^(계|합계|총계|소계|전체|전국|총인구)$")
LEVEL_NM = {1: "시도", 2: "시군구", 3: "읍면동"}
MODE_NM = {"value": "값", "trend": "추이", "rank": "순위"}
TREND_RE = re.compile(r"추이|변화|변해|증가|감소|늘었|줄었|늘어|줄어|년 전|동안|부터|가장 (많|적)았던 (해|시기|연도)")
MAX_ROWS = 60
ROUTE_TOPN = int(os.getenv("ROUTE_TOPN", "10"))   # 임베딩으로 LLM 에 넘길 후보 표 수 (0 = 전체 목록)


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def chat_json(messages, schema, **kw):
    """chat + JSON 보정. HCX-005 처럼 구조화 출력을 지원하지 않는 모델은 형식 예시를 덧붙이고,
    'answer: ... / key_points: - ...' 같은 텍스트로 오면 스키마 키 기준으로 파싱"""
    props = schema["properties"]
    example = {k: ([] if v["type"] == "array" else False if v["type"] == "boolean" else "") for k, v in props.items()}
    msgs = messages[:-1] + [{"role": messages[-1]["role"], "content": messages[-1]["content"]
                             + f"\n\n출력 형식(JSON 객체 하나만, 다른 글 금지): {json.dumps(example, ensure_ascii=False)}"}]
    out = chat(msgs, schema=schema, **kw)
    if "_raw" not in out:
        return out
    raw = re.sub(r"\*\*", "", out["_raw"])
    keys = "|".join(map(re.escape, props))
    parts = re.split(rf"^\s*[-*]?\s*({keys})\s*[:：]", raw, flags=re.M)
    res = {"_raw": out["_raw"]}
    for k, v in zip(parts[1::2], parts[2::2]):
        v = v.strip()
        if props[k]["type"] == "array":
            res[k] = [re.sub(r"^[-*•\d.)\s]+", "", x).strip().strip('"') for x in re.split(r"\n|,\s*(?=DT_)", v)
                      if re.sub(r"^[-*•\d.)\s]+", "", x).strip()]
        elif props[k]["type"] == "boolean":
            res[k] = v.lower().startswith(("true", "예", "yes"))
        else:
            res[k] = v.strip('"')
    return res


# 1) prepare: CSV → parquet + 카탈로그
def stage_prepare(force=False):
    if not CSV.exists():
        raise SystemExit(f"입력 CSV 없음: {CSV}")
    c = duckdb.connect()
    if force or not PQ.exists() or PQ.stat().st_mtime < CSV.stat().st_mtime:
        print(f"CSV → parquet 변환 중 ({CSV.stat().st_size / 1e6:.0f}MB) ...", flush=True)
        t0 = time.time()
        c.execute(f"""
        COPY (
          SELECT TBL_ID AS tbl_id, TBL_NM AS tbl_nm, SOURCE_FOLDER AS survey,
                 C1 AS c1, C1_OBJ_NM AS c1_obj, trim(C1_NM) AS c1_nm,
                 ITM_ID AS itm_id, trim(ITM_NM) AS itm_nm, coalesce(UNIT_NM, '') AS unit,
                 PRD_SE AS prd_se, PRD_DE AS prd_de,
                 try_cast(replace(DT, ',', '') AS DOUBLE) AS value
          FROM read_csv({sql_str(CSV.as_posix())}, all_varchar=true, header=true)
        ) TO {sql_str(PQ.as_posix())} (FORMAT PARQUET)""")
        print(f"  완료 {time.time() - t0:.0f}s → {PQ} ({PQ.stat().st_size / 1e6:.0f}MB)")
    src = f"read_parquet({sql_str(PQ.as_posix())})"
    tables = []
    for tid, nm, sv, obj in c.execute(
            f"SELECT tbl_id, any_value(tbl_nm), any_value(survey), any_value(c1_obj) FROM {src} "
            f"GROUP BY tbl_id ORDER BY tbl_id").fetchall():
        items = [{"itm_id": a, "nm": b, "unit": u} for a, b, u in c.execute(
            f"SELECT itm_id, any_value(itm_nm), any_value(unit) FROM {src} WHERE tbl_id = ? "
            f"GROUP BY itm_id ORDER BY itm_id", [tid]).fetchall()]
        years = [r[0] for r in c.execute(
            f"SELECT DISTINCT prd_de FROM {src} WHERE tbl_id = ? ORDER BY prd_de", [tid]).fetchall()]
        codes = c.execute(f"SELECT c1, any_value(c1_nm) FROM {src} WHERE tbl_id = ? GROUP BY c1 ORDER BY c1",
                          [tid]).fetchall()
        tot = [cd for cd, n in codes if cd.strip("0") == "" or TOTAL_RE.match(str(n))]
        tables.append({"tbl_id": tid, "tbl_nm": nm, "survey": sv, "c1_obj": obj, "geo": bool(GEO_RE.search(str(obj))),
                       "items": items, "years": years, "n_codes": len(codes), "total_code": tot[0] if tot else None})
    CATALOG.write_text(json.dumps(tables, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"카탈로그 {len(tables)}개 표 → {CATALOG}")
    return tables


_con, _tables, _regions = None, None, {}


def con():
    global _con
    if _con is None:
        if not PQ.exists():
            stage_prepare()
        _con = duckdb.connect()
        _con.execute(f"CREATE VIEW pop AS SELECT * FROM read_parquet({sql_str(PQ.as_posix())})")
    return _con


def tables():
    global _tables
    if _tables is None:
        _tables = (json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() and PQ.exists()
                   else stage_prepare())
    return {t["tbl_id"]: t for t in _tables}


def regions(tbl_id):
    """표의 분류 코드 목록: code, name, depth(0 합계 / 1 시도 / 2 시군구 / 3 읍면동, 지역 아닌 분류는 1), label"""
    if tbl_id in _regions:
        return _regions[tbl_id]
    t = tables()[tbl_id]
    df = con().execute("SELECT c1 AS code, any_value(c1_nm) AS name FROM pop WHERE tbl_id = ? GROUP BY c1 ORDER BY c1",
                       [tbl_id]).df()

    def depth(code, name):
        if code.strip("0") == "" or TOTAL_RE.match(str(name)):
            return 0
        if not t["geo"]:
            return 1
        return 1 if len(code) <= 2 else 2 if len(code) <= 5 else 3
    df["depth"] = [depth(c, n) for c, n in zip(df.code, df.name)]
    # 이름이 겹치면(서울 중구 / 부산 중구) 상위 지역 이름을 붙여 구분
    name_of = dict(zip(df.code, df.name))
    dup = df.name.duplicated(keep=False)
    df["label"] = [f"{name_of.get(c[:2], '')} {n}".strip() if d and t["geo"] and len(c) > 2 else n
                   for c, n, d in zip(df.code, df.name, dup)]
    _regions[tbl_id] = df
    return df


def match_regions(question, tbl_id):
    """질문에 나온 지역 → 이 표의 코드. 시도 줄임말(서울, 경북) 인식, 상위·하위가 같이 나오면 하위만 남김"""
    reg = regions(tbl_id)
    sido = [nm for nm in SIDO if nm in question or (len(short_name(nm)) >= 2 and short_name(nm) in question)]
    hits = {c: str(n) for c, n, d in zip(reg.code, reg.name, reg.depth)
            if d > 0 and ((len(str(n)) >= 2 and str(n) in question)
                          or (d == 1 and any(short_name(s) == short_name(str(n)) for s in sido)))}
    names = set(hits.values())
    codes = [c for c, n in hits.items() if not any(n != m and n in m for m in names)]   # '동구' ⊂ '강동구' 제거
    tops = [c for c in codes if len(c) <= 2]
    if tops:                                           # 같은 이름의 하위 지역은 질문의 시도 안의 것만
        codes = [c for c in codes if len(c) <= 2 or any(c.startswith(p) for p in tops)]
    codes = [c for c in codes if not any(o != c and o.startswith(c) for o in codes)]
    return codes, sido


# 좌표(plan) → 데이터
# plan = {"tbl_id", "items": [항목명], "mode": value|trend|rank, "regions": [코드], "years": [시점],
#         "level": 순위 비교 단계(depth), "within": 순위 비교 범위(상위 지역 코드)}
def item_ids(t, names):
    ids = [i["itm_id"] for n in names for i in t["items"] if i["nm"] == n]
    if not ids:                                        # 이름이 조금 다르면 포함 관계로 찾기
        ids = [i["itm_id"] for n in names for i in t["items"] if n and (n in i["nm"] or i["nm"] in n)]
    return list(dict.fromkeys(ids)) or [t["items"][0]["itm_id"]]


def fetch(plan):
    t = tables()[plan["tbl_id"]]
    reg = regions(plan["tbl_id"])
    ids = item_ids(t, plan.get("items") or [])
    years = [y for y in plan.get("years") or [] if y in t["years"]]
    if plan["mode"] == "rank":
        lv = plan.get("level") or 1
        codes = [c for c, d in zip(reg.code, reg.depth) if d == lv]
        if plan.get("within"):
            codes = [c for c in codes if c.startswith(plan["within"])]
        ids, years = ids[:1], years[-1:] or t["years"][-1:]
    else:
        codes = plan.get("regions") or ([t["total_code"]] if t["total_code"] else list(reg.code[reg.depth == 1]))
        if plan["mode"] == "trend":
            years = [y for y in t["years"] if min(years) <= y <= max(years)] if len(years) >= 2 else t["years"]
        else:
            years = years or t["years"][-1:]
    df = con().execute(
        "SELECT prd_de, c1, itm_id, itm_nm, unit, value FROM pop WHERE tbl_id = ? "
        "AND list_contains(?, itm_id) AND list_contains(?, c1) AND list_contains(?, prd_de)",
        [plan["tbl_id"], ids, codes, years]).df()
    df["지역"] = df.c1.map(dict(zip(reg.code, reg.label)))
    order = {i: k for k, i in enumerate(ids)}
    if plan["mode"] == "rank":
        df = df.sort_values("value", ascending=False, na_position="last")
    else:
        df = df.assign(_o=df.itm_id.map(order)).sort_values(["c1", "_o", "prd_de"]).drop(columns="_o")
    return df.reset_index(drop=True), {"items": [n for n in df.itm_nm.unique()], "regions": codes, "years": years}


def facts(df, mode):
    """조회 결과에서 핵심 수치 문장 (kosis_views.facts_trend / facts_breakdown 과 같은 기준)"""
    d = df.dropna(subset=["value"])
    out = []
    if d.empty:
        return out
    if mode == "trend":
        for (rg, it), s in d.groupby(["지역", "itm_nm"], sort=False):
            if len(s) < 2:
                continue
            a, b = s.iloc[0], s.iloc[-1]
            txt = f"{rg} {it}: {a.prd_de} {fmt_v(a.value)} → {b.prd_de} {fmt_v(b.value)} {b.unit}, 변화 {fmt_v(b.value - a.value)}"
            if a.value:
                txt += f" (약 {(b.value - a.value) / abs(a.value) * 100:+.1f}%)"
            mx, mn = s.loc[s.value.idxmax()], s.loc[s.value.idxmin()]
            out.append(txt + f", 최대 {mx.prd_de} {fmt_v(mx.value)}, 최소 {mn.prd_de} {fmt_v(mn.value)}")
    elif mode == "rank":
        out.append(f"비교 범주 {len(d)}개 ({d.prd_de.iloc[0]}, {d.itm_nm.iloc[0]})")
        out += [f"{k}위 {r.지역} {fmt_v(r.value)} {r.unit}" for k, r in enumerate(d.head(5).itertuples(), 1)]
        if len(d) > 5:
            lo = d.iloc[-1]
            out.append(f"최하위 {lo.지역} {fmt_v(lo.value)} {lo.unit}")
    return out


def caveats(t, years):
    cv = []
    if t["survey"] == "주민등록인구현황":
        cv.append("주민등록 기준 인구로, 실제 거주 기준인 인구총조사와 수치가 다를 수 있음")
    if t["survey"] == "장래가구추계" or "추계" in t["tbl_nm"]:
        cv.append("추계(전망)값으로 실측치가 아님")
    if t["survey"] == "인구총조사" and years and min(years) < "2015" <= max(years):
        cv.append("2015년부터 등록센서스(행정자료 기반) 방식으로 바뀌어 이전 시점과 직접 비교에 주의")
    if "연도 끝자리" in t["tbl_nm"]:
        cv.append("읍면동 자료는 연도 끝자리가 0·5인 해만 제공, 그 외 연도는 시군구까지")
    if t["geo"] and len(t["years"]) > 1:
        cv.append("행정구역 개편으로 시점별 지역 범위가 다를 수 있음")
    return cv


def context_block(plan, df, used, missing=()):
    t = tables()[plan["tbl_id"]]
    reg = regions(plan["tbl_id"])
    lab = dict(zip(reg.code, reg.label))
    if plan["mode"] == "rank":
        scope = f"{LEVEL_NM.get(plan.get('level'), '범주') if t['geo'] else t['c1_obj']}별 비교" + (
            f" ({lab.get(plan['within'], plan['within'])} 안)" if plan.get("within") else "")
    else:
        scope = ", ".join(lab.get(c, c) for c in used["regions"][:10]) + (" 외" if len(used["regions"]) > 10 else "")
    yrs = used["years"]
    lines = [f"[자료 id={t['tbl_id']}]",
             f"제목: {t['tbl_nm']} (자료: 「{t['survey']}」, KOSIS)",
             f"조회 조건: 방식={MODE_NM[plan['mode']]}, 항목={', '.join(used['items'])}, {t['c1_obj']}={scope}, "
             f"시점={yrs[0] + '~' + yrs[-1] if len(yrs) > 1 else ''.join(yrs)}"]
    if missing:
        lines.append("⚠ 질문 조건 중 이 자료에 없는 것: " + "; ".join(missing)
                     + " → 이 자료의 값을 질문 대상의 값으로 답하지 말 것")
    if df.empty:
        lines.append("데이터: 조건에 맞는 값 없음")
        return "\n".join(lines)
    lines.append("데이터(시점 | 지역/분류 | 항목 | 값 | 단위):")
    rows = df.head(MAX_ROWS) if plan["mode"] != "rank" else pd.concat([df.head(15), df.tail(3)]).drop_duplicates()
    for r in rows.itertuples():
        lines.append(f"  {r.prd_de} | {r.지역} | {r.itm_nm} | {fmt_v(r.value)} | {r.unit}")
    if len(df) > len(rows):
        lines.append(f"  … 외 {len(df) - len(rows)}행")
    f = facts(df, plan["mode"])
    if f:
        lines.append("핵심 수치: " + "; ".join(f))
    cv = caveats(t, yrs)
    if cv:
        lines.append("주의: " + " / ".join(cv))
    return "\n".join(lines)


# 2) gen: 데이터 사실 → LLM 질문 작성
GEN_SCHEMA = {"type": "object", "properties": {
    "questions": {"type": "array", "items": {"type": "string"}}}, "required": ["questions"]}
GEN_SYS = ("너는 한국 인구통계 질의응답 평가셋 작성자다. 주어진 [자료]만으로 답할 수 있는 사용자 질문을 만든다. "
           "자료에 없는 조건을 추가하지 않고, 질문 안에 답(숫자)을 쓰지 않는다. "
           "항목명은 일상어로 자연스럽게 바꾼다 (예: '일반가구_가구원_남자' → '일반가구 남자 가구원 수', '1인' → '1인 가구'). "
           "지역·연도 조건은 반드시 질문에 포함한다. JSON만 출력.")
GEN_HINT = {"value": "특정 지역·연도의 값을 묻는 질문", "trend": "기간 동안의 변화·추이를 묻는 질문",
            "rank": "가장 많은/적은 곳이나 순위를 묻는 질문"}


def sample_plan(rng):
    """무작위 표·항목·방식·지역·시점 → 질문 생성용 plan"""
    t = rng.choice(list(tables().values()))
    reg = regions(t["tbl_id"])
    it = rng.choice(t["items"][:20])
    lv_cnt = reg[reg.depth > 0].depth.value_counts()
    levels = [int(d) for d, n in lv_cnt.items() if n >= 3]
    modes = ["value"] + (["trend"] if len(t["years"]) >= 2 else []) + (["rank"] if levels else [])
    mode = rng.choice(modes)
    plan = {"tbl_id": t["tbl_id"], "items": [it["nm"]], "mode": mode, "regions": [], "years": []}
    if mode == "rank":
        plan["level"] = rng.choice(levels)
        plan["years"] = [rng.choice(t["years"])]
        if plan["level"] >= 2 and rng.random() < 0.5:
            tops = [c for c, d in zip(reg.code, reg.depth) if d == 1]
            if tops:
                plan["within"] = rng.choice(tops)
    else:
        pick = reg[reg.depth.isin([1, 2] if rng.random() < 0.3 else [1])]
        if len(pick) and (rng.random() < 0.6 or not t["total_code"]):
            plan["regions"] = [rng.choice(list(pick.code))]
        if mode == "value":
            plan["years"] = [rng.choice(t["years"])]
    return plan


def generate(n, per=2, seed=0):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        for _ in range(20):                            # 값이 비어 있으면 다시 뽑기
            plan = sample_plan(rng)
            df, used = fetch(plan)
            if df.value.notna().sum() >= (3 if plan["mode"] == "rank" else 1):
                break
        ctx = context_block(plan, df, used)
        res = chat_json([{"role": "system", "content": GEN_SYS},
                    {"role": "user", "content": f"[자료]\n{ctx}\n\n위 자료로 답할 수 있는 {GEN_HINT[plan['mode']]}을 "
                                                f"{per}개 만들어라. 1개는 구어체, 1개는 짧은 키워드형."}],
                   schema=GEN_SCHEMA, temperature=0.5, max_tokens=400)
        qs = [q.strip() for q in (res.get("questions") or []) if isinstance(q, str) and q.strip()][:per]
        for q in qs:
            out.append({"question": q, "gold": {**plan, "items": used["items"]}, "context": ctx})
            print(f"  [{len(out)}/{n}] ({MODE_NM[plan['mode']]}) {q}   ← {tables()[plan['tbl_id']]['tbl_nm']}", flush=True)
    return out[:n]


def stage_gen(args):
    qs = generate(args.n, args.per, args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{datetime.now():%Y%m%d_%H%M%S}_questions.jsonl"
    p.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qs), encoding="utf-8")
    print(f"\n질문 {len(qs)}개 저장: {p}")
    return qs


# 3) ask: 표 선택 → 조건 추출 → 조회 → 답변
ROUTE_SCHEMA = {"type": "object", "properties": {
    "tables": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
    "required": ["tables", "reason"]}
ROUTE_SYS = ("너는 한국 인구통계 표 선택 도우미다. [표 목록]에서 질문에 답할 수 있는 표 id 를 관련도 순으로 최대 2개 고른다. "
             "질문의 연도가 표의 시점 범위 안에 있는지, 지역 단계(시도/시군구/읍면동)와 항목이 맞는지 확인한다. "
             "연도가 없으면 최신 시점까지 있는 표를 우선한다. JSON만 출력.")
PLAN_SCHEMA = {"type": "object", "properties": {
    "items": {"type": "array", "items": {"type": "string"}},
    "mode": {"type": "string", "enum": ["value", "trend", "rank"]},
    "level": {"type": "string"},
    "years": {"type": "array", "items": {"type": "string"}}},
    "required": ["items", "mode", "level", "years"]}
PLAN_SYS = ("너는 통계표 조회 조건을 정하는 도우미다. 질문에 맞게 고른다.\n"
            "- items: [항목 목록]에 있는 이름 그대로 1~4개\n"
            "- mode: value(특정 값) | trend(시간에 따른 변화·추이) | rank(가장 많은/적은 곳, 순위, 지역 비교)\n"
            "- level: rank 일 때 비교할 단계([비교 단계] 중 하나), 아니면 빈 문자열\n"
            "- years: [시점 목록]에 있는 값만. 질문에 연도가 없으면 빈 배열 (최신 시점 사용)\n"
            "JSON만 출력.")
ANSWER_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"}, "summary": {"type": "string"},
    "key_points": {"type": "array", "items": {"type": "string"}},
    "used_ids": {"type": "array", "items": {"type": "string"}}, "insufficient": {"type": "boolean"}},
    "required": ["answer", "summary", "key_points", "used_ids", "insufficient"]}
ANSWER_SYS = """너는 한국 공식통계(KOSIS)를 근거로 답하는 인구통계 안내원이다.
규칙:
1. 반드시 [자료]에 있는 숫자만 쓴다. 계산(차이·증감률)이 필요하면 [자료]의 숫자로 계산하고 '약'을 붙인다. 없는 숫자를 만들지 않는다.
2. 질문에 맞는 자료가 없거나 조건(연도·지역)이 다르면 insufficient=true 로 하고, 가장 가까운 자료로 무엇을 알 수 있는지 설명한다.
   자료의 지역·시점이 질문과 다르면 그 값을 질문 대상의 값처럼 쓰지 않는다 (예: 전국 값을 서울 값으로 쓰지 않는다).
3. 기준 시점과 단위를 항상 밝힌다. 주의사항이 있으면 한 문장으로 덧붙인다.
4. 문체는 '~입니다'체. answer 는 3~6문장, summary 는 1문장, key_points 는 핵심 수치 2~4개.
5. used_ids 에 실제로 근거로 쓴 자료 id 를 넣는다.
JSON만 출력한다."""


def catalog_text(ids=None):
    lines = []
    for t in (tables()[i] for i in ids) if ids else tables().values():
        ys = t["years"]
        its = ", ".join(i["nm"] for i in t["items"][:12]) + (f" 외 {len(t['items']) - 12}개" if len(t["items"]) > 12 else "")
        lines.append(f"{t['tbl_id']} | {t['tbl_nm']} | {t['survey']} | 분류: {t['c1_obj']}({t['n_codes']}개) | "
                     f"시점: {ys[0]}~{ys[-1]}({len(ys)}개) | 항목: {its}")
    return "\n".join(lines)


def as_strs(v):
    """LLM 이 문자열 대신 숫자·dict({"id": ...}) 를 돌려준 경우 → 문자열 목록으로 정리"""
    out = []
    for x in v if isinstance(v, list) else [v] if v else []:
        if isinstance(x, dict):
            x = next((x[k] for k in ("id", "tbl_id", "table", "nm", "name", "item") if k in x),
                     next(iter(x.values()), ""))
        if x not in (None, ""):
            out.append(str(x))
    return out


def table_doc(t):
    """임베딩용 표 설명: 표 이름·조사·분류·시점·항목 전체 (catalog_text 와 달리 항목을 자르지 않음)"""
    ys = t["years"]
    its = ", ".join(i["nm"] for i in t["items"][:80])
    return (f"{t['tbl_nm']} ({t['survey']}) | 분류: {t['c1_obj']} | 시점: {ys[0]}~{ys[-1]}년 "
            f"({', '.join(ys[-12:])}) | 항목: {its}")


_tvec = None


def table_vecs():
    """표 69개 임베딩 (kosis_rag_qa 의 embed_cache.sqlite 에 캐시 → 최초 1회만 API 호출)"""
    global _tvec
    if _tvec is None:
        ids = list(tables())
        _tvec = ids, normalize(embed_many([table_doc(tables()[i]) for i in ids]))
    return _tvec


def candidates(question, n=ROUTE_TOPN):
    """질문과 표 설명의 코사인 유사도 상위 n개 → [(tbl_id, 점수)]"""
    ids, mat = table_vecs()
    sims = mat @ normalize(embed_one(question))
    return [(ids[i], round(float(sims[i]), 4)) for i in sims.argsort()[::-1][:n]]


def route(question, k=2):
    """1) 임베딩으로 후보 표 ROUTE_TOPN 개 → 2) LLM 이 후보 중 최대 k개 선택.
    임베딩 실패·ROUTE_TOPN=0 이면 전체 목록을 LLM 에 넘김"""
    cands = []
    if ROUTE_TOPN > 0:
        try:
            cands = candidates(question)
        except Exception as e:                         # 임베딩 API 오류 → 기존 방식으로 진행
            print(f"[route] 임베딩 후보 실패, 전체 목록 사용: {e}", file=sys.stderr)
    pool = [i for i, _ in cands] or list(tables())
    out = chat_json([{"role": "system", "content": ROUTE_SYS},
                {"role": "user", "content": f"[표 목록]\n{catalog_text(pool)}\n\n[질문]\n{question}"}],
               schema=ROUTE_SCHEMA, max_tokens=300)
    ids = [i for i in as_strs(out.get("tables")) if i in pool]
    if not ids:                                        # 구조화 출력 실패 → 응답 원문에서 표 id 찾기
        ids = [i for i in re.findall(r"DT_\w+", out.get("_raw", "")) if i in pool]
    if not ids and cands:                              # LLM 이 못 고르면 유사도 1위
        ids = [cands[0][0]]
    return list(dict.fromkeys(ids))[:k], out.get("reason", ""), cands


def make_plan(question, tbl_id):
    """LLM: 항목·방식·시점 / 코드 매칭: 지역 → plan + 적용 못 한 조건"""
    t = tables()[tbl_id]
    reg = regions(tbl_id)
    levels = sorted(int(d) for d in reg.depth.unique() if d > 0)
    lv_names = [LEVEL_NM[d] for d in levels] if t["geo"] else [t["c1_obj"]]
    out = chat_json([{"role": "system", "content": PLAN_SYS},
                {"role": "user", "content": f"[표] {t['tbl_nm']}\n"
                                            f"[항목 목록] {' | '.join(i['nm'] for i in t['items'])}\n"
                                            f"[비교 단계] {' | '.join(lv_names)}\n"
                                            f"[시점 목록] {', '.join(t['years'])}\n\n[질문]\n{question}"}],
               schema=PLAN_SCHEMA, max_tokens=300)
    mode = out.get("mode") if out.get("mode") in MODE_NM else "value"
    q_years = re.findall(r"(1[89]\d{2}|20\d{2})\s*년?", question)
    years = [str(y) for y in (out.get("years") or []) if str(y) in t["years"]] or [y for y in q_years if y in t["years"]]
    if mode == "value" and TREND_RE.search(question) and len(t["years"]) >= 2:   # LLM 이 추이 질문을 값으로 분류한 경우 보정
        mode = "trend"
        years = years if len(q_years) >= 2 else []
    if re.search(r"최근|최신|요즘|현재", question) and mode != "trend" and not years:
        years = t["years"][-1:]
    codes, sido = match_regions(question, tbl_id)
    plan = {"tbl_id": tbl_id, "items": as_strs(out.get("items")), "mode": mode, "regions": codes, "years": years}
    missing = []
    if mode == "rank":
        lv = next((d for d, n in zip(levels, lv_names) if n == out.get("level")), None)
        tops = [c for c in codes if len(c) <= 2]
        plan["level"] = lv or (levels[1] if tops and len(levels) > 1 else levels[0] if levels else 1)
        if tops and plan["level"] >= 2:                # '서울에서 가장 많은 구' → 서울 안의 시군구 비교
            plan["within"] = tops[0]
    miss_y = [y for y in q_years if y not in t["years"]]
    if miss_y:
        missing.append(f"시점({', '.join(miss_y)}): 수록 {t['years'][0]}~{t['years'][-1]} 밖")
    if sido and not codes:
        missing.append(f"지역({', '.join(sido)}): " + ("이 표의 지역 목록에 없음" if t["geo"] else "이 표에는 지역 분류가 없음"))
    return plan, missing


def answer(question, k=2, save=True):
    t0 = time.time()
    tids, reason, cands = route(question, k)
    if not tids:
        raise SystemExit("질문에 맞는 표를 고르지 못했습니다.")
    blocks, plans = [], []
    for tid in tids:
        plan, missing = make_plan(question, tid)
        df, used = fetch(plan)
        blocks.append(context_block(plan, df, used, missing))
        plans.append({**plan, "missing": missing, "n_rows": len(df)})
    plans_order = sorted(range(len(plans)), key=lambda i: (bool(plans[i]["missing"]), plans[i]["n_rows"] == 0))
    context = "\n\n".join(blocks[i] for i in plans_order)
    out = chat_json([{"role": "system", "content": ANSWER_SYS},
                {"role": "user", "content": f"[질문]\n{question}\n\n[자료]\n{context}"}],
               schema=ANSWER_SCHEMA, max_tokens=1200)
    ans = out.get("answer") or out.get("_raw", "")
    used_ids = [u for u in as_strs(out.get("used_ids")) if u in tids] or tids[:1]
    cond_ok = any(not p["missing"] and p["n_rows"] for p in plans)
    summary = str(out.get("summary") or "")
    kps = [str(k) for k in (out.get("key_points") or [])]   # LLM 이 숫자만 돌려주는 경우 대비
    result = {
        "question": question, "tables": tids, "route_reason": reason, "route_candidates": cands, "plans": plans,
        "answer": ans, "summary": summary, "key_points": kps,
        "insufficient": bool(out.get("insufficient")) or not cond_ok,
        "unverified_numbers": verify_numbers(" ".join([str(ans), summary] + kps), context),
        "used_ids": used_ids,
        "sources": [f"자료: 「{tables()[u]['survey']}」 {tables()[u]['tbl_nm']} (KOSIS {u})" for u in used_ids],
        "context": context, "elapsed_s": round(time.time() - t0, 2),
    }
    if save:
        d = OUT / "answers"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{datetime.now():%Y%m%d_%H%M%S}.json"
        p.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        result["saved"] = str(p)
        log = [f"## {datetime.now():%Y-%m-%d %H:%M:%S}  ({result['elapsed_s']}s)", "",   # 검토용 누적 로그
               f"**질문**: {question}", "", f"**표**: {', '.join(map(str, tids))}", "", "**답변**:", "", ans, "",
               f"**요약**: {result['summary']}", ""]
        log += ["**핵심 수치**:"] + [f"- {k}" for k in result["key_points"]] + [""] if result["key_points"] else []
        log += ["**출처**:"] + [f"- {s}" for s in result["sources"]] + [""] if result["sources"] else []
        if result["insufficient"]:
            log.append("> ⚠ 자료 부족 판정\n")
        if result["unverified_numbers"]:
            full = " ".join([ans, result["summary"]] + list(result["key_points"]))
            log.append(f"> ⚠ 근거에서 확인 안 된 수치: {result['unverified_numbers']}")
            for n in result["unverified_numbers"]:          # 숫자가 쓰인 문장 일부를 함께 기록
                i = full.find(n)
                log.append(f">   - {n}: …{full[max(0, i - 30):i + len(n) + 15]}…" if i >= 0 else f">   - {n}")
            log.append("")
        from kosis_pop_eval import evidence_text       # 근거 자료·수치 대조·5대 지표 (LLM 답변과 실제 값 비교용)
        log += ["**근거 자료·자동 판정**:", "", "```text", evidence_text(result), "```", ""]
        with (d / "qa_log.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n---\n\n")
    return result


def print_result(r, show_context=False):
    print(f"\n질문: {r['question']}  ({r['elapsed_s']}s)")
    for p in r["plans"]:
        t = tables()[p["tbl_id"]]
        ys = t["years"]
        if p["years"]:
            yr = p["years"][:5]
        elif ys:                                       # 빈 시점 → 실제 사용 범위 표시
            yr = f"전체({ys[0]}~{ys[-1]}, {len(ys)}개)" if p["mode"] == "trend" else f"최신({ys[-1]})"
        else:
            yr = "-"
        print(f"  · 표 {p['tbl_id']} {t['tbl_nm']} | 방식 {MODE_NM[p['mode']]} | 항목 {p['items'][:4]} "
              f"| 지역 {p['regions'][:5]} | 시점 {yr}" + (f" | 없음 {p['missing']}" if p["missing"] else ""))
    print("\n■ 답변\n" + r["answer"])
    if r["key_points"]:
        print("\n■ 핵심 수치\n" + "\n".join(f"- {p}" for p in r["key_points"]))
    if r["insufficient"]:
        print("\n⚠ 질문 조건과 정확히 맞는 자료가 없어 가장 가까운 자료로 답했습니다.")
    if r["unverified_numbers"]:
        print(f"\n⚠ 자료에서 확인되지 않은 숫자(계산값일 수 있음): {r['unverified_numbers']}")
    print("\n■ 출처\n" + "\n".join(f"- {s}" for s in r["sources"]))
    from kosis_pop_eval import evidence_text           # 근거 자료·수치 대조·5대 지표 자동 판정
    print("\n" + evidence_text(r))
    if show_context:
        print("\n■ 근거 자료\n" + r["context"])
    if r.get("saved"):
        print(f"\n저장: {r['saved']}")


def stage_ask(args):
    print_result(answer(args.query, k=args.k), show_context=args.show_context)


def stage_run(args):
    """질문 생성(또는 파일) → 답변 → 표 선택 정확도"""
    if args.questions:
        qs = [json.loads(l) for l in Path(args.questions).open(encoding="utf-8") if l.strip()]
    else:
        print(f"질문 {args.n}개 생성 중 ...")
        qs = stage_gen(args)
    rows, hit = [], 0
    for i, q in enumerate(qs, 1):
        print("\n" + "=" * 80 + f"\n[{i}/{len(qs)}]")
        r = answer(q["question"], k=args.k, save=False)
        print_result(r, show_context=args.show_context)
        gold = (q.get("gold") or {}).get("tbl_id")
        if gold:
            ok = gold in r["tables"]
            hit += ok
            print(f"\n정답 표 {gold}: {'✓ 선택됨' if ok else '✗ 놓침'}")
        rows.append({**{k: v for k, v in r.items() if k != "context"}, "gold": q.get("gold")})
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{datetime.now():%Y%m%d_%H%M%S}_answers.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    n_gold = sum(1 for q in qs if (q.get("gold") or {}).get("tbl_id"))
    print("\n" + "=" * 80)
    if n_gold:
        print(f"표 선택 정확도: {hit}/{n_gold} = {hit / n_gold:.2f}")
    print(f"자료 부족 답변: {sum(r['insufficient'] for r in rows)}개, 미확인 숫자 포함: "
          f"{sum(bool(r['unverified_numbers']) for r in rows)}개")
    print(f"저장: {p}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")       # cp949 콘솔에서 ⚠ 등 출력 오류 방지
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="ask", choices=["prepare", "gen", "ask", "run"])  # 생략 시 ask
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--n", type=int, default=5, help="gen/run: 생성할 질문 수")
    ap.add_argument("--per", type=int, default=2, help="gen: 사실 1개당 질문 수")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--k", type=int, default=2, help="ask: 사용할 표 수 (최대)")
    ap.add_argument("--questions", default=None, help="run: 질문 jsonl (없으면 생성)")
    ap.add_argument("--show-context", action="store_true", help="LLM 에 준 근거 자료 원문(context)도 출력")
    ap.add_argument("--force", action="store_true", help="prepare: parquet 다시 생성")
    args = ap.parse_args()
    if args.stage == "prepare":
        stage_prepare(args.force)
    elif args.stage == "gen":
        stage_gen(args)
    elif args.stage == "ask":
        if args.query:
            stage_ask(args)
            return
        while True:                                    # 인자 없이 실행하면 대화식 반복 입력
            try:
                args.query = input("\n질문을 입력하세요 (종료: 빈 줄 또는 q): ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if args.query.lower() in ("", "q", "quit", "exit"):
                break
            try:
                stage_ask(args)
            except Exception as e:                     # 한 질문이 실패해도 다음 질문은 계속
                import traceback
                traceback.print_exc()
                print(f"⚠ 오류: {e.__class__.__name__}: {e}")
        print("종료합니다.")
    elif args.stage == "run":
        stage_run(args)


if __name__ == "__main__":
    main()
