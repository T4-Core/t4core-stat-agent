"""
[엔드포인트 4] build_view — 검색으로 찾은 표(메타데이터) + 슬롯 dict → View 카드(Record, doc_type="view")

  1) 표 지연 정규화 (normalize.ensure_normalized): raw CSV → 정제 parquet + 실제 프로필
  2) 슬롯 → 그 표의 실제 코드 조건 (시점·지역·성별·연령·지표/대상)
  3) parquet 에서 조건대로 잘라 View 데이터 → output/views/<id>.csv
  4) 카드: id · lexical_text · table{columns, rows} · doc_type=view · parent_id · metadata · source
           · notes(못 맞춘 조건 dict 목록) · match(검색·표 고르기 결과, views.py 에서 붙임)  [NEW 11-03]
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


def specific_stems(names, stems):
    """[NEW v4] 이 값들 중 맞는 것이 있는 단어만, 그중 다른 맞는 단어에 포함되는 넓은 단어는 뺌
    예) 단어 {'가구', '1인가구'}, 값에 '1인가구' 가 있음 → {'1인가구'} ('가구' 는 더 구체적인 '1인가구' 에 포함)
        값에 '1인가구' 가 없으면 → {'가구'} (예전과 같음)"""
    hit = {s for s in stems if s and any(s in squash(n) for n in names)}
    return {s for s in hit if not any(s != t and s in t for t in hit)} or set(stems)


def match_name_ctx(name, stems, context=""):
    """[NEW v4] 분류 값 + 분류 이름으로 맞추기: 값이 질문 단어의 앞부분이고 나머지가 분류 이름에 있으면 같은 것
    예) 질문 '1인가구', 분류 '가구원수별' 의 값 '1인' → '1인' + '가구'(분류 이름에 있음) = '1인가구'
    값이 한 글자(남·여·1 …)면 쓰지 않음. 직접 일치(match_name)가 없을 때만 부른다"""
    n, ctx = squash(name), squash(context)
    if len(n) < 2 or not ctx:
        return False
    return any(s.startswith(n) and len(s) > len(n) and s[len(n):] in ctx for s in stems)


# ── notes (못 맞춘 조건) — 판단 모듈이 규칙으로 읽을 수 있게 dict 로 (2026-11-03) ──
#   {slot, dim, type, requested, applied, text}
#   slot : 시점 · 지역 · 성별 · 연령 · 지표 · 시나리오 · 행수
#   type : missing(요청 값이 표에 없음) · default(못 맞춰 기본값 사용) · partial(일부만 맞춤)
#          · latest_shift(최신 연도에 값이 없어 앞 연도) · truncated(행 잘라냄) · empty(빈 View)
SLOT_OF_KIND = {"regions": "지역", "sex": "성별", "ages": "연령", "scenario": "시나리오"}


def note(notes, slot, type_, text, dim=None, requested=None, applied=None):
    notes.append({"slot": slot, "dim": dim, "type": type_, "requested": requested, "applied": applied, "text": text})


def requested_of(slot, f):
    # 슬롯 이름 → 슬롯 dict 에서 요청한 값 (notes.requested 용)
    if slot == "지표":
        return (f.get("지표") or []) + (f.get("대상") or []) or None
    if slot == "지역":
        return f.get("지역") or f.get("비교축")
    if slot == "시나리오":
        return "중위"
    return f.get(slot)


DASH_RE = re.compile(r"^\s*[-－–]\s*")


def full_names(names):
    # '-' 로 시작하는 줄은 바로 위 일반 줄의 하위 항목 (KOSIS 표기) → 윗줄 앞부분을 이어붙임
    #   '고령인구(천명): 65세+', '- 구성비(%): 65세+' → …, '고령인구 구성비(%): 65세+'
    #   '중국', '-조선족' → …, '중국 조선족'
    # 부모 코드(parent)가 비어 있는 표가 있어 줄 순서로 판단 (메타 코드 순서 = KOSIS 화면 순서)
    head, out = "", []
    for n in names:
        n = str(n or "")
        if DASH_RE.match(n) and head:
            out.append(f"{head} {DASH_RE.sub('', n)}")
        else:
            head = re.split(r"[(:（]", n)[0].strip() or head
            out.append(n)
    return out


# ── 시점 ────────────────────────────────────────────────────────
def match_period(prof, f, notes):
    se = next((s for s in SE_PREF if s in prof["periods"]), next(iter(prof["periods"])))
    avail = sorted({p["year"] for p in prof["periods"][se]})
    want = f.get("시점")
    if want:
        use = [y for y in want if y in avail]
        miss = [y for y in want if y not in avail]
        if miss:
            note(notes, "시점", "missing", f"시점 {miss} 은 이 표에 없음 (수록 {avail[0]}~{avail[-1]})", requested=miss)
        if not use:
            use = [avail[-1]]
            note(notes, "시점", "default", f"요청 시점이 모두 없어 최신 {avail[-1]} 사용", requested=want, applied=use)
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
        note(notes, "연령", "partial" if sel else "missing",
             f"{what}: 연령 {lo}~{hi if hi is not None else ''} 을 정확히 덮는 코드 없음"
             + (f" (가까운 코드 {len(sel)}개 사용)" if sel else ""),
             dim=what, requested=rng, applied=[c.get("std") or c.get("name") for c in sel] or None)
    return sel


def match_level(l, f, stems, notes):
    kind, codes = l["kind"], l["codes"]
    if kind == "ages" and not any(c.get("age_from") is not None for c in codes):
        kind = "other"      # [CHANGED 11-03] 연령 숫자가 하나도 안 읽히는 '연령' 분류('고령인구(천명): 65세+' …)는 지표 분류로
    default = [c for c in codes if c["code"] == l["default_code"]]
    name = l["obj_nm"]

    def fallback(why):
        if default:
            slot = SLOT_OF_KIND.get(kind, "지표")
            note(notes, slot, "default", f"{name}: {why} → 기본값 '{default[0]['std']}'({l['default_reason']})",
                 dim=name, requested=requested_of(slot, f), applied=[default[0]["std"]])
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
                note(notes, "지역", "missing", f"{name}: 지역 {miss} 없음", dim=name, requested=miss)
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
        return [c for c in codes if c["is_total"]] or fallback("합계 코드 없음")
        # [CHANGED 11-03] 이전: … or default  (기본값을 notes 없이 골라 판단 모듈이 알 수 없었음)
    if kind == "ages":
        if f.get("연령"):
            return age_codes(codes, f["연령"], notes, name) or fallback("연령 범위 코드 없음")
        return [c for c in codes if c["is_total"]] or fallback("합계 코드 없음")
        # [CHANGED 11-03] 이전: … or default
    if kind == "scenario":
        # 시나리오는 지표 단어로 고르지 않는다: 이름이 '높은 출산율 추계(… 기대수명-중위 …)' 처럼 길어서
        # 지표 '기대수명' 이 모든 시나리오에 걸림. 슬롯에 시나리오가 없으므로 기본값(중위) 하나
        if default and l["default_reason"] != "기본 추계(중위)":
            note(notes, "시나리오", "default",
                 f"{name}: 중위(기본) 시나리오가 없어 '{default[0]['std']}'({l['default_reason']}) 사용",
                 dim=name, requested="중위", applied=[default[0]["std"]])
        return default
    full = full_names([c["name"] for c in codes])                                     # '-' 줄은 윗줄 이름 이어받기
    sel = [c for c, n in zip(codes, full) if not c["is_total"] and match_name(n, specific_stems(full, stems))]
    # [CHANGED v4] 이전: match_name(n, stems) — 지표 '가구' 가 '1세대가구·2세대가구·1인가구 …' 를 다 골라
    #   대상 '1인가구' 를 물어도 세대구성 전체가 들어감. 같은 분류 안에서 더 구체적인 단어가 맞으면 그것만
    if sel:
        return sel
    # [NEW v4] 값 + 분류 이름 ('가구원수별' 의 '1인' = '1인가구'). 이전엔 못 맞춰 합계 코드로 넘어감
    sel = [c for c, n in zip(codes, full) if not c["is_total"] and match_name_ctx(n, stems, name)]
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
            note(notes, "성별", "missing", f"성별 {sorted(sexes)}: 이 표에 성별 구분 없음",
                 dim="항목", requested=sorted(sexes))
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
        note(notes, "지표", "default", "항목: 지표·대상과 맞는 항목 없음 → 항목 전체",
             dim="항목", requested=requested_of("지표", f), applied=[i["name"] for i in items])
        return items
    tot = [i for i in items if i["is_total"]] or items[:1]
    note(notes, "지표", "default", f"항목: 지표·대상과 맞는 항목 없음 → '{tot[0]['name']}'",
         dim="항목", requested=requested_of("지표", f), applied=[tot[0]["name"]])
    return tot


# ── View 만들기 ─────────────────────────────────────────────────
def build_view(tbl_id, f, num, con=None):
    # f = 슬롯 dict (연령은 {"from","to"}), num = id 번호 자리 ('질문ID-순위', 예: '12-1')
    # 반환: (record dict = 카드, notes = 못 맞춘 조건 메모 dict 목록 — record["notes"] 와 같은 것)
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
            note(notes, "지역", "default", f"지역 {want_geo}: 이 표에는 지역 구분이 없음 → 전국 값",
                 requested=want_geo, applied=["전국"])
            # [CHANGED 11-05] notes 가 dict 목록이 되어 (위 note()) 문장 대신 같은 모양으로
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
                note(notes, "시점", "latest_shift", f"최신 {years[-1]} 은 값이 없어 값이 있는 최신 {y} 사용",
                     requested=[years[-1]], applied=[int(y)])
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
        note(notes, "행수", "truncated", f"행이 {MAX_ROWS}개를 넘어 앞부분만 사용", applied=MAX_ROWS)
    if df.empty:
        note(notes, "행수", "empty", "조건에 맞는 값이 없음 (빈 View)", applied=0)

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
        "notes": notes,                                         # [NEW 11-03] 못 맞춘 조건 (dict 목록, 위 note() 형식)
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
