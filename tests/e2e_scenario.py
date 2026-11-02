"""[NEW] 통합 Swagger 시나리오 — tests/test_pipeline_e2e.py 가 별도 프로세스로 실행 (환경변수로 저장소 위치를 바꾸기 위해)

    STORAGE_DIR=<임시폴더>/storage  (그 아래 kosis_data 에 fake_kosis.build 결과)
    python -m tests.e2e_scenario
"""
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.core.llm as llm
import backend.rag.retrieval.dense as dense
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post            # HCX 대화·임베딩 대역
dense._post = fake_kosis.fake_dense_post        # View 모듈 임베딩 대역

from backend.core import config  # noqa: E402
from backend.main import app  # noqa: E402

c = TestClient(app)


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:800]}"
    return r.json()


# 0) 경로가 환경변수 STORAGE_DIR 아래로 해석됐는지
paths = ok(c.get("/api/v1/system/paths"))
assert paths["KOSIS_DATA_DIR"]["exists"], paths
assert Path(paths["KOSIS_DATA_DIR"]["path"]).parts[-2:] == ("storage", "kosis_data"), paths   # Windows(\\) / posix(/) 모두
print("[0] paths:", paths["KOSIS_DATA_DIR"]["path"], "| VIEW_OUT_DIR:", paths["VIEW_OUT_DIR"]["path"])

# ⓪ 준비: 메타 프로필 → 표 색인
ok(c.post("/api/v1/rag/chunk-and-index"))
for _ in range(100):
    st = ok(c.get("/api/v1/rag/chunk-and-index/status"))
    if not st["running"]:
        break
    time.sleep(0.2)
assert st["error"] is None and st["result"]["index"]["n_tables"] == 3, st
print("[⓪] chunk-and-index:", st["result"]["index"])

# ① 재작성 → view_bundle (입출력 변환 확인)
q = "작년 대구의 남자 20대 인구 수"
rw = ok(c.post("/api/v1/rag/query-rewrite", json={"question": q, "today": "2026-11-02", "query_id": "t1"}))
vf = rw["view_bundle"]["filters"]
assert rw["bundle"]["filters"]["시점"] == ["2025년"]                 # 재작성 모듈: 문자열
assert vf["시점"] == [2025] and vf["연령"] == {"from": 20, "to": 29}  # View 모듈: int / {from,to}
assert vf["지역"] == ["대구광역시"] and vf["의도"] == "값 조회"
print("[①] bundle.filters:", rw["bundle"]["filters"], "\n    view_bundle.filters:", vf, "\n    search_text:",
      rw["view_bundle"]["search_text"])

# ② view_bundle 그대로 → Record 목록
recs = ok(c.post("/api/v1/rag/views", json=rw["view_bundle"], params={"top_k": 3, "n_views": 2}))
assert recs and all(r["doc_type"] == "view" for r in recs)
age = next(r for r in recs if r["source"]["tbl_id"] == "DT_1IN1503")
assert age["table"]["rows"], age
print("[②] records:", [r["id"] for r in recs])
print("    ", age["table"]["columns"], age["table"]["rows"][:3])

# ③ Record 목록 그대로 → 답변
ans = ok(c.post("/api/v1/agent/answer", json={"question": q, "records": recs}))
assert ans["answer"] and ans["used_ids"] and ans["chart"]["rows"], ans
print("[③] answer:", ans["answer"], "| chart:", ans["chart"]["type"], ans["chart"]["x"], "| unverified:",
      ans["unverified_numbers"])

# ★ 전체 한 번에
full = ok(c.post("/api/v1/chat", json={"question": "최근 5년간 대전의 인구 변화 추이", "today": "2026-11-02"}))
assert full["view_bundle"]["filters"]["의도"] == "추이" and full["records"], full["notes"]
trend = next(r for r in full["records"] if r["source"]["tbl_id"] == "DT_1B040A3")
assert trend["metadata"]["view_type"] == "trend" and trend["metadata"]["prd_from"] == "2021", trend["metadata"]
print("[★] chat timings:", full["timings"], "| records:", len(full["records"]), "| chart:", full["result"]["chart"]["type"])

# ④ 좌표 재조회: 월간표 + 연도 시점 (입출력 보정 확인)
mv = ok(c.post("/api/v1/chat", json={"question": "2025년 대전 전입 이동자 월별", "today": "2026-11-02", "n_views": 3}))
mrec = next((r for r in mv["records"] if r["source"]["tbl_id"] == "DT_1B26001"), None)
assert mrec is not None, [r["id"] for r in mv["records"]]
assert mrec["source"]["period"] == {"in": ["2025"]}, mrec["source"]   # build_view 는 시점을 '연도'로 기록
assert len(mrec["table"]["rows"]) >= 12                              # 카드 자체에는 12개월 값이 있음
src = mrec["source"]
from backend.rag.ingestion.view_builder import load_view  # noqa: E402
before = len(load_view(src, config.VIEW_OUT_DIR))           # 예전 방식: prd_de('202501') vs '2025' → 0행
after = ok(c.post("/api/v1/data/source", json=src))["n_rows"]
assert before == 0 and after > 0, (before, after)
print(f"[④] 월간표 연도 좌표: load_view {before}행 → load_record_data {after}행")

# legacy: kosis_views(view_builder) → records.jsonl → 하이브리드 인덱스 → 검색·답변
import argparse  # noqa: E402

from backend.rag.ingestion import indexer, view_builder  # noqa: E402

va = argparse.Namespace(data=str(config.KOSIS_DATA_DIR), out=str(config.RAG_VIEWS_DIR), surveys=None, tables=None,
                        max_tables=None, force=False, kiwi=False, catalog=None, workers=1)
view_builder.stage_prepare(va)
view_builder.stage_views(va)
ia = argparse.Namespace(records=config.RAG_VIEWS_DIR / "records.jsonl", doc_type=None, limit=None, variant="base",
                        dense_mode="single", workers=2)
indexer.stage_index(ia)
hits = ok(c.post("/api/v1/rag/hybrid-search", json={"query": "대전 인구 추이", "k": 5}))
assert hits, hits
leg = ok(c.post("/api/v1/chat/legacy", json={"question": "대전 인구 추이", "k": 3, "use_rewrite": False}))
assert leg["answer"], leg
print("[legacy] hybrid hits:", [h["title"][:30] for h in hits[:3]], "| answer:", leg["answer"][:40])

# openapi 에 모든 단계가 한 문서로
spec = ok(c.get("/openapi.json"))
for p in ("/api/v1/rag/query-rewrite", "/api/v1/rag/views", "/api/v1/agent/answer", "/api/v1/chat",
          "/api/v1/rag/chunk-and-index", "/api/v1/rag/retrieve", "/api/v1/data/source"):
    assert p in spec["paths"], p
print("[swagger] paths:", len(spec["paths"]))
print(json.dumps({"E2E": "PASS"}))
