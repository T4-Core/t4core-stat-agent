"""[NEW] 테스트용 가짜 KOSIS 수집 결과 + HCX 대역(mock)

실제 kosis_data 와 같은 폴더 모양(catalog.csv, meta/*.json, raw/<조사>/*.csv)을 작게 만들어
경로 해석·모듈 연결·입출력 계약을 API 키·네트워크 없이 확인한다.
"""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

SIDO = [("00", "전국", ""), ("11", "서울특별시", "00"), ("22", "대구광역시", "00"), ("25", "대전광역시", "00")]


def _itm(obj_id, obj_nm, sn, codes):
    return [{"OBJ_ID": obj_id, "OBJ_NM": obj_nm, "OBJ_ID_SN": str(sn), "ITM_ID": c, "ITM_NM": n, "UP_ITM_ID": up}
            for c, n, up in codes]


def _items(items):
    return [{"OBJ_ID": "ITEM", "OBJ_NM": "항목", "ITM_ID": i, "ITM_NM": n, "UNIT_NM": u} for i, n, u in items]


TABLES = [
    {  # 연간, 지역 × 항목(성별이 항목 이름에)
        "org_id": "101", "tbl_id": "DT_1B040A3", "tbl_nm": "행정구역(시군구)별, 성별 인구수",
        "category": "주민등록인구현황", "section": "주민등록인구", "josa": "주민등록인구현황",
        "levels": [("A", "행정구역(시군구)별", SIDO)],
        "items": [("T20", "총인구수", "명"), ("T21", "남자인구수", "명"), ("T22", "여자인구수", "명")],
        "prd_se": "A", "prd_meta": "년", "periods": [str(y) for y in range(2021, 2026)],
    },
    {  # 5년 주기, 지역 × 성별 × 연령
        "org_id": "101", "tbl_id": "DT_1IN1503", "tbl_nm": "성 및 연령별 인구",
        "category": "인구총조사", "section": "인구부문", "josa": "인구총조사",
        "levels": [("A", "행정구역별(시도)", SIDO[:1] + SIDO[2:]),
                   ("B", "성별", [("0", "계", ""), ("1", "남자", "0"), ("2", "여자", "0")]),
                   ("C", "연령별", [("000", "합계", ""), ("020", "20~24세", "000"), ("025", "25~29세", "000"),
                                  ("065", "65세 이상", "000")])],
        "items": [("T00", "인구", "명")],
        "prd_se": "A", "prd_meta": "5년", "periods": ["2015", "2020", "2025"],
    },
    {  # 월간 — Record.source.period(연도) ↔ prd_de(YYYYMM) 불일치 확인용
        "org_id": "101", "tbl_id": "DT_1B26001", "tbl_nm": "시도별 이동자수",
        "category": "국내인구이동통계", "section": "시도별 이동", "josa": "국내인구이동통계",
        "levels": [("A", "행정구역(시도)별", SIDO)],
        "items": [("T10", "총전입", "명"), ("T20", "총전출", "명")],
        "prd_se": "M", "prd_meta": "월", "periods": [f"{y}{m:02d}" for y in (2024, 2025) for m in range(1, 13)],
    },
    {  # catalog.csv 에는 있지만 selected=False (메타 JSON 은 있음) → 개인 카탈로그 'catalog_csv' 경로
        "org_id": "101", "tbl_id": "DT_1B83A35", "tbl_nm": "시도별 혼인건수",
        "category": "인구동향조사", "section": "혼인", "josa": "인구동향조사",
        "levels": [("A", "행정구역(시도)별", SIDO)],
        "items": [("T1", "혼인건수", "건")],
        "prd_se": "A", "prd_meta": "년", "periods": ["2023", "2024", "2025"], "selected": False,
    },
    {  # catalog.csv 에도 없고 메타 JSON 도 없는 raw CSV 만 → 'data_only' 경로
        "org_id": "101", "tbl_id": "DT_1B81A01", "tbl_nm": "시도별 출생아수",
        "category": "인구동향조사", "section": "출생", "josa": "인구동향조사",
        "levels": [("A", "행정구역(시도)별", SIDO)],
        "items": [("T1", "출생아수", "명")],
        "prd_se": "A", "prd_meta": "년", "periods": ["2023", "2024", "2025"], "catalog": False, "meta": False,
    },
]


def build(data_dir):
    """data_dir 아래에 catalog.csv / meta / raw 생성"""
    data_dir = Path(data_dir)
    rows = []
    for t in TABLES:
        key = f"{t['org_id']}_{t['tbl_id']}"
        if t.get("catalog", True):  # catalog.csv 에 행을 넣을지
            rows.append({"category": t["category"], "section": t["section"], "path": f"{t['category']} > {t['section']}",
                     "depth": 2, "org_id": t["org_id"], "tbl_id": t["tbl_id"], "tbl_nm": t["tbl_nm"],
                     "stat_id": "1", "send_de": "2026-01-01", "rec_tbl": "", "root": "인구", "is_sample": False,
                     "is_full": False, "survey_type": "구분없음(전체집계)", "selected": t.get("selected", True), "related_hint": "",
                     "dup": False, "also_in": ""})
        itm = []
        for sn, (oid, onm, codes) in enumerate(t["levels"], 1):
            itm += _itm(oid, onm, sn, codes)
        itm += _items(t["items"])
        meta = {"TBL": [{"TBL_NM": t["tbl_nm"]}], "ITM": itm,
                "PRD": [{"PRD_SE": t["prd_meta"], "STRT_PRD_DE": t["periods"][0], "END_PRD_DE": t["periods"][-1]}],
                "CMMT": [], "SOURCE": [{"JOSA_NM": f"「{t['josa']}」"}]}
        (data_dir / "meta").mkdir(parents=True, exist_ok=True)
        if t.get("meta", True):  # 메타 JSON 을 만들지
            (data_dir / "meta" / f"{key}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        # 원본: 모든 분류 조합 × 항목 × 시점
        combos = [{}]
        for i, (oid, onm, codes) in enumerate(t["levels"], 1):
            combos = [{**c, f"C{i}": code, f"C{i}_OBJ_NM": onm, f"C{i}_NM": nm} for c in combos for code, nm, _ in codes]
        recs = []
        for c in combos:
            for itm_id, itm_nm, unit in t["items"]:
                for k, p in enumerate(t["periods"]):
                    seed = int(hashlib.md5(f"{key}{c}{itm_id}".encode()).hexdigest()[:6], 16)
                    recs.append({"ORG_ID": t["org_id"], "TBL_ID": t["tbl_id"], "TBL_NM": t["tbl_nm"], **c,
                                 "ITM_ID": itm_id, "ITM_NM": itm_nm, "UNIT_NM": unit, "PRD_SE": t["prd_se"],
                                 "PRD_DE": p, "DT": str(10000 + seed % 90000 + k * 37), "LST_CHN_DE": "2026-01-01"})
        raw = data_dir / "raw" / t["category"] / f"{key}.csv"
        raw.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(recs).to_csv(raw, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(data_dir / "catalog.csv", index=False, encoding="utf-8-sig")
    return data_dir


# ── HCX 대역 ─────────────────────────────────────────────────────
def fake_vec(text, dim=256):
    """글자 2-gram 해시 벡터 (같은 단어가 많을수록 코사인 ↑)"""
    v = np.zeros(dim, dtype=np.float32)
    t = re.sub(r"\s+", "", str(text))
    for i in range(len(t) - 1):
        v[int(hashlib.md5(t[i:i + 2].encode()).hexdigest()[:8], 16) % dim] += 1
    return (v + 1e-3).tolist()


SLOTS = {   # 질문 속 단어 → HCX 가 돌려줄 슬롯 (재작성 모듈이 검증·보정함). 키 = 2-2 코드 추출 뒤에도 남는 단어
    # [CHANGED v3] 재작성 모듈 v3 응답 모양: slots.의도 = 목록, sub_questions[].의도 = 문자열 하나
    "대구의 남자": {"slots": {"시점": ["2025년"], "지역": ["대구광역시"], "대상": ["인구"], "성별": ["남자"],
                                       "연령": ["20~29세"], "지표": ["인구수"], "의도": ["값 조회"]}, "sub_questions": []},
    "대전의 인구 변화": {"slots": {"시점": ["2021년", "2022년", "2023년", "2024년", "2025년"],
                                        "지역": ["대전광역시"], "대상": ["인구"], "지표": ["인구수"], "의도": ["추이"]},
                                 "sub_questions": []},
    "대전 전입 이동자": {"slots": {"시점": ["2025년"], "지역": ["대전광역시"], "이동": ["전입"], "지표": ["이동자수"],
                                   "의도": ["추이"]}, "sub_questions": []},
    "인구랑 구별 인구 순위": {"slots": {"시점": ["2025년"], "지역": ["대전광역시"], "대상": ["인구"], "지표": ["인구수"],
                                       "비교축": ["시군구"], "의도": ["값 조회", "순위"]},
                             "sub_questions": [
                                 {"시점": ["2025년"], "지역": ["대전광역시"], "대상": ["인구"], "지표": ["인구수"], "의도": "값 조회"},
                                 {"시점": ["2025년"], "지역": ["대전광역시"], "대상": ["가구"], "지표": ["가구수"],
                                  "비교축": ["시군구"], "의도": "순위"}]},
    "무슨 뜻이야": {"slots": {"대상": ["합계출산율"], "의도": ["범위 밖"]}, "sub_questions": []},
}


def fake_hcx_post(path, body, timeout=60):
    """backend.core.llm._post 대역: 대화(슬롯 추출·답변)와 임베딩을 흉내"""
    if "embedding" in path:
        return {"embedding": fake_vec(body["text"])}
    sys_msg = body["messages"][0]["content"]
    user = body["messages"][-1]["content"]
    if "슬롯" in sys_msg:                                   # 재작성 2-3
        q = re.search(r"<question>(.*?)</question>", user, re.S).group(1)
        out = next((v for k, v in SLOTS.items() if k in q), {"slots": {"의도": "값 조회"}, "sub_questions": []})
        full = {k: [] for k in ["시점", "지역", "전출지", "전입지", "국적", "대상", "성별", "연령", "조건", "이동", "지표", "비교축"]}
        out = {"slots": {**full, **out["slots"]}, "sub_questions": [{**full, **x} for x in out["sub_questions"]]}
    elif "통계 안내원" in sys_msg:                           # 답변
        ids = re.findall(r"\[자료 id=([^\]]+)\]", user)
        num = next(iter(re.findall(r"\d{1,3}(?:,\d{3})+", user)), "0")
        out = {"answer": f"자료 기준 값은 {num}명입니다.", "summary": f"{num}명", "key_points": [f"{num}명"],
               "used_ids": ids[:1], "chart_id": ids[0] if ids else "", "insufficient": False}
    else:
        out = {"rewritten": user, "sub_questions": []}
    return {"message": {"content": json.dumps(out, ensure_ascii=False)}}


def fake_dense_post(text, timeout=60):
    """backend.rag.retrieval.dense._post 대역"""
    return fake_vec(text)
