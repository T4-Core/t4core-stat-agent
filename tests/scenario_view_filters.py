"""View 가 질의 분석 결과를 어떻게 자르는가 — tests/test_view_filters.py 가 별도 프로세스로 실행 (가짜 KOSIS)

  ① '2023년 전국과 서울의 혼인건수 비교' 류: 지역 ['전국', '서울특별시'] → 전국 합계 행 + 서울 행
  ② '혼인건수가 가장 적은 해는?' 류: 비교축 연도 · 의도 순위 · 시점 없음 → 표의 수록 기간 전체 (예전: 최신 1행)
"""
import json
import time

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post

from backend.main import app  # noqa: E402
from backend.rag.view.build import build_view  # noqa: E402
from backend.rag.view.viewset import build_viewset  # noqa: E402

c = TestClient(app)
c.post("/api/v1/ingest/prepare", params={"workers": 2})
while c.get("/api/v1/ingest/prepare/status").json()["running"]:
    time.sleep(0.2)

# ① 전국 + 다른 지역 (DT_1B040A3: 전국 · 서울 · 대구 · 대전, 2021~2025)
f1 = {"시점": [2023], "지역": ["전국", "서울특별시"], "지표": ["인구수"], "의도": "비교"}
rec, notes = build_view("DT_1B040A3", f1, "v-1")
regions = {r[1] for r in rec["table"]["rows"]}
assert regions == {"전국", "서울특별시"}, rec["table"]["rows"]
assert not [n for n in notes if n["slot"] == "지역"], notes
rec_only, _ = build_view("DT_1B040A3", {**f1, "지역": ["서울특별시"]}, "v-2")
assert {r[1] for r in rec_only["table"]["rows"]} == {"서울특별시"}              # 지역만 → 그대로
rec_nat, _ = build_view("DT_1B040A3", {k: v for k, v in f1.items() if k != "지역"}, "v-3")
assert {r[1] for r in rec_nat["table"]["rows"]} == {"전국"}                     # 지역 없음(전국만) → 전국 합계
print("[①] 전국 + 서울:", sorted(regions))

# 묶음까지: 판단·충돌 판정이 전국 행을 '조건 못 맞춤' 으로 보지 않음
def cands(*tbls):
    return lambda query, top_k=10, filters=None, question=None, unit="main": [
        {"rank": i, "tbl_id": t, "tbl_nm": t, "survey_nm": "", "score": 1.0 / i} for i, t in enumerate(tbls, 1)]


VB = {"query_id": "nat", "original": "2023년 전국과 서울의 인구 비교", "rewritten": "2023년 전국 서울특별시 인구수 비교",
      "filters": f1, "sub_questions": [], "sub_filters": None, "search_text": "인구수"}
vs = build_viewset(VB, search_fn=cands("DT_1B040A3"))
assert vs["status"] == "ok" and vs["units"][0]["conflict"]["views"][0]["usable"], vs["units"][0]["conflict"]
assert {r[1] for r in vs["records"][0]["table"]["rows"]} == {"전국", "서울특별시"}

# ② 해끼리 비교인데 시점 없음 → 수록 기간 전체
f2 = {"지역": ["전국"], "지표": ["인구수"], "비교축": "연도", "의도": "순위"}
rec2, notes2 = build_view("DT_1B040A3", f2, "v-4")
years = sorted({r[0] for r in rec2["table"]["rows"]})
assert years == ["2021", "2022", "2023", "2024", "2025"], years
assert not [n for n in notes2 if n["slot"] == "시점"], notes2            # 바꾼 값이 아니라 메모 없음
rec3, _ = build_view("DT_1B040A3", {**f2, "비교축": None}, "v-5")
assert {r[0] for r in rec3["table"]["rows"]} == {"2025"}                 # 비교축이 연도가 아니면 지금처럼 최신 해
rec4, _ = build_view("DT_1B040A3", {**f2, "시점": [2023, 2024]}, "v-6")
assert {r[0] for r in rec4["table"]["rows"]} == {"2023", "2024"}         # 기간을 적으면 그 기간
vs2 = build_viewset({**VB, "query_id": "yr", "original": "인구가 가장 적은 해는?", "filters": f2}, search_fn=cands("DT_1B040A3"))
chk = vs2["units"][0]["conflict"]["views"][0]["checks"]
assert chk["의도"]["status"] == "match" and "해끼리" in chk["의도"]["evidence"], chk["의도"]
assert len({r[0] for r in vs2["records"][0]["table"]["rows"]}) == 5
chk1 = vs["units"][0]["conflict"]["views"][0]["checks"]
assert chk1["지역"]["status"] == "match" and chk1["의도"]["status"] == "match", (chk1["지역"], chk1["의도"])   # 전국 + 서울 = 비교 대상 2개
print("[②] 비교축 연도 · 시점 없음:", years, "| 판단:", chk["의도"]["evidence"])
print(json.dumps({"VIEW_FILTERS": "PASS"}, ensure_ascii=False))
