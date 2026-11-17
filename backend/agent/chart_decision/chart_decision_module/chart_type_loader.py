"""입력 읽기·정리 (노트북 1번)

QueryBundle은 질문 1개와 2번 모듈이 쓰는 키만, Views는 unit마다 rank 1 View만 남긴다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import json


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def slim_query_bundle(data):
    """리스트로 감싼 QueryBundle에서 질문 1개를 꺼내고, 2번 모듈이 쓰는 키만 남긴다.
    다른 데이터 모양도 같은 모양으로 맞춘다.
      - intent가 문자열("값 조회")이면 리스트(["값 조회"])로
      - sub_questions·sub_filters가 없거나 null이면 빈 리스트로 (질문을 나누지 않은 경우)
      - filters가 없으면 빈 dict로
    """
    qb = data[0] if isinstance(data, list) else data
    keys = ["original", "rewritten", "sub_questions", "intent", "filters", "sub_filters"]
    out = {k: qb.get(k) for k in keys}
    intent = out.get("intent")
    out["intent"] = [intent] if isinstance(intent, str) else list(intent or [])
    out["sub_questions"] = list(out.get("sub_questions") or [])
    out["sub_filters"] = list(out.get("sub_filters") or [])
    out["filters"] = out.get("filters") or {}
    return out

def slim_view_input(data):
    """모든 unit: candidates 제거, views는 rank 1만"""
    for unit in data["units"]:
        unit.pop("candidates", None)
        if unit.get("views"):
            unit["views"] = [min(unit["views"], key=lambda v: v["rank"])]
    return data
