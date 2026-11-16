"""글자 정규화 · 표기 변형 (채널들이 같이 씀)"""
from __future__ import annotations

import math
import re
import unicodedata

_PUNCT = re.compile(r"[\s·ㆍ,\.\-_/'\"“”‘’:;~–()（）\[\]{}<>「」?!|]+")
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）")
# 표를 가르지 못하는 값 (어느 표에나 있는 합계 줄 · 숫자만)
TOTALS = {"계", "합계", "총계", "전체", "소계", "총합계", "전국", "기타", "미상", "해당없음"}


def norm(s) -> str:
    """비교용: NFKC · 소문자 · 공백·구두점 제거 ('출생아 수' = '출생아수')"""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")).lower())


def variants(name) -> set[str]:
    """값 이름 → 같은 값으로 볼 표기 ('출생아수(명)' → 출생아수·출생아, '행정구역(시도)별' → 행정구역시도별·행정구역·행정구역별)"""
    out = {norm(name), norm(_PAREN.sub("", str(name or "")))}
    for v in list(out):
        if v.endswith("별") and len(v) > 2:
            out.add(v[:-1])
        if v.endswith("수") and len(v) > 2:
            out.add(v[:-1])
        if "_" in str(name):                              # '내국인_계' → 내국인
            head = norm(str(name).split("_")[0])
            if len(head) >= 2:
                out.add(head)
    return {v for v in out if len(v) >= 2 and v not in TOTALS and not v.isdigit()}


def bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def idf(df: int, n: int) -> float:
    return math.log(1.0 + n / max(df, 1))
