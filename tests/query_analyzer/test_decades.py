"""연대 표현 → 시점 ('80~90년대 울산광역시 출생아수' 에서 시점이 빠지던 문제)"""
from datetime import date

import pytest

from backend.rag.query_analyzer.extract import rule_extract
from backend.rag.search.query import synonyms

TODAY = date(2026, 11, 2)


def years(q):
    _, found, _ = rule_extract(q, TODAY)
    ys = [int(t[:4]) for t in found.get("시점") or []]
    return (ys[0], ys[-1], len(ys)) if ys else None


@pytest.mark.parametrize("q, want", [
    ("80~90년대 울산광역시 출생아수?", (1980, 1999, 20)),
    ("1990년대 인구", (1990, 1999, 10)),
    ("90년대 인구", (1990, 1999, 10)),
    ("70년대 인구", (1970, 1979, 10)),
    ("2000년대 연도별 출생아 수", (2000, 2009, 10)),
    ("2000년대 초반 혼인", (2000, 2003, 4)),         # 초반 0~3 · 중반 4~6 · 후반 7~9 · 전반 0~4
    ("2000년대 중반 서울 인구", (2004, 2006, 3)),
    ("90년대 후반 이혼건수", (1997, 1999, 3)),
    ("90년대 말 이혼건수", (1997, 1999, 3)),
    ("1990년대 전반 사망자", (1990, 1994, 5)),
    ("80년대 후반~90년대 초반 출생아", (1987, 1993, 7)),
    ("1980년대부터 1990년대까지 사망자", (1980, 1999, 20)),
    ("80·90년대 혼인건수", (1980, 1999, 20)),
    ("1990년대와 2000년대 출생아", (1990, 2009, 20)),
    ("2020년대 출생아 추이", (2020, 2025, 6)),       # 끝은 작년까지
    ("2010~2020년 인구", (2010, 2020, 11)),         # 연도 범위는 그대로
    ("최근 30년 이민자 수", (1996, 2025, 30)),
])
def test_decade_to_years(q, want):
    assert years(q) == want


@pytest.mark.parametrize("q", ["80년대생 인구", "1980년대생 여성"])
def test_decade_cohort_is_birth_year_not_period(q):
    _, found, _ = rule_extract(q, TODAY)
    assert found.get("시점") is None and found.get("조건") == ["출생연도=1980~1989년생"]


def test_age_is_not_a_decade():
    _, found, _ = rule_extract("20대 인구", TODAY)
    assert found.get("시점") is None and found.get("연령")


def test_immigrant_words_add_foreign_population_terms():
    assert synonyms("최근 30년 이민자 수")[:2] == ["체류외국인", "외국인주민"]
    assert "체류외국인" not in synonyms("결혼이민자 수")          # 결혼이민자는 따로
    assert "체류외국인" not in synonyms("이민자 교육 프로그램 참여")
