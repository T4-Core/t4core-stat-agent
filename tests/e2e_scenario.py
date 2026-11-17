"""통합 파이프라인 시나리오 — tests/test_pipeline_e2e.py 가 별도 프로세스로 실행

    STORAGE_DIR=<임시폴더>/storage  (그 아래 kosis_data 에 fake_kosis.build 결과)
    python -m tests.e2e_scenario
"""
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

CALLS = {"chat": 0}


def counting_post(path, body, timeout=60):
    if "embedding" not in path:
        CALLS["chat"] += 1
    return fake_kosis.fake_hcx_post(path, body, timeout)


llm._post = counting_post

from backend.main import app  # noqa: E402

c = TestClient(app)
TODAY = "2026-11-02"


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:800]}"
    return r.json()


# 0) 경로가 STORAGE_DIR 아래로 해석됐는지
paths = ok(c.get("/api/v1/system/paths"))
assert paths["KOSIS_DATA_DIR"]["exists"], paths
assert Path(paths["KOSIS_DATA_DIR"]["path"]).parts[-2:] == ("storage", "kosis_data"), paths
print("[0] paths:", paths["KOSIS_DATA_DIR"]["path"])

# ⓪ 준비 한 번에: 메타 프로필 → 표 색인 → CSV 값 사전
ok(c.post("/api/v1/ingest/prepare", params={"workers": 2}))
for _ in range(300):
    st = ok(c.get("/api/v1/ingest/prepare/status"))
    if not st["running"]:
        break
    time.sleep(0.2)
assert st["error"] is None and st["result"]["index"]["n_tables"] == 3, st
assert st["result"]["csv_index"]["n_tables"] >= 3, st["result"]
health = ok(c.get("/health"))
assert health["meta_profiles"] and health["table_index"] and health["csv_index"], health
print("[⓪] prepare:", st["result"]["index"], st["result"]["csv_index"])

# ① 질의 분석 → view_bundle
q = "작년 대구의 남자 20대 인구 수"
a = ok(c.post("/api/v1/rag/analyze", json={"question": q, "today": TODAY, "query_id": "t1"}))
vf = a["view_bundle"]["filters"]
assert a["status"] == "ok" and a["trace"][0]["step"] == "재작성", a["status"]
assert vf["시점"] == [2025] and vf["연령"] == {"from": 20, "to": 29} and vf["지역"] == ["대구광역시"], vf
assert vf["의도"] == "값 조회" and a["view_bundle"]["query_id"] == "t1"
print("[①] filters:", vf, "| search_text:", a["view_bundle"]["search_text"])

# ② view_bundle → View 묶음 (충돌이면 첫 선택지)
vs = ok(c.post("/api/v1/rag/views", json={"view_bundle": a["view_bundle"], "n_views": 2, "auto_select": "first"}))
assert vs["status"] == "ok" and vs["records"] and all(r["doc_type"] == "view" for r in vs["records"]), vs["status"]
age = next(r for r in vs["records"] if r["source"]["tbl_id"] == "DT_1IN1503")
assert age["table"]["rows"], age
print("[②] records:", [r["id"] for r in vs["records"]])

# ②-1 검색만
sr = ok(c.post("/api/v1/rag/search", json={"query": "대구 남자 20대 인구", "top_k": 3, "filters": vf}))
assert sr["candidates"] and sr["candidates"][0]["rank"] == 1, sr

# ③ Record 목록 → 답변
ans = ok(c.post("/api/v1/agent/answer", json={"question": q, "records": vs["records"]}))
assert ans["answer"] and ans["used_ids"] and ans["chart"]["rows"], ans
print("[③] answer:", ans["answer"], "| chart:", ans["chart"]["type"])

# ★ 한 번에
tq = "최근 5년간 대전의 인구 변화 추이"
full = ok(c.post("/api/v1/chat", json={"question": tq, "today": TODAY}))
assert full["status"] == "ok" and full["records"] and full["result"]["answer"], full["notes"]
assert full["analysis"]["view_bundle"]["filters"]["의도"] == "추이"
conf = full["views"]["units"][0]["conflict"]                          # 두 인구 표의 대전 값이 다름 → 첫 선택지로 답변
assert conf["status"] == "ambiguous" and conf["selected_option"] == "opt-1" and len(conf["options"]) >= 2, conf["status"]
assert all(r["metadata"]["view_type"] == "trend" for r in full["records"])
assert set(full["timings"]) >= {"analyze", "views", "answer", "total"}, full["timings"]
print("[★] chat timings:", full["timings"], "| records:", len(full["records"]), "| 충돌:", conf["clusters"])

# ★-0 auto_select=false → needs_selection → 선택지 골라 이어서 (분석·검색 다시 안 함)
p = ok(c.post("/api/v1/chat", json={"question": tq, "today": TODAY, "auto_select": False}))
assert p["status"] == "needs_selection" and p["result"] is None and p["views"]["pending"], p["status"]
pend = p["views"]["pending"][0]
pick = next(o for o in pend["options"] if "DT_1B040A3" in o["tbl_ids"])
n0 = CALLS["chat"]
s2 = ok(c.post("/api/v1/chat", json={"question": tq, "previous": p, "view_selections": [
    {"selection_token": pend["selection_token"], "option_id": pick["option_id"]}]}))
assert s2["status"] == "ok" and CALLS["chat"] == n0 + 1 and "select" in s2["timings"], (s2["status"], CALLS)
trend = next(r for r in s2["records"] if r["source"]["tbl_id"] == "DT_1B040A3")
assert trend["metadata"]["view_type"] == "trend" and trend["metadata"]["prd_from"] == "2021", trend["metadata"]
assert not any(r["source"]["tbl_id"] == "DT_1IN1503" for r in s2["records"])
print("[★-0] 선택:", pick["option_id"], pick["tbl_ids"], "→ records", [r["id"] for r in s2["records"]])

# ★-1 범위 밖 → 검색·답변 HCX 없이 안내
n0 = CALLS["chat"]
o = ok(c.post("/api/v1/chat", json={"question": "합계출산율이 무슨 뜻이야?"}))
assert o["status"] == "out_of_scope" and o["records"] == [] and o["views"] is None and o["result"]["insufficient"], o
assert CALLS["chat"] == n0 + 1                                       # 재작성 1회만

# ★-2 되묻기 → 이어서 (재작성 HCX 다시 안 부름)
cq = "출생아 수 알려줘"
m = ok(c.post("/api/v1/chat", json={"question": cq, "today": TODAY, "overrides": {"csv_scope": "all"}}))
assert m["status"] == "needs_clarification" and m["result"] is None, m["status"]
slots = {x["slot"] for x in m["analysis"]["clarifications"]}
assert {"시점", "지역"} <= slots, slots
n0 = CALLS["chat"]
m2 = ok(c.post("/api/v1/chat", json={"question": cq, "today": TODAY, "overrides": {"csv_scope": "all"}, "previous": m,
                                      "selections": {"지역": ["대전광역시"], "시점": ["2025년"]}}))
assert m2["status"] == "ok" and m2["analysis"]["view_bundle"]["filters"]["지역"] == ["대전광역시"], m2["status"]
assert CALLS["chat"] == n0 + 1, CALLS                                 # 답변 1회만
print("[★-2] 되묻기:", sorted(slots), "→ ok")

# ★-3 서브쿼리: 단위마다 의도 (값 조회 / 순위)
sub = ok(c.post("/api/v1/chat", json={"question": "2025년 대전 인구랑 구별 인구 순위", "today": TODAY}))
intents = [u["filters"]["의도"] for u in sub["views"]["units"]]
assert sub["status"] == "ok" and intents == ["값 조회", "순위"], intents
jr = ok(c.post("/api/v1/rag/judge/from-chat", json=sub))
assert jr["units"], jr
assert c.post("/api/v1/rag/judge/from-chat", json=o).status_code == 422     # 검색까지 안 간 응답
print("[★-3] 단위 의도:", intents, "| 판단:", jr["verdict"])

# ④ 좌표 재조회: 월간표 + 연도 시점 (year 열로 거름). 지표 '이동자수' 가 CSV 에 없어도 soft 모드는 멈추지 않음
mv = ok(c.post("/api/v1/chat", json={"question": "2025년 대전 전입 이동자 월별", "today": TODAY, "n_views": 3,
                                      "overrides": {"clarify_mode": "soft"}}))
assert mv["status"] == "ok" and mv["analysis"]["clarifications"], mv["status"]          # 되묻기 후보는 남김
mrec = next((r for r in mv["records"] if r["source"]["tbl_id"] == "DT_1B26001"), None)
assert mrec is not None, [r["id"] for r in mv["records"]]
assert mrec["source"]["period"] == {"in": ["2025"]} and len(mrec["table"]["rows"]) >= 12, mrec["source"]
n = ok(c.post("/api/v1/data/source", json=mrec["source"]))["n_rows"]
full_rec = ok(c.post("/api/v1/data/source", json=mrec))
assert n >= 12 and full_rec["chart"]["type"] in ("line", "bar", "table"), (n, full_rec.get("chart"))
print(f"[④] 월간표 연도 좌표 → {n}행")

# ⑤ catalog.csv 선택 밖 표 · catalog/메타 둘 다 없는 raw CSV 도 View 생성
from backend.rag.ingestion.normalize import load_targets  # noqa: E402
from backend.rag.view.build import build_view  # noqa: E402

for tid, unit in (("DT_1B83A35", "건"), ("DT_1B81A01", "명")):
    row = next(load_targets([tid]).itertuples())
    assert row.category == "인구동향조사" and row.org_id == "101", row
    rec, vnotes = build_view(tid, {"지역": ["대전광역시"], "기간": {"years": [2025]}}, "t-1")
    vals = rec["table"]["rows"]
    assert vals and not vnotes and "대전" in str(vals), (tid, rec, vnotes)
    assert unit in str(rec["table"]) or unit in str(rec["metadata"]), rec
    print(f"[⑤] {tid} → {rec['id']} rows={len(vals)}")

# 일괄 실행 (synthetic_gold_pipeline.score_rag_results 입력 형식)
from backend.agent.batch import run_one  # noqa: E402

br = run_one({"id": "B1", "question": q}, TODAY, answer=True)
assert br["status"] == "ok" and br["final"]["records"] and br["answer"]["answer"], br
assert {s["slot"] for s in br["stages"]["query"]["slots"]} >= {"시점", "지역"}
assert br["units"][0]["candidates"][0]["rank"] == 1 and br["units"][0]["views"][0]["source"]["tbl_id"]
print("[batch]", br["status"], br["final"]["records"][:2])

# Swagger
spec = ok(c.get("/openapi.json"))
for p in ("/api/v1/ingest/prepare", "/api/v1/rag/analyze", "/api/v1/rag/clarify", "/api/v1/rag/views",
          "/api/v1/rag/views/select", "/api/v1/rag/search", "/api/v1/agent/answer", "/api/v1/chat", "/api/v1/data/source",
          "/api/v1/rag/judge", "/api/v1/csv-index/build"):
    assert p in spec["paths"], p
assert not [p for p in spec["paths"] if "/v4/" in p or "legacy" in p or "hybrid" in p], list(spec["paths"])
names = list(spec["components"]["schemas"])
assert not [n for n in names if "__" in n or n.endswith(("-Input", "-Output"))], names
assert c.get("/docs").status_code == 200
print("[swagger] paths:", len(spec["paths"]))
print(json.dumps({"E2E": "PASS"}))
