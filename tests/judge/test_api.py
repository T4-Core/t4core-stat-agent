"""[NEW] 판단 API (backend/api/v1_judge.py) HTTP 경로 테스트

fastapi 가 설치되어 있지 않으면 이 파일 전체를 '건너뜀(skip)' 으로 표시한다 (실패가 아님).
  → pip install -r requirements.txt 후에는 자동으로 실행된다.
"""
import copy

import pytest

pytest.importorskip("fastapi")   # 없으면 여기서 멈추고 skip. 있으면 아래 import 로 계속

from fastapi.testclient import TestClient   # noqa: E402  (importorskip 다음에 import 해야 해서 맨 위가 아님)

from backend.main import app                 # noqa: E402
from backend.schemas.judge import EX_JUDGE_REQUEST   # noqa: E402

# TestClient: 서버를 띄우지 않고 앱에 HTTP 요청을 보내 보는 도구 (자바 Spring 의 MockMvc 와 비슷)
client = TestClient(app)


def test_judge_swagger_example():
    r = client.post("/api/v1/rag/judge", json=EX_JUDGE_REQUEST)
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "partial" and body["score"] == pytest.approx(0.75)
    slots = body["units"][0]["records"][0]["slots"]
    assert slots["연령"]["status"] == "missing"          # [P1] 연령 분류 없는 View
    assert slots["국적"]["status"] == "unsupported"      # 변환 단계에서 빠진 슬롯
    assert body["reasons"] == ["slot_substituted", "slot_dropped_upstream"]


def test_judge_invalid_config_is_422():
    req = {**EX_JUDGE_REQUEST, "config": {"pass_threshold": 0.5, "partial_threshold": 0.7}}
    assert client.post("/api/v1/rag/judge", json=req).status_code == 422   # model_validator 가 거부


def test_judge_config_defaults():
    r = client.get("/api/v1/rag/judge/config")
    assert r.status_code == 200 and r.json()["upstream_tier"] == "minor"


def test_judge_from_chat():
    # /chat 응답 모양을 흉내 낸다 (판정에 쓰는 필드 + 필수 필드만)
    ex = copy.deepcopy(EX_JUDGE_REQUEST)   # deepcopy: 안쪽 dict 까지 복사 → 예시 원본이 바뀌지 않게
    chat = {"question": ex["bundle"]["original"], "view_bundle": ex["bundle"], "views": ex["views"],
            "records": [ex["views"]["units"][0]["views"][0]["record"]],
            "result": {"answer": "…"},
            "notes": ex["upstream_notes"] + ["[main] DT_X View 생성 실패: KeyError"],   # 단위 메모는 무시돼야 함
            "judge_config": {"upstream_tier": None}}
    r = client.post("/api/v1/rag/judge/from-chat", json=chat)
    assert r.status_code == 200
    body = r.json()
    slots = body["units"][0]["records"][0]["slots"]
    assert "main" not in slots                          # '[main] …' 메모가 슬롯으로 들어가지 않음
    assert slots["국적"]["status"] == "unsupported"
    # upstream_tier=None → 국적은 점수에서 빠짐: 4.5 / 5.5 = 0.8182 → pass  (국적 minor 포함이면 4.5 / 6.0 = 0.75)
    assert body["score"] == pytest.approx(0.8182) and body["verdict"] == "pass"
    assert "slot_dropped_upstream" in body["reasons"]   # 점수에서 빠져도 사유는 남는다
