"""View 가 요청을 못 맞출 때 — ①~③ 요청 지표가 없는 표('최근 30년 이민자 수' → 출생아수), ④ 요청 기간이 수록 기간 밖
tests/test_indicator_missing.py 가 별도 프로세스로 실행 (가짜 KOSIS 에 DT_1B8000F 모양의 표를 더해서)

  기본항목별 = 출생아수(명) · 사망자수(명) · 혼인건수(건) · 이혼건수(건)  (합계 코드 없음)
  항목      = '인구동태건수 및 동태율'  (항목 이름에 '인구' 가 있어도 지표가 맞은 것으로 보지 않아야 함)
"""
import json
import time

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

CALLS = {"chat": 0}


def post(path, body, timeout=60):
    if "embedding" not in path:
        CALLS["chat"] += 1
    return fake_kosis.fake_hcx_post(path, body, timeout)


llm._post = post

from backend.agent import pipeline  # noqa: E402
from backend.agent.modules import run_modules  # noqa: E402
from backend.main import app  # noqa: E402
from backend.rag.view.build import build_view  # noqa: E402
from backend.rag.view.viewset import build_viewset  # noqa: E402

c = TestClient(app)
c.post("/api/v1/ingest/prepare", params={"workers": 2})
while c.get("/api/v1/ingest/prepare/status").json()["running"]:
    time.sleep(0.2)

YEARS = list(range(2016, 2026))
FOREIGN = {"시점": YEARS, "지역": ["전국"], "대상": ["외국인"], "지표": ["인구수"], "의도": "추이"}

# ① View: 첫 코드로 바꿔치기하지 않고 missing + metadata.indicator_missing
rec, notes = build_view("DT_1B8000F", FOREIGN, "t-1")
assert rec["metadata"]["indicator_missing"] == ["기본항목별"], rec["metadata"]
miss = [n for n in notes if n["slot"] == "지표" and n["type"] == "missing"]
assert miss and "출생아수(명)" in miss[0]["text"] and miss[0]["applied"] == [], notes
assert not [n for n in notes if n["slot"] == "지표" and n["type"] == "default"], notes
print("[①] missing:", miss[0]["text"])

# 있는 지표를 물으면 예전처럼 그 코드를 고름
rec2, notes2 = build_view("DT_1B8000F", {**FOREIGN, "대상": ["혼인"], "지표": ["혼인건수"]}, "t-2")
assert "indicator_missing" not in rec2["metadata"] and {r[1] for r in rec2["table"]["rows"]} == {"혼인건수(건)"}, rec2["table"]["rows"][:3]
# 지표를 나누지 않는 분류(합계 없음)는 지금처럼 기본값 — 지표는 항목에서 맞춤
rec3, _ = build_view("DT_1B040A3", {"시점": [2025], "지역": ["대구광역시"], "지표": ["인구수"]}, "t-3")
assert "indicator_missing" not in rec3["metadata"]


def cands(*tbls):
    def fn(query, top_k=10, filters=None, question=None, unit="main"):
        return [{"rank": i, "tbl_id": t, "tbl_nm": t, "survey_nm": "", "score": 1.0 / i} for i, t in enumerate(tbls, 1)]
    return fn


VB = {"query_id": "imm", "original": "최근 30년 이민자 수", "rewritten": "2016~2025년 전국 외국인 인구수 연도별 추이",
      "filters": FOREIGN, "sub_questions": [], "sub_filters": None, "search_text": "외국인 인구수"}

# ② 단위의 View 가 모두 '요청 지표 없음' → records 없음 + 단위 메모 → 답변은 다른 지표로 하지 않음
vs = build_viewset(VB, search_fn=cands("DT_1B8000F"))
assert vs["status"] == "ok" and vs["records"] == [], [r["id"] for r in vs["records"]]
note = next(n for n in vs["units"][0]["notes"] if "찾지 못함" in n)
assert not vs["units"][0]["conflict"]["views"][0]["usable"]
n0 = CALLS["chat"]
ans = pipeline._answer(VB["original"], None, vs, 40)
assert ans["insufficient"] and "출생" not in ans["answer"] and "찾지 못함" in ans["answer"] and CALLS["chat"] == n0, ans
mods = run_modules(vs, use_llm_chart=False, draw=False)
assert mods["answer"]["insufficient"] and mods["records"] == [], mods["answer"]
print("[②]", ans["answer"])

# ③ 다른 표가 같이 있으면 그 표만 넘김 (keep_unusable 이어도 바꿔치기한 View 는 빠짐)
vs2 = build_viewset(VB, search_fn=cands("DT_1B8000F", "DT_1B040A3"))
ids = [r["id"] for r in vs2["records"]]
assert ids and all("DT_1B8000F" not in i for i in ids) and any("DT_1B040A3" in i for i in ids), ids
assert not any("찾지 못함" in n for n in vs2["units"][0]["notes"])
print("[③] records:", ids)

# ④ 요청 기간이 표 수록 기간(2021~2025) 밖 → notes · metadata.period_outside · 검색 unmet 에 남김
from backend.rag.search.resolve import profile, unmet  # noqa: E402

OLD = {"시점": list(range(1980, 2000)), "지역": ["대구광역시"], "지표": ["인구수"], "의도": "추이"}
rec4, notes4 = build_view("DT_1B040A3", OLD, "t-4")
assert rec4["metadata"]["period_outside"] == {"requested": "1980~1999", "available": "2021~2025", "applied": 2021}, rec4["metadata"]
assert any(n["type"] == "missing" and "요청 기간(1980~1999) 이 표 수록 기간(2021~2025) 밖" == n["text"] for n in notes4), notes4
assert {r[0] for r in rec4["table"]["rows"]} == {"2021"}                 # 가장 가까운 해 (요청이 모두 앞이라 첫 해)
um = [n["text"] for n in unmet(profile("DT_1B040A3"), OLD) if n["slot"] == "시점"]
assert um == ["요청 기간(1980~1999) 이 표 수록 기간(2021~2025) 밖"], um
part = [n["text"] for n in unmet(profile("DT_1B040A3"), {**OLD, "시점": list(range(2019, 2024))}) if n["slot"] == "시점"]
assert part == ["시점 2019~2020 없음 (수록 2021~2025)"], part
print("[④] 기간 밖:", [n["text"] for n in notes4 if n["slot"] == "시점"])
print(json.dumps({"INDICATOR_MISSING": "PASS"}, ensure_ascii=False))
