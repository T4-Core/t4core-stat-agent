"""④-1 차트 요청 · 데이터 모양 점수 (고도화 3단계) — 규칙, HCX 호출 없음

  requested_chart(texts)                → (차트, 찾은 말) 질문 속 차트 이름. 없으면 (None, None)
  shape_score(chart, profile, measure)  → (점수, 근거) 데이터 모양에 얼마나 잘 맞는지

  - 차트 이름은 원 질문 → 하위질문 → 재작성 순서로 찾는다 (재작성에서 '지도로' 같은 말이 빠질 수 있어서)
  - 점수는 2단계 profile 의 category_axis · series_axis · dims 를 쓴다
"""
import re

from .chart_type_rules import CHART_WORDS, SHAPE_SCORES

TIME = "시점"


def _ns(s):
    return re.sub(r"\s+", "", str(s or ""))


def requested_chart(texts):
    """texts(문장 목록, 앞쪽이 우선)에서 차트 이름 찾기 → (차트, 찾은 말)"""
    words = sorted(CHART_WORDS, key=lambda w: -len(_ns(w)))       # 긴 말부터
    for text in texts:
        t = _ns(text)
        if not t:
            continue
        hits = []
        for w in words:
            k = _ns(w)
            pos = t.find(k)
            if pos >= 0:
                hits.append((pos, w))
                t = t.replace(k, "□" * len(k))                      # 찾은 부분은 지워 짧은 말이 다시 걸리지 않게
        if hits:
            pos, w = min(hits)                                       # 문장에서 가장 앞에 나온 차트 이름
            return CHART_WORDS[w], w
    return None, None


def shape_score(chart, profile, measure):
    """차트 하나의 데이터 모양 점수 → (점수, 근거 문장)"""
    cat = profile.get("category_axis") or {}
    ser = profile.get("series_axis") or {}
    dims = profile.get("dims") or []
    n_cat = profile.get("n_categories", 0)
    if chart == "pyramid" and cat.get("axis") == "연령" and ser.get("axis") == "성별" and ser.get("n") == 2:
        return SHAPE_SCORES["pyramid_age_sex"], "범주 = 연령, 계열 = 성별 2개"
    if chart == "line" and cat.get("axis") == TIME and cat.get("n", 0) >= 3:
        return SHAPE_SCORES["line_time"], f"범주 = 시점 {cat.get('n')}개"
    if chart == "heatmap":
        non_time = [d for d in dims if d.get("axis") != TIME]
        if len(non_time) >= 2 and all(d.get("n", 0) >= 3 for d in non_time[:2]):
            return SHAPE_SCORES["heatmap_two_axes"], f"나눔 2개 ({non_time[0]['col']} × {non_time[1]['col']})"
    if chart == "donut" and measure == "share" and n_cat <= 5:
        return SHAPE_SCORES["donut_small_share"], f"비중 · 범주 {n_cat}개"
    if chart == "bar":
        if measure == "rank":
            return SHAPE_SCORES["bar_rank"], "순위"
        return SHAPE_SCORES["bar_base"], "기본"
    return 0, ""
