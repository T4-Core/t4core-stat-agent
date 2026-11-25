"""조사 이름 읽기 — 질문 속 조사 이름·줄임말 → 코퍼스의 조사 이름 (survey_nm)

왜   검색은 질문에 조사 이름이 글자 그대로 있을 때만 그 조사 표를 올렸다 (engine.feasibility survey_hit).
     '센서스'·'인구동향'·'주민등록' 처럼 줄여 말하면 조사가 반영되지 않았고, 사용자가 조사를 지정할 길도 없었다.
무엇  ALIASES = 조사마다 그 이름에서 나온 일반적인 줄임말 (실패 문항에서 고른 낱말이 아님).
     '총조사'·'센서스' 처럼 여러 조사를 가리키는 말은 그 조사들 모두.
     '연앙인구' 는 주민등록 연앙인구 표가 국내인구이동통계에 있어 그쪽 (주민등록인구현황 아님).

  detect_surveys(question) → {survey_nm, …}
  survey_options(candidates, ratio) → 상위 후보가 여러 조사로 갈리고 점수가 비슷하면 조사별 대표 표 목록 (아니면 [])
"""
from __future__ import annotations

import re

# 긴 말을 먼저 (짧은 말이 긴 말의 일부로 먼저 잡히지 않게)
ALIASES = {
    "인구주택총조사": ("인구총조사", "주택총조사"),
    "세종시특별센서스": ("세종시 특별센서스",), "특별센서스": ("세종시 특별센서스",),
    "인구총조사": ("인구총조사",), "주택총조사": ("주택총조사",),
    "총조사": ("인구총조사", "주택총조사"), "센서스": ("인구총조사", "주택총조사"),
    "인구동향": ("인구동향조사",),
    "사할린": ("영주귀국사할린동포실태조사",),
    "외국인주민현황": ("지방자치단체외국인주민현황",), "외국인주민": ("지방자치단체외국인주민현황",),
    "체류외국인": ("출입국자및체류외국인통계",), "출입국": ("출입국자및체류외국인통계",),
    "국내인구이동": ("국내인구이동통계",), "연앙인구": ("국내인구이동통계",),
    "국제인구이동": ("국제인구이동통계",),
    "장래인구추계": ("장래인구추계",), "인구추계": ("장래인구추계",),
    "장래가구추계": ("장래가구추계",), "가구추계": ("장래가구추계",),
    "인구동태패널": ("인구동태패널통계",), "패널통계": ("인구동태패널통계",),
    "고령친화": ("고령친화용품제조업실태조사",),
    "주민등록인구": ("주민등록인구현황",), "주민등록": ("주민등록인구현황",),
}
_ORDER = sorted(ALIASES, key=len, reverse=True)


def _squash(t):
    return re.sub(r"\s+", "", str(t or ""))


def detect_surveys(question) -> set:
    """질문에 나온 조사 이름·줄임말 → 조사 이름 집합. 긴 말이 잡힌 자리는 짧은 말로 다시 세지 않음"""
    q = _squash(question)
    out = set()
    for a in _ORDER:
        if a in q:
            out.update(ALIASES[a])
            q = q.replace(a, " ")
    return out


def survey_options(candidates, ratio=0.9, max_n=4):
    """후보 목록 [{rank, tbl_id, survey_nm, score}] → 조사별 대표(그 조사에서 가장 높은 표)
    1위 조사 밖에 점수 비 ≥ ratio 인 다른 조사가 있을 때만 (아니면 []) — 앱이 '어느 조사 기준으로 볼까요' 를 물을 수 있게"""
    best = {}
    for c in candidates or []:
        s = c.get("survey_nm") or ""
        if s and s not in best:
            best[s] = c
    if len(best) < 2:
        return []
    top = next(iter(best.values()))
    a = float(top.get("score") or 0)
    if a <= 0:
        return []
    close = [c for s, c in best.items() if c is top or float(c.get("score") or 0) / a >= ratio]
    if len(close) < 2:
        return []
    return [{"survey_nm": c["survey_nm"], "tbl_id": c["tbl_id"], "tbl_nm": c.get("tbl_nm"), "rank": c["rank"],
             "score": c.get("score")} for c in close[:max_n]]
