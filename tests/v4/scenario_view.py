"""[NEW v4] Step 4 시나리오 — tests/v4/test_view_v4.py 가 별도 프로세스로 실행 (Swagger 와 같은 HTTP 경로)

① 충돌 재현: 같은 교차점(2025·대전·인구수)에서 표마다 다른 값 → ambiguous + 선택지(주석·설명·기준) + 토큰
   천명 단위 표는 단위를 맞추면 같은 값 → 같은 선택지
② 선택 왕복: previous 와 함께 / 토큰만(좌표로 View 다시 만들기) / 변조·만료·없는 선택지
③ auto_select · 허용 오차(ok + 교차 확인) · 필수 메타 못 쓴 View(partial) · 비교 대상 하나(ok)
④ /views/points (검색 없이 Record 끼리) · 질문부터(analyze → views) · 되묻기 상태 전달
"""
import base64
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.core.llm as llm
import backend.rag.retrieval.dense as dense
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post
dense._post = fake_kosis.fake_dense_post

from backend.main import app  # noqa: E402

c = TestClient(app)
V = "/api/v1/rag/v4/views"


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:1500]}"
    return r.json()


ok(c.post("/api/v1/rag/chunk-and-index"))
for _ in range(200):
    s = ok(c.get("/api/v1/rag/chunk-and-index/status"))
    if not s["running"]:
        break
    time.sleep(0.2)
assert s["error"] is None and s["result"]["index"]["n_tables"] == 6, s
ok(c.post("/api/v1/csv-index/build", json={"scope": "all", "workers": 2}))

VB = {"query_id": "q1", "original": "2025년 대전 인구 수", "search_text": "2025년 대전광역시 인구수",
      "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["인구수"], "의도": "값 조회"}}
KEY = "시점=2025 | 지역=대전광역시 | 지표=인구수 | 단위=명"

# ① 충돌 재현
vs = ok(c.post(V, json={"view_bundle": VB, "n_views": 5}))
u = vs["units"][0]
cf = u["conflict"]
assert vs["status"] == "needs_selection" and cf["status"] == "ambiguous" and vs["records"] == [], (vs["status"], cf["notes"])
tbls = [v["tbl_id"] for v in u["views"]]
assert {"DT_Y001", "DT_Y002", "DT_1B040A3"} <= set(tbls), tbls
d = next(x for x in cf["differing_points"] if x["key_str"] == KEY)
vals = {x["tbl_id"]: (x["value"], x["unit"], x["base_value"]) for x in d["values"]}
assert vals["DT_Y002"][1] == "천명" and abs(vals["DT_Y002"][2] - vals["DT_1B040A3"][0]) < 1e-6        # 단위 맞춰 비교
assert vals["DT_Y001"][0] == vals["DT_1B040A3"][0] + 12345
opts = {o["option_id"]: o for o in cf["options"]}
by_tbl = {t: o for o in cf["options"] for t in o["tbl_ids"]}
assert by_tbl["DT_Y002"] is by_tbl["DT_1B040A3"] or by_tbl["DT_Y002"]["option_id"] == by_tbl["DT_1B040A3"]["option_id"]
assert by_tbl["DT_Y001"]["option_id"] != by_tbl["DT_1B040A3"]["option_id"]
o1 = by_tbl["DT_Y001"]
assert {"type": "통계표", "target": "", "text": "외국인 포함 집계"} in o1["footnotes"]
assert {"type": "항목", "target": "총인구수", "text": "내국인+외국인"} in o1["footnotes"]
assert not any(f["target"] == "세대수" for f in o1["footnotes"])                       # 이 View 와 무관한 항목 주석은 뺌
assert "항목: 총인구수" in o1["description"] and o1["basis"]["조사"] == "주민등록인구현황" and o1["kosis_url"]
assert o1["value_preview"][0]["key_str"] == KEY and o1["value_preview"][0]["others"]
checks = {v["tbl_id"]: v for v in cf["views"]}
assert all(checks[t]["usable"] and checks[t]["used"] == {"시점": True, "지역": True, "지표": True}
           for t in ("DT_Y001", "DT_Y002", "DT_1B040A3"))
for t, ch in checks.items():                                                       # 지표가 없는 표는 비교에서 빠짐
    if t == "DT_1B26001":
        assert not ch["usable"] and ch["used"]["지표"] is False
assert vs["pending"][0]["selection_token"] == cf["selection_token"] and len(vs["pending"][0]["options"]) == len(opts)
# '세대구성별' 은 성별이 아님 → 대상 '1인가구' 코드를 골라 자름 (이전: 성별로 판정돼 합계 '계' 만 → 전체 가구 수)
HH = {"query_id": "hh", "original": "2025년 전국 1인 가구 수", "search_text": "2025년 전국 1인가구 가구수",
      "filters": {"시점": [2025], "대상": ["1인가구"], "지표": ["가구수"], "의도": "값 조회"}}
hh = ok(c.post(V, json={"view_bundle": HH, "n_views": 3}))
hv = next(v for v in hh["units"][0]["views"] if v["tbl_id"] == "DT_1JC1516")
assert hv["record"]["source"]["dims"]["c2"]["codes"] == ["05"], hv["record"]["source"]          # 1인가구만 (1세대가구 등 아님)
assert {r[2] for r in hv["record"]["table"]["rows"]} == {"1인가구"}, hv["record"]["table"]
hc = next(v for v in hh["units"][0]["conflict"]["views"] if v["tbl_id"] == "DT_1JC1516")
assert hc["usable"] and hc["used"]["대상"] and hc["checks"]["대상"]["status"] == "match", hc
# 예전 규칙으로 만든 캐시 프로필(세대구성별=sex) → 읽을 때 다시 판정해 다시 정규화
from backend.core.config import OUT  # noqa: E402
from backend.data_engine.duckdb_client import connect  # noqa: E402
from backend.rag.ingestion.normalize import ensure_normalized  # noqa: E402
pf = Path(OUT) / "profiles" / "101_DT_1JC1516.json"
pj = json.loads(pf.read_text(encoding="utf-8"))
for lv in pj["levels"]:
    if lv["obj_nm"] == "세대구성별":
        lv["kind"] = "sex"
pj.pop("kind_rules", None)
pf.write_text(json.dumps(pj, ensure_ascii=False), encoding="utf-8")
con = connect()
p2 = ensure_normalized(con, "DT_1JC1516")
con.close()
assert next(lv["kind"] for lv in p2["levels"] if lv["obj_nm"] == "세대구성별") == "other" and p2["kind_rules"] >= 2
print("[①] 충돌:", KEY, {t: v[0] for t, v in vals.items()}, "| 선택지:", [o["tbl_ids"] for o in cf["options"]])

# ② 선택 왕복 — previous 와 함께
pick = by_tbl["DT_1B040A3"]["option_id"]
sel = ok(c.post(V + "/select", json={"selections": [{"selection_token": cf["selection_token"], "option_id": pick}],
                                     "previous": vs}))
got = [r["source"]["tbl_id"] for r in sel["records"]]
assert sel["viewset"]["status"] == "ok" and "DT_1B040A3" in got and "DT_Y002" in got and "DT_Y001" not in got, got
assert sel["viewset"]["units"][0]["conflict"]["selected_option"] == pick and sel["applied"][0]["rebuilt"] == []
assert "DT_1B26001" in got                                                          # 기본: 못 쓴 View 도 넘김 (기존과 같음)
strict = ok(c.post(V, json={"view_bundle": VB, "n_views": 5, "auto_select": "first", "overrides": {"view_keep_unusable": False}}))
assert "DT_1B26001" not in [r["source"]["tbl_id"] for r in strict["records"]] and strict["records"]
# 토큰만 (다른 실행·CLI): 좌표로 View 를 다시 만들어 같은 id
sel2 = ok(c.post(V + "/select", json={"selections": [{"selection_token": cf["selection_token"], "option_id": o1["option_id"]}]}))
assert [r["id"] for r in sel2["records"]] == o1["record_ids"] and sel2["applied"][0]["rebuilt"] == o1["record_ids"]
orig = next(v["record"] for v in u["views"] if v["tbl_id"] == "DT_Y001")
assert sel2["records"][0]["table"] == orig["table"]
# 변조 · 없는 선택지 · 만료
body, sig = cf["selection_token"].rsplit(".", 1)
p = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
p["o"][0]["r"] = ["view::evil"]
bad = base64.urlsafe_b64encode(json.dumps(p).encode()).rstrip(b"=").decode() + "." + sig
r = c.post(V + "/select", json={"selections": [{"selection_token": bad, "option_id": "opt-1"}]})
assert r.status_code == 404 and "서명" in r.text, r.text
r = c.post(V + "/select", json={"selections": [{"selection_token": cf["selection_token"], "option_id": "opt-9"}]})
assert r.status_code == 404 and "opt-9" in r.text
short = ok(c.post(V, json={"view_bundle": VB, "n_views": 5, "overrides": {"selection_ttl_hours": 0}}))
time.sleep(1.1)
r = c.post(V + "/select", json={"selections": [{"selection_token": short["pending"][0]["selection_token"], "option_id": "opt-1"}]})
assert r.status_code == 404 and "만료" in r.text
print("[②] 선택 왕복: previous ·토큰만(다시 만듦)· 변조/없는 선택지/만료 거부")

# ③ auto_select · 허용 오차 · partial · 비교 대상 하나
a = ok(c.post(V, json={"view_bundle": VB, "n_views": 5, "auto_select": "first"}))
assert a["status"] == "ok" and a["units"][0]["conflict"]["selected_option"] == "opt-1" and a["records"]
assert a["records"][0]["source"]["tbl_id"] == cf["options"][0]["tbl_ids"][0]
t = ok(c.post(V, json={"view_bundle": VB, "n_views": 5, "overrides": {"conflict_rel_tol": 5.0}}))
assert t["status"] == "ok" and t["units"][0]["conflict"]["status"] == "ok" and "교차 확인" in t["units"][0]["conflict"]["notes"][0]
assert len(t["records"]) == len(t["units"][0]["views"])
px = ok(c.post(V, json={"view_bundle": {**VB, "filters": {**VB["filters"], "지표": ["외계인수"]}}, "n_views": 3}))
assert px["units"][0]["conflict"]["status"] == "partial" and px["status"] == "ok" and px["records"]   # 비교 없이 기존처럼 전달
one = ok(c.post(V, json={"view_bundle": {**VB, "search_text": "2025년 대전광역시 이동자수",
                                           "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["총전입"]}}, "n_views": 3}))
assert one["units"][0]["conflict"]["status"] == "ok" and one["units"][0]["conflict"]["n_compared_keys"] == 0
# 서브쿼리가 있으면 본 질의 단위는 생략 (설정으로 켤 수 있음)
SUB = {**VB, "query_id": "qs", "sub_questions": ["2025년 대전광역시 인구수", "2025년 대전광역시 총전입"],
       "sub_filters": [VB["filters"], {"시점": [2025], "지역": ["대전광역시"], "지표": ["총전입"], "의도": "값 조회"}]}
sb = ok(c.post(V, json={"view_bundle": SUB, "n_views": 3}))
assert [x["unit_id"] for x in sb["units"]] == ["qs-1", "qs-2"], [x["unit_id"] for x in sb["units"]]
sb2 = ok(c.post(V, json={"view_bundle": SUB, "n_views": 3, "overrides": {"view_main_with_subs": True}}))
assert [x["unit_id"] for x in sb2["units"]] == ["main", "qs-1", "qs-2"]
print("[③] auto_select · 허용 오차 → ok(교차 확인) · partial · 비교 대상 하나")

# ④ /views/points — 검색 없이 Record 끼리 (성별은 항목 이름에서)
recs = [v["record"] for v in u["views"] if v["tbl_id"] in ("DT_1B040A3", "DT_Y001")]
pt = ok(c.post(V + "/points", json={"records": recs, "filters": VB["filters"]}))
assert pt["conflict"]["status"] == "ambiguous" and pt["conflict"]["options"][0]["option_id"] == "opt-1"
assert all(p["key_str"] == KEY for ps in pt["points"].values() for p in ps)
sx = ok(c.post("/api/v1/rag/views", json={**VB, "filters": {**VB["filters"], "성별": ["남자"]}}, params={"n_views": 3}))
sx_rec = next(r for r in sx if r["source"]["tbl_id"] == "DT_1B040A3")
ps = ok(c.post(V + "/points", json={"records": [sx_rec], "filters": {**VB["filters"], "성별": ["남자"]}}))["points"]
assert next(iter(ps.values()))[0]["key"]["성별"] == "남자", ps

# 질문부터 (analyze → views) / 되묻기는 그대로 전달
q = ok(c.post(V, json={"question": "작년 대전의 인구 변화", "today": "2026-11-02", "n_views": 5}))
assert q["analysis_status"] == "ok" and q["status"] in ("ok", "needs_selection") and q["units"]
an = ok(c.post("/api/v1/rag/v4/analyze", json={"question": "작년 대전의 인구 변화", "today": "2026-11-02"}))
q2 = ok(c.post(V, json={"analysis": an, "n_views": 5}))
assert q2["query_id"] == an["view_bundle"]["query_id"] and len(q2["units"]) == len(q["units"])
cl = ok(c.post(V, json={"question": "출생아 수 알려줘", "overrides": {"csv_scope": "all"}}))
assert cl["status"] == "needs_clarification" and cl["clarifications"] and not cl["units"]
assert c.post(V, json={}).status_code == 422
print("[④] /views/points · 질문부터 · analysis 응답 · 되묻기 전달")

spec = ok(c.get("/openapi.json"))
names = list(spec["components"]["schemas"])
assert not [n for n in names if "__" in n or n.endswith(("-Input", "-Output"))], names   # 스키마 이름 충돌 없음
assert {"/api/v1/rag/v4/views", "/api/v1/rag/v4/views/select", "/api/v1/rag/v4/views/points"} <= set(spec["paths"])

print(json.dumps({"VIEW_V4": "PASS"}))
