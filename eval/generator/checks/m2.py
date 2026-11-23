"""모듈 2 chart_decision: 차트 유형 · measure (계획 2.4). 기대 하위 질문 단위"""
from eval.generator.findings import Finding
from eval.generator.schema import SubQuestion
from eval.generator.status import SubExpect
from eval.generator.subq import SubResult


def check(spec: SubQuestion, exp: SubExpect, res: SubResult) -> list[Finding]:
    out: list[Finding] = []
    if exp.source == "a0":
        return out                                   # Generator 미실행
    if res.status != "matched":
        if exp.expect == "answer":
            out.append(Finding("m2_missing", "metric", "M2", False, "대응되는 출력 하위 질문 없음", spec.key))
        return out
    charts = res.out.charts if res.out else []
    acc = spec.m2.acceptable_charts
    if acc:
        types = [c.get("chart_type") for c in charts] or [None]
        ok = any(t in acc for t in types)
        out.append(Finding("chart_type", "metric", "M2", ok, f"선택 {types} / 허용 {acc}", spec.key,
                           {"selected": types, "acceptable": acc}))
    if spec.m2.measure:
        ms = [c.get("measure") for c in charts]
        out.append(Finding("measure", "metric", "M2", spec.m2.measure in ms if ms else None,
                           f"measure {ms} / 기대 {spec.m2.measure}", spec.key))
    if None in acc and charts:
        out.append(Finding("no_chart", "metric", "M2", True, "", spec.key,
                           {"expected_null_allowed": True, "predicted_null": all(c.get("chart_type") is None for c in charts)}))
    return out
