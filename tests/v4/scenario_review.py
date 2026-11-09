"""[NEW v4] 단계별 검수 카드 (eval/pipeline_review/review_v4.py) — tests/v4/test_review_v4.py 가 별도 프로세스로 실행"""
import csv
import json
import sys
from pathlib import Path

import backend.core.llm as llm
import backend.rag.retrieval.dense as dense
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post
dense._post = fake_kosis.fake_dense_post
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval" / "pipeline_review"))

import review_v4 as rv  # noqa: E402
from backend.core.config import TEST_DATA_DIR  # noqa: E402
from backend.rag.csv_index import build_index  # noqa: E402
from backend.rag.ingestion import meta_profile, table_text  # noqa: E402

meta_profile.build_all()
table_text.build_index(progress=lambda m: None)
build_index(scope="all", log=lambda m: None)

# 질문 파일: 질문 열만 쓰고 정답 참고 열은 무시해야 함
Path(TEST_DATA_DIR).mkdir(parents=True, exist_ok=True)
with (Path(TEST_DATA_DIR) / "kosis_rag_eval_80_queries.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "question", "gold_answer"])
    w.writerows([["Q001", "2025년 대전 인구 수", "정답은 쓰지 않음"], ["Q002", "출생아 수 알려줘", ""],
                 ["Q003", "합계출산율이 무슨 뜻이야?", ""]])
items = rv.load_questions("80")
assert items == [{"id": "Q001", "question": "2025년 대전 인구 수"}, {"id": "Q002", "question": "출생아 수 알려줘"},
                 {"id": "Q003", "question": "합계출산율이 무슨 뜻이야?"}], items

run, data = rv.run_batch("80", png=False, log=print, overrides={"csv_scope": "all"})
assert run.dir.name == "kosis_rag_eval_80_queries__v4"
for f in ("results.json", "review.csv", "run_meta.json", "json/Q001.json", "cards/Q001.html"):
    assert (run.dir / f).exists(), f
q1 = data["Q001"]
assert q1["auto"]["conflict"]["grade"] == "PARTIAL" and any(x["code"] == "c.ambiguous" for x in q1["auto"]["conflict"]["reasons"])
v = q1["units"][0]["views"][0]
assert v["raw"]["exists"] and v["raw"]["n"] >= 1 and v["raw"]["ok"] == v["raw"]["n"], v["raw"]      # 원본 대조 일치
assert v["kosis_url"].startswith("https://kosis.kr/") and Path(v["raw"]["path"]).exists()
assert q1["stages"]["query"]["slots"] and q1["units"][0]["candidates"][0]["kosis_url"].startswith("https://kosis.kr/")
q2 = data["Q002"]
assert any(x["code"] == "q.clarify" for x in q2["auto"]["query"]["reasons"]) and q2["stages"]["query"]["clarify_answer"]
q3 = data["Q003"]
assert q3["auto"]["query"]["grade"] == "CHECK" and not q3["units"] and q3["auto"]["search"]["grade"] == "-"

card = (run.card_dir / "Q001.html").read_text(encoding="utf-8")
for s in ("① 쿼리 분석", "② 검색", "③ View", "④ 충돌·선택", "원본 대조", "KOSIS", "원본 CSV", "슬롯 → CSV 값 접지"):
    assert s in card, s

# 원본과 값이 다르면 잡아냄
import duckdb  # noqa: E402
from backend.rag.view import build_viewset  # noqa: E402
vb = {"query_id": "rc", "original": "x", "search_text": "2025년 대전광역시 인구수",
      "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["인구수"]}}
rec = build_viewset(vb, n_views=1, overrides={"conflict_rel_tol": 9.0})["records"][0]
rec2 = json.loads(json.dumps(rec))
rec2["table"]["rows"][0][-1] = 123.456
bad = rv.raw_check(rec2, con=duckdb.connect())
assert bad["n"] == 1 and bad["ok"] == 0 and bad["bad"], bad

# 사람 판정 저장 → 카드·CSV 반영, 다시 실행해도 유지
rv.set_review(run, "Q001", query="PASS", search="PASS", view="PASS", conflict="FAIL", first_fail="conflict",
              comment="외국인 포함 표와 주민등록 표는 다른 기준", png=False)
df = rv.review_df(rv.load_results(run))
row = df[df["id"] == "Q001"].iloc[0]
assert row["사람_④ 충돌·선택"] == "FAIL" and row["사람_첫_실패_단계"] == "④ 충돌·선택" and row["검수"] == "Y"
assert "외국인 포함 표와" in (run.card_dir / "Q001.html").read_text(encoding="utf-8")
_, data2 = rv.run_batch("80", ids=["Q001"], force=True, png=False, log=lambda m: None, overrides={"csv_scope": "all"})
assert data2["Q001"]["human"]["comment"].startswith("외국인 포함")

gt, rt = rv.stage_summary(rv.load_results(run))
assert "④ 충돌·선택" in gt.index and "c.ambiguous" in set(rt["사유 코드"])
assert rv.questions_with(rv.load_results(run), "q.clarify") == ["Q002"]
print(json.dumps({"REVIEW_V4": "PASS"}))
