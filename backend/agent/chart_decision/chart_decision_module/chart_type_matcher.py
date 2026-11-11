"""① 하위질문 ↔ View 짝짓기 (노트북 2번)

sub_questions[i]와 units[].query를 공백 지우고 비교해 짝짓고, chart_id를 붙인다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import re


def norm_text(s):
    """공백을 모두 지운 문장 (짝짓기 비교용)"""
    return re.sub(r"\s+", "", s or "")

def match_units(query_bundle, view_input):
    """하위질문과 View 입력의 unit을 짝짓고, unit마다 rank 1 View를 연결한다. 짝지은 순서대로 chart_id(c1, c2…)를 붙인다.

    - 하위질문이 있으면: main을 빼고, 공백 지운 sub_questions[i]와 units[].query가 같으면 짝.
      문장이 달라 못 찾으면 unit_id 순서(<query_id>-1, -2 …)로 짝짓는다.
    - 하위질문이 없으면(질문을 나누지 않은 경우): main unit을 rewritten·filters와 짝지어 차트 1개.
    - sub_filters[i]가 없으면 전체 filters를 쓴다.

    반환: (matches, errors)
      matches: [{"chart_id", "unit_id", "sub_question", "sub_filter", "view", "match_by"}, ...]
      errors : [{"sub_question", "reason"}, ...]  짝이 없거나 View가 없는 하위질문
    """
    sub_qs = query_bundle.get("sub_questions") or []
    sub_fs = list(query_bundle.get("sub_filters") or [])
    filters = query_bundle.get("filters") or {}
    units = view_input.get("units") or []
    by_text = {norm_text(u["query"]): u for u in units if u["unit_id"] != "main"}   # main 제외
    by_id = {u["unit_id"]: u for u in units}
    matches, errors = [], []

    if sub_qs:
        pairs = []
        for i, sub_q in enumerate(sub_qs):
            sub_f = sub_fs[i] if i < len(sub_fs) and sub_fs[i] else filters
            unit, how = by_text.get(norm_text(sub_q)), "문장"
            if unit is None:                                                  # 문장이 다르면 순서로
                unit, how = by_id.get(f'{view_input.get("query_id")}-{i + 1}'), "순서"
            pairs.append((sub_q, sub_f, unit, how))
    else:                                                                     # 하위질문 없음 → main 하나
        main = by_id.get("main")
        pairs = [(query_bundle.get("rewritten") or (main or {}).get("query"), filters, main, "main")]

    for sub_q, sub_f, unit, how in pairs:
        if unit is None:
            errors.append({"sub_question": sub_q, "reason": "짝 없음 (같은 문장·순서의 unit 없음)"})
            continue
        if not unit.get("views"):
            errors.append({"sub_question": sub_q, "reason": f"View 없음 ({unit['unit_id']})"})
            continue
        view = min(unit["views"], key=lambda v: v["rank"])             # rank 1
        matches.append({"chart_id": f"c{len(matches) + 1}",            # 짝지은 순서대로
                        "unit_id": unit["unit_id"], "sub_question": sub_q,
                        "sub_filter": sub_f, "view": view, "match_by": how})
    return matches, errors
