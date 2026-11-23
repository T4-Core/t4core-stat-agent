"""Generator 평가기 테스트용 합성 RunRecord (HCX 없음). 실제 통계값이 아니라 판정 규칙을 고정하는 입력이다"""
import copy

REC_BIRTH = "view::101_DT_1B81A23::Y::q1-1::breakdown"


def record(rid, columns, rows, unit="", prd_se="Y", survey="인구동향조사"):
    return {"id": rid, "table": {"columns": columns, "rows": rows}, "metadata": {"unit": unit, "prd_se": prd_se, "survey_nm": survey},
            "notes": [], "lexical_text": "", "parent_id": "table::x"}


def births(seoul=True, national=True, national_value=238317.0):
    rows = []
    if national:
        rows.append(["2024", "전국", "출생아수", national_value])
    if seoul:
        rows.append(["2024", "서울특별시", "출생아수", 41605.0])
    return record(REC_BIRTH, ["시점", "시군구별", "항목", "값"], rows, unit="명")


def share_calc(part=41605.0, total=238317.0, same_row=False, sub="q1-1"):
    value = part / total * 100 if total else None
    return {"step_id": "a1", "sub_question_id": sub, "op": "share", "value": value, "unit": "%", "display_ref": "d1",
            "inputs": [{"role": "part", "record_id": REC_BIRTH, "item": "출생아수", "key": {"시점": "2024"}, "value": part, "unit": "명"},
                       {"role": "total", "record_id": REC_BIRTH, "item": "출생아수", "key": {"시점": "2024"},
                        "value": part if same_row else total, "unit": None}],
            "record_ids": [REC_BIRTH], "note": None}


def run(records, calcs, answer, *, question="2024년 전국 대비 서울 출생아 비중은?", qid="q1", subs=None, caveats=None,
        withheld=None, method="hcx", charts=None, viewset=True, analysis_status="ok", notes=None, qa=None, insufficient=False):
    subs = subs or [question]
    m3 = {"query_id": qid, "chart_plan": {"answer_steps": [{"step_id": c["step_id"], "op": c["op"], "sub_question_id": c.get("sub_question_id"),
                                                             "operands": [{"record_id": REC_BIRTH, "select": {"시군구별": ["서울특별시"], "시점": ["2024"]}}]}
                                                            for c in calcs],
                                           "warnings": [w["text"] for w in withheld or []], "withheld": withheld or []},
          "chart_contents": [], "calc_results": calcs, "displays": {"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1, "digits": None}},
          "validation": {}}
    m6 = {"query_id": qid, "answer": answer, "insufficient": insufficient, "method": method, "tables": [], "caveats": caveats or [],
          "used_step_ids": [c["step_id"] for c in calcs if c.get("value") is not None], "notes": []}
    vs = {"status": "ok", "query_id": qid, "original": question, "units": [], "records": records,
          "view_bundle": {"query_id": qid, "original": question, "sub_questions": subs if len(subs) > 1 else []}} if viewset else None
    return {"id": "X", "run": 1, "ok": True, "source": "full", "question": question,
            "analysis": {"status": analysis_status, "notes": notes or []}, "viewset": vs, "records": records,
            "modules": {"charts": charts or [{"chart_id": "c1", "sub_question_ids": [f"{qid}-1"], "chart_type": None, "measure": "share"}],
                        "chart_plan": {"charts": []}, "module3": m3, "answer": m6, "drawn": [], "notes": [], "qa": qa or {},
                        "render_status": {}, "request_outcomes": [], "chart_notices": []},
            "result": {"answer": answer, "caveats": [c["text"] for c in caveats or []]}}


def clone(x):
    return copy.deepcopy(x)
