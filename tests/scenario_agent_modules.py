"""검색·View(②) → 모듈 2·3·5·6 연결 시나리오 — tests/test_agent_modules.py 가 별도 프로세스로 실행

  가짜 KOSIS(fake_kosis) 위에서 실제 /rag/views 결과(ViewSet)를 모듈에 그대로 넣는다.
  HCX 는 fake_kosis 대역에 모듈 3(계산 계획)·모듈 6(답변 문장) 응답만 덧붙인다.
"""
import json
import re
import time

from fastapi.testclient import TestClient

import backend.core.llm as llm
from backend.agent.prompts import ANSWER_COMPOSE_SYS, CHART_PLAN_SYS
from tests import fake_kosis

YEARS = ["2021", "2022", "2023", "2024", "2025"]
EMPTY_DEN = {"scope": "", "basis": "", "label": "", "record_id": "", "item": "", "conditions": []}
EMPTY = {"from": "", "to": "", "base": "", "agg": "", "top_n": 0, "kind": "", "order": "", "join_on": [],
         "denominator": EMPTY_DEN}
CALLS = {"m3": 0, "m6": 0}


def _cond(**kw):
    return [{"column": k, "values": v} for k, v in kw.items()]


def module3_reply(user):
    """세트 형식 프롬프트에서 record_id · chart_id · 하위 질문 ID 를 읽어 '대구 총인구수 2021→2025 증감률' 계획을 만든다"""
    rid = re.search(r"record_id=(\S+)", user).group(1)
    chart = re.search(r'charts 의 chart_id = "([^"]+)"', user).group(1)
    sid = re.search(r'sub_question_id = "([^"]+)"', user).group(1)
    sel = _cond(**{"행정구역(시군구)별": ["대구광역시"], "항목": ["총인구수"]})
    return {"charts": [{"chart_id": chart, "title": "", "record_id": rid, "series": [], **EMPTY,
                        "conditions": sel + _cond(시점=YEARS)}],
            "answers": [{"sub_question_id": sid, "op": "growth_rate", **EMPTY, "from": "2021", "to": "2025",
                         "operands": [{"role": "value", "record_id": rid, "item": "총인구수", "conditions": sel}]}]}


def post(path, body, timeout=60):
    if "embedding" not in path:
        sys_msg = body["messages"][0]["content"]
        if sys_msg == CHART_PLAN_SYS:
            CALLS["m3"] += 1
            return {"message": {"content": json.dumps(module3_reply(body["messages"][-1]["content"]), ensure_ascii=False)}}
        if sys_msg == ANSWER_COMPOSE_SYS:
            CALLS["m6"] += 1
            out = {"answer": "대구 인구는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} 변했습니다."}
            return {"message": {"content": json.dumps(out, ensure_ascii=False)}}
    return fake_kosis.fake_hcx_post(path, body, timeout)


llm._post = post

from backend.agent.modules import run_modules, split_roles, view_input_of  # noqa: E402
from backend.main import app  # noqa: E402

c = TestClient(app)
TODAY = "2026-11-02"
Q = "2021년부터 2025년까지 대구 인구 추이"


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:1500]}"
    return r.json()


ok(c.post("/api/v1/ingest/prepare", params={"workers": 2}))
for _ in range(300):
    if not ok(c.get("/api/v1/ingest/prepare/status"))["running"]:
        break
    time.sleep(0.2)

# ① ② 실제 검색·View 결과
vs = ok(c.post("/api/v1/rag/views", json={"question": Q, "today": TODAY}))
assert vs["status"] == "ok" and vs["records"], vs["status"]
top = min(vs["units"][0]["views"], key=lambda v: v["rank"])["record"]["id"]
print("[②] views:", [(u["unit_id"], [v["tbl_id"] for v in u["views"]]) for u in vs["units"]])

# 모듈 2 (단계별 API): ViewSet 을 그대로 view_input 에 넣는다
d = ok(c.post("/api/v1/chart/decide", json={"query_bundle": vs["view_bundle"], "view_input": vs, "use_llm": False}))
assert [(x["chart_id"], x["chart_type"], x["view_ids"]) for x in d["charts"]] == [("c1", "line", [top])], d["charts"]
assert [r["id"] for r in d["records"]] == [top]
print("[모듈 2] /chart/decide:", d["charts"][0]["chart_type"], d["charts"][0]["sub_question_ids"])

# 모듈 3 → 6 (단계별 API)
m3 = ok(c.post("/api/v1/chart/calc", json={"query_bundle": vs["view_bundle"], "records": d["records"], "charts": d["charts"]}))
a1 = next(x for x in m3["calc_results"] if x["step_id"] == "a1")
rows = {r[0]: r[3] for r in d["records"][0]["table"]["rows"]}
assert abs(a1["value"] - (rows["2025"] - rows["2021"]) / rows["2021"] * 100) < 1e-9, a1
assert m3["validation"]["c1"]["final_chart_type"] == "line" and m3["chart_contents"], m3["validation"]
m6 = ok(c.post("/api/v1/answer/compose", json={"query_bundle": vs["view_bundle"], "records": d["records"],
                                                "calc_results": m3["calc_results"], "displays": m3["displays"],
                                                "answer_steps": m3["chart_plan"]["answer_steps"]}))
assert m6["method"] == "hcx" and m6["used_step_ids"] == ["a1"] and "2021년" in m6["answer"], m6
print("[모듈 3·6] 단계별:", m6["answer"])

# 한 번에: /agent/modules (모듈 5 그림 포함)
mods = ok(c.post("/api/v1/agent/modules", json={"views": vs, "use_llm_chart": False}))
assert mods["answer"]["answer"] == m6["answer"], mods["answer"]
assert [x["status"] for x in mods["drawn"]] == ["drawn"] and mods["drawn"][0]["figure"]["data"], mods["drawn"]
print("[모듈 5] drawn:", [(x["chart_id"], x["chart_type"], x["status"]) for x in mods["drawn"]])
bad = c.post("/api/v1/agent/modules", json={"views": {**vs, "status": "needs_selection"}})
assert bad.status_code == 409, bad.text

# /chat: 기본은 예전 답변 그대로, answer_mode=modules 만 모듈을 탄다
n6 = CALLS["m6"]
base = ok(c.post("/api/v1/chat", json={"question": Q, "today": TODAY}))
assert base["status"] == "ok" and base["modules"] is None and CALLS["m6"] == n6
assert base["result"]["answer"].startswith("자료 기준 값은"), base["result"]
chat = ok(c.post("/api/v1/chat", json={"question": Q, "today": TODAY, "answer_mode": "modules", "draw": False}))
assert chat["status"] == "ok" and chat["modules"]["drawn"] == [] and CALLS["m6"] == n6 + 1
assert chat["result"]["answer"] == chat["modules"]["answer"]["answer"] and chat["result"]["used_ids"], chat["result"]
assert chat["result"]["sources"][0].startswith("https://kosis.kr/"), chat["result"]
print("[/chat modules]", chat["result"]["answer"], "| timings", chat["timings"])

# 충돌 선택: 선택에서 빠진 카드는 모듈에 넘기지 않는다 (records 에 없는 View 제외)
vs2 = json.loads(json.dumps(vs))
vs2["records"] = [r for r in vs2["records"] if r["id"] != top]
vi = view_input_of(vs2)
assert top not in {v["record"]["id"] for u in vi["units"] for v in u["views"]}

# 역할 단위(분모): 질문에서 빼고 그 View 를 세트에 붙인다
qid = "rq"
vb = {"query_id": qid, "original": "대구 인구 중 남자 비율", "sub_questions": ["대구 남자 인구", "인구"],
      "sub_filters": [{"지역": ["대구광역시"]}, {"지역": ["대구광역시"], "지표": ["인구"], "역할": "분모"}]}
unit = lambda uid, q, rid: {"unit_id": uid, "query": q, "views": [{"record": {"id": rid}, "rank": 1, "tbl_id": "T"}]}
b2, vi2, extra = split_roles(vb, {"query_id": qid, "units": [unit(f"{qid}-1", "대구 남자 인구", "A"), unit(f"{qid}-2", "인구", "B")]})
assert b2["sub_questions"] == ["대구 남자 인구"] and [u["unit_id"] for u in vi2["units"]] == [f"{qid}-1"], (b2, vi2)
assert [v["record"]["id"] for v in extra] == ["B"]
vb3 = {**vb, "sub_questions": ["대구 남자 인구", "대구 여자 인구", "인구"],
       "sub_filters": [{}, {}, {"역할": "분모"}]}
b3, vi3, extra3 = split_roles(vb3, {"query_id": qid, "units": [unit(f"{qid}-1", "a", "A"), unit(f"{qid}-2", "b", "C"),
                                                                unit(f"{qid}-3", "인구", "B")]})
assert b3["sub_questions"] == ["대구 남자 인구", "대구 여자 인구"] and [u["unit_id"] for u in vi3["units"]] == [f"{qid}-1", f"{qid}-2"]
# 실제 검색 결과로: 분모 단위가 차트를 따로 만들지 않고, 본 질문 세트에 분모 View 가 같이 들어감
vr = ok(c.post("/api/v1/rag/views", json={"question": "2025년 대구 인구 중 남자 비율", "today": TODAY}))
assert [(f or {}).get("역할") for f in vr["view_bundle"]["sub_filters"]] == [None, "분모"], vr["view_bundle"]
mr = run_modules(vr, use_llm_chart=False, draw=False)
assert len(mr["charts"]) == 1 and len(mr["charts"][0]["view_ids"]) == 2 and len(mr["records"]) == 2, mr["charts"]
print("[역할 단위] 분모 View 를 세트에 붙임:", mr["charts"][0]["view_ids"])

names = list(ok(c.get("/openapi.json"))["components"]["schemas"])
assert not [n for n in names if "__" in n or n.endswith(("-Input", "-Output"))], names
print(json.dumps({"AGENT_MODULES": "PASS", "hcx_calls": CALLS}, ensure_ascii=False))
