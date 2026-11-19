"""재작성 충실도 시나리오 — tests/test_rewrite_fidelity.py 가 별도 프로세스로 실행 (가짜 KOSIS 데이터, HCX 대역)

POST /api/v1/rag/analyze 로 분석 단계 전체를 지나게 함:
  · '최근 5년 혼인건수 얼마나 변했어?' — HCX 가 시점을 [2021, 2025] 로 줄여도 view_bundle 시점은 2021~2025 다섯 해
  · HCX 가 대상을 질문에 없는 상위어로 바꾸면 질문의 CSV 표현(원문)으로 되돌리고 재작성 문장도 다시 만듦
"""
import json
import re

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

KEYS = ["시점", "지역", "전출지", "전입지", "국적", "대상", "성별", "연령", "조건", "이동", "지표", "비교축"]
REPLIES = {  # 질문 속 단어 → HCX 응답 (보고서의 실제 재작성 실수를 흉내)
    "혼인건수 얼마나 변했어": {"시점": ["2021년", "2025년"], "지역": ["전국"], "대상": ["혼인"], "지표": ["혼인건수"],
                       "의도": ["증감"]},
    "총전입 알려줘": {"시점": ["2025년"], "지역": ["대구광역시"], "대상": ["외국인"], "의도": ["값 조회"]},
}


def fake_post(path, body, timeout=60):
    if "embedding" in path or "슬롯" not in body["messages"][0]["content"]:
        return fake_kosis.fake_hcx_post(path, body, timeout)
    q = re.search(r"<question>(.*?)</question>", body["messages"][-1]["content"], re.S).group(1)
    slots = next((v for k, v in REPLIES.items() if k in q), None)
    if slots is None:
        return fake_kosis.fake_hcx_post(path, body, timeout)
    out = {"slots": {**{k: [] for k in KEYS}, **slots}, "sub_questions": []}
    return {"message": {"content": json.dumps(out, ensure_ascii=False)}}


llm._post = fake_post

from backend.main import app  # noqa: E402

c = TestClient(app)
TODAY = "2026-11-19"
OV = {"csv_scope": "all", "question_terms_max_share": 1.0}  # 가짜 데이터는 표가 6개라 '흔한 말' 기준을 풂


def ok(r):
    assert r.status_code == 200, f"{r.request.url} → {r.status_code}: {r.text[:1500]}"
    return r.json()


s = ok(c.post("/api/v1/csv-index/build", json={"scope": "all", "workers": 2}))
assert s["n_errors"] == 0, s

# ── 최근 5년 + 변화 ──
a = ok(c.post("/api/v1/rag/analyze", json={"question": "최근 5년 혼인건수 얼마나 변했어?", "today": TODAY, "overrides": OV}))
vb = a["view_bundle"]
assert a["status"] == "ok", a["status"]
assert vb["filters"]["시점"] == [2021, 2022, 2023, 2024, 2025], vb["filters"]
assert vb["rewritten"].startswith("2021~2025년") and vb["rewritten"].endswith("증감"), vb["rewritten"]
assert vb["intent"] == "증감", vb["intent"]
print("[최근 5년]", vb["rewritten"], vb["filters"]["시점"], vb["intent"])

# ── 대상 상위어 되돌림 ──
a = ok(c.post("/api/v1/rag/analyze", json={"question": "2025년 대구 총전입 알려줘", "today": TODAY, "overrides": OV}))
vb = a["view_bundle"]
assert a["state"]["raw_slots"]["대상"] == ["총전입"], a["state"]["raw_slots"]
assert "외국인" not in vb["rewritten"] and "총전입" in vb["rewritten"], vb["rewritten"]
assert any("원문 표현으로 바꿈" in n for n in a["notes"]), a["notes"]
print("[대상 원문]", vb["rewritten"], a["state"]["raw_slots"]["대상"])

# ── 숫자 기준 조건이 state 로 남는가 ──
a = ok(c.post("/api/v1/rag/analyze", json={"question": "2025년 출생아수가 1,000명 이상인 지역의 혼인건수",
                                           "today": TODAY, "overrides": OV}))
assert [t["말"] for t in a["state"]["thresholds"]] == ["출생아수"], a["state"]
assert any(n.startswith("조건 기준:") for n in a["notes"]), a["notes"]
print("[조건 기준]", a["state"]["thresholds"])

print(json.dumps({"REWRITE_FIDELITY": "PASS"}, ensure_ascii=False))
