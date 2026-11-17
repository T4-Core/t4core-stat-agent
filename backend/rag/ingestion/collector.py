"""
KOSIS OpenAPI 수집 — 주제(기본: 인구) → (표본 제외) 전수부문 통계표의 메타·수치 원본

  python -m backend.rag.ingestion.collector catalog    # 1) 목록 트리 탐색 → catalog.csv (전수/표본 판별)
  python -m backend.rag.ingestion.collector schema     # 2) 선택된 표의 메타(분류·항목·시점·주석) → meta/*.json, table_schema.csv
  python -m backend.rag.ingestion.collector download   # 3) 수치 → raw/<조사>/<기관>_<표>.csv (4만 셀 제한 자동 분할, 이어받기)
  python -m backend.rag.ingestion.collector status     #    조사별 진행 현황 → status.csv
  python -m backend.rag.ingestion.collector all        #    1~3
  python -m backend.rag.ingestion.collector roots      #    주제별 최상위 목록 ID

여러 주제 폴더를 한 catalog 로 (2015년 이후 주택총조사 표는 '주거' 주제 아래에 있음)
  … catalog --root 인구 주거:주택총조사         # 루트는 ID(A) 또는 이름, ':정규식' 은 그 루트의 1단계 폴더 필터
  … catalog --root 주거:주택총조사 --append      # 기존 catalog.csv 에 추가만

옵션: --surveys 인구총조사 …(특정 조사) · --max-tables 20 · --recent 5(최근 N개 시점) · --max-cells N(큰 표 건너뜀)
.env: KOSIS_API_KEY
"""
import argparse
import ast
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from backend.core.config import KOSIS_DATA_DIR

API_KEY = os.getenv("KOSIS_API_KEY")

BASE = "https://kosis.kr/openapi"
URL_LIST = f"{BASE}/statisticsList.do"  # 통계목록
URL_META = f"{BASE}/statisticsData.do"  # 메타자료 (method=getMeta)
URL_DATA = f"{BASE}/Param/statisticsParameterData.do"  # 통계자료 (통계표선택 방식)
URL_EXPL = f"{BASE}/statisticsExplData.do"  # 통계설명

VW_CD = "MT_ZTITLE"  # 국내통계 > 주제별
ROOT_LIST_ID = "A"  # 주제별 > 인구  (catalog 실행 시 루트 이름을 출력해 확인)
OUT = KOSIS_DATA_DIR

CELL_LIMIT = 40_000  # 매뉴얼: 요청당 4만 셀 이하
SLEEP = 0.35  # 매뉴얼: 분당 200건 제한 → 호출 간 간격

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


WORKERS = 4  # 동시 요청 수 (서버 응답 대기 시간을 겹쳐서 활용)
MIN_INTERVAL = 60 / 180  # 분당 200건 제한보다 약간 낮게 (전체 스레드 합산)
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
                if code == "30":  # 조회결과 없음
                    return []
                if code == "40":  # 분당 호출 제한 → 대기 후 재시도
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
def crawl(list_id, path, rows, seen, only=None, root=""):
    """only: 루트 바로 아래(1단계) 폴더 이름 정규식 — 맞는 폴더만 내려감 (예: 주거 주제에서 '주택총조사'만)"""
    items = call(URL_LIST, {"method": "getList", "vwCd": VW_CD, "parentListId": list_id})
    for it in items:
        if only and not path and not (it.get("LIST_NM") and re.search(only, it["LIST_NM"])):
            continue
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
                "root": root,
            })
        elif it.get("LIST_ID") and it["LIST_ID"] not in seen:
            seen.add(it["LIST_ID"])
            print("  " * len(path) + f"📁 {it['LIST_NM']} ({it['LIST_ID']})")
            crawl(it["LIST_ID"], path + [it["LIST_NM"]], rows, seen, only, root)


def stage_roots(args):
    """주제별 최상위 목록 출력 → 인구 외 다른 주제를 --root 로 수집할 때 ID 확인용"""
    for pid in ("", VW_CD):
        items = call(URL_LIST, {"method": "getList", "vwCd": VW_CD, "parentListId": pid})
        if items:
            for it in items:
                print(f"{it.get('LIST_ID') or it.get('TBL_ID')}\t{it.get('LIST_NM') or it.get('TBL_NM')}")
            return
    print("최상위 목록을 받지 못했습니다. KOSIS 화면의 주제 폴더 ID를 --root 로 직접 지정하세요.")


def list_roots():
    for pid in ("", VW_CD):
        items = call(URL_LIST, {"method": "getList", "vwCd": VW_CD, "parentListId": pid})
        if items:
            return items
    return []


def resolve_root(spec):
    """'A' | '인구' | '주거:주택총조사' → (목록 ID, 이름, 1단계 폴더 정규식)"""
    root, _, only = str(spec).partition(":")
    root = root.strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", root):  # ID 로 지정
        return root, root, only or None
    roots = list_roots()
    hit = [r for r in roots if str(r.get("LIST_NM", "")).strip() == root] or \
        [r for r in roots if root in str(r.get("LIST_NM", ""))]
    if not hit:
        raise SystemExit(f"주제 '{root}' 를 최상위 목록에서 찾지 못했습니다 → python -m backend.rag.ingestion.collector roots 로 ID 확인")
    return hit[0]["LIST_ID"], hit[0]["LIST_NM"], only or None


def stage_catalog(args):
    rows = []
    specs = args.root or [ROOT_LIST_ID]
    for spec in specs:
        list_id, name, only = resolve_root(spec)
        print(f"=== 목록 탐색: vwCd={VW_CD}, 주제={name}({list_id})" + (f", 1단계 폴더 /{only}/ 만" if only else "") + " ===")
        n0 = len(rows)
        crawl(list_id, [], rows, set(), only, name)
        print(f"  → 표 {len(rows) - n0}개")
    if getattr(args, "append", False) and (OUT / "catalog.csv").exists():
        old = pd.read_csv(OUT / "catalog.csv", dtype=str)
        have = set(zip(old["org_id"], old["tbl_id"]))
        new = [r for r in rows if (str(r["org_id"]), str(r["tbl_id"])) not in have]
        print(f"기존 catalog {len(old)}행 + 새 표 {len(new)}개 (이미 있는 {len(rows) - len(new)}개 제외)")
        old_rows = old.drop(columns=[c for c in ("is_sample", "is_full", "survey_type", "selected", "related_hint",
                                                  "dup", "also_in") if c in old.columns]).to_dict("records")
        rows = old_rows + new
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
        for t in args.tables:  # '@파일' 이면 파일의 줄 단위 tbl_id 목록
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
    if per_year is None:  # Y, F(다년), IR 등 → 연 단위로 생성 (없는 해는 빈 결과)
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
    for i, r in enumerate(cat.itertuples(), 1):
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
    sch = pd.DataFrame(rows)
    sch.to_csv(OUT / "table_schema.csv", index=False, encoding="utf-8-sig")
    print(f"\n스키마 저장 → {OUT/'table_schema.csv'}")
    print(sch.groupby(["category", "section"])["est_cells_total"].agg(["count", "sum"]).to_string())


# ─────────────────────────────── 3) 데이터 수집 ───────────────────────────────
def chunks(lst, k):
    for i in range(0, len(lst), k):
        yield lst[i:i + k]


MAX_CODES_PER_CALL = 100  # '+'로 묶을 코드 수 상한 (URL 길이 보호)


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
    i = max(free, key=lambda j: len(levels[j]["codes"]))  # 가장 큰 분류부터 분할
    rest = est // len(levels[i]["codes"])  # 이 분류 코드 1개당 셀 수
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
    if per_prd <= CELL_LIMIT or len(periods) <= 1:  # 작은 표는 범위 요청이라 낭비 없음
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
    for i, r in enumerate(cat.itertuples(), 1):
        out = OUT / "raw" / safe(r.category) / f"{r.org_id}_{r.tbl_id}.csv"
        if out.exists() and getattr(args, "refresh", False):  # 최신 자료로 다시 받기
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
            for n, fu in enumerate(as_completed(futs), 1):
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
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df = df[[c for c in KEEP_COLS if c in df.columns]].drop_duplicates()
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"    → {len(df):,} rows, {time.time() - t0:.0f}s", flush=True)
            if not tbl_fails:
                shutil.rmtree(part_dir, ignore_errors=True)  # 완료된 표의 조각 삭제
        if tbl_fails:  # 표 단위로 즉시 기록 (중단돼도 남도록)
            fails += tbl_fails
            fp = OUT / "failed.csv"
            pd.DataFrame(tbl_fails).to_csv(fp, mode="a", header=not fp.exists(), index=False,
                                           encoding="utf-8-sig")
    if skipped:
        pd.DataFrame(skipped).to_csv(OUT / "skipped_large.csv", index=False, encoding="utf-8-sig")
        print(f"대용량으로 건너뛴 표 {len(skipped)}개 → {OUT / 'skipped_large.csv'}")
    if fails:
        print(f"실패 {len(fails)}건 → {OUT / 'failed.csv'}")


def main():
    if not API_KEY:
        raise ValueError(".env 파일에서 KOSIS_API_KEY를 찾을 수 없습니다.")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["roots", "catalog", "schema", "download", "status", "all"])
    ap.add_argument("--root", nargs="*", default=None,
                    help="수집할 주제: ID(A) 또는 이름(인구, 주거), ':정규식' 으로 1단계 폴더 제한 (예: 주거:주택총조사). 여러 개 가능")
    ap.add_argument("--append", action="store_true", help="catalog: 기존 catalog.csv 를 유지하고 새 표만 추가")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 KOSIS_DATA_DIR)")
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
    args = ap.parse_args()
    if args.refresh and args.recent:
        ap.error("--refresh 와 --recent 를 함께 쓰면 기존 과거 시점 데이터가 지워집니다. 둘 중 하나만 쓰세요.")
    if args.refresh and not args.tables:
        ap.error("--refresh 는 --tables 로 대상 표를 지정할 때만 쓸 수 있습니다.")
    global OUT
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


if __name__ == "__main__":
    main()
