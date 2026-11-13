"""가상 KOSIS 형식 데이터 생성 (실제 KOSIS 데이터·API 키 없이 파이프라인 검증용).

collector.py 출력과 같은 폴더 모양을 만든다:
  <root>/catalog.csv, <root>/meta/<ORG>_<TBL>.json, <root>/raw/<조사명>/<ORG>_<TBL>.csv,
  <root>/store/data/<ORG>_<TBL>.parquet (분기표 1개는 RAW 없이 store parquet 만), <root>/stored_views/<ORG>_<TBL>/*.csv

포함 사례 (README 표 참고)
  - 동일 지표 서로 다른 연도 / 서로 다른 지역 / 월별 vs 분기별 (PRD_DE 문자열이 같아도 주기가 다름)
  - 단위 스케일 차이 (명 vs 천명) / 총계(전국·계)와 하위 분류 / 정상 0 · 음수 (순이동)
  - 결측 기호 ("-", "X", "*", "", "NaN") / 분모 0 / 같은 이름(중구) 다른 지역 코드 / 코드 체계 충돌
  - 실측 vs 추계 (C1 = 시나리오, C2 = 지역 → C1=지역 가정 금지 확인) / 공통 Join Key 를 가진 복수 표
  - 다대다 Join 행 증폭 (같은 좌표 중복 행) / 대체 Positive (같은 값의 구 표) / Hard Negative (외국인 모집단 등)
  - 답변 불가 (수록되지 않은 연도, 미래 시점, 모호한 지역명, 범위 밖 주제)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from synthetic_gold_pipeline.utils import PACKAGE_ROOT

DEFAULT_DEMO_ROOT = PACKAGE_ROOT / "outputs" / "demo_kosis_data"

SIDO = [("00", "전국", None), ("11", "서울특별시", "00"), ("26", "부산광역시", "00"), ("27", "대구광역시", "00"),
        ("29", "광주광역시", "00"), ("30", "대전광역시", "00"), ("41", "경기도", "00")]
BASE_POP = {"11": 9_450_000, "26": 3_330_000, "27": 2_380_000, "29": 1_440_000, "30": 1_450_000, "41": 13_600_000}
POP_TREND = {"11": -0.008, "26": -0.009, "27": -0.007, "29": -0.004, "30": -0.003, "41": 0.006}
SEX = [("0", "계", None), ("1", "남자", "0"), ("2", "여자", "0")]


def _h(*parts) -> int:
    return int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _pop(code: str, year: int) -> int:
    v = BASE_POP[code] * (1 + POP_TREND[code]) ** (year - 2020)
    return int(round(v + (_h("pop", code, year) % 2000) - 1000))


def _itm_rows(obj_id, obj_nm, sn, codes):
    return [{"OBJ_ID": obj_id, "OBJ_NM": obj_nm, "OBJ_ID_SN": str(sn), "ITM_ID": c, "ITM_NM": n, "UP_ITM_ID": up}
            for c, n, up in codes]


def _items_meta(items):
    return [{"OBJ_ID": "ITEM", "OBJ_NM": "항목", "ITM_ID": i, "ITM_NM": n, "UNIT_NM": u} for i, n, u in items]


def _rec(org, tbl, tbl_nm, dims, itm, prd_se, prd_de, dt):
    r = {"ORG_ID": org, "TBL_ID": tbl, "TBL_NM": tbl_nm}
    for i, (obj_nm, code, nm) in enumerate(dims, 1):
        r[f"C{i}"], r[f"C{i}_OBJ_NM"], r[f"C{i}_NM"] = code, obj_nm, nm
    r.update({"ITM_ID": itm[0], "ITM_NM": itm[1], "UNIT_NM": itm[2], "PRD_SE": prd_se, "PRD_DE": prd_de, "DT": dt,
              "LST_CHN_DE": "2026-10-01"})
    return r


def _fmt(v: int | float) -> str:
    return f"{v}"


def build_tables() -> list[dict]:
    T = []
    # T1 주민등록인구 — 시도 × 항목(총·남·여), 연간 2020~2024. 결측 기호 포함, '기타(99)' 지역은 인구 0 (분모 0)
    recs = []
    regions = SIDO + [("99", "기타(미상)", "00")]
    items = [("T20", "총인구수", "명"), ("T21", "남자인구수", "명"), ("T22", "여자인구수", "명")]
    for y in range(2020, 2025):
        tot = {c: _pop(c, y) for c in BASE_POP}
        male = {c: int(tot[c] * (0.485 + (_h("m", c) % 20) / 1000)) for c in tot}
        for code, nm, _ in regions:
            if code == "00":
                vals = {"T20": sum(tot.values()), "T21": sum(male.values()), "T22": sum(tot.values()) - sum(male.values())}
            elif code == "99":
                vals = {"T20": 0, "T21": 0, "T22": 0}
            else:
                vals = {"T20": tot[code], "T21": male[code], "T22": tot[code] - male[code]}
            for itm in items:
                dt = _fmt(vals[itm[0]])
                if (y, code, itm[0]) == (2022, "29", "T22"):
                    dt = "-"
                if (y, code, itm[0]) == (2021, "30", "T21"):
                    dt = "X"
                recs.append(_rec("101", "DT_DEMO_POP", "행정구역(시도)별 성별 인구", [("행정구역(시도)별", code, nm)],
                                 itm, "A", str(y), dt))
    T.append({"key": "101_DT_DEMO_POP", "survey": "주민등록인구현황", "section": "주민등록인구", "records": recs,
              "levels": [("A", "행정구역(시도)별", 1, regions)], "items": items, "prd": ("년", "2020", "2024"),
              "cmmt": [{"CMMT_DC": "매년 12월 31일 기준 주민등록인구. \"-\": 해당 숫자 없음, \"X\": 비밀보호"}],
              "path": "주민등록인구현황 > 주민등록인구"})
    # T2 혼인건수 (INH_ 표 ID) — 시도, 연간 2020~2024, 단위 건
    recs = []
    for y in range(2020, 2025):
        v = {c: int(_pop(c, y) * (0.0040 + (_h("mar", c, y) % 9) / 10000)) for c in BASE_POP}
        for code, nm, _ in SIDO:
            dt = sum(v.values()) if code == "00" else v[code]
            recs.append(_rec("101", "INH_DEMO_MARRY", "시도별 혼인건수", [("시도별", code, nm)],
                             ("T1", "혼인건수", "건"), "A", str(y), _fmt(dt)))
    T.append({"key": "101_INH_DEMO_MARRY", "survey": "인구동향조사", "section": "혼인", "records": recs,
              "levels": [("A", "시도별", 1, SIDO)], "items": [("T1", "혼인건수", "건")], "prd": ("년", "2020", "2024"),
              "cmmt": [{"CMMT_DC": "신고 기준 혼인 건수"}], "path": "인구동향조사 > 혼인"})
    # T3 인구총조사 가구 — 시도 × 가구주 성별, 항목 일반가구·1인가구, 2015·2020 (5년 주기)
    recs = []
    for y in (2015, 2020):
        def hh(code):
            pops = _pop(code, y)
            gen_t = int(pops / 2.4)
            one_t = int(gen_t * (0.27 + (_h("one", code, y) % 60) / 1000 + (0.03 if y == 2020 else 0)))
            m_one = 0.44 + (_h("msh", code, y) % 13) / 100           # 남성 가구주 1인가구 비중 44~56%
            gm = int(gen_t * 0.68)
            om = int(one_t * m_one)
            return {"0": (gen_t, one_t), "1": (gm, om), "2": (gen_t - gm, one_t - om)}
        vals = {c: hh(c) for c in BASE_POP}
        vals["00"] = {sc: tuple(sum(vals[c][sc][i] for c in BASE_POP) for i in (0, 1)) for sc in ("0", "1", "2")}
        for code, nm, _ in SIDO:
            for sc, snm, _ in SEX:
                gen, one = vals[code][sc]
                for itm, val in ((("T1", "일반가구", "가구"), gen), (("T2", "1인가구", "가구"), one)):
                    recs.append(_rec("101", "DT_DEMO_HH", "시도별 가구주 성별 일반가구",
                                     [("행정구역별(시도)", code, nm), ("가구주의 성별", sc, snm)], itm, "A", str(y), _fmt(val)))
    T.append({"key": "101_DT_DEMO_HH", "survey": "인구총조사", "section": "가구부문", "records": recs,
              "levels": [("A", "행정구역별(시도)", 1, SIDO), ("B", "가구주의 성별", 2, SEX)],
              "items": [("T1", "일반가구", "가구"), ("T2", "1인가구", "가구")], "prd": ("5년", "2015", "2020"),
              "cmmt": [{"CMMT_DC": "11월 1일 0시 기준, 일반가구 대상 (집단가구·외국인가구 제외)"}],
              "path": "인구총조사 > 가구부문 > 전수부문(등록센서스)"})
    # T4 경제활동인구 — 단위 천명 (스케일 차이)
    recs = []
    for y in (2022, 2023, 2024):
        act = {c: round(_pop(c, y) * (0.56 + (_h("eco", c, y) % 30) / 1000) / 1000) for c in BASE_POP}
        emp = {c: round(act[c] * 0.965) for c in act}
        rate = {c: round(60 + (_h("lfpr", c, y) % 80) / 10, 1) for c in act}
        rate_all = round(sum(rate[c] * act[c] for c in act) / sum(act.values()), 1)
        for code, nm, _ in SIDO:
            for itm, src in ((("T1", "경제활동인구", "천명"), act), (("T2", "취업자", "천명"), emp),
                             (("T3", "경제활동참가율", "%"), {**rate, "00": rate_all})):
                dt = src["00"] if "00" in src and code == "00" else (sum(src.values()) if code == "00" else src[code])
                if (y, code, itm[0]) == (2023, "27", "T2"):
                    dt = "*"
                recs.append(_rec("101", "DT_DEMO_ECON", "시도별 경제활동인구", [("시도별", code, nm)], itm, "A", str(y), _fmt(dt)))
    T.append({"key": "101_DT_DEMO_ECON", "survey": "경제활동인구조사", "section": "고용", "records": recs,
              "levels": [("A", "시도별", 1, SIDO)],
              "items": [("T1", "경제활동인구", "천명"), ("T2", "취업자", "천명"), ("T3", "경제활동참가율", "%")],
              "prd": ("년", "2022", "2024"), "cmmt": [{"CMMT_DC": "15세 이상 인구 대상 표본조사 연간 평균"}],
              "path": "경제활동인구조사 > 고용"})
    # T5 국내인구이동 월별 — 순이동은 음수·0 포함
    recs = []
    for m in range(1, 7):
        prd = f"2024{m:02d}"
        for code, nm, _ in SIDO:
            if code == "00":
                continue
            inn = 10_000 + _h("in", code, m) % 40_000
            out = inn + (_h("net", code, m) % 3000) - 1500
            if (code, m) == ("30", 3):
                out = inn                    # 순이동 0
            for itm, val in ((("T10", "총전입", "명"), inn), (("T20", "총전출", "명"), out), (("T30", "순이동", "명"), inn - out)):
                recs.append(_rec("101", "DT_DEMO_MOVE_M", "시도별 이동자수(월)", [("행정구역(시도)별", code, nm)], itm, "M", prd,
                                 _fmt(val)))
    T.append({"key": "101_DT_DEMO_MOVE_M", "survey": "국내인구이동통계", "section": "시도별 이동", "records": recs,
              "levels": [("A", "행정구역(시도)별", 1, [s for s in SIDO if s[0] != "00"])],
              "items": [("T10", "총전입", "명"), ("T20", "총전출", "명"), ("T30", "순이동", "명")],
              "prd": ("월", "202401", "202406"), "cmmt": [], "path": "국내인구이동통계 > 시도별 이동"})
    # T6 국내인구이동 분기별 — PRD_DE 202401/202402 (분기) : 월별 202401 과 문자열이 같지만 다른 기간. RAW 없이 store parquet
    recs = []
    for q in (1, 2):
        prd = f"2024{q:02d}"
        for code, nm, _ in SIDO[1:]:
            inn = 40_000 + _h("qin", code, q) % 90_000
            recs.append(_rec("101", "DT_DEMO_MOVE_Q", "시도별 이동자수(분기)", [("행정구역(시도)별", code, nm)],
                             ("T10", "총전입", "명"), "Q", prd, _fmt(inn)))
    T.append({"key": "101_DT_DEMO_MOVE_Q", "survey": "국내인구이동통계", "section": "시도별 이동(분기)", "records": recs,
              "levels": [("A", "행정구역(시도)별", 1, SIDO[1:])], "items": [("T10", "총전입", "명")],
              "prd": ("분기", "202401", "202402"), "cmmt": [], "path": "국내인구이동통계 > 분기", "store_only": True})
    # T7 장래인구추계 — C1 = 시나리오, C2 = 시도 (C1 이 지역이 아님)
    recs = []
    scen = [("1", "중위 추계", None), ("2", "고위 추계", None)]
    for y in range(2023, 2027):
        for sc, snm, _ in scen:
            for code, nm, _ in SIDO:
                f = 1.0 if sc == "1" else 1.004
                val = sum(_pop(c, y) for c in BASE_POP) if code == "00" else _pop(code, y)
                val = int(val * f * (1 + (_h("proj", code, y) % 7) / 1000))
                recs.append(_rec("101", "DT_DEMO_PROJ", "시도별 추계인구", [("시나리오별", sc, snm), ("시도별", code, nm)],
                                 ("T1", "추계인구", "명"), "A", str(y), _fmt(val)))
    T.append({"key": "101_DT_DEMO_PROJ", "survey": "장래인구추계", "section": "시도편", "records": recs,
              "levels": [("S", "시나리오별", 1, scen), ("A", "시도별", 2, SIDO)], "items": [("T1", "추계인구", "명")],
              "prd": ("년", "2023", "2026"), "cmmt": [{"CMMT_DC": "2022년 기준 장래인구추계 (7월 1일 기준)"}],
              "path": "장래인구추계 > 시도편"})
    # T8 외국인주민 — 메타 JSON 없음 (raw only), 다른 모집단 → Hard Negative 후보
    recs = []
    for y in (2022, 2023, 2024):
        for code, nm, _ in SIDO:
            val = sum(int(_pop(c, y) * 0.04) for c in BASE_POP) if code == "00" else int(_pop(code, y) * 0.04)
            recs.append(_rec("101", "DT_DEMO_FOREIGN", "시도별 외국인주민 수", [("행정구역(시도)별", code, nm)],
                             ("T1", "외국인주민수", "명"), "A", str(y), _fmt(val)))
    T.append({"key": "101_DT_DEMO_FOREIGN", "survey": "외국인주민현황", "section": "외국인주민", "records": recs,
              "levels": [], "items": [], "prd": None, "cmmt": [], "path": "외국인주민현황", "no_meta": True})
    # T9 시군구 인구 — '중구' 가 서울(11140)·부산(26110) 두 곳 (같은 이름, 다른 코드)
    sgg = [("11", "서울특별시", None), ("11110", "종로구", "11"), ("11140", "중구", "11"), ("26", "부산광역시", None),
           ("26110", "중구", "26"), ("26140", "서구", "26")]
    sgg_base = {"11110": 139_000, "11140": 121_000, "26110": 39_000, "26140": 103_000}
    recs = []
    for y in (2023, 2024):
        vals = {c: int(v * (1 - 0.01 * (y - 2023)) + _h("sgg", c, y) % 500) for c, v in sgg_base.items()}
        vals["11"] = vals["11110"] + vals["11140"]
        vals["26"] = vals["26110"] + vals["26140"]
        for code, nm, _ in sgg:
            recs.append(_rec("101", "DT_DEMO_SGG", "시군구별 인구", [("행정구역(시군구)별", code, nm)],
                             ("T1", "인구", "명"), "A", str(y), _fmt(vals[code])))
    T.append({"key": "101_DT_DEMO_SGG", "survey": "주민등록인구현황", "section": "시군구", "records": recs,
              "levels": [("A", "행정구역(시군구)별", 1, sgg)], "items": [("T1", "인구", "명")], "prd": ("년", "2023", "2024"),
              "cmmt": [], "path": "주민등록인구현황 > 시군구"})
    # T10 시군구 가구 — 다른 코드 체계: 11140 이 '용산구' (이름 충돌 → 코드 체계 불일치)
    sgg2 = [("11010", "종로구", None), ("11020", "중구", None), ("11140", "용산구", None), ("21010", "중구", None),
            ("21020", "서구", None)]
    recs = [_rec("101", "DT_DEMO_SGG_HH", "시군구별 일반가구", [("행정구역별(시군구)", c, n)], ("T1", "일반가구", "가구"), "A",
                 "2024", _fmt(20_000 + _h("hh2", c) % 40_000)) for c, n, _ in sgg2]
    T.append({"key": "101_DT_DEMO_SGG_HH", "survey": "인구총조사", "section": "시군구 가구", "records": recs,
              "levels": [("A", "행정구역별(시군구)", 1, sgg2)], "items": [("T1", "일반가구", "가구")], "prd": ("년", "2024", "2024"),
              "cmmt": [], "path": "인구총조사 > 시군구"})
    # T11 같은 좌표 중복 행 (산업 분류 컬럼이 빠진 수집본) → 다대다 Join 행 증폭
    recs = []
    for y in (2023, 2024):
        for code, nm, _ in SIDO[1:]:
            for k in (1, 2):
                recs.append(_rec("101", "DT_DEMO_DUP", "시도별 종사자수", [("시도별", code, nm)], ("T1", "종사자수", "명"), "A",
                                 str(y), _fmt(int(_pop(code, y) * (0.2 if k == 1 else 0.25)))))
    T.append({"key": "101_DT_DEMO_DUP", "survey": "전국사업체조사", "section": "종사자", "records": recs,
              "levels": [("A", "시도별", 1, SIDO[1:])], "items": [("T1", "종사자수", "명")], "prd": ("년", "2023", "2024"),
              "cmmt": [], "path": "전국사업체조사"})
    # T12 대체 Positive: T1 총인구수와 같은 값의 구 표 (2023~2024)
    recs = [dict(r, TBL_ID="DT_DEMO_POP_OLD", TBL_NM="행정구역(시도)별 총인구(구 표)") for r in T[0]["records"]
            if r["ITM_ID"] == "T20" and r["PRD_DE"] in ("2023", "2024")]
    T.append({"key": "101_DT_DEMO_POP_OLD", "survey": "주민등록인구현황", "section": "주민등록인구(구)", "records": recs,
              "levels": [("A", "행정구역(시도)별", 1, regions)], "items": [("T20", "총인구수", "명")], "prd": ("년", "2023", "2024"),
              "cmmt": [{"CMMT_DC": "매년 12월 31일 기준 주민등록인구 (구 표, 신규 표로 이관)"}],
              "path": "주민등록인구현황 > 주민등록인구 > 구 표", "also_in": "101_DT_DEMO_POP"})
    # T13 결측 기호 모음 ("" / NaN) — 일부 항목이 비어 있는 표
    recs = []
    for y in (2023, 2024):
        for code, nm, _ in SIDO:
            dt = "" if code == "29" else ("NaN" if code == "26" and y == 2023 else _fmt(int(_pop(code, y) * 0.001) if code != "00"
                                                                                    else int(sum(_pop(c, y) for c in BASE_POP) * 0.001)))
            recs.append(_rec("101", "DT_DEMO_SPARSE", "시도별 사망자수(잠정)", [("시도별", code, nm)], ("T1", "사망자수", "명"), "A",
                             str(y), dt))
    T.append({"key": "101_DT_DEMO_SPARSE", "survey": "인구동향조사", "section": "사망", "records": recs,
              "levels": [("A", "시도별", 1, SIDO)], "items": [("T1", "사망자수", "명")], "prd": ("년", "2023", "2024"),
              "cmmt": [{"CMMT_DC": "잠정치. 빈 칸은 미집계"}], "path": "인구동향조사 > 사망"})
    return T


def _write_if_changed(path: Path, data: bytes):
    """내용이 같으면 파일을 건드리지 않음 (수정 시각 유지 → 인덱스 캐시가 그대로 유효)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    path.write_bytes(data)


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def build_demo_dataset(root: str | Path = DEFAULT_DEMO_ROOT, overwrite: bool = True) -> dict:
    root = Path(root)
    if root.exists() and (root / "catalog.csv").exists() and not overwrite:
        return {"root": str(root), "created": False}
    tables = build_tables()
    cat_rows = []
    for t in tables:
        org, tbl = t["key"].split("_", 1)
        tbl_nm = t["records"][0]["TBL_NM"]
        cat_rows.append({"category": t["survey"], "section": t["section"], "path": t["path"], "depth": 2, "org_id": org,
                         "tbl_id": tbl, "tbl_nm": tbl_nm, "stat_id": "1", "send_de": "2026-10-01", "rec_tbl": "",
                         "root": "인구", "is_sample": False, "is_full": "전수" in t["path"],
                         "survey_type": "전수부문" if "전수" in t["path"] else "구분없음(전체집계)", "selected": True,
                         "related_hint": "", "dup": bool(t.get("also_in")), "also_in": t.get("also_in", "")})
        df = pd.DataFrame(t["records"])
        if t.get("store_only"):
            p = root / "store" / "data" / f"{t['key']}.parquet"
            tidy = pd.DataFrame({"table_key": t["key"], "prd_se": df["PRD_SE"], "prd_de": df["PRD_DE"],
                                 "c1_code": df["C1"], "c1_name": df["C1_NM"], "c1_obj_nm": df["C1_OBJ_NM"],
                                 "itm_id": df["ITM_ID"], "itm_nm": df["ITM_NM"], "unit": df["UNIT_NM"],
                                 "value_raw": df["DT"]})
            import io
            buf = io.BytesIO()
            tidy.to_parquet(buf, index=False)
            _write_if_changed(p, buf.getvalue())
        else:
            _write_if_changed(root / "raw" / t["survey"] / f"{t['key']}.csv", _csv_bytes(df))
        if not t.get("no_meta"):
            itm = []
            for obj_id, obj_nm, sn, codes in t["levels"]:
                itm += _itm_rows(obj_id, obj_nm, sn, codes)
            itm += _items_meta(t["items"])
            se, a, b = t["prd"]
            meta = {"TBL": [{"TBL_NM": tbl_nm}], "ITM": itm, "PRD": [{"PRD_SE": se, "STRT_PRD_DE": a, "END_PRD_DE": b}],
                    "CMMT": t["cmmt"], "SOURCE": [{"JOSA_NM": f"「{t['survey']}」"}]}
            _write_if_changed(root / "meta" / f"{t['key']}.json", json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    _write_if_changed(root / "catalog.csv", _csv_bytes(pd.DataFrame(cat_rows)))
    # 방식 A: 저장된 View — T1 2024 총인구수 중 서울·부산·대구만 (원본 행 번호 _src_row 포함)
    t1 = pd.DataFrame(tables[0]["records"])
    t1["_src_row"] = range(1, len(t1) + 1)
    sv = t1[(t1["ITM_ID"] == "T20") & (t1["PRD_DE"] == "2024") & t1["C1"].isin(["11", "26", "27"])]
    _write_if_changed(root / "stored_views" / "101_DT_DEMO_POP" / "pop_2024_selected_sido.csv", _csv_bytes(sv))
    return {"root": str(root), "created": True, "n_tables": len(tables), "stored_views": 1}


def main():  # pragma: no cover
    ap = argparse.ArgumentParser(description="가상 KOSIS 데이터 생성")
    ap.add_argument("--out", default=str(DEFAULT_DEMO_ROOT))
    args = ap.parse_args()
    print(json.dumps(build_demo_dataset(args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
