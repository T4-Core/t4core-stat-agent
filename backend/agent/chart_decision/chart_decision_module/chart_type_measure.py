"""② measure 판단 (노트북 4번)

규칙(재작성 질문)으로 먼저 정하고, 확신이 없으면 LLM이 원 질문·재작성 질문을 보고 채운다.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import re
import time

from .chart_type_llm import hcx_chat
from .chart_type_rules import (
    DATA_SCOPE, INTENT_TO_MEASURE, MEASURE_CHOICES, MEASURE_KEYWORDS, MEASURES, OUT_OF_SCOPE,
)


def _ns(s):
    """공백 제거 (키워드 비교용)"""
    return re.sub(r"\s+", "", str(s or ""))

def end_intent(text):
    """문장 끝의 INTENTS 키워드. 긴 키워드부터 비교 ('증감률'이 '증감'보다 먼저)"""
    t = _ns(text).rstrip(".?!")
    for kw in sorted(INTENT_TO_MEASURE, key=lambda k: -len(_ns(k))):
        if t.endswith(_ns(kw)):
            return kw
    return None

def keyword_hits(text):
    """문장 안의 일반 키워드로 measure 후보 찾기.
    긴 키워드부터 찾고, 찾은 부분은 지워서 짧은 키워드가 다시 걸리지 않게 한다
    (예: '연평균 증가율'을 찾으면 '증가율'·'평균'은 다시 안 걸림)"""
    t = _ns(text)
    pairs = sorted(((_ns(kw), m) for m, kws in MEASURE_KEYWORDS.items() for kw in kws),
                   key=lambda p: -len(p[0]))
    hits = []
    for kw, m in pairs:
        if kw in t:
            t = t.replace(kw, "□")
            if m not in hits:
                hits.append(m)
    return hits

def decide_measure_rule(sub_question, query_bundle):
    """규칙으로 measure 판단 (재작성 질문만 봄). 반환: (measure, 확신 여부, 근거, 힌트)
    확신이 없으면 measure는 None으로 비워 두고 LLM이 채운다.
    순서: ① 하위질문 끝 키워드 → ② rewritten 끝 키워드 → ③ intent 필드 → ④ 일반 키워드 → ⑤ 못 찾음"""
    # ①② 재작성 질문 끝의 INTENTS 키워드
    for name, text in (("sub_question 끝", sub_question), ("rewritten 끝", query_bundle.get("rewritten"))):
        kw = end_intent(text)
        if kw:
            if INTENT_TO_MEASURE[kw] is None:            # 예: '범위 밖' → LLM이 확인
                return None, False, f"{name} '{kw}' → LLM 확인", [kw]
            return INTENT_TO_MEASURE[kw], True, f"{name} '{kw}'", []

    # ③ QueryBundle의 intent 필드 (INTENTS와 같은 값). 하나로 정해질 때만 확신
    intents = [i for i in (query_bundle.get("intent") or []) if i in INTENT_TO_MEASURE]
    measures = {INTENT_TO_MEASURE[i] for i in intents}
    if len(measures) == 1 and None not in measures:
        return measures.pop(), True, f"intent {intents}", []

    # ④ 일반 키워드 (하위질문 + rewritten). 후보가 하나일 때만 확신
    hits = keyword_hits(f"{sub_question} {query_bundle.get('rewritten') or ''}")
    if len(hits) == 1:
        return hits[0], True, f"키워드 → {hits[0]}", []
    if len(hits) > 1:
        return None, False, f"키워드 후보 여러 개 {hits}", hits

    # ⑤ 못 찾음 → 비워 두고 LLM이 채움
    return None, False, "키워드 없음", []

MEASURE_SCHEMA = {
    "type": "object",
    "properties": {
        "measure": {"type": "string", "enum": MEASURE_CHOICES},
        "reason": {"type": "string"},     # 이 값을 고른 이유
    },
    "required": ["measure", "reason"],
}

MEASURE_SYSTEM_PROMPT = (
    "너는 통계 질문을 보고 값을 어떻게 가공해 보여줄지(measure) 고르는 분류기다.\n"
    "사용자의 원 질문과 재작성된 질문을 함께 보고, 아래 값 중 하나만 고른다.\n"
    "\n"
    "[measure 11개]\n"
    "raw: 통계표 숫자를 그대로 (값 조회, 추이, 비교)\n"
    "change: 이전 시점 대비 몇 개 늘거나 줄었는지\n"
    "growth_rate: 이전 시점 대비 몇 % 늘거나 줄었는지\n"
    "cagr: 여러 해 변화를 1년 평균 몇 %로 환산\n"
    "index: 기준 시점=100으로 환산\n"
    "share: 전체 중 각 항목 비중(%)\n"
    "diff: 같은 시점 두 항목 값의 차이(A−B)\n"
    "ratio: 한 항목이 다른 항목의 몇 배(A÷B)\n"
    "rank: 크기순 순위, 상위·하위 몇 개\n"
    "extreme: 가장 큰 값/가장 작은 값 하나와 그 시점·항목\n"
    "aggregate: 합계 또는 평균으로 하나로 요약\n"
    "\n"
    "[범위 밖]\n"
    "지금 가진 데이터는 KOSIS(국가통계포털)의 '인구' 분야 통계뿐이다. 다음 12개 통계만 있다.\n"
    + "\n".join(f"- {s}" for s in DATA_SCOPE) + "\n"
    "인구 수, 가구, 출생·사망·혼인·이혼, 인구 이동, 외국인·출입국, 장래 인구·가구 추계처럼 "
    "위 통계로 답할 수 있는 질문만 범위 안이다.\n"
    "위 통계는 대부분 시도·시군구 같은 지역별, 성별·연령별로 나뉘어 있다. "
    "그래서 '어느 지역에 ○○가 가장 많은가', '○○가 많이 사는 동네'처럼 지역을 묻는 질문도, "
    "○○가 인구·외국인 주민·가구 등 위 통계의 대상이면 범위 안이다.\n"
    "다음 중 하나에 해당하면 measure 대신 '범위 밖'을 고른다.\n"
    "- 인구 분야가 아닌 주제를 묻는다. (예: 날씨, 기온, 미세먼지, 물가, 주가, 환율, 부동산 가격, 교통, 맛집, 뉴스, 일반 상식)\n"
    "- 통계 수치로 답할 수 없는 질문이다. (예: 의견, 추천, 잡담, 인사, 서비스 사용법)\n"
    "지역 이름이나 연도가 들어 있어도, 묻는 대상이 인구 통계가 아니면 범위 밖이다.\n"
    "반대로 묻는 대상이 인구 통계라면, 시점·지역이 빠졌거나 표현이 애매해도 범위 밖으로 고르지 않는다. "
    "이때는 measure 11개 중 가장 가까운 것을 고르고, 잘 모르겠으면 raw를 고른다.\n"
    "범위 밖은 묻는 주제가 인구 분야가 아닐 때만 고른다. 아래 이유로는 절대 범위 밖을 고르지 않는다: 질문이 짧다, 구체적인 내용이 없다, 계산·수치 요청이 없다, 시점이나 지역이 없다. 이런 경우는 모두 raw다.\n"
    "예: '서울 날씨' → 범위 밖 / '삼성전자 주가 알려줘' → 범위 밖 / '서울 인구 몇 명이야' → raw / "
    "'요즘 아기 덜 태어나?' → 출생아수 변화를 묻는 인구 통계 질문이므로 범위 안 (change) / '우리 동네 사람 많아?' → 인구 수를 묻는 질문이므로 범위 안 (raw) / '외국인 제일 많이 사는 동네' → 지역별 외국인 주민 수로 답할 수 있으므로 범위 안 (extreme)\n"
    "'출생아수', '혼인건수', '외국인 주민', '고령인구', '서울 인구'처럼 지표나 대상 이름만 있고 계산 표현이 없는 질문 → 인구 통계 값을 그대로 묻는 것이므로 raw (질문이 짧거나 애매하다는 이유로 범위 밖을 고르지 않는다)\n"
    "\n"
    "답은 JSON으로 하고, reason에는 질문의 어떤 표현 때문에 그 값을 골랐는지 한 문장으로 쓴다. "
    "범위 밖을 골랐다면 왜 인구 통계로 답할 수 없는지 쓴다."
)

def decide_measure_llm(sub_question, query_bundle, hints):
    """규칙이 정하지 못한 measure를 HCX가 채운다 (B안).
    원 질문(original)과 재작성 질문(rewritten, 하위질문)을 함께 보여주고, measure와 고른 이유를 받는다.
    반환: (measure 11개 중 하나 또는 '범위 밖', 없으면 None), reason"""
    user = (f"원 질문: {query_bundle.get('original')}\n"
            f"재작성된 전체 질문: {query_bundle.get('rewritten')}\n"
            f"재작성된 하위질문: {sub_question}\n"
            f"의도: {query_bundle.get('intent')}\n"
            f"규칙이 찾은 힌트: {hints or '없음'}")
    out = hcx_chat([{"role": "system", "content": MEASURE_SYSTEM_PROMPT},
                    {"role": "user", "content": user}], schema=MEASURE_SCHEMA, max_tokens=300)
    out = out if isinstance(out, dict) else {"_raw": out}
    measure = out.get("measure")
    reason = out.get("reason") or out.get("_raw") or ""
    if measure not in MEASURE_CHOICES:           # 허용 값 밖이면 비워 둠
        reason = f"(LLM 응답 '{measure}'가 허용 값에 없어 비워 둠) {reason}"
        measure = None
    return measure, reason

def decide_measure(sub_question, query_bundle, use_llm=True):
    """measure 판단. 반환: {"measure", "confident", "source", "basis", "llm_called", "llm_reason", "llm_seconds"}
    - 규칙이 확신하면 규칙 값 (source="rule")
    - 확신이 없으면 measure를 비워 두고 LLM이 채운다 (source="llm", '범위 밖'도 여기서 채워짐)
    - LLM을 안 쓰거나 실패하면 measure는 None (source="none")"""
    measure, confident, basis, hints = decide_measure_rule(sub_question, query_bundle)
    result = {"measure": measure, "confident": confident, "source": "rule",
              "basis": basis, "llm_called": False, "llm_reason": None, "llm_seconds": None}
    if confident:
        return result
    result["source"] = "none"                    # LLM이 채우기 전까지 비어 있음
    if not use_llm:
        return result
    result["llm_called"] = True
    t0 = time.perf_counter()                     # LLM 호출 ~ 응답까지 시간
    try:
        result["measure"], result["llm_reason"] = decide_measure_llm(sub_question, query_bundle, hints)
        if result["measure"] is not None:
            result["source"] = "llm"
    except Exception as e:                       # LLM 실패 시 비워 둠
        result["llm_reason"] = f"LLM 실패: {e}"
    finally:
        result["llm_seconds"] = round(time.perf_counter() - t0, 2)
    return result
