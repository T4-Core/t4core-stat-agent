"""저장된 실행 결과(dashboard/rewrite_trace.json)와 같은 결과가 나오는지 확인 (HCX 호출 없음)
trace 에 저장된 HCX 응답을 그대로 넣고, 코드 단계(2-1·2-2·프롬프트·2-4·3·4)를 다시 계산해 비교.
모듈을 고친 뒤 결과가 바뀌었는지 볼 때 씀 (일부러 바꿨다면 scripts/run_eval.py 로 trace 를 다시 만들면 됨)"""
import json
from dataclasses import asdict
from datetime import date

import pytest

from backend.rag.query_analyzer.bundle import make_bundle
from backend.rag.query_analyzer.config import DASHBOARD_DIR
from backend.rag.query_analyzer.extract import rule_extract
from backend.rag.query_analyzer.sentence import build_sentences
from backend.rag.query_analyzer.slots import build_slot_messages
from backend.rag.query_analyzer.terms import lookup_terms
from backend.rag.query_analyzer.validate import validate_slots

TRACE_PATH = DASHBOARD_DIR / "rewrite_trace.json"
TRACE = json.loads(TRACE_PATH.read_text(encoding="utf-8")) if TRACE_PATH.exists() else {"meta": {}, "items": []}


@pytest.mark.skipif(not TRACE["items"], reason="dashboard/rewrite_trace.json 없음")
@pytest.mark.parametrize("it", TRACE["items"], ids=lambda it: f"Q{it['no']:02d}")
def test_same_as_saved(it):
    today = date.fromisoformat(TRACE["meta"]["today"])
    q = it["question"]
    q2, found, notes = rule_extract(q, today)
    assert (q2, found, notes) == (it["input_question"], it["rule_found"], it["time_notes"])
    assert [[a, list(t)] for a, t in lookup_terms(q2)] == it["term_hits"]
    messages, _ = build_slot_messages(q, today)
    assert messages[0]["content"] == TRACE["meta"]["system_prompt"]
    assert messages[1]["content"] == it["user_prompt"]
    v = validate_slots({"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
                        "hcx_slots": it["hcx_slots"], "hcx_subs": it["hcx_subs"], "error": it["error"]})
    assert (v["slots"], v["sub_slots"], v["log"]) == (it["valid_slots"], it["valid_subs"], it["valid_log"])
    sres = build_sentences(v)
    assert (sres["rewritten"], sres["sub_questions"]) == (it["rewritten"], it["sub_questions"])
    assert asdict(make_bundle(q, v, sres)) == it["bundle"]
