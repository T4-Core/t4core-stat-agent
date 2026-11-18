"""
[NEW 11-17] 한국어 문장 도우미 — 조사, 시점 표기, 항목 이름의 단위 괄호 (모듈 3 · 모듈 6 이 같이 쓴다)

  [MOVED 11-17] answer_compose/facts.py 의 josa · key_text · _YEAR, chart_calculate/display.py 의 strip_unit · 단위 괄호 정규식.
  사용자용 사유 문장(core/reasons.py)을 모듈 3 의 차트 경고에도 쓰려고 두 모듈 아래가 아닌 core 로 옮겼다 (자체 검토 A-6).
  예전 위치(facts · display)에서도 같은 이름으로 import 된다.
"""
import re
from typing import Any

UNIT_TAIL = re.compile(r"\(([^()]+)\)\s*$")     # '혼인건수(건)' 의 '(건)'

# 받침 판단: 한글은 유니코드로, 숫자는 읽는 소리(영·일·삼·육·칠·팔 = 받침 있음)로 본다
_DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
_JOSA = {"은": ("은", "는"), "이": ("이", "가"), "을": ("을", "를"), "과": ("과", "와"), "으로": ("으로", "로")}


def josa(word: str, kind: str) -> str:
    """josa('혼인건수', '은') → '혼인건수는'. kind = 은 · 이 · 을 · 과 · 으로"""
    with_final, without = _JOSA[kind]
    last = word.rstrip()[-1:] if word.strip() else ""
    final = False
    if "가" <= last <= "힣":
        n = (ord(last) - 0xAC00) % 28
        final = n != 0 and not (kind == "으로" and n == 8)     # '으로' 는 ㄹ 받침도 '로'
    elif last in _DIGIT_FINAL:
        final = _DIGIT_FINAL[last]
        if kind == "으로" and last in "178":                    # 일 · 칠 · 팔 = ㄹ 받침
            final = False
    return word + (with_final if final else without)


_YEAR = re.compile(r"\d{4}")


def key_text(key: dict[str, Any] | None) -> str:
    """문장용 key_label: 시점이 4자리 연도면 '2021년'. (표는 key_label 그대로 '2021')"""
    return " ".join(f"{v}년" if c == "시점" and _YEAR.fullmatch(str(v)) else str(v) for c, v in (key or {}).items())


# [NEW 11-18] 항목 이름 끝 괄호가 단위인지의 판단. 허용 목록으로만 읽는다 — '인구(1세이상)' · '인구(내국인)' · '인구(남/여)' 의 괄호는
# 대상 설명이라 단위가 아니다 (전체 파이프라인 테스트 Q06·Q13·Q21·Q22·Q26). 이전: 끝 괄호를 모두 단위로 읽었다
_UNIT_TOKENS = frozenset({
    "명", "건", "가구", "세대", "개", "호", "%", "%p", "‰", "원", "천원", "만원", "백만원", "십억원", "억원", "조원", "달러", "천달러", "백만달러",
    "천명", "만명", "천가구", "천호", "세", "년", "개월", "일", "시간", "회", "배", "㎡", "㎢", "㎞²", "km²", "ha", "kg", "톤", "대", "index"})
# 인구천명당 · 천명당 · 10만명당 · 인구10만명당 (분모가 사람 · 가구 수인 비율 단위). '1인당' · '세대당' 같은 설명은 해당 없음
_RATE_UNIT = re.compile(r"^(?:인구|가구)?\d*(?:천|만|십만|백만)?(?:명|가구|세대|건|호)당$")


def unit_text(text: str) -> str | None:
    """단위로 읽히면 공백을 뺀 단위 글자, 아니면 None. '천 명' → '천명', '명/㎢' → '명/㎢', '1세이상' · '남/여' → None"""
    t = re.sub(r"\s+", "", text or "")
    if not t:
        return None
    if t in _UNIT_TOKENS or _RATE_UNIT.match(t):
        return t
    parts = t.split("/")
    if len(parts) == 2 and all(p in _UNIT_TOKENS for p in parts):    # 명/㎢ · 건/천명: 양쪽이 모두 단위일 때만
        return t
    return None


def unit_tail(item: str | None) -> str | None:
    """항목 이름 맨 끝 괄호가 단위이면 그 단위, 아니면 None ('인구(1세이상)(명)' → '명', '인구(1세이상)' → None)"""
    m = UNIT_TAIL.search(item or "")
    return unit_text(m.group(1)) if m else None


def strip_unit(item: str) -> str:
    """'혼인건수(건)' → '혼인건수' (축 이름·범례용). 단위로 읽히는 끝 괄호만 뗀다 ('인구(1세이상)(명)' → '인구(1세이상)')"""
    out = item.strip()
    while (m := UNIT_TAIL.search(out)) and unit_text(m.group(1)):
        out = out[:m.start()].strip()
    return out
