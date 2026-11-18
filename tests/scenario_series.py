"""시계열 묶음 후보 (ingestion/series.py) — tests/test_series.py 가 별도 프로세스로 실행

가짜 KOSIS 에 기간이 나뉜 출생아수 표 셋(제목 같음 2 + 제목 다름 1)과 헷갈리게 하는 표를 더해 둔다.
"""
import csv
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post

from backend.main import app  # noqa: E402
from backend.rag.ingestion import series  # noqa: E402

c = TestClient(app)
c.post("/api/v1/ingest/prepare", params={"workers": 2})
while c.get("/api/v1/ingest/prepare/status").json()["running"]:
    time.sleep(0.2)

out = Path(series.series_path()).parent / "series_candidates.csv"
recs = series.mine(str(out), check_values=10)
pairs = {(r["a_tbl"], r["b_tbl"]): r for r in recs}
print("[mine]", [(k, r["score"], r["value_check"]) for k, r in pairs.items()])

# 제목이 같고 기간만 나뉜 쌍 (1993~2004 + 2004~2025, 2004 겹침)
ab = pairs[("DT_S1", "DT_S2")]
assert ab["same_title"] == 1 and ab["overlap"] == 1 and ab["gap"] == 0 and ab["union"] == "Y 1993~2025", ab
assert ab["value_check"].startswith("겹치는 1개 해 최대 차이"), ab["value_check"]
# 제목이 달라도 항목·분류가 같으면 (1980~1992 + 1993~2004) — 같은 사슬
ca = pairs[("DT_S3", "DT_S1")]
assert ca["same_title"] == 0 and ca["item_sim"] == 1.0 and ca["gap"] == 0, ca
assert ca["value_check"].startswith("이어지는 해 1992→1993 비율"), ca["value_check"]
assert ab["group"] == ca["group"]
# 기간판이 아닌 것은 후보가 아님: 기간을 덮는 표끼리(DT_S4 ⊃ DT_S1·DT_S2), 다른 통계(혼인건수)
assert not {("DT_S1", "DT_S4"), ("DT_S2", "DT_S4"), ("DT_S4", "DT_S2")} & set(pairs), pairs.keys()
assert ("DT_S3", "DT_S4") in pairs                      # 1980~1992 + 1993~2025 는 이어짐 → 후보 (사람이 고름)
assert not any("DT_1B83A35" in k for k in pairs)
assert not any("DT_S5" in k for k in pairs)                 # 성별이 다른 짝은 뺌

# 검토 → build → series.json
rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
for r in rows:
    r["판정"] = "Y" if {r["a_tbl"], r["b_tbl"]} <= {"DT_S1", "DT_S2", "DT_S3"} else "N"
    r["메모"] = "1992→1993 기준 같음 (확인)" if r["a_tbl"] == "DT_S3" else ""
with open(out, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
built = series.build(str(out))
assert len(built) == 1, built
s = built[0]
assert [t["tbl_id"] for t in s["tables"]] == ["DT_S3", "DT_S1", "DT_S2"] and s["union"] == [1980, 2025], s
assert s["name"] == "시도별 출생아수" and s["notes"] == ["1992→1993 기준 같음 (확인)"], s
assert series.show()[0]["id"] == "S001"
print(json.dumps({"SERIES": "PASS"}, ensure_ascii=False))
