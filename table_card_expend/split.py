"""
[1] 나누기 — 표마다 조건표(conditions) 와 카드 재료(pieces) 를 만든다

table_card step1 과 같은 역할이지만 재료를 더 넓고 정확하게 읽는다
  구조    메타(분류 코드·상위 코드·단위) + 원본 CSV 스캔(실제로 들어 있는 코드·항목·단위·시점) — 둘 다 있으면 CSV 에 실제로
          있는 코드만 남기고, 메타가 없으면 CSV 만으로 만든다 (table_card 는 메타만 → 메타 없는 표가 '시점 []·지역 전국')
  시점    CSV 의 실제 시점 (메타의 '정의된' 범위가 아니라). 5년 주기 표는 2015·2020 처럼 해마다 따로 → 조건 확인이 정확
  지역    위 단계부터 이어 붙인 표준 이름 ('서울특별시 중구'), 상위가 없으면 코드 앞자리로 보정
  카드 재료 제목·주제(메뉴 경로)·축·항목(측정 종류)·대상·지표(근거 포함)·모집단·주석(이어 붙임)·용어 정의·조사 설명·관점

출력  <out>/conditions.jsonl  <out>/pieces.jsonl  <out>/unmapped.csv  <out>/split_report.txt
"""
from __future__ import annotations

import collections
import csv
import json
import re

from backend.core.utils import norm_space
from backend.rag.ingestion.normalize import PRD_SE_MAP, STRONG_TOTAL, build_level_dims, parse_meta

from table_card_expend import rules as R
from table_card_expend.sources import survey_explanation

SEX_CODE_NAMES = {"남자", "여자", "남", "여", "남성", "여성", "계", "합계", "전체", "남녀"}
KIND_AXIS = {"sex": "성별", "ages": "연령", "nationality": "국적", "cohort": "출생연도", "scenario": "추계 가정"}
NOT_REGION_AXIS = re.compile(r"항구|공항|성씨|본관|국적")
GEO_AXIS = re.compile(r"거주지|목적지|주소|전입지|전출지|통근|통학|행정구역|지역|출생지")
SE_LABEL = {"Y": "년", "M": "월", "Q": "분기", "H": "반기", "F": "다년", "IR": "부정기", "D": "일"}
MAX_NAMES = 300


# ── 구조 합치기: 메타 + CSV ──────────────────────────────────────
def structure(meta, scan):
    """→ (분류 [(info, rows)], 항목 [{itm_id, name, unit}], 출처). CSV 에 있는 코드만 남김 (CSV 가 있을 때)"""
    levels_meta, items_meta = parse_meta(meta) if meta.get("ITM") else ([], [])
    src = "meta"
    if scan:
        src = "csv+meta" if levels_meta else "csv"
        by_name = {norm_space(l["obj_nm"]): l for l in levels_meta}
        new_levels = []
        for i, d in enumerate(scan.get("dims") or [], 1):
            lm = by_name.get(norm_space(d["obj_nm"])) or (levels_meta[i - 1] if i - 1 < len(levels_meta) else None)
            present = {str(v["code"]): v["name"] for v in d.get("values") or []}
            if lm:
                codes = [c for c in lm["codes"] if c["code"] in present] or \
                        [{"code": c, "name": n, "parent": ""} for c, n in present.items()]
                new_levels.append({**lm, "codes": codes})
            else:
                new_levels.append({"obj_id": f"C{i}", "obj_nm": d["obj_nm"], "sn": i,
                                   "codes": [{"code": c, "name": n, "parent": ""} for c, n in present.items()]})
        levels_meta = new_levels
        unit_of = {i["itm_id"]: i["unit"] for i in items_meta}
        items_meta = [{"itm_id": i["itm_id"], "name": i["name"], "unit": i.get("unit") or unit_of.get(i["itm_id"], ""),
                       "parent": ""} for i in scan.get("items") or []] or items_meta
    dims = [build_level_dims(n, lv) for n, lv in enumerate(levels_meta, 1)]
    return dims, items_meta, src


def year_spans(years):
    """[2015, 2016, 2017, 2020] → [(2015, 2017), (2020, 2020)]"""
    ys = sorted(set(years))
    out = []
    for y in ys:
        if out and y == out[-1][1] + 1:
            out[-1][1] = y
        else:
            out.append([y, y])
    return [tuple(x) for x in out]


def periods_of(meta, scan):
    """→ (조건표 시점, 프로필 periods, 출처). CSV 의 실제 시점이 있으면 그것, 없으면 메타 범위"""
    if scan and scan.get("periods"):
        cond, prof = [], []
        for se_raw, des in scan["periods"].items():
            se = PRD_SE_MAP.get(norm_space(se_raw), norm_space(se_raw)) or "Y"
            if se not in SE_LABEL and str(se_raw).endswith("년"):
                se = "F"
            years = sorted({int(d[:4]) for d in des if len(d) >= 4 and d[:4].isdigit()})
            if not years:
                continue
            label = norm_space(se_raw) if re.search(r"[가-힣]", str(se_raw)) else SE_LABEL.get(se, se)
            cond.append({"주기": label, "시작": years[0], "끝": years[-1],
                         "연도": years, "시점수": len(des)})
            prof += [{"se": se, "se_raw": norm_space(se_raw), "year_from": a, "year_to": b} for a, b in year_spans(years)]
        if cond:
            return cond, prof, "csv"
    cond, prof = [], []
    for p in meta.get("PRD") or []:
        if not isinstance(p, dict):
            continue
        a, b = str(p.get("STRT_PRD_DE") or "")[:4], str(p.get("END_PRD_DE") or "")[:4]
        if not (a.isdigit() and b.isdigit()):
            continue
        se_raw = norm_space(p.get("PRD_SE"))
        se = PRD_SE_MAP.get(se_raw) or ("F" if se_raw.endswith("년") else se_raw or "Y")
        cond.append({"주기": se_raw, "시작": int(a), "끝": int(b), "연도": None, "시점수": None})
        prof.append({"se": se, "se_raw": se_raw, "year_from": int(a), "year_to": int(b)})
    return cond, prof, "meta"


# ── 지역 ────────────────────────────────────────────────────────
def region_like(dims, tbl_nm):
    """지역 분류로 판정되지 않았지만 시도 이름이 3개 이상인 분류 ('현거주지별', '출생지별' …) → [(obj_id, 이름, 표준 목록)]"""
    out = []
    for info, rows in dims:
        if info["kind"] == "regions" or NOT_REGION_AXIS.search(info["obj_nm"]):
            continue
        sido = [R.sido_std(r["name"]) for r in rows if R.sido_std(r["name"])]
        if len(set(sido)) >= 3 or (GEO_AXIS.search(info["obj_nm"]) and len(set(sido)) >= 2):
            names = (["전국"] if any(r["is_total"] or r["name"] == "전국" for r in rows) else []) + list(dict.fromkeys(sido))
            out.append((info["obj_id"], R.clean_axis(info["obj_nm"]), names))
    return out


def item_regions(items):
    def base(n):
        return re.split(r"[-–]", re.sub(r"^.*[:：]\s*", "", norm_space(n)))[0].strip()
    sido = [(i["name"], R.sido_std(base(i["name"]))) for i in items if R.sido_std(base(i["name"]))]
    if len({s for _, s in sido}) < 3:
        return None, [], set()
    role, used = "", {n for n, _ in sido}
    names = []
    for i in items:
        m = re.match(r"^(.*?)\s*[:：]?\s*전국(?:[-–].*)?$", norm_space(i["name"]))
        if m:
            used.add(i["name"])
            role = role or m.group(1).strip(" _-:：")
            names = names or ["전국"]
    return role or "항목", names + list(dict.fromkeys(s for _, s in sido)), used


def regions_of(t, dims, items):
    reg = [(info, rows) for info, rows in dims if info["kind"] == "regions"]
    like = region_like(dims, t.tbl_nm)
    role2, names2, _ = item_regions(items)
    bare, orig = [], {}
    if reg:
        names, orig, bare = R.region_full_names(reg[0][1])
        src = "분류"
        if len(reg) > 1 and not names2:
            n2, _, _ = R.region_full_names(reg[1][1])
            role2, names2 = R.clean_axis(reg[1][0]["obj_nm"]), n2
        elif like and not names2:
            role2, names2 = like[0][1], like[0][2]
    elif like:
        names, src = like[0][2], f"분류({like[0][1]}, 지역 판정 보정)"
        if len(like) > 1 and not names2:
            role2, names2 = like[1][1], like[1][2]
    elif len(names2) >= 3:
        names, src, role2, names2 = names2, "항목", None, []
    else:
        title_sido = [R.sido_std(m) for m in R.SIDO_RE.findall(t.tbl_nm) if R.sido_std(m)]
        if title_sido:
            names, src = list(dict.fromkeys(title_sido)), "제목"
        else:
            names, src = ["전국"], "없음(전국으로 봄)"
    return {"지역": names, "지역_출처": src, "지역_원래이름": orig, "지역_상위없음": bare[:20],
            "지역2": {"역할": role2, "이름": names2} if names2 else None}


# ── 관점 (이 표로 답할 수 있는 질문의 모양 — 연도·지역 이름 없이) ───────────
def viewpoints(indicators, axes, levels, limit=8):
    """원본 CSV 에서 View 를 자르는 방식(지표 하나 × 나뉘는 기준)을 글로: '시도별 성별 인구수'"""
    lv = [x for x in levels if x != "전국"][:2]
    ax = [a["표준"] or a["원래"] for a in axes if a["값_수"] >= 2][:4]
    out = []
    for ind in indicators[:2]:
        combos = [[], *[[x] for x in lv[:1]], *[[a] for a in ax], *([[lv[0], a] for a in ax[:2]] if lv else []),
                  *([[ax[0], ax[1]]] if len(ax) >= 2 else [])]
        for c in combos:
            out.append(" ".join([*(f"{re.sub(r'별$', '', x)}별" for x in c), ind]).strip())
    return list(dict.fromkeys(out))[:limit]


# ── 표 하나 ─────────────────────────────────────────────────────
def split_table(t, scan, D):
    meta = t.meta()
    dims, items_meta, struct_src = structure(meta, scan)
    reg = regions_of(t, dims, items_meta)
    period_cond, period_prof, period_src = periods_of(meta, scan)
    like_ids = {oid for oid, _, _ in region_like(dims, t.tbl_nm)}
    reg_ids = {info["obj_id"] for info, _ in dims if info["kind"] == "regions"}

    axes = []
    for info, rows in dims:
        if info["obj_id"] in reg_ids:
            continue
        kind = info["kind"]
        if info["obj_id"] in like_ids:
            axes.append({"원래": R.clean_axis(info["obj_nm"]), "표준": None, "kind": "regions_like", "역할": info["role"],
                         "값_수": 0, "값": []})
            continue
        if kind == "sex" and not {r["name"] for r in rows if not r["is_total"]} <= SEX_CODE_NAMES:
            kind = "other"
        vals = list(dict.fromkeys(r["name"] for r in rows if not r["is_total"] and r["name"] not in STRONG_TOTAL))
        a = R.clean_axis(info["obj_nm"])
        std = KIND_AXIS.get(kind) or D["축"].get(R.nospace(a)) or (R.find_terms(a, D["축"]) or [None])[0]
        axes.append({"원래": a, "표준": std, "kind": kind, "역할": info["role"], "값_수": len(vals),
                     "값": [v for v in vals if not R.SIDO_RE.search(v)][:40],
                     "나이": [{"from": r["age_from"], "to": r["age_to"]} for r in rows if r.get("age_from") is not None][:60]
                     if kind == "ages" else None})

    _, _, region_items = item_regions(items_meta)
    items = []
    for i in items_meta:
        if i["name"] in region_items:
            continue
        nm = R.clean_item(i["name"])
        if nm:
            items.append({"name": nm, "unit": norm_space(i.get("unit")), "kind": R.measure_kind(nm, i.get("unit"))})
    items = list({x["name"]: x for x in items}.values())
    if reg["지역2"]:
        items = [{"name": reg["지역2"]["역할"], "unit": "", "kind": "other"}, *items]
    units = sorted({i["unit"] for i in items if i["unit"]})

    notes = R.merge_notes(meta.get("CMMT"))
    defs = R.definitions(notes)
    sub_notes = [norm_space(c.get("CMMT_DC")) for c in meta.get("CMMT") or []
                 if isinstance(c, dict) and c.get("CMMT_NM") in ("분류", "항목") and norm_space(c.get("CMMT_DC"))][:5]

    survey = norm_space((meta.get("SOURCE") or [{}])[0].get("JOSA_NM", "")).strip("「」") if meta.get("SOURCE") \
        else (scan or {}).get("survey_nm") or t.category
    survey = survey or t.category
    title = R.clean_title(t.tbl_nm)
    topic = R.clean_path(t.path, survey)
    item_names = [i["name"] for i in items]
    small_vals = [v for a in axes if a["kind"] not in ("ages", "cohort") and a["값_수"] <= 40 for v in a["값"]]
    target = R.find_terms(f"{title} {' '.join(item_names)} {' '.join(small_vals)}", D["대상"])
    if "가구" in title and any(re.fullmatch(r"1\s*인(\s*가구)?", v) for v in [*small_vals, *item_names]) \
            and "1인가구" not in target:
        target.append("1인가구")
    indic = R.find_terms(" ".join([title, *item_names]), D["지표"])
    real_items = [i for i in items if not (reg["지역2"] and i["name"] == reg["지역2"]["역할"])]   # 지역2 역할 이름은 측정값 아님
    inferred = [(x, why) for x, why in R.infer_indicators(title, real_items, target, D["_지표목록"]) if x not in indic]
    indic_all = indic + [x for x, _ in inferred]
    move = R.find_terms(" ".join([title, *item_names, *[a["원래"] for a in axes]]), D["이동"])
    pop = R.population(t.tbl_nm, items_meta, notes)
    levels = R.region_levels(reg["지역"])

    # 프로필: resolve.unmet 이 읽는 모양 (검색 쪽 조건 확인이 기존과 같은 함수로 돌게)
    prof_levels = []
    for info, rows in dims:
        names = [r["name"] for r in rows][:MAX_NAMES]
        lv = {"obj_id": info["obj_id"], "obj_nm": info["obj_nm"], "kind": info["kind"], "n_codes": info["n_codes"],
              "names": names}
        if info["kind"] == "regions":
            lv["sido"] = sorted({r["std"] for r in rows if r["geo_type"] == "시도"})
            lv["geo_types"] = dict(collections.Counter(r["geo_type"] for r in rows))
            lv["names"] = [r["name"] for r in rows if r["geo_type"] in ("전국", "시도", "동읍면부", "기타")][:MAX_NAMES]
        prof_levels.append(lv)
    profile = {"tbl_id": t.tbl_id, "tbl_nm": t.tbl_nm, "periods": period_prof, "levels": prof_levels,
               "items": [{"itm_id": i.get("itm_id"), "name": i["name"], "unit": norm_space(i.get("unit"))}
                         for i in items_meta][:MAX_NAMES],
               "units": units, "profile_from": f"table_card_expend:{struct_src}"}

    cond = {"tbl_id": t.tbl_id, "org_id": t.org_id, "시점": period_cond, "최신연도": max(
        (p["끝"] for p in period_cond), default=None), **reg, "지역수준": levels,
            "조사구분": t.survey_type, "단위": units, "모집단": pop,
            "근거": {"구조": struct_src, "시점": period_src, "메타": bool(meta.get("ITM")), "원본CSV": bool(scan)},
            "프로필": profile}
    piece = {"tbl_id": t.tbl_id, "org_id": t.org_id, "set": t.set_name, "조사명": survey, "제목": title,
             "제목_원래": t.tbl_nm, "주제": topic, "축": axes, "항목": item_names[:80], "항목_상세": items[:80],
             "항목_수": len(item_names), "대상": target, "지표": indic_all, "지표_사전": indic,
             "지표_추론": [{"지표": x, "근거": why} for x, why in inferred], "이동": move, "모집단": pop,
             "주석": notes[:8], "분류주석": sub_notes, "정의": defs, "조사설명": survey_explanation(t.stat_id),
             "지역수준": levels, "관점": viewpoints(indic_all or item_names[:2], axes, levels),
             "also_in": t.also_in, "근거": cond["근거"]}
    return cond, piece


def run(tables, scans, out_dir, log=print):
    D = R.load_dict()
    out_dir.mkdir(parents=True, exist_ok=True)
    conds, pieces, unmapped, errors = [], [], collections.defaultdict(lambda: [0, ""]), []
    stat = collections.Counter()
    for t in tables:
        try:
            c, p = split_table(t, scans.get(t.tbl_id), D)
        except Exception as e:  # noqa: BLE001  (한 표 실패가 전체를 막지 않게)
            errors.append({"tbl_id": t.tbl_id, "error": f"{e.__class__.__name__}: {str(e)[:200]}"})
            continue
        conds.append(c)
        pieces.append(p)
        stat["표"] += 1
        stat[f"구조:{c['근거']['구조']}"] += 1
        stat[f"시점:{c['근거']['시점']}"] += 1
        stat["대상 있음"] += bool(p["대상"])
        stat["지표 있음"] += bool(p["지표"])
        stat["지표 추론"] += bool(p["지표_추론"])
        stat["모집단 있음"] += bool(p["모집단"])
        stat["정의 있음"] += bool(p["정의"])
        stat["조사설명 있음"] += bool(p["조사설명"])
        stat["지역 상위없음 표"] += bool(c["지역_상위없음"])
        stat[f"지역출처:{c['지역_출처'].split('(')[0]}"] += 1
        for a in p["축"]:
            stat["축 전체"] += 1
            stat["축 매핑"] += a["표준"] is not None
            if a["표준"] is None and a["kind"] != "regions_like":
                unmapped[("축", a["원래"])][0] += 1
                unmapped[("축", a["원래"])][1] = unmapped[("축", a["원래"])][1] or t.tbl_id
        if not (p["대상"] or p["지표"] or p["이동"]):
            unmapped[("제목(대상·지표·이동 없음)", p["제목"])][0] += 1
            unmapped[("제목(대상·지표·이동 없음)", p["제목"])][1] = t.tbl_id
    for name, rows in (("conditions.jsonl", conds), ("pieces.jsonl", pieces)):
        with (out_dir / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    with (out_dir / "unmapped.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["종류", "말", "표_수", "예시_표"])
        for (k, word), (n, ex) in sorted(unmapped.items(), key=lambda x: (x[0][0], -x[1][0])):
            w.writerow([k, word, n, ex])
    n = stat["표"] or 1
    pct = lambda a, b=n: f"{a}/{b} ({a / b * 100:.0f}%)" if b else "0"  # noqa: E731
    lines = [f"표 {stat['표']}개 (실패 {len(errors)})",
             "구조 출처: " + ", ".join(f"{k.split(':')[1]} {v}" for k, v in stat.items() if k.startswith("구조:")),
             "시점 출처: " + ", ".join(f"{k.split(':')[1]} {v}" for k, v in stat.items() if k.startswith("시점:")),
             "지역 출처: " + ", ".join(f"{k.split(':')[1]} {v}" for k, v in stat.items() if k.startswith("지역출처:")),
             f"대상 있음 {pct(stat['대상 있음'])} · 지표 있음 {pct(stat['지표 있음'])} · 지표 추론 {pct(stat['지표 추론'])}",
             f"모집단 {pct(stat['모집단 있음'])} · 용어 정의 {pct(stat['정의 있음'])} · 조사설명 {pct(stat['조사설명 있음'])}",
             f"축 매핑 {pct(stat['축 매핑'], stat['축 전체'])}",
             f"상위 지역 없이 남은 이름이 있는 표 {stat['지역 상위없음 표']}",
             *[f"  ✗ {e['tbl_id']} {e['error']}" for e in errors[:10]]]
    (out_dir / "split_report.txt").write_text("\n".join(lines), encoding="utf-8")
    log("\n".join(lines))
    return conds, pieces, errors
