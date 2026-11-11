"""⑥ reason 작성 (노트북 8번)

템플릿 "{지표} {비교축}별 {의도}"로 차트를 고른 이유 문장을 만든다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
from .chart_type_measure import end_intent
from .chart_type_rules import REASON_TEMPLATE


def make_reason(sub_filters, query_bundle, sub_questions=()):
    """템플릿 "{지표} {비교축}별 {의도}"로 차트를 고른 이유 문장을 만든다.
    - 지표·비교축: sub_filters[i] (combo처럼 하위질문이 여러 개면 지표를 '·'로 이음)
    - 의도: QueryBundle의 intent. 없으면 하위질문 끝의 INTENTS 키워드
    - 비교축이 없으면 "{지표} {의도}"로 줄인다.
    """
    def as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def uniq(xs):
        return list(dict.fromkeys(x for x in xs if x))

    indicators = uniq(x for f in sub_filters for x in as_list(f.get("지표")))
    axes = uniq(x for f in sub_filters for x in as_list(f.get("비교축")))
    intents = uniq(as_list(query_bundle.get("intent")))
    if not intents:                                            # intent가 비면 하위질문 끝 키워드로
        intents = uniq(end_intent(q) for q in sub_questions)

    지표 = "·".join(indicators) or "값"
    의도 = "·".join(intents) or "조회"
    if axes:
        return REASON_TEMPLATE.format(지표=지표, 비교축="·".join(axes), 의도=의도)
    return f"{지표} {의도}"
