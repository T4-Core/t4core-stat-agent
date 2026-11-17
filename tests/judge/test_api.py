"""판단 API (backend/api/judge.py) HTTP 경로 테스트"""
import copy

import pytest

from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.judge import EX_JUDGE_REQUEST

client = TestClient(app)


def test_judge_swagger_example():
    r = client.post("/api/v1/rag/judge", json=EX_JUDGE_REQUEST)
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "partial" and body["score"] == pytest.approx(0.75)
    slots = body["units"][0]["records"][0]["slots"]
    assert slots["연령"]["status"] == "missing"  # 연령 분류 없는 View
    assert slots["국적"]["status"] == "unsupported"  # 변환 단계에서 빠진 슬롯
    assert body["reasons"] == ["slot_substituted", "slot_dropped_upstream"]


def test_judge_invalid_config_is_422():
    req = {**EX_JUDGE_REQUEST, "config": {"pass_threshold": 0.5, "partial_threshold": 0.7}}
    assert client.post("/api/v1/rag/judge", json=req).status_code == 422  # model_validator 가 거부


def test_judge_config_defaults():
    r = client.get("/api/v1/rag/judge/config")
    assert r.status_code == 200 and r.json()["upstream_tier"] == "minor"


def test_judge_from_chat():
    # /chat 응답 모양을 흉내 낸다 (판정에 쓰는 필드 + 필수 필드만)
    ex = copy.deepcopy(EX_JUDGE_REQUEST)
    views = {**ex["views"], "status": "ok", "view_bundle": ex["bundle"],
             "units": [{**u, "conflict": {"unit_id": u["unit_id"], "status": "ok"}} for u in ex["views"]["units"]]}
    chat = {"question": ex["bundle"]["original"], "status": "ok", "views": views,
            "records": [ex["views"]["units"][0]["views"][0]["record"]],
            "result": {"answer": "…"},
            "notes": ex["upstream_notes"] + ["[main] DT_X View 생성 실패: KeyError"],  # 단위 메모는 무시돼야 함
            "judge_config": {"upstream_tier": None}}
    r = client.post("/api/v1/rag/judge/from-chat", json=chat)
    assert r.status_code == 200
    body = r.json()
    slots = body["units"][0]["records"][0]["slots"]
    assert "main" not in slots  # '[main] …' 메모가 슬롯으로 들어가지 않음
    assert slots["국적"]["status"] == "unsupported"
    # upstream_tier=None → 국적은 점수에서 빠짐: 4.5 / 5.5 = 0.8182 → pass  (국적 minor 포함이면 4.5 / 6.0 = 0.75)
    assert body["score"] == pytest.approx(0.8182) and body["verdict"] == "pass"
    assert "slot_dropped_upstream" in body["reasons"]  # 점수에서 빠져도 사유는 남는다
