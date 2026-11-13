"""[NEW] answer_compose 테스트들이 함께 쓰는 입력 (파일 이름이 test_ 로 시작하지 않아 pytest 가 실행하지 않는다)"""
from backend.schemas.answer import Module6Request
from backend.schemas.chart import CalcResult, Display
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

BUNDLE = QueryBundle(query_id="27077dec", original="최근 5년 혼인건수 얼마나 변했어?",
                     sub_questions=["2021~2025년 전국 혼인건수 추이"])
DISPLAYS = {"d1": Display(source_unit="%", display_unit="%"), "d2": Display(source_unit="건", display_unit="건")}


def inp(year, value=None, item="혼인건수(건)", rid=VID, unit="건"):
    return {"role": "value", "record_id": rid, "item": item, "key": {"시점": year}, "value": value, "unit": unit}


def growth(step_id="a1", value=24.84013568337775):
    """명세의 a1: 혼인건수 2021 → 2025 증감률"""
    return CalcResult.model_validate({
        "step_id": step_id, "op": "growth_rate", "value": value, "unit": "%", "display_ref": "d1",
        "inputs": [inp("2021", 192507), inp("2025", 240326)], "record_ids": [VID]})


def request(results=None, records=None, **kw) -> Module6Request:
    return Module6Request(query_bundle=BUNDLE, records=[view()] if records is None else records,
                          calc_results=[growth()] if results is None else results, displays=DISPLAYS, **kw)


def fake(*replies):
    """차례로 replies 를 돌려주는 가짜 chat. Exception 이면 던진다. calls 에 받은 messages 가 쌓인다"""
    calls: list = []
    queue = list(replies)

    def chat(messages, schema=None, **kw):
        calls.append(messages)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    chat.calls = calls
    return chat
