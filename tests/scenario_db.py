"""AWS DB 구성 시나리오 — tests/test_db_aws.py 가 별도 프로세스로 두 번 실행 (실제 PostgreSQL · pgvector · Redis 필요)

phase1  (parquet, 원본 있음)   준비 → 모든 표 정규화 → 질문들의 결과를 parquet 모드로 저장 → PostgreSQL 에 적재 → verify
phase2  (postgres, 원본·parquet 없음 = EC2)
        같은 질문들 → phase1 결과와 같아야 함 · 좌표 재조회 · 시리즈 값 비교
        + pgvector: sqlite 임베딩 가져오기 · dense 묶음 · DB 점수 = 메모리 점수
        + Redis 세션: session_id 만으로 이어가기 · GET /sessions · 만료 세션 409
        + 대화 이력: app.chat_turn
"""
import json
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.core.llm as llm
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post

from backend.main import app  # noqa: E402

PHASE, OUT = sys.argv[1], Path(sys.argv[2])
TODAY = "2026-11-02"
c = TestClient(app)


def ok(r):
    assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:1500]}"
    return r.json()


QUESTIONS = [
    {"question": "작년 대구의 남자 20대 인구 수", "today": TODAY},
    {"question": "최근 5년간 대전의 인구 변화 추이", "today": TODAY},
    {"question": "2025년 대전 인구랑 구별 인구 순위", "today": TODAY},
    {"question": "2025년 대전 전입 이동자 월별", "today": TODAY, "n_views": 3, "overrides": {"clarify_mode": "soft"}},
]


def essence(resp):
    """비교할 것: 상태 · Record(표·좌표) · 답변 문장"""
    def rid(x):  # view::표::주기::<질문id>-순위::종류 — 질문 id 는 실행마다 다름
        p = x.split("::")
        return "::".join(p[:3] + [p[3].rsplit("-", 1)[-1]] + p[4:]) if len(p) >= 5 else x
    recs = [{"id": rid(r["id"]), "table": r["table"], "source": r["source"], "notes": r.get("notes")}
            for r in resp.get("records") or []]
    return {"status": resp["status"], "records": recs, "answer": (resp.get("result") or {}).get("answer")}


def run_questions():
    out = []
    for q in QUESTIONS:
        r = ok(c.post("/api/v1/chat", json=q))
        e = essence(r)
        src = next((x["source"] for x in e["records"] if x["source"]["tbl_id"] == "DT_1B26001"), None)
        if src:
            e["data_source"] = ok(c.post("/api/v1/data/source", json=src))["rows"]
        out.append(e)
    return out


def series_values():
    from backend.data_engine.duckdb_client import connect
    from backend.rag.ingestion.series import _total_series
    con = connect()
    vals = {t: sorted([[k[0], k[1], v] for k, v in _total_series(con, t, "Y")[0].items()])
            for t in ("DT_1B040A3", "DT_1IN1503")}
    con.close()
    return vals


if PHASE == "phase1":
    assert os.environ.get("STAT_BACKEND") in (None, "", "parquet")
    ok(c.post("/api/v1/ingest/prepare", params={"workers": 2}))
    for _ in range(300):
        st = ok(c.get("/api/v1/ingest/prepare/status"))
        if not st["running"]:
            break
        time.sleep(0.2)
    assert st["error"] is None, st
    from backend.db import stats
    norm = stats.normalize(all_selected=True)
    assert norm["normalized"] >= 3 and not norm["failed"], norm
    expected = {"questions": run_questions(), "series": series_values()}
    # 적재 (깨끗한 DB 에서)
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as pg:
        pg.execute("DROP SCHEMA IF EXISTS kosis CASCADE; DROP SCHEMA IF EXISTS app CASCADE; "
                   "DROP TABLE IF EXISTS public.t4_schema_migrations")
    res = stats.load(None)
    assert res["loaded"] and not res["failed"], res
    again = stats.load(None)                                          # 바뀐 것 없음 → 모두 건너뜀
    assert not again["loaded"] and len(again["skipped"]) == len(res["loaded"]), again
    forced = stats.load(["DT_1B040A3"], force=True)                    # 다시 올리기 (파티션 바꿔 끼우기)
    assert forced["loaded"] == ["101_DT_1B040A3"], forced
    v = stats.verify(sample=500)
    assert v["ok"] == len(res["loaded"]) and not v["different"], v
    st = stats.status()
    assert st["tables"] == len(res["loaded"]) and st["rows"] > 0, st
    OUT.write_text(json.dumps(expected, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"PHASE1": "PASS", "tables": st["tables"], "rows": st["rows"]}))

else:
    assert os.environ["STAT_BACKEND"] == "postgres" and os.environ["VECTOR_STORE"] == "pgvector"
    from backend.core.config import KOSIS_DATA_DIR, VIEW_OUT_DIR
    assert not (Path(VIEW_OUT_DIR) / "processed").exists() and not (Path(KOSIS_DATA_DIR) / "raw").exists()
    expected = json.loads(OUT.read_text(encoding="utf-8"))
    import psycopg
    with psycopg.connect(os.environ["VECTOR_DB_URL"], autocommit=True) as vg:
        vg.execute("DROP SCHEMA IF EXISTS vec CASCADE; DROP TABLE IF EXISTS public.t4_schema_migrations")
    from backend.db import conn, migrate, vectors
    conn.redis_client().flushdb()                                      # 시험 전용 Redis db
    migrate.migrate_configured()
    imp = vectors.import_sqlite(os.environ["SQLITE_CACHE"])            # phase1 의 sqlite 임베딩 → pgvector
    assert imp["added"] > 0, imp
    db = ok(c.get("/api/v1/system/db"))
    assert db["database"]["ok"] and db["vector_db"]["ok"] and db["redis"]["ok"], db
    assert db["database"]["stat_tables"] >= 3 and db["vector_db"]["cached_embeddings"] == imp["added"], db
    h = ok(c.get("/health"))
    assert h["stat_backend"] == "postgres" and h["n_pg_tables"] >= 3 and h["n_normalized"] == 0, h

    got = {"questions": run_questions(), "series": series_values()}
    def first_diff(a, b, path=""):
        if type(a) is not type(b):
            return f"{path}: {a!r} != {b!r}"
        if isinstance(a, dict):
            for k in sorted(set(a) | set(b)):
                if a.get(k) != b.get(k):
                    return first_diff(a.get(k), b.get(k), f"{path}.{k}")
        elif isinstance(a, list):
            if len(a) != len(b):
                return f"{path}: 길이 {len(a)} != {len(b)}"
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    return first_diff(x, y, f"{path}[{i}]")
        return None if a == b else f"{path}: {a!r} != {b!r}"

    for a, b in zip(expected["questions"], got["questions"]):
        assert a == b, first_diff(a, b)
    assert expected["series"] == got["series"], (expected["series"], got["series"])
    print("[phase2] parquet 결과 = postgres 결과:", [q["status"] for q in got["questions"]])

    # pgvector: dense 묶음이 db-server 에 있고, DB 에서 계산한 점수 = 메모리 점수
    import numpy as np
    from backend.rag.search.engine import get_search
    s = get_search()
    d = s.ch.dense
    assert d is not None and d.set_ids and all(x is not None for x in d.set_ids), d.set_ids
    q = d.emb.embed_queries(["대전 인구 추이"])[0]
    assert np.allclose(d._raw_scores(0, q), d.Ms[0] @ q, atol=1e-5)
    vs = vectors.status()
    assert vs["doc_sets"] >= 1, vs

    # Redis 세션: 선택 대기 → session_id 만으로 이어가기
    sid = "test-session-0001"
    tq = "최근 5년간 대전의 인구 변화 추이"
    p = ok(c.post("/api/v1/chat", json={"question": tq, "today": TODAY, "auto_select": False, "session_id": sid}))
    assert p["status"] == "needs_selection" and p["session_id"] == sid, p["status"]
    sess = ok(c.get(f"/api/v1/sessions/{sid}"))
    assert sess["status"] == "needs_selection" and sess["response"]["views"]["pending"] and sess["turns"] == 1, sess["status"]
    pend = p["views"]["pending"][0]
    pick = next(o for o in pend["options"] if "DT_1B040A3" in o["tbl_ids"])
    s2 = ok(c.post("/api/v1/chat", json={"question": tq, "session_id": sid, "view_selections": [
        {"selection_token": pend["selection_token"], "option_id": pick["option_id"]}]}))
    assert s2["status"] == "ok" and "select" in s2["timings"], s2["status"]
    assert ok(c.get(f"/api/v1/sessions/{sid}"))["status"] == "ok"
    gone = c.post("/api/v1/chat", json={"question": tq, "session_id": "no-such-session-1", "view_selections": [
        {"selection_token": pend["selection_token"], "option_id": pick["option_id"]}]})
    assert gone.status_code == 409, gone.text
    assert c.get("/api/v1/sessions/no-such-session-1").status_code == 404
    print("[phase2] 세션 이어가기 ok")

    # 대화 이력
    hist = ok(c.get("/api/v1/history", params={"session_id": sid}))
    assert [t["kind"] for t in hist] == ["select", "ask"] and hist[0]["status"] == "ok", hist
    one = ok(c.get(f"/api/v1/history/{hist[0]['turn_id']}"))
    assert one["response"]["status"] == "ok" and "previous" not in one["request"], one["request"]
    all_turns = ok(c.get("/api/v1/history", params={"limit": 100}))
    assert len(all_turns) >= len(QUESTIONS) + 2, len(all_turns)
    os.environ["ADMIN_TOKEN"] = "secret"
    assert c.get("/api/v1/history").status_code == 401
    assert c.get("/api/v1/history", headers={"X-Admin-Token": "secret"}).status_code == 200
    # db-server 가 꺼져 있으면: 표 전체를 HCX 로 다시 임베딩하지 않고 파일 사본으로
    os.environ.update(VECTOR_DB_URL="postgresql://postgres@127.0.0.1:1/none", DB_POOL_TIMEOUT="2")
    from backend.rag.search.index import DenseRetriever, table_corpus
    calls = []
    real = llm._post
    llm._post = lambda path, body, timeout=60: (calls.append(path), real(path, body, timeout))[1]
    r2 = DenseRetriever(d.emb).fit(table_corpus())
    assert r2.set_ids == [None] and np.allclose(r2.Ms[0], d.Ms[0]) and not calls, (r2.set_ids, len(calls))
    print("[phase2] 벡터 DB 꺼짐 → 파일 사본 ok")
    print(json.dumps({"PHASE2": "PASS"}))
