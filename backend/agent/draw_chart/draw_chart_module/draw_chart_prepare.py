"""
모듈 5 ② 그리기 준비 — ChartPlan 차트 순서대로 차트 하나당 DrawJob 하나

  - ChartContent가 스키마 오류  → FAILED
  - ChartContent가 없음        → SKIPPED. 이유는 skip_reason (모듈 2가 차트 없음으로 판단 / 모듈 3 검증 실패 이유)
  - 계획 유형 ≠ 최종 유형       → 경고 '대체됨'
  - ChartPlan에 없는 ChartContent는 뒤에 붙이고 경고
  나머지 검사(유형별 약속)는 draw_chart_tool.precheck에서 한다.
"""
from .draw_chart_schema import FAILED, SKIPPED, DrawJob

KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}"   # backend/rag/ingestion/build_view.py와 같은 형식


def display_refs_of(content) -> list:
    """차트가 가리키는 display_ref: axis.x/y/y2.display_ref + options.display_ref (축 없는 차트), 순서 유지·중복 제거"""
    refs = [a.display_ref for a in content.axis.values() if a.display_ref]
    if content.options.get("display_ref"):
        refs.append(content.options["display_ref"])
    return list(dict.fromkeys(refs))


def source_links_of(record_ids):
    """record_id → KOSIS 통계표 링크. 'view::101_DT_1B8000G::Y::…' → orgId=101, tblId=DT_1B8000G
    첫 번째 '_' 앞을 orgId로 본다 (KOSIS orgId는 숫자). 형식이 다르면 링크 없이 경고만 돌려준다"""
    links, warns = {}, []
    for rid in record_ids:
        parts = rid.split("::")
        key = parts[1] if len(parts) > 1 and parts[0] == "view" else ""
        org, _, tbl = key.partition("_")
        if org.isdigit() and tbl:
            links.setdefault((org, tbl), {"label": f"KOSIS {tbl}", "url": KOSIS_URL.format(org=org, tbl=tbl)})
        else:
            warns.append(f"출처 링크를 만들 수 없는 record_id: {rid}")
    return list(links.values()), warns


OUT_OF_SCOPE = "범위 밖"     # 모듈 2 measure 값: 차트 없음 (backend/agent/chart_calculate/from_module2.py와 같은 규칙)


def _check_text(check) -> str:
    """모듈 3 CheckResult(dict) → '유형: 실패 이유'"""
    why = check.get("reasons") or check.get("failed") or []
    return f"{check.get('chart_type')}: {', '.join(map(str, why)) or '검증 실패'}"


def skip_reason(plan_chart, validation) -> str:
    """ChartContent가 없는 차트의 이유
      - 모듈 2가 차트 없음으로 판단 (chart_type 없음 / measure '범위 밖') → 모듈 3도 내용을 만들지 않는다
      - 모듈 3 validation이 있으면 원래·대체 차트의 실패 이유
      - 둘 다 아니면 일반 문구"""
    if plan_chart is not None and (not plan_chart.get("chart_type") or plan_chart.get("measure") == OUT_OF_SCOPE):
        why = "범위 밖" if plan_chart.get("measure") == OUT_OF_SCOPE else "chart_type 없음"
        return f"모듈 2가 차트 없음으로 판단 ({why})" + (f" — {plan_chart['reason']}" if plan_chart.get("reason") else "")
    if validation:
        parts = [_check_text(validation["original"])] if validation.get("original") else []
        if validation.get("fallback"):
            parts.append("대체 " + _check_text(validation["fallback"]))
        if parts:
            return "모듈 3 검증 실패 — " + " / ".join(parts)
    return "모듈 3에서 차트 내용을 만들지 못함 (원래·대체 차트 모두 구성 실패)"


def build_jobs(chart_plan, chart_contents, displays, load_errors, validation=None) -> list[DrawJob]:
    """ChartPlan 차트 순서대로 DrawJob을 만든다. validation은 모듈 3 출력의 {chart_id: ChartValidation dict} (없어도 된다)"""
    validation = validation or {}
    planned = {c["chart_id"]: c for c in chart_plan.get("charts", [])}
    jobs = []
    for cid in [*planned, *[k for k in chart_contents if k not in planned]]:
        p = planned.get(cid)
        job = DrawJob(chart_id=cid,
                      sub_question_ids=list((p or {}).get("sub_question_ids", [])),
                      planned_type=(p or {}).get("chart_type"))
        if p is None:
            job.warnings.append("ChartPlan에 없는 차트 (ChartContent에만 있음)")

        if cid in chart_contents and chart_contents[cid] is None:
            job.status, job.reason = FAILED, load_errors.get(f"chart_contents.{cid}", "ChartContent 스키마 오류")
        elif cid not in chart_contents:
            job.status, job.reason = SKIPPED, skip_reason(p, validation.get(cid))
        else:
            c = chart_contents[cid]
            job.content, job.chart_type = c, c.chart_type
            job.display_refs = display_refs_of(c)
            job.displays = {r: displays[r] for r in job.display_refs if r in displays}
            job.source_links, warns = source_links_of(c.record_ids)
            job.warnings += list(c.warnings) + warns
            if job.planned_type and job.planned_type != c.chart_type:
                job.warnings.append(f"대체됨: {job.planned_type} → {c.chart_type}")
        jobs.append(job)
    return jobs
