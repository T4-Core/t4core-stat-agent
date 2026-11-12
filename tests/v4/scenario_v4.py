"""[NEW v4] 쿼리 모듈 v4 시나리오 — tests/v4/test_query_v4.py 가 별도 프로세스로 실행 (저장소 위치를 환경변수로 바꾸기 위해)

가짜 KOSIS 데이터 + 추가 표(사망자수, 지역 없는 전국 표) + 메타 주석 → CSV 값 사전 → 동의어 → 접지 → 시점 규칙 →
되묻기 왕복(HCX 1회) → 서브쿼리 → view_bundle 을 기존 POST /api/v1/rag/views 에 그대로
"""
import json
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import backend.core.llm as llm
import backend.rag.retrieval.dense as dense
from tests import fake_kosis

CALLS = {"chat": 0}


def counting_post(path, body, timeout=60):
    if "embedding" not in path:
        CALLS["chat"] += 1
    return fake_kosis.fake_hcx_post(path, body, timeout)


llm._post = counting_post
dense._post = fake_kosis.fake_dense_post

from backend.core.config import CSV_INDEX_DIR, KOSIS_DATA_DIR  # noqa: E402
from backend.main import app  # noqa: E402

c = TestClient(app)
ALL = {"csv_scope": "all"}           # 가짜 데이터의 출생·혼인·사망 표는 catalog.csv selected 밖


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:1200]}"
    return r.json()


# ── 준비: 추가 표 + 메타 주석 ──────────────────────────────────────
kd = Path(KOSIS_DATA_DIR)
d = kd / "raw" / "인구동향조사"
b = pd.read_csv(d / "101_DT_1B81A01.csv", dtype=str, encoding="utf-8-sig")
b["TBL_ID"], b["TBL_NM"], b["ITM_NM"] = "DT_1B82A01", "시도별 사망자수", "사망자수"
b["DT"] = [str(30000 + i) for i in range(len(b))]
b.to_csv(d / "101_DT_1B82A01.csv", index=False, encoding="utf-8-sig")
meta_f = kd / "meta" / "101_DT_1B040A3.json"
meta = json.loads(meta_f.read_text(encoding="utf-8"))
meta["CMMT"] = [{"CMMT_NM": "통계표", "CMMT_DC": "주민등록 기준, 외국인 제외"},
                {"CMMT_NM": "항목", "ITM_NM": "총인구수", "CMMT_DC": "남자+여자"}]
meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

# ⓪ CSV 값 사전
s = ok(c.post("/api/v1/csv-index/build", json={"scope": "all", "workers": 2}))
assert s["n_tables"] == 6 and s["n_errors"] == 0 and s["by_slot"]["지역"] > 0, s
assert (Path(CSV_INDEX_DIR) / "values.parquet").exists()
t = ok(c.get("/api/v1/csv-index/tables/DT_1IN1503"))
assert [x["kind"] for x in t["dims"]] == ["regions", "sex", "ages"] and t["years"] == [2015, 2020, 2025], t["dims"]
assert {"20~24세", "65세 이상"} <= {v["name"] for v in t["dims"][2]["values"]}
t2 = ok(c.get("/api/v1/csv-index/tables/DT_1B040A3"))
assert {"type": "항목", "target": "총인구수", "text": "남자+여자"} in t2["footnotes"], t2["footnotes"]   # 주석 (Step 4 선택지 설명용)
assert {i["name"]: i["unit"] for i in t2["items"]}["총인구수"] == "명"
reg = ok(c.get("/api/v1/csv-index/values", params={"slot": "지역", "scope": "all"}))
assert {"전국", "대전광역시", "서울특별시"} <= {r["value"] for r in reg}
f = ok(c.get("/api/v1/csv-index/find", params={"text": "출생아 수", "scope": "all"}))
assert [(r["tbl_id"], r["kind"]) for r in f] == [("DT_1B81A01", "item")], f
s2 = ok(c.post("/api/v1/csv-index/build", json={"scope": "all"}))
assert s2["n_scanned"] == 0, s2                                      # 원본이 같으면 다시 스캔 안 함
print("[⓪] CSV 값 사전:", {k: s[k] for k in ("n_tables", "n_values", "by_slot")})

# 1-2 동의어 조회 계층
def look(text, slot="지표"):
    return ok(c.post("/api/v1/rag/v4/lexicon/lookup", json={"text": text, "slot": slot, "overrides": ALL}))
h = look("출생아 수")["hits"][0]
assert (h["value"], h["source"], h["grounded"]) == ("출생아수", "csv", True), h            # 띄어쓰기 변형
h = look("신생아 수")["hits"][0]
assert (h["value"], h["source"]) == ("출생아수", "term>csv"), h                            # term_dict → CSV
h = look("대구", "지역")["hits"][0]
assert (h["value"], h["source"], h["n_tables"]) == ("대구광역시", "rule", 6), h            # rule_dict
h = look("인구수")["hits"][0]
assert h["grounded"] and {"DT_1B040A3", "DT_1IN1503"} <= set(h["tables"]), h               # 포함 일치까지 표 집합
nf = look("출산아수")
assert not nf["hits"] or not nf["hits"][0]["grounded"]
assert "출생아수" in nf["suggestions"], nf                                                 # 비슷한 이름 제안
ok(c.post("/api/v1/rag/v4/lexicon/learn", json={"surface": "아기 수", "value": "출생아수"}))
assert "아기수" in ok(c.get("/api/v1/rag/v4/lexicon/pending"))
assert not look("아기 수")["hits"] or look("아기 수")["hits"][0]["source"] != "learned"     # 승인 전에는 안 씀
ok(c.post("/api/v1/rag/v4/lexicon/learn", json={"surface": "아기 수", "value": "출생아수", "approve": True}))
h = look("아기 수")["hits"][0]
assert (h["value"], h["source"]) == ("출생아수", "learned"), h
print("[1-2] 동의어: 띄어쓰기·term_dict·rule_dict·포함·제안·학습 ok")


def analyze(q, **kw):
    return ok(c.post("/api/v1/rag/v4/analyze", json={"question": q, "today": "2026-11-02",
                                                      "overrides": {**ALL, **kw.pop("overrides", {})}, **kw}))


# ① 정상: 슬롯 접지 + view_bundle
a = analyze("작년 대구의 남자 20대 인구 수", query_id="v4a")
assert a["status"] == "ok", a["clarifications"]
sl = a["slots"]
assert sl["시점"][0]["value"] == 2025 and sl["지역"][0]["value"] == "대구광역시" and sl["연령"][0]["value"] == {"from": 20, "to": 29}
assert sl["연령"][0]["tables"] == ["DT_1IN1503"]                                       # 20~29세와 겹치는 연령 분류가 있는 표
assert sl["지표"][0]["match"] == "variant" and a["view_bundle"]["filters"]["지표"] == ["인구수"]    # 표기 변형은 원래 값 유지
vb = a["view_bundle"]
assert vb["filters"]["시점"] == [2025] and vb["filters"]["연령"] == {"from": 20, "to": 29} and vb["query_id"] == "v4a"
assert "대구" not in vb["search_text"] and "2025" not in vb["search_text"], vb["search_text"]
assert [t["step"] for t in a["trace"]][0] == "1-1 재작성(v3)" and all("seconds" in t for t in a["trace"])
print("[1-3] 접지:", {k: v[0]["value"] for k, v in sl.items()}, "| 검색 문장:", vb["search_text"])

# ① 시점 규칙: '요즘' → 2026, '변화' → 2022~2026 (시점이 비었을 때만)
n0 = CALLS["chat"]
r1 = analyze("요즘 대전 출생아 수")
assert r1["status"] == "ok" and r1["slots"]["시점"][0]["value"] == 2026 and r1["applied_rules"][0].startswith("'요즘' → 2026년"), r1
assert r1["view_bundle"]["filters"]["지표"] == ["출생아수"] and any("질문 속 CSV 표현" in n for n in r1["notes"])   # 대상 보충
assert r1["slots"]["시점"][0]["note"]                                                       # 2026년 자료 없음 메모 (되묻지 않음)
r2 = analyze("대전 출생아 수 변화")
assert [x["value"] for x in r2["slots"]["시점"]] == [2022, 2023, 2024, 2025, 2026] and "변화" in r2["applied_rules"][0], r2
r3 = analyze("대전 출생아 수 변화", overrides={"base_year": 2025, "trend_years": 3})        # 설정 바꾸기 (overrides)
assert [x["value"] for x in r3["slots"]["시점"]] == [2023, 2024, 2025]
r4 = analyze("최근 3년 대전 출생아 수 추이")                                                 # 기간이 명시되면 재작성 모듈 해석 그대로
assert r4["applied_rules"] == [] and [x["value"] for x in r4["slots"]["시점"]] == [2023, 2024, 2025], r4["slots"]["시점"]
print("[1-4] 시점 규칙:", r1["applied_rules"], r2["applied_rules"])

# ① 되묻기 → 선택 → 이어서 (HCX 다시 안 부름)
q = "출생아 수 알려줘"
n0 = CALLS["chat"]
m = analyze(q)
assert m["status"] == "needs_clarification" and m["view_bundle"] is None
cl = {x["slot"]: x for x in m["clarifications"]}
assert set(cl) == {"시점", "지역"}, cl.keys()                                                # 대상(출생아수)은 접지됨
assert cl["지역"]["options"][0]["value"] == "전국" and "대전광역시" in [o["value"] for o in cl["지역"]["options"]]
assert cl["시점"]["options"][0]["value"].endswith("년") and any(o["value"] == "2025년" for o in cl["시점"]["options"])
assert CALLS["chat"] == n0 + 1
done = ok(c.post("/api/v1/rag/v4/clarify", json={"question": q, "previous": m, "overrides": ALL,
                                                  "selections": {"지역": ["대전광역시"], "시점": ["2025년"]}}))
assert done["status"] == "ok" and CALLS["chat"] == n0 + 1, (done["status"], CALLS)
assert done["view_bundle"]["filters"]["지역"] == ["대전광역시"] and done["view_bundle"]["filters"]["시점"] == [2025]
assert "알려줘" not in done["search_text"] and "값 조회" not in done["search_text"], done["search_text"]   # 의도 값은 검색어 아님
mt = analyze("2025년 대전 그거 수치")                                                       # 대상이 없음/못 찾음 → 대상 후보
ct = {x["slot"]: x for x in mt["clarifications"]}
assert "대상" in ct and len(ct["대상"]["options"]) >= 3, mt["clarifications"]
d2 = ok(c.post("/api/v1/rag/v4/clarify", json={"question": "2025년 대전 그거 수치", "previous": mt, "overrides": ALL,
                                                "selections": {"대상": [ct["대상"]["options"][0]["value"]]}}))
assert d2["status"] == "ok" and d2["view_bundle"]["filters"]["지표"] == [ct["대상"]["options"][0]["value"]]
print("[1-4] 되묻기:", list(cl), "→ 선택 → ok (HCX 1회)", "| 대상 후보:", [o["value"] for o in ct["대상"]["options"]][:5])

# ① 서브쿼리: 함께 가진 표가 없으면 지표별, 있으면 하나 / 재작성 모듈 하위 질문은 그대로
dd = ok(c.post("/api/v1/rag/v4/decompose", json={"question": "x", "overrides": ALL,
                                                  "slots": {"시점": ["2025년"], "지역": ["대전광역시"], "지표": ["출생아수", "사망자수"]}}))
assert [s["slots"]["지표"] for s in dd["sub_queries"]] == [["출생아수"], ["사망자수"]], dd
assert dd["sub_queries"][0]["candidate_tables"] == ["DT_1B81A01"] and "함께 가진 표가 없음" in dd["reason"]
d1 = ok(c.post("/api/v1/rag/v4/decompose", json={"question": "x", "overrides": {**ALL, "split_policy": "no_common_table"},
                                                  "slots": {"지역": ["대전광역시"], "지표": ["총인구수", "남자인구수"]}}))
assert d1["sub_queries"] == [] and "함께 가진 표 1개" in d1["reason"], d1                     # 같은 표에 둘 다 있음
# [NEW 11-12] 분리 정책 always: 같은 표에 둘 다 있어도 지표마다 서브쿼리 (후보 표는 함께 가진 표가 앞)
d1a = ok(c.post("/api/v1/rag/v4/decompose", json={"question": "x", "overrides": {**ALL, "split_policy": "always"},
                                                   "slots": {"시점": ["2021년", "2022년", "2023년"], "지역": ["대전광역시"],
                                                             "지표": ["총인구수", "남자인구수"]}}))
assert [s["slots"]["지표"] for s in d1a["sub_queries"]] == [["총인구수"], ["남자인구수"]], d1a
assert "분리 정책 always" in d1a["reason"] and d1a["sub_queries"][0]["text"].startswith("2021~2023년 "), d1a
d0 = ok(c.post("/api/v1/rag/v4/decompose", json={"question": "x", "overrides": ALL,
                                                  "slots": {"대상": ["인구"], "지표": ["인구수"]}}))
assert d0["sub_queries"] == [], d0                                                           # 대상 '인구' 는 지표 '인구수' 에 흡수
full = analyze("2025년 대전 출생아 수와 사망자 수 차이")
vb2 = full["view_bundle"]
assert full["status"] == "ok" and len(vb2["sub_questions"]) == 2 and [f["지표"] for f in vb2["sub_filters"]] == [["출생아수"], ["사망자수"]], full
sub3 = analyze("2025년 대전 인구랑 구별 인구 순위")
assert sub3["decompose_reason"].startswith("재작성 모듈") and len(sub3["view_bundle"]["sub_questions"]) == 2, sub3
assert [f.get("의도") for f in sub3["view_bundle"]["sub_filters"]] == ["값 조회", "순위"]
print("[1-5] 서브쿼리:", full["decompose_reason"], "|", sub3["decompose_reason"])

# [NEW 11-12] HCX 가 지표 이름을 지역 칸에, '추이'를 전출지 칸에 넣은 응답 (실제 사례) → 지표 3개로 바로잡아 3개로 나눔
YRS = [f"{y}년" for y in range(2021, 2026)]
fake_kosis.SLOTS["사망자수 추이"] = {"slots": {"시점": YRS, "지역": ["혼인건수", "출생아수", "사망자수"], "전출지": ["추이"],
                                             "의도": ["값 조회"]}, "sub_questions": []}
mis = analyze("2021~2025년 혼인건수와 출생아수 그리고 사망자수 추이")
assert mis["status"] == "ok", mis.get("clarifications") or mis["notes"]
assert mis["state"]["raw_slots"]["지역"] == ["전국"] and "전출지" not in mis["state"]["raw_slots"], mis["state"]["raw_slots"]
assert [x["slots"]["지표"] for x in mis["sub_queries"]] == [["혼인건수"], ["출생아수"], ["사망자수"]], mis["sub_queries"]
assert all(x["text"].startswith("2021~2025년 전국 ") for x in mis["sub_queries"]), [x["text"] for x in mis["sub_queries"]]
assert all(x["slots"]["시점"] == YRS for x in mis["sub_queries"]) and mis["state"]["intents"] == ["추이"]
print("[1-5] 지역 칸 지표 바로잡기:", mis["decompose_reason"], [x["text"] for x in mis["sub_queries"]])

oos = analyze("합계출산율이 무슨 뜻이야?")
assert oos["status"] == "out_of_scope" and oos["view_bundle"] is None

# ② 기존 /rag/views 에 view_bundle 그대로 (하위 호환)
ok(c.post("/api/v1/rag/chunk-and-index"))
for _ in range(150):
    st = ok(c.get("/api/v1/rag/chunk-and-index/status"))
    if not st["running"]:
        break
    time.sleep(0.2)
assert st["error"] is None, st
recs = ok(c.post("/api/v1/rag/views", json=a["view_bundle"], params={"top_k": 3, "n_views": 1}))
assert recs and recs[0]["table"]["rows"], recs[:1]
print("[②] view_bundle → /rag/views:", recs[0]["id"], len(recs[0]["table"]["rows"]), "행")
spec = ok(c.get("/openapi.json"))
assert "QueryAnalysis" in spec["components"]["schemas"] and "/api/v1/rag/v4/clarify" in spec["paths"]
schemas = spec.get("components", {}).get("schemas", {})
paths = spec.get("paths", {})

print("\n===== OpenAPI DEBUG =====")

print(
    "QueryAnalysis 존재:",
    "QueryAnalysis" in schemas
)

print(
    "clarify API 존재:",
    "/api/v1/rag/v4/clarify" in paths
)

print("\nQuery 관련 스키마:")
print([s for s in schemas if "Query" in s])

print("\nRAG 관련 API:")
print([p for p in paths if "rag" in p.lower()])

print(json.dumps({"V4": "PASS"}))
