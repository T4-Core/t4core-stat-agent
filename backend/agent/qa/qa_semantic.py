"""내용 경고 · 답할 수 없는 질문 판단 — 형식은 맞지만 사람이 확인해야 하는 결과 (qa 설계.md 15 · 17장)

  meaning_issues(m3, m6, bundle, charts, drawn) → [Issue]    최종 출력을 읽기만 한다. 재시도 · 빼기 · 중단은 하지 않는다
    withheld                모듈 3 이 계산을 보류함 (chart_plan.withheld: 지표 불일치 · 분모 없음 · 조건 적용 불가 …)
    plan_warning            보류 범위가 없는 모듈 3 사용자 경고 (예: 일부 연도 자료가 없어 다른 기간으로 계산)
    answer_fallback         모듈 6 이 HCX 문장을 쓰지 못함 (method = template · none)
    condition_unused        질문의 숫자 기준(99,000명 이상)이 조건식에 없는데 수치 답변이 나감
    ratio_missing           비율을 물었는데 비율 계산도, 표의 비율 값도 없이 수치 답변이 나감
    measure_mismatch        모듈 2 는 계산을 요구했는데 모듈 3 결과가 원값뿐
    too_many_marks          막대 차트의 막대가 너무 많음
    chart_answer_mismatch   차트는 그렸는데 답변은 수치를 내지 못함
    answer_caveat_conflict  보류된 질문의 값을 '참고로' 없이 답함
    value_list              규칙 문장이 값을 길게 나열함 ('… 외 N개')

  unanswerable(viewset, notes) → [지표]    사전에도 없고 고른 표에도 없는 지표 (있으면 A0 에서 조기 종료)

  사유 문장은 모듈 6 이 이미 답변의 주의사항으로 보여 주므로 QA 안내 문구(qa.message)에 다시 넣지 않는다.
"""
import re

from .qa_check import WARNING, Issue
from .qa_policy import (ANSWER_LIST_MIN, BAR_CHARTS, COMPUTED_MEASURES, MAX_BAR_MARKS, NOT_THRESHOLD_UNITS, RATIO_OPS)

FALLBACK_TEXT = {
    "template": "HCX 답변 대신 규칙 문장으로 대체됨",
    "none": "답변할 계산 결과가 없음",
}

_RATIO_WORD = re.compile(r"비율|비중|구성비|점유율|%|퍼센트")
_RATIO_NAME = re.compile(r"비율|비중|구성비|점유율|%|퍼센트|[율률]")     # 표의 항목 · 단위가 이미 비율이면 원값 조회가 정답
_THRESHOLD = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([가-힣%\s]{0,5}?)\s*(이상|이하|초과|미만)")
_LIST_TAIL = re.compile(r"외\s*(\d+)\s*개")
_UNKNOWN_INDICATOR = re.compile(r"\[지표\]\s*'(.+?)'\s*를 CSV·사전에서 찾지 못함")


def _squash(s) -> str:
    return re.sub(r"[\s,]", "", str(s))


def _has_value(r) -> bool:
    return r.value is not None and r.value != []


def _held_subs(m3) -> set[str]:
    """답변 계산을 보류한 하위 질문. 차트 계획의 보류(chart_id 있음)는 제외한다 (모듈 6 facts.withheld_subs 와 같은 기준)"""
    return {w.sub_question_id for w in m3.chart_plan.withheld if w.sub_question_id and not w.chart_id}


def _cited(m3, m6) -> list:
    """답변이 인용한 계산 결과. 인용 기록이 없으면 값이 있는 결과 전부"""
    results = [r for r in m3.calc_results if _has_value(r)]
    used = set(m6.used_step_ids or [])
    return [r for r in results if r.step_id in used] or results


# ── 질문과 계산 ─────────────────────────────────────────────────
def _condition_unused(bundle, answered) -> list[Issue]:
    """조건식이 있으면 모듈 3 이 적용하거나 보류한다 → 조건식이 비어 있을 때만 질문의 숫자 기준을 본다.
    65세 이상 · 5인 이상처럼 표의 분류 이름인 표현은 조건이 아니다"""
    if bundle is None or not answered or any(f and f.조건식 for f in [bundle.filters, *(bundle.sub_filters or [])]):
        return []
    labels = [_squash(x) for r in answered for i in r.inputs for x in (i.item, *i.key.values()) if x is not None]
    out = []
    for m in _THRESHOLD.finditer(bundle.original or ""):
        unit = _squash(m[2])
        phrase = f"{_squash(m[1])}{unit}{m[3]}"
        if unit in NOT_THRESHOLD_UNITS or any(phrase in x for x in labels):
            continue
        out.append(Issue("M3-out", "chart_plan.answer_steps", "condition_unused", WARNING,
                         f"질문의 조건 '{m[0].strip()}' 이 계산에 쓰이지 않음", m[0].strip()))
    return out


def _ratio_missing(bundle, m3, answered) -> list[Issue]:
    if bundle is None or not answered:
        return []
    words = [bundle.original or ""]
    for f in [bundle.filters, *(bundle.sub_filters or [])]:
        words += (f.원문표현 or []) if f else []
    if not any(_RATIO_WORD.search(w) for w in words):
        return []
    if any(r.op in RATIO_OPS for r in m3.calc_results) or any(c.measure in RATIO_OPS for c in m3.chart_contents):
        return []
    names = [x for r in answered for x in (r.unit, *(y for i in r.inputs for y in (i.item, i.unit))) if x]
    if any(_RATIO_NAME.search(str(x)) for x in names):
        return []
    return [Issue("M3-out", "calc_results", "ratio_missing", WARNING, "비율을 물었는데 비율 계산 없이 수치로 답함",
                  ", ".join(sorted({r.op for r in answered})))]


def _measure_mismatch(m3, charts, held: set[str]) -> list[Issue]:
    """모듈 2 가 계산을 요구했는데 그 차트 · 하위 질문의 결과가 원값뿐일 때만. 모듈 2 가 raw 인데 모듈 3 이 계산한 것은 정상일 수 있다"""
    withheld_charts = {w.chart_id for w in m3.chart_plan.withheld if w.chart_id}
    out = []
    for i, c in enumerate(charts or []):
        cid, want, subs = c.get("chart_id"), c.get("measure"), set(c.get("sub_question_ids") or [])
        if want not in COMPUTED_MEASURES or cid in withheld_charts or subs & held:
            continue
        ops = {x.measure for x in m3.chart_contents if x.chart_id == cid}
        ops |= {r.op for r in m3.calc_results if _has_value(r) and (r.sub_question_id in subs or r.sub_question_id is None)}
        if ops == {"raw"}:
            out.append(Issue("M3-out", f"charts[{i}].measure", "measure_mismatch", WARNING,
                             f"모듈 2 는 {want} 계산을 요구했는데 모듈 3 결과는 원값뿐", cid))
    return out


# ── 결과끼리 · 보여 주는 방식 ────────────────────────────────────
def _too_many_marks(m3) -> list[Issue]:
    return [Issue("M3-out", f"chart_contents[{i}].rows", "too_many_marks", WARNING,
                  f"막대 {len(c.rows)}개 (기준 {MAX_BAR_MARKS}개 초과)", c.chart_id)
            for i, c in enumerate(m3.chart_contents) if c.chart_type in BAR_CHARTS and len(c.rows) > MAX_BAR_MARKS]


def _chart_answer_mismatch(m6, drawn) -> list[Issue]:
    ids = [d.get("chart_id") for d in drawn or [] if d.get("status") == "drawn"]
    if not (ids and m6.insufficient):
        return []
    return [Issue("A9", "answer.insufficient", "chart_answer_mismatch", WARNING,
                  "차트는 그렸는데 답변은 수치를 내지 못함", ", ".join(map(str, ids)))]


def _answer_caveat_conflict(bundle, m3, m6, cited, held: set[str]) -> list[Issue]:
    """보류된 하위 질문의 값을 답하면서 '참고로' 로 낮추지 않은 경우. 다른 하위 질문의 보류는 정상이다.
    범위를 모르는 사유(ref=plan)는 하위 질문이 하나이거나, 사유 문장이 답변에 쓴 항목을 직접 말할 때만 같은 범위로 본다
    (예: 답변 '보증부월세 1,404가구' + 사유 '요청한 지표가 이 표에 없어 계산하지 못했습니다 (표의 항목: 보증부월세)')"""
    if m6.insufficient or not cited or "참고로" in (m6.answer or ""):
        return []
    hit = sorted({r.sub_question_id for r in cited if r.sub_question_id in held})
    single = bundle is None or len(bundle.sub_questions or []) <= 1
    items = {re.sub(r"\(.*?\)", "", i.item).strip() for r in cited for i in r.inputs if i.item} - {""}
    if not hit and any(c.source == "plan_warning" and c.ref == "plan" and "계산하지 못" in c.text
                       and (single or any(x in c.text for x in items)) for c in m6.caveats):
        hit = ["plan"]
    if not hit:
        return []
    return [Issue("A9", "answer.caveats", "answer_caveat_conflict", WARNING,
                  "수치를 답했는데 같은 범위에 '계산하지 못함' 주의사항이 있음", ", ".join(hit))]


def _value_list(m6) -> list[Issue]:
    if m6.method != "template":
        return []
    n = max((int(x) for x in _LIST_TAIL.findall(m6.answer or "")), default=0)
    if n < ANSWER_LIST_MIN:
        return []
    return [Issue("M6-out", "answer", "value_list", WARNING, f"규칙 문장이 값을 나열함 (외 {n}개)", str(n))]


def meaning_issues(m3, m6, bundle=None, charts=None, drawn=None) -> list[Issue]:
    out: list[Issue] = []
    if m3 is not None:
        said, seen = set(), set()
        for i, w in enumerate(m3.chart_plan.withheld):
            scope = w.sub_question_id or w.chart_id or "질문 전체"
            said.add(w.text)
            if (scope, w.text) in seen:          # 같은 하위 질문의 답변 계산 · 차트 계산이 같은 사유로 보류되면 한 건
                continue
            seen.add((scope, w.text))
            out.append(Issue("M3-out", f"chart_plan.withheld[{i}]", "withheld", WARNING, f"계산 보류: {w.text}", scope))
        for i, text in enumerate(m3.chart_plan.warnings):
            if text not in said:
                out.append(Issue("M3-out", f"chart_plan.warnings[{i}]", "plan_warning", WARNING, text, "질문 전체"))
                said.add(text)
        out += _too_many_marks(m3)
    if m6 is not None and m6.method in FALLBACK_TEXT:
        out.append(Issue("M6-out", "method", "answer_fallback", WARNING, FALLBACK_TEXT[m6.method], m6.method))
    if m3 is not None and m6 is not None:
        held = _held_subs(m3)
        cited = _cited(m3, m6)
        answered = [] if m6.insufficient else [r for r in cited if r.sub_question_id not in held]
        out += _condition_unused(bundle, answered)
        out += _ratio_missing(bundle, m3, answered)
        out += _measure_mismatch(m3, charts, held)
        out += _chart_answer_mismatch(m6, drawn)
        out += _answer_caveat_conflict(bundle, m3, m6, cited, held)
        out += _value_list(m6)
    return out


# ── 답할 수 없는 질문 ───────────────────────────────────────────
def unanswerable(viewset: dict, notes: list | None) -> list[str]:
    """본 질문의 지표가 모두 ① 질의 분석의 사전에 없고 ② 고른 표 어디에도 없으면 그 지표들. 아니면 [].
    ② 만 보면 안 된다: '인구수' 를 물었는데 표의 항목이 '국제결혼 이주자' 인 질문은 표 안에 정답이 있다"""
    unknown = {m[1] for n in notes or [] if (m := _UNKNOWN_INDICATOR.search(str(n)))}
    if not unknown:
        return []
    units = [u for u in viewset.get("units") or [] if not (u.get("filters") or {}).get("역할")]
    if not units:
        return []
    names: list[str] = []
    for u in units:
        want = (u.get("filters") or {}).get("지표") or []
        views = (u.get("conflict") or {}).get("views") or []
        if not want or not views or not set(want) <= unknown:
            return []
        if any((v.get("used") or {}).get("지표") is not False for v in views):
            return []
        names += want
    return list(dict.fromkeys(names))
