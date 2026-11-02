"""
표 설명문 + 표 색인 — ③ search 의 후보 검색용 (메타 프로필 → 표 설명문 + BM25 토큰)

설명문에 넣는 것 = "이 표가 무엇을 세었는가": 조사명 · 표 이름 · 분류(지역은 수준만) · 항목 · 단위 · 기간 · 메뉴 경로
설명문에 넣지 않는 것 = 지역 코드 수천 개, 연도 목록 — "어디·언제" 는 검색이 아니라 View 를 자를 때(슬롯) 정확히 처리

출력  view_model/output/table_index/
        ids.json        표 순서 (tbl_id)
        texts.jsonl     표 설명문
        tokens.json     BM25 용 형태소 토큰 (kiwi)
        meta.json       표 수·생성 시각

설명문 임베딩(bge-m3)은 여기서 미리 하지 않는다. 검색 때 BM25 로 뽑힌 10개만 그때 임베딩한다 (search.py, 캐시 사용)

실행  API : POST /search/index/build (백그라운드), GET /search/index/status
      CLI : cd view_model && ../.venv/Scripts/python.exe -m services.table_text     # 몇 초
"""
import json
import sys
import time
from datetime import datetime

from config import OUT
from services.meta_profile import load_meta_profiles

INDEX = OUT / "table_index"
SMALL_LEVEL = 30                # 코드가 이 수 이하인 분류는 코드 이름까지 설명문에 (성별·시나리오·종류 …)
TOKEN_TAGS = ("NN", "SL", "SN", "XR", "VV", "VA")   # 명사·외국어·숫자·어근·동사·형용사 (공용 코드와 같은 기준)
GEO_ORDER = ["전국", "시도", "시군구", "읍면동", "동읍면부"]


def level_text(l):
    if l["kind"] == "regions":
        lv = [g for g in GEO_ORDER if g in (l.get("geo_types") or {}) and g != "전국"]
        return f"{l['obj_nm']}({'·'.join(lv) or '지역'})"
    if l["n_codes"] <= SMALL_LEVEL:
        return f"{l['obj_nm']}({', '.join(l['names'][:15])})"
    return f"{l['obj_nm']}({l['n_codes']}개: {', '.join(l['names'][:8])} …)"


def table_text(p):
    years = [f"{x['se_raw']} {x['year_from']}~{x['year_to']}" for x in p["periods"] if x.get("year_from")]
    items = [i["name"] for i in p["items"]]
    parts = [f"{p['survey_nm']} | {p['tbl_nm']}",
             "분류: " + " / ".join(level_text(l) for l in p["levels"]) if p["levels"] else "",
             "항목: " + ", ".join(items[:30]) + (f" 외 {len(items) - 30}개" if len(items) > 30 else "") if items else "",
             "단위: " + ", ".join(p["units"]) if p["units"] else "",
             "기간: " + "; ".join(years) if years else "",
             "경로: " + (p.get("path") or "")]
    return "\n".join(x for x in parts if x)[:1500]


_kiwi = None


def tokenize(text):
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return [t.form for t in _kiwi.tokenize(text) if t.tag.startswith(TOKEN_TAGS)]


def build_index(progress=print):
    profs = [p for p in load_meta_profiles() if p["raw"]["exists"]]   # 원본 없는 표는 골라도 정규화 불가 → 제외
    ids = [p["tbl_id"] for p in profs]
    texts = [table_text(p) for p in profs]
    progress(f"표 {len(ids)}개 설명문 생성 (원본 없는 표 제외)")
    t0 = time.time()
    tokens = [tokenize(t) for t in texts]
    progress(f"BM25 토큰 완료 ({time.time() - t0:.1f}초)")
    INDEX.mkdir(parents=True, exist_ok=True)
    (INDEX / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    with (INDEX / "texts.jsonl").open("w", encoding="utf-8") as f:
        for i, t in zip(ids, texts):
            f.write(json.dumps({"tbl_id": i, "text": t}, ensure_ascii=False) + "\n")
    (INDEX / "tokens.json").write_text(json.dumps(tokens, ensure_ascii=False), encoding="utf-8")
    meta = {"n_tables": len(ids), "created": datetime.now().isoformat(timespec="seconds")}
    (INDEX / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(f"표 색인 저장 → {INDEX}  ({meta})")
    return meta


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    build_index(progress=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
