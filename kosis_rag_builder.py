"""
전용 사용법
KOSIS 인구 카테고리 → (표본 제외) 전수부문 통계표만 수집 → 조사별 병합 CSV → RAG 문서 생성

단계별 실행 (앞 단계 결과는 캐시되어 재실행 시 이어서 진행됨
python kosis_rag_builder.py catalog    # 1) 목록 트리 전체 탐색 → catalog.csv (전수/표본 판별 포함)
python kosis_rag_builder.py schema     # 2) 선택된 표의 메타(분류·항목·시점·주석) → table_schema.csv
python kosis_rag_builder.py download   # 3) 수치 데이터 수집 (4만 셀 제한 자동 분할)
python kosis_rag_builder.py status     #    조사별 진행 현황 (남은 표, 대용량 건너뜀, 실패)
python kosis_rag_builder.py build      # 4) 조사별 병합 CSV + RAG 문서(csv/jsonl)
python kosis_rag_builder.py store      # 5) 에이전트용 저장소: 표 카드 + 분류 사전 + 표별 parquet + DuckDB
python kosis_rag_builder.py all
python kosis_rag_builder.py roots      #    주제별 최상위 목록 ID 확인 (인구 외 주제 수집 시 --root, --out)


python kosis_rag_builder.py catalog 
python kosis_rag_builder.py schema 
python kosis_rag_builder.py download 
python kosis_rag_builder.py status

python kosis_rag_builder.py build
python kosis_rag_builder.py store 
python kosis_rag_builder.py all
python kosis_rag_builder.py roots 



옵션
  --surveys 인구총조사 주민등록인구현황   # 특정 조사만
  --max-tables 20                         # 테스트용 표 개수 제한
  --recent 5                              # 표마다 최근 N개 시점만 수집 (생략 시 전체)

필요 패키지: requirements.txt 동봉하였음
.env : KOSIS_API_KEY=발급키
"""
import argparse
import ast
import json
import math
import os
import re
import time
import hashlib
import shutil
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv(dotenv_path=Path.cwd() / ".env")
API_KEY = os.getenv("KOSIS_API_KEY")

BASE = "https://kosis.kr/openapi"
URL_LIST = f"{BASE}/statisticsList.do"                     # 통계목록
URL_META = f"{BASE}/statisticsData.do"                     # 메타자료 (method=getMeta)
URL_DATA = f"{BASE}/Param/statisticsParameterData.do"      # 통계자료 (통계표선택 방식)
URL_EXPL = f"{BASE}/statisticsExplData.do"                 # 통계설명

VW_CD = "MT_ZTITLE"      # 국내통계 > 주제별
ROOT_LIST_ID = "A"       # 주제별 > 인구  (catalog 실행 시 루트 이름을 출력해 확인)
OUT = Path("kosis_data")

CELL_LIMIT = 40_000      # 매뉴얼: 요청당 4만 셀 이하
SLEEP = 0.35             # 매뉴얼: 분당 200건 제한 → 호출 간 간격

# 경로(폴더명) 중 하나라도 매칭되면 '표본'으로 보고 제외
SAMPLE_PATTERNS = [r"표본", r"\d+\s*%\s*부문", r"샘플"]
# 경로에 이 패턴이 있으면 '전수'로 표시
FULL_PATTERNS = [r"전수", r"등록센서스"]

# 함께 참고하면 좋은 조사 (인구 루트 아래에 있으면 자동 포함되므로 표시용 태그)
RELATED_HINT = {
    "인구총조사": "핵심: 성·연령·지역별 인구/가구 전수 집계",
    "주민등록인구현황": "월별 주민등록 인구 (총조사와 기준이 다름: 등록 vs 상주)",
    "인구동향조사": "출생·사망·혼인·이혼 (인구 변동 요인)",
    "장래인구추계": "미래 인구 전망",
    "장래가구추계": "미래 가구 전망",
    "국내인구이동통계": "시도·시군구 간 전입/전출",
    "국제인구이동통계": "국제 입출국 이동",
    "주택총조사": "가구·주택 질문 보완용",
}

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

######## 추가 코드##########
try:
    from tqdm import tqdm             # 진행률 표시
except ImportError:                   # tqdm 미설치 시 아무것도 하지 않는 대체 객체
    class tqdm:
        def __init__(self, *a, total=0, **k):
            self.n, self.total = 0, total
        def update(self, k=1):
            self.n += k
        def set_postfix_str(self, *a, **k): pass
        def refresh(self): pass
        def close(self): pass
######## 추가 코드##########

WORKERS = 4                       # 동시 요청 수 (서버 응답 대기 시간을 겹쳐서 활용)
MIN_INTERVAL = 60 / 180           # 분당 200건 제한보다 약간 낮게 (전체 스레드 합산)
_tls = threading.local()
_rate_lock = threading.Lock()
_last_call = [0.0]


def _session():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
    return _tls.s


def _throttle():
    """모든 스레드 합산으로 호출 간격 MIN_INTERVAL 보장"""
    with _rate_lock:
        wait = _last_call[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
PRD_SE_MAP = {"년": "Y", "연": "Y", "반기": "H", "분기": "Q", "월": "M", "일": "D",
              "격월": "B", "부정기": "IR", "2년": "F", "3년": "F", "5년": "F", "10년": "F"}


class KosisError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"[{code}] {msg}")
        self.code = str(code)


# 전체 호출
def call(url, params, retries=4):
    """KOSIS 호출. jsonVD=Y 로 표준 JSON 수신, 에러코드 처리."""
    p = {"apiKey": API_KEY, "format": "json", "jsonVD": "Y", **params}
    last = None
    for attempt in range(retries):
        try:
            _throttle()
            r = _session().get(url, params=p, timeout=120)
            text = r.text.strip()
            if not text:
                return []
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = ast.literal_eval(text)
            if isinstance(data, dict) and "err" in data:
                code = str(data["err"])
                if code == "30":                     # 조회결과 없음
                    return []
                if code == "40":                     # 분당 호출 제한 → 대기 후 재시도
                    time.sleep(60)
                    continue
                raise KosisError(code, data.get("errMsg", ""))
            return data if isinstance(data, list) else [data]
        except (requests.RequestException, ValueError, SyntaxError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise KosisError("NET", str(last))


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


def match_any(patterns, texts):
    return any(re.search(p, t) for p in patterns for t in texts)


# 내부 목록 탐색
def crawl(list_id, path, rows, seen):
    items = call(URL_LIST, {"method": "getList", "vwCd": VW_CD, "parentListId": list_id})
    for it in items:
        if it.get("TBL_ID"):
            rows.append({
                "category": path[0] if path else "",
                "section": path[1] if len(path) > 1 else "",
                "path": " > ".join(path),
                "depth": len(path),
                "org_id": it.get("ORG_ID"),
                "tbl_id": it.get("TBL_ID"),
                "tbl_nm": it.get("TBL_NM"),
                "stat_id": it.get("STAT_ID"),
                "send_de": it.get("SEND_DE"),
                "rec_tbl": it.get("REC_TBL_SE"),
            })
        elif it.get("LIST_ID") and it["LIST_ID"] not in seen:
            seen.add(it["LIST_ID"])
            print("  " * len(path) + f"📁 {it['LIST_NM']} ({it['LIST_ID']})")
            crawl(it["LIST_ID"], path + [it["LIST_NM"]], rows, seen)


def stage_roots(args):
    """주제별 최상위 목록 출력 → 인구 외 다른 주제를 --root 로 수집할 때 ID 확인용"""
    for pid in ("", VW_CD):
        items = call(URL_LIST, {"method": "getList", "vwCd": VW_CD, "parentListId": pid})
        if items:
            for it in items:
                print(f"{it.get('LIST_ID') or it.get('TBL_ID')}\t{it.get('LIST_NM') or it.get('TBL_NM')}")
            return
    print("최상위 목록을 받지 못했습니다. KOSIS 화면의 주제 폴더 ID를 --root 로 직접 지정하세요.")


def stage_catalog(args):
    rows = []
    print(f"=== 목록 탐색: vwCd={VW_CD}, parentListId={ROOT_LIST_ID} ===")
    crawl(ROOT_LIST_ID, [], rows, set())
    cat = pd.DataFrame(rows)
    segs = cat["path"].str.split(" > ")
    cat["is_sample"] = segs.apply(lambda s: match_any(SAMPLE_PATTERNS, s) or False)
    cat["is_full"] = segs.apply(lambda s: match_any(FULL_PATTERNS, s) or False)
    cat["survey_type"] = cat.apply(
        lambda r: "표본" if r.is_sample else ("전수" if r.is_full else "구분없음(전체집계)"), axis=1)
    cat["selected"] = ~cat["is_sample"]
    cat["related_hint"] = cat["category"].map(RELATED_HINT).fillna("")
    # 같은 표가 여러 조사/폴더에 걸려 있으면 수집은 1번만 하되(대표=첫 비표본 경로),
    # 다른 소속은 also_in 에 남겨 검색 시 어느 조사로 찾아도 걸리게 함
    cat["dup"] = cat.duplicated(["org_id", "tbl_id"])
    paths = (cat[~cat["is_sample"]].groupby(["org_id", "tbl_id"])["path"]
             .apply(lambda x: list(dict.fromkeys(x))))
    cat["also_in"] = cat.apply(
        lambda r: " || ".join(p for p in paths.get((r.org_id, r.tbl_id), []) if p != r.path), axis=1)
    cat.loc[cat["dup"], "selected"] = False

    OUT.mkdir(parents=True, exist_ok=True)
    cat.to_csv(OUT / "catalog.csv", index=False, encoding="utf-8-sig")
    summary = (cat.groupby(["category", "survey_type"]).size().unstack(fill_value=0))
    print("\n=== 조사별 전수/표본 통계표 수 ===")
    print(summary.to_string())
    print(f"\n선택된 표: {cat['selected'].sum()} / 전체 {len(cat)} → {OUT/'catalog.csv'}")


def load_selected(args):
    cat = pd.read_csv(OUT / "catalog.csv", dtype=str)
    cat = cat[cat["selected"] == "True"]
    if args.surveys:
        cat = cat[cat["category"].isin(args.surveys)]
    if getattr(args, "tables", None):
        ids = []
        for t in args.tables:               # '@파일' 이면 파일의 줄 단위 tbl_id 목록
            ids += [x.strip() for x in Path(t[1:]).read_text(encoding="utf-8").split()] if t.startswith("@") else [t]
        cat = cat[cat["tbl_id"].isin(ids)]
    if args.max_tables:
        cat = cat.head(args.max_tables)
    return cat


def stage_status(args):
    """조사별 진행 현황: 목록 → 선택 → 메타 → 수집완료 / 대용량건너뜀 / 실패"""
    cat = pd.read_csv(OUT / "catalog.csv", dtype=str)
    sel = cat[cat["selected"] == "True"].copy()
    sel["meta"] = sel.apply(lambda r: meta_path(r.org_id, r.tbl_id).exists(), axis=1)
    sel["done"] = sel.apply(lambda r: (OUT / "raw" / safe(r.category) / f"{r.org_id}_{r.tbl_id}.csv").exists(),
                            axis=1)
    sk = OUT / "skipped_large.csv"
    sk_ids = set(pd.read_csv(sk, dtype=str)["tbl_id"]) if sk.exists() else set()
    fl = OUT / "failed.csv"
    fl_ids = set(pd.read_csv(fl, dtype=str)["tbl_id"]) if fl.exists() else set()
    sel["skipped"] = sel["tbl_id"].isin(sk_ids) & ~sel["done"]
    sel["failed"] = sel["tbl_id"].isin(fl_ids) & ~sel["done"]
    allc = cat.groupby("category").agg(전체=("tbl_id", "size"),
                                       표본제외=("is_sample", lambda x: (x == "True").sum()),
                                       중복=("dup", lambda x: (x == "True").sum()))
    st = sel.groupby("category").agg(선택=("tbl_id", "size"), 메타=("meta", "sum"), 완료=("done", "sum"),
                                     대용량건너뜀=("skipped", "sum"), 실패=("failed", "sum"))
    rep = allc.join(st, how="left").fillna(0).astype(int)
    rep["남음"] = rep["선택"] - rep["완료"]
    rep.loc["합계"] = rep.sum()
    print(rep.to_string())
    rep.to_csv(OUT / "status.csv", encoding="utf-8-sig")
    zero = rep[(rep["선택"] == 0) & (rep.index != "합계")]
    if len(zero):
        print("\n선택된 표가 0개인 조사 (전부 표본이거나 다른 조사와 중복):")
        for c in zero.index:
            d = cat[cat["category"] == c]
            n_s, n_d = (d["is_sample"] == "True").sum(), (d["dup"] == "True").sum()
            why = []
            if n_s:
                why.append(f"표본 {n_s}개는 제외 규칙에 해당 (SAMPLE_PATTERNS 확인)")
            if n_d:
                why.append(f"중복 {n_d}개는 다른 조사 폴더에 저장되고 also_in 에 '{c}'로 기록됨")
            print(f"  - {c}: " + " / ".join(why))


# 메타 , 스키마 데이터용
def get_meta(org, tbl, typ):
    try:
        return call(URL_META, {"method": "getMeta", "type": typ, "orgId": org, "tblId": tbl})
    except KosisError as e:
        return [{"_error": str(e)}]


def parse_itm(itm_rows):
    """ITM 메타 → (분류 레벨 리스트, 항목 리스트). OBJ_ID == 'ITEM' 이 항목."""
    levels, items = {}, []
    for r in itm_rows:
        if "_error" in r:
            continue
        if r.get("OBJ_ID") == "ITEM":
            items.append({"id": r["ITM_ID"], "nm": r.get("ITM_NM"), "unit": r.get("UNIT_NM")})
            continue
        key = r.get("OBJ_ID")
        if key not in levels:
            levels[key] = {"obj_id": key, "obj_nm": r.get("OBJ_NM"),
                           "sn": int(r.get("OBJ_ID_SN") or len(levels) + 1), "codes": []}
        levels[key]["codes"].append({"id": r["ITM_ID"], "nm": r.get("ITM_NM"),
                                     "up": r.get("UP_ITM_ID")})
    ordered = sorted(levels.values(), key=lambda x: x["sn"])
    return ordered, items


def expand_range(se, start, end):
    """시작~종료 시점 → 시점 목록. KOSIS 코드: Y=YYYY, M=YYYYMM, Q=YYYYQQ(01~04), H=YYYYHH(01~02)."""
    start, end = str(start).strip(), str(end).strip()
    sy, ey = int(start[:4]), int(end[:4])
    per_year = {"M": 12, "Q": 4, "H": 2}.get(se)
    if per_year is None:                       # Y, F(다년), IR 등 → 연 단위로 생성 (없는 해는 빈 결과)
        return [str(y) for y in range(sy, ey + 1)]
    s_sub = int(start[4:6] or 1)
    e_sub = int(end[4:6] or per_year)
    out = []
    for y in range(sy, ey + 1):
        for p in range(1, per_year + 1):
            if (y, p) < (sy, s_sub) or (y, p) > (ey, e_sub):
                continue
            out.append(f"{y}{p:02d}")
    return out


def parse_prd(prd_rows):
    """PRD 메타 → {prdSe코드: [시점...]}
    응답 형식 2가지 모두 처리: ① PRD_DE 개별 시점  ② STRT_PRD_DE ~ END_PRD_DE 범위"""
    out = {}
    for r in prd_rows or []:
        if not isinstance(r, dict) or "_error" in r:
            continue
        se = str(r.get("PRD_SE", "")).strip()
        se = PRD_SE_MAP.get(se, se)
        if not se:
            continue
        if r.get("PRD_DE"):
            out.setdefault(se, []).append(str(r["PRD_DE"]))
        start = r.get("STRT_PRD_DE") or r.get("START_PRD_DE")
        end = r.get("END_PRD_DE")
        if start and end:
            try:
                out.setdefault(se, []).extend(expand_range(se, start, end))
            except ValueError:
                pass
    return {k: sorted(set(v)) for k, v in out.items() if v}


def meta_path(org, tbl):
    return OUT / "meta" / f"{org}_{tbl}.json"


def stage_schema(args):
    cat = load_selected(args)
    (OUT / "meta").mkdir(parents=True, exist_ok=True)
    rows = []
    ######## 추가 코드##########
    _pbar = tqdm(total=len(cat), desc="schema", unit="표")
    ######## 추가 코드##########
    for i, r in enumerate(cat.itertuples(), 1):
        ######## 추가 코드##########
        _pbar.n = i - 1
        _pbar.set_postfix_str(str(r.tbl_nm)[:30])
        _pbar.refresh()
        ######## 추가 코드##########
        mp = meta_path(r.org_id, r.tbl_id)
        if mp.exists():
            meta = json.loads(mp.read_text(encoding="utf-8"))
        else:
            meta = {t: get_meta(r.org_id, r.tbl_id, t) for t in ("TBL", "ITM", "PRD", "CMMT", "SOURCE")}
            mp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        levels, items = parse_itm(meta["ITM"])
        prds = parse_prd(meta["PRD"])
        n_per_prd = max(1, len(items)) * math.prod(len(l["codes"]) for l in levels) if levels else len(items)
        n_prd = sum(len(v) for v in prds.values())
        rows.append({
            "category": r.category, "section": r.section, "path": r.path,
            "org_id": r.org_id, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm,
            "survey_type": r.survey_type,
            "dimensions": " | ".join(f"objL{k+1}:{l['obj_nm']}({len(l['codes'])})" for k, l in enumerate(levels)),
            "items": " | ".join(f"{it['nm']}[{it['unit']}]" for it in items[:30]),
            "n_items": len(items),
            "prd_se": ",".join(prds.keys()),
            "prd_range": ";".join(f"{k}:{v[0]}~{v[-1]}({len(v)})" for k, v in prds.items() if v),
            "est_cells_per_period": n_per_prd,
            "est_cells_total": n_per_prd * n_prd,
        })
        print(f"[{i}/{len(cat)}] {r.tbl_nm[:40]:40s} {rows[-1]['dimensions'][:60]}")
    ######## 추가 코드##########
    _pbar.n = _pbar.total
    _pbar.refresh()
    _pbar.close()
    ######## 추가 코드##########
    sch = pd.DataFrame(rows)
    sch.to_csv(OUT / "table_schema.csv", index=False, encoding="utf-8-sig")
    print(f"\n스키마 저장 → {OUT/'table_schema.csv'}")
    print(sch.groupby(["category", "section"])["est_cells_total"].agg(["count", "sum"]).to_string())


# ─────────────────────────────── 3) 데이터 수집 ───────────────────────────────
def chunks(lst, k):
    for i in range(0, len(lst), k):
        yield lst[i:i + k]


MAX_CODES_PER_CALL = 100   # '+'로 묶을 코드 수 상한 (URL 길이 보호)


def split_levels(levels, n_items, fixed):
    """셀 수가 한도 이하가 될 때까지 가장 큰 분류를 코드 묶음('11+21+...')으로 쪼갬.
    fixed[i] = None 은 ALL, 문자열이면 해당 코드(묶음)만 선택."""
    def size(i):
        return len(fixed[i].split("+")) if fixed[i] else len(levels[i]["codes"])

    est = n_items * math.prod(size(i) for i in range(len(levels)))
    free = [i for i, f in enumerate(fixed) if f is None and len(levels[i]["codes"]) > 1]
    if est <= CELL_LIMIT or not free:
        yield list(fixed)
        return
    i = max(free, key=lambda j: len(levels[j]["codes"]))   # 가장 큰 분류부터 분할
    rest = est // len(levels[i]["codes"])                 # 이 분류 코드 1개당 셀 수
    k = max(1, min(MAX_CODES_PER_CALL, CELL_LIMIT // max(1, rest)))
    for grp in chunks([c["id"] for c in levels[i]["codes"]], k):
        f2 = list(fixed)
        f2[i] = "+".join(grp)
        yield from split_levels(levels, n_items, f2)


def plan(levels, items, periods):
    n_items = max(1, len(items))
    per_prd = n_items * math.prod(len(l["codes"]) for l in levels)
    if per_prd <= CELL_LIMIT:
        k = max(1, CELL_LIMIT // per_prd)
        for ch in chunks(periods, k):
            yield [None] * len(levels), ch[0], ch[-1]
    else:
        for p in periods:
            for sel in split_levels(levels, n_items, [None] * len(levels)):
                yield sel, p, p


# 응답 필드 축소 (영문명 등 제외) → 응답 크기·서버 처리시간 감소. --slim 일 때만 사용
SLIM_FIELDS = "ORG_ID TBL_ID TBL_NM OBJ_ID OBJ_NM NM ITM_ID ITM_NM UNIT_NM PRD_SE PRD_DE LST_CHN_DE"
SLIM = {"on": False}


def fetch(org, tbl, prd_se, sel, start, end):
    params = {"method": "getList", "orgId": org, "tblId": tbl, "itmId": "ALL",
              "prdSe": prd_se, "startPrdDe": start, "endPrdDe": end}
    for k in range(8):
        params[f"objL{k+1}"] = (sel[k] or "ALL") if k < len(sel) else ""
    if SLIM["on"]:
        params["outputFields"] = SLIM_FIELDS
    return call(URL_DATA, params)


def check_slim(org, tbl, prd_se, levels, period):
    """outputFields 적용 응답에 필수 컬럼이 다 오는지 1회 확인, 아니면 자동 해제"""
    sel = [l["codes"][0]["id"] for l in levels]
    try:
        d = fetch(org, tbl, prd_se, sel, period, period)
    except KosisError as e:
        d, msg = [], str(e)
    need = {"DT", "PRD_DE", "ITM_NM", "C1_NM"}
    if d and need <= set(d[0]):
        print("  ✓ --slim 응답 확인: 필드 축소 사용", flush=True)
        return
    SLIM["on"] = False
    print(f"  ! --slim 응답에 필수 컬럼 없음 → 전체 필드로 진행 (받은 컬럼: {list(d[0]) if d else '없음'})",
          flush=True)


def fetch_part(part_dir, org, tbl, prd_se, sel, start, end):
    """요청 1건 결과를 조각 파일로 저장 → 중단 후 재실행 시 받은 조각은 건너뜀"""
    key = hashlib.md5(f"{prd_se}|{sel}|{start}|{end}".encode()).hexdigest()[:16]
    fp = part_dir / f"{key}.csv"
    if fp.exists():
        return pd.read_csv(fp, dtype=str) if fp.stat().st_size > 3 else None
    data = fetch(org, tbl, prd_se, sel, start, end)
    part_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(data)
    if len(df):
        df = df[[c for c in KEEP_COLS if c in df.columns]]
    df.to_csv(fp, index=False, encoding="utf-8-sig")
    return df


def real_periods(org, tbl, prd_se, levels, items, periods):
    """범위로 생성한 시점 중 실제 자료가 있는 시점만 남김.
    (예: 5년 주기 총조사를 매년으로 펼치면 큰 표에서 빈 요청이 4/5를 차지)
    각 분류의 첫 코드만 골라 전체 기간을 1회 조회 → 셀 수가 작아 빠름."""
    n_items = max(1, len(items))
    per_prd = n_items * math.prod(len(l["codes"]) for l in levels)
    if per_prd <= CELL_LIMIT or len(periods) <= 1:      # 작은 표는 범위 요청이라 낭비 없음
        return periods
    sel = [l["codes"][0]["id"] for l in levels]
    try:
        data = fetch(org, tbl, prd_se, sel, periods[0], periods[-1])
    except KosisError:
        return periods
    found = sorted({str(d.get("PRD_DE")) for d in data if d.get("PRD_DE")})
    return found or periods


KEEP_COLS = (["ORG_ID", "TBL_ID", "TBL_NM"]
             + [f"C{i}{s}" for i in range(1, 9) for s in ("", "_OBJ_NM", "_NM")]
             + ["ITM_ID", "ITM_NM", "UNIT_NM", "PRD_SE", "PRD_DE", "DT", "LST_CHN_DE"])


def stage_download(args):
    cat = load_selected(args)
    if args.exclude:
        mask = cat["tbl_nm"].str.contains(args.exclude, regex=True, na=False)
        print(f"--exclude '{args.exclude}' → {mask.sum()}개 표 제외")
        cat = cat[~mask]
    SLIM["on"] = args.slim
    slim_checked = False
    sch = {}
    if args.max_cells and (OUT / "table_schema.csv").exists():
        s_df = pd.read_csv(OUT / "table_schema.csv", dtype={"tbl_id": str})
        sch = dict(zip(s_df["tbl_id"], s_df["est_cells_total"]))
    fails, skipped = [], []
    ######## 추가 코드##########
    _pbar = tqdm(total=len(cat), desc="download", unit="표")
    ######## 추가 코드##########
    for i, r in enumerate(cat.itertuples(), 1):
        ######## 추가 코드##########
        _pbar.n = i - 1                   # continue 로 건너뛰어도 완료 수가 맞도록 시작 시점에 갱신
        _pbar.set_postfix_str(str(r.tbl_nm)[:30])
        _pbar.refresh()
        ######## 추가 코드##########
        out = OUT / "raw" / safe(r.category) / f"{r.org_id}_{r.tbl_id}.csv"
        if out.exists() and getattr(args, "refresh", False):     # 최신 자료로 다시 받기
            out.unlink()
            shutil.rmtree(OUT / "parts" / f"{r.org_id}_{r.tbl_id}", ignore_errors=True)
            meta0 = {t: get_meta(r.org_id, r.tbl_id, t) for t in ("TBL", "ITM", "PRD", "CMMT", "SOURCE")}
            meta_path(r.org_id, r.tbl_id).parent.mkdir(parents=True, exist_ok=True)
            meta_path(r.org_id, r.tbl_id).write_text(json.dumps(meta0, ensure_ascii=False), encoding="utf-8")
        if out.exists():
            continue
        est = sch.get(r.tbl_id)
        if args.max_cells and est and est > args.max_cells:
            skipped.append({"category": r.category, "org_id": r.org_id, "tbl_id": r.tbl_id,
                            "tbl_nm": r.tbl_nm, "est_cells_total": est})
            print(f"[{i}/{len(cat)}] 건너뜀(예상 {est:,.0f}셀 > {args.max_cells:,}): {r.tbl_nm}")
            continue
        mp = meta_path(r.org_id, r.tbl_id)
        if not mp.exists():
            print(f"  메타 없음 → 먼저 schema 실행: {r.tbl_id}")
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        levels, items = parse_itm(meta["ITM"])
        prds = parse_prd(meta["PRD"])
        if not levels or not prds:
            reason = ("분류(ITM) 없음 " if not levels else "") + ("시점(PRD) 없음 " if not prds else "")
            fails.append({"tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm, "reason": "메타 파싱 실패: " + reason,
                          "raw_prd": json.dumps(meta.get("PRD"), ensure_ascii=False)[:300]})
            print(f"  ✗ {r.tbl_nm}: {reason}| PRD 원본: {str(meta.get('PRD'))[:200]}")
            continue
        if SLIM["on"] and not slim_checked:
            se0, p0 = next(iter(prds.items()))
            check_slim(r.org_id, r.tbl_id, se0, levels, p0[-1])
            slim_checked = True
        t0 = time.time()
        part_dir = OUT / "parts" / f"{r.org_id}_{r.tbl_id}"
        tasks = []
        for prd_se, periods in prds.items():
            periods = real_periods(r.org_id, r.tbl_id, prd_se, levels, items, periods)
            if args.recent:
                periods = periods[-args.recent:]
            tasks += [(prd_se, sel, s, e) for sel, s, e in plan(levels, items, periods)]
        print(f"[{i}/{len(cat)}] {r.category} | {r.tbl_nm} — 요청 {len(tasks)}건", flush=True)

        frames, tbl_fails = [], []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_part, part_dir, r.org_id, r.tbl_id, *t): t for t in tasks}
            ######## 추가 코드##########
            _sub = tqdm(total=len(tasks), desc="  요청", unit="건", leave=False, position=1)
            ######## 추가 코드##########
            for n, fu in enumerate(as_completed(futs), 1):
                ######## 추가 코드##########
                _sub.update(1)
                ######## 추가 코드##########
                prd_se, sel, s, e = futs[fu]
                try:
                    df_part = fu.result()
                    if df_part is not None and len(df_part):
                        frames.append(df_part)
                except KosisError as err:
                    tbl_fails.append({"tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm, "prd": f"{s}-{e}",
                                      "sel": str(sel)[:200], "reason": str(err)})
                if len(tasks) >= 20 and n % 20 == 0:
                    print(f"    {n}/{len(tasks)} ({time.time() - t0:.0f}s)", flush=True)
            ######## 추가 코드##########
            _sub.close()
            ######## 추가 코드##########
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df = df[[c for c in KEEP_COLS if c in df.columns]].drop_duplicates()
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"    → {len(df):,} rows, {time.time() - t0:.0f}s", flush=True)
            if not tbl_fails:
                shutil.rmtree(part_dir, ignore_errors=True)   # 완료된 표의 조각 삭제
        if tbl_fails:                       # 표 단위로 즉시 기록 (중단돼도 남도록)
            fails += tbl_fails
            fp = OUT / "failed.csv"
            pd.DataFrame(tbl_fails).to_csv(fp, mode="a", header=not fp.exists(), index=False,
                                           encoding="utf-8-sig")
    ######## 추가 코드##########
    _pbar.n = _pbar.total
    _pbar.refresh()
    _pbar.close()
    ######## 추가 코드##########
    if skipped:
        pd.DataFrame(skipped).to_csv(OUT / "skipped_large.csv", index=False, encoding="utf-8-sig")
        print(f"대용량으로 건너뛴 표 {len(skipped)}개 → {OUT / 'skipped_large.csv'}")
    if fails:
        print(f"실패 {len(fails)}건 → {OUT / 'failed.csv'}")


# ─────────────────────────────── 4) 병합 + RAG 문서 ───────────────────────────────
def fmt_value(dt, unit):
    if dt is None or (isinstance(dt, float) and math.isnan(dt)) or str(dt).strip() in ("", "-"):
        return "자료없음"
    s = str(dt).replace(",", "")
    try:
        v = float(s)
        s = f"{int(v):,}" if v.is_integer() else f"{v:,.2f}"
    except ValueError:
        pass
    return f"{s}{(' ' + unit) if unit and str(unit) != 'nan' else ''}"


def flatten(rows, skip=("_error",)):
    parts = []
    for r in rows or []:
        for k, v in r.items():
            if k in skip or v in (None, "", "nan"):
                continue
            parts.append(f"{k}: {v}")
    return "; ".join(parts)


def survey_docs(cat):
    """통계설명(statisticsExplData)으로 조사 개요 문서 생성 — 용어/기준 질문 대응용."""
    docs = []
    for (category, stat_id), _ in cat.groupby(["category", "stat_id"], dropna=True):
        try:
            rows = call(URL_EXPL, {"method": "getList", "statId": stat_id, "metaItm": "All"})
        except KosisError:
            continue
        text = flatten(rows)
        if text:
            docs.append({"doc_id": f"survey::{stat_id}", "doc_type": "survey_overview",
                         "category": category, "text": f"[{category} 조사 설명]\n{text}"})
    return docs


def table_doc(r, meta):
    levels, items = parse_itm(meta["ITM"])
    prds = parse_prd(meta["PRD"])
    dims = []
    for l in levels:
        sample = ", ".join(c["nm"] for c in l["codes"][:15])
        more = f" 외 {len(l['codes']) - 15}개" if len(l["codes"]) > 15 else ""
        dims.append(f"- {l['obj_nm']} ({len(l['codes'])}개): {sample}{more}")
    item_txt = ", ".join("{}({})".format(it["nm"], it["unit"]) for it in items)
    prd_txt = "; ".join("{} {}~{}".format(k, v[0], v[-1]) for k, v in prds.items() if v)
    text = (
        f"[통계표] {r.tbl_nm} ({r.org_id}/{r.tbl_id})\n"
        f"분류경로: {r.path}\n"
        + (f"함께 수록된 조사: {r.also_in}\n" if str(getattr(r, "also_in", "nan")) != "nan" and r.also_in else "")
        + f"조사구분: {r.survey_type}\n"
        f"분류축:\n" + "\n".join(dims) + "\n"
        f"항목: {item_txt}\n"
        f"수록기간: {prd_txt}\n"
        f"주석: {flatten(meta.get('CMMT'))[:1500]}\n"
        f"출처: {flatten(meta.get('SOURCE'))[:300]}"
    )
    return {"doc_id": f"table::{r.org_id}_{r.tbl_id}", "doc_type": "table_card",
            "category": r.category, "section": r.section, "path": r.path,
            "org_id": r.org_id, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm, "text": text}


def data_docs(r, df, max_lines):
    """(시점, 1번째 분류값) 단위로 행을 묶어 자연어 문장 청크로 변환."""
    docs = []
    name_cols = [f"C{i}_NM" for i in range(2, 9) if f"C{i}_NM" in df.columns]
    obj1 = df["C1_OBJ_NM"].iloc[0] if "C1_OBJ_NM" in df.columns else "분류"
    group_cols = [c for c in ("PRD_DE", "C1_NM") if c in df.columns]
    for keys, g in df.groupby(group_cols, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        prd, c1 = (list(keys) + [""])[:2]
        lines = []
        for row in g.itertuples(index=False):
            d = row._asdict()
            sub = " ".join(str(d[c]) for c in name_cols if d.get(c) and str(d[c]) != "nan")
            lines.append(f"- {sub + ' | ' if sub else ''}{d.get('ITM_NM')}: "
                         f"{fmt_value(d.get('DT'), d.get('UNIT_NM'))}")
        for part, ch in enumerate(chunks(lines, max_lines)):
            header = (f"[{r.category} > {r.section}] {r.tbl_nm}\n"
                      f"시점: {prd} / {obj1}: {c1}\n")
            docs.append({"doc_id": f"data::{r.tbl_id}::{prd}::{c1}::{part}", "doc_type": "data_chunk",
                         "category": r.category, "section": r.section, "path": r.path,
                         "org_id": r.org_id, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm,
                         "prd_de": prd, "c1_nm": c1, "text": header + "\n".join(ch)})
    return docs


def stage_build(args):
    cat = load_selected(args)
    (OUT / "merged").mkdir(parents=True, exist_ok=True)
    (OUT / "rag").mkdir(parents=True, exist_ok=True)
    rag_csv, rag_jsonl = OUT / "rag" / "rag_documents.csv", OUT / "rag" / "rag_documents.jsonl"
    for p in (rag_csv, rag_jsonl):
        p.unlink(missing_ok=True)

    def emit(docs):
        if not docs:
            return
        d = pd.DataFrame(docs)
        d.to_csv(rag_csv, mode="a", header=not rag_csv.exists(), index=False, encoding="utf-8-sig")
        with rag_jsonl.open("a", encoding="utf-8") as f:
            for doc in docs:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    emit(survey_docs(cat))
    ######## 추가 코드##########
    _pbar = tqdm(total=len(cat), desc="build", unit="표")
    _done = 0
    ######## 추가 코드##########
    for category, sub in cat.groupby("category"):
        merged = OUT / "merged" / f"{safe(category)}.csv"
        merged.unlink(missing_ok=True)
        n_rows = 0
        for r in sub.itertuples():
            ######## 추가 코드##########
            _pbar.n = _done
            _done += 1
            _pbar.set_postfix_str(str(category)[:20])
            _pbar.refresh()
            ######## 추가 코드##########
            raw = OUT / "raw" / safe(category) / f"{r.org_id}_{r.tbl_id}.csv"
            mp = meta_path(r.org_id, r.tbl_id)
            if mp.exists():
                emit([table_doc(r, json.loads(mp.read_text(encoding="utf-8")))])
            if not raw.exists():
                continue
            df = pd.read_csv(raw, dtype=str)
            # 표준화된 병합 컬럼
            df.insert(0, "category", category)
            df.insert(1, "section", r.section)
            df.insert(2, "path", r.path)
            df.insert(3, "survey_type", r.survey_type)
            df["VALUE"] = pd.to_numeric(df["DT"].str.replace(",", ""), errors="coerce")
            df = df.reindex(columns=["category", "section", "path", "survey_type"] + KEEP_COLS + ["VALUE"])
            df.to_csv(merged, mode="a", header=not merged.exists(), index=False, encoding="utf-8-sig")
            n_rows += len(df)
            if not args.no_data_docs:
                emit(data_docs(r, df, args.chunk_lines))
        print(f"{category}: {n_rows:,} rows → {merged}")
    ######## 추가 코드##########
    _pbar.n = _pbar.total
    _pbar.refresh()
    _pbar.close()
    ######## 추가 코드##########
    print(f"RAG 문서 → {rag_csv} / {rag_jsonl}")



# ─────────────────────────────── 5) 에이전트용 저장소 ───────────────────────────────
TOTAL_NAMES = re.compile(r"^(계|합계|총계|소계|전체|전국|총인구|총수|Total|전 ?연령)$")


def dim_rows(tbl_key, levels):
    """분류 코드 사전: 코드·이름·상위코드·깊이·합계여부 (차트/집계 시 이중합산 방지용)"""
    rows = []
    for k, l in enumerate(levels, 1):
        parent = {c["id"]: c.get("up") for c in l["codes"]}

        def depth(cid, seen=()):
            up = parent.get(cid)
            return 0 if not up or up not in parent or cid in seen else 1 + depth(up, seen + (cid,))
        has_child = {c.get("up") for c in l["codes"] if c.get("up")}
        for c in l["codes"]:
            rows.append({"table_key": tbl_key, "level": k, "obj_id": l["obj_id"], "obj_nm": l["obj_nm"],
                         "code": c["id"], "name": c["nm"], "parent_code": c.get("up") or "",
                         "depth": depth(c["id"]), "has_children": c["id"] in has_child,
                         "is_total": bool(TOTAL_NAMES.match(str(c["nm"]).strip()))})
    return rows


def chart_hint(levels, prds):
    n_prd = sum(len(v) for v in prds.values())
    hints = []
    if n_prd > 2:
        hints.append("시계열(line): 시점 축")
    if any(len(l["codes"]) > 1 for l in levels):
        hints.append("범주 비교(bar): " + ", ".join(l["obj_nm"] for l in levels if len(l["codes"]) > 1))
    if any(any(TOTAL_NAMES.match(str(c["nm"]).strip()) for c in l["codes"]) for l in levels):
        hints.append("구성비(stacked bar/pie): 합계 행 제외 후 하위 항목")
    return " / ".join(hints)


def tidy(df, tbl_key):
    out = pd.DataFrame({"table_key": tbl_key, "prd_se": df.get("PRD_SE"), "prd_de": df.get("PRD_DE")})
    for i in range(1, 9):
        if f"C{i}" in df.columns:
            out[f"c{i}_code"] = df[f"C{i}"]
            out[f"c{i}_name"] = df.get(f"C{i}_NM")
    out["itm_id"], out["itm_nm"], out["unit"] = df.get("ITM_ID"), df.get("ITM_NM"), df.get("UNIT_NM")
    out["value_raw"] = df["DT"]
    out["value"] = pd.to_numeric(df["DT"].astype(str).str.replace(",", ""), errors="coerce")
    return out


def save_table(df, path):
    try:
        df.to_parquet(path.with_suffix(".parquet"), index=False)
        return path.with_suffix(".parquet")
    except ImportError:
        p = path.with_suffix(".csv.gz")
        df.to_csv(p, index=False, compression="gzip", encoding="utf-8")
        return p


def stage_store(args):
    """에이전트용 구조화 저장소
    store/tables.csv      표 1개 = 1행 (검색·선택용 카드 + 차트 힌트)
    store/dimensions.csv  표별 분류 코드 사전 (계층·합계 여부)
    store/data/*.parquet  표별 tidy 수치 (표마다 컬럼 의미가 다르므로 표 단위로 분리 저장)
    store/kosis.duckdb    (duckdb 설치 시) facts 뷰로 전체 SQL 조회
    """
    cat = load_selected(args)
    st = OUT / "store"
    (st / "data").mkdir(parents=True, exist_ok=True)
    tables, dims = [], []
    ######## 추가 코드##########
    _pbar = tqdm(total=len(cat), desc="store", unit="표")
    ######## 추가 코드##########
    for i, r in enumerate(cat.itertuples(), 1):
        ######## 추가 코드##########
        _pbar.n = i - 1
        _pbar.set_postfix_str(str(r.tbl_nm)[:30])
        _pbar.refresh()
        ######## 추가 코드##########
        key = f"{r.org_id}_{r.tbl_id}"
        mp = meta_path(r.org_id, r.tbl_id)
        if not mp.exists():
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        levels, items = parse_itm(meta["ITM"])
        prds = parse_prd(meta["PRD"])
        dims += dim_rows(key, levels)
        raw = OUT / "raw" / safe(r.category) / f"{key}.csv"
        n_rows, data_path, real_prd = 0, "", ""
        if raw.exists():
            t = tidy(pd.read_csv(raw, dtype=str), key)
            n_rows = len(t)
            data_path = str(save_table(t, st / "data" / key).relative_to(st))
            ps = sorted(t["prd_de"].dropna().unique())
            real_prd = f"{ps[0]}~{ps[-1]} ({len(ps)}개 시점)" if ps else ""
        also = getattr(r, "also_in", "")
        also = "" if str(also) == "nan" else also
        tables.append({
            "table_key": key, "org_id": r.org_id, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm,
            "category": r.category, "section": r.section, "path": r.path, "also_in": also,
            "survey_type": r.survey_type,
            "dimensions": " | ".join(f"c{k}={l['obj_nm']}({len(l['codes'])})" for k, l in enumerate(levels, 1)),
            "items": " | ".join(f"{it['nm']}[{it['unit']}]" for it in items[:40]),
            "units": ", ".join(sorted({str(it["unit"]) for it in items if it.get("unit")})),
            "periods_meta": "; ".join(f"{k}:{v[0]}~{v[-1]}" for k, v in prds.items() if v),
            "periods_data": real_prd, "n_rows": n_rows, "data_path": data_path,
            "chart_hint": chart_hint(levels, prds),
            "note": flatten(meta.get("CMMT"))[:800],
        })
        if i % 100 == 0:
            print(f"  {i}/{len(cat)}", flush=True)
    ######## 추가 코드##########
    _pbar.n = _pbar.total
    _pbar.refresh()
    _pbar.close()
    ######## 추가 코드##########
    tb = pd.DataFrame(tables)
    tb.to_csv(st / "tables.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(dims).to_csv(st / "dimensions.csv", index=False, encoding="utf-8-sig")
    print(f"표 {len(tb)}개 (수치 있음 {int((tb['n_rows'] > 0).sum())}) → {st}")
    try:
        import duckdb
        con = duckdb.connect(str(st / "kosis.duckdb"))
        con.execute(f"CREATE OR REPLACE TABLE tables AS SELECT * FROM read_csv_auto('{(st / 'tables.csv').as_posix()}')")
        con.execute(f"CREATE OR REPLACE TABLE dimensions AS SELECT * FROM read_csv_auto('{(st / 'dimensions.csv').as_posix()}')")
        if list((st / "data").glob("*.parquet")):
            con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{(st / 'data').as_posix()}/*.parquet', union_by_name=true)")
        con.close()
        print(f"DuckDB → {st / 'kosis.duckdb'}")
    except ImportError:
        print("(duckdb 미설치: pip install duckdb pyarrow 하면 SQL 저장소도 생성)")


# ─────────────────────────────── main ───────────────────────────────
def main():
    if not API_KEY:
        raise ValueError(".env 파일에서 KOSIS_API_KEY를 찾을 수 없습니다.")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["roots", "catalog", "schema", "download", "status", "build", "store", "all"])
    ap.add_argument("--root", default=None, help="수집할 주제 목록 ID (기본 A=인구). roots 단계로 확인")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 kosis_data, 다른 주제는 별도 폴더 권장)")
    ap.add_argument("--surveys", nargs="*", help="수집할 조사명 (catalog의 category 값)")
    ap.add_argument("--tables", nargs="*", help="tbl_id 지정. '@refresh_tables.txt' 처럼 파일도 가능")
    ap.add_argument("--refresh", action="store_true", help="download: 지정 표의 기존 raw·메타를 지우고 다시 받기")
    ap.add_argument("--max-tables", type=int, default=None)
    ap.add_argument("--recent", type=int, default=None, help="표마다 최근 N개 시점만")
    ap.add_argument("--workers", type=int, default=WORKERS, help="동시 요청 수")
    ap.add_argument("--slim", action="store_true", help="outputFields로 응답 필드 축소 (자동 검증)")
    ap.add_argument("--exclude", default=None, help="표 이름 정규식으로 제외 (예: '읍면동')")
    ap.add_argument("--max-cells", type=int, default=None,
                    help="예상 셀 수가 이보다 큰 표는 건너뛰고 skipped_large.csv에 기록")
    ap.add_argument("--chunk-lines", type=int, default=60, help="RAG 데이터 청크당 최대 줄 수")
    ap.add_argument("--no-data-docs", action="store_true", help="수치 청크 없이 표 카드/조사설명만 생성")
    args = ap.parse_args()
    if args.refresh and args.recent:
        ap.error("--refresh 와 --recent 를 함께 쓰면 기존 과거 시점 데이터가 지워집니다. 둘 중 하나만 쓰세요.")
    if args.refresh and not args.tables:
        ap.error("--refresh 는 --tables 로 대상 표를 지정할 때만 쓸 수 있습니다.")
    global ROOT_LIST_ID, OUT
    if args.root:
        ROOT_LIST_ID = args.root
    if args.out:
        OUT = Path(args.out)

    if args.stage == "roots":
        stage_roots(args)
    if args.stage in ("catalog", "all"):
        stage_catalog(args)
    if args.stage in ("schema", "all"):
        stage_schema(args)
    if args.stage in ("download", "all"):
        stage_download(args)
    if args.stage == "status":
        stage_status(args)
    if args.stage in ("build", "all"):
        stage_build(args)
    if args.stage in ("store", "all"):
        stage_store(args)


if __name__ == "__main__":
    main()
