"""
[NEW 11-18] 질문의 지표와 계산에 쓸 항목이 같은 것인지 판단한다 (F7 · F16)

  '2023년 시도별 인구 순위' 에 출생성비 표가 와도 HCX 가 첫 항목(총출생성비)을 골라 순위를 냈다 (Q08).
  단어가 겹친다는 이유만으로 같은 지표로 보지 않는다: '인구수' 와 '인구성장률' 은 다른 지표다.

  대응으로 보는 경우 (정규화한 이름이)
    · 같다                       인구수(명) ↔ 인구, 혼인건수 ↔ 혼인건수(건), 총인구 ↔ 인구
    · 알려진 동의어              출생 ↔ 출생아, 사망 ↔ 사망자, 구성비 ↔ 비율
    · 범위를 좁히지 않는 수식어   추계인구 ↔ 인구
    · 항목에만 모집단 설명 괄호가 있음   인구(1세이상) ↔ 인구수  (지표에도 괄호가 있으면 서로 같아야 한다)
  대응하지 않는 경우
    · 비율 · 증가 · 지수 계열 접미사가 한쪽에만 있다   인구성장률 ≠ 인구수, 출생성비 ≠ 출생아수
    · 양쪽에 모집단 설명 괄호가 있는데 다르다          인구(내국인) ≠ 인구(외국인)
    · 일부를 뜻하는 수식어                            남자인구 · 1인가구 ≠ 인구 · 가구수
  정규화는 **질문의 지표 쪽에만** 계산어(증감률 · 추이 …)를 뗀다. 항목 이름의 '증가율' 은 지표의 일부라서 지우지 않는다.
"""
import re

from backend.core.korean import strip_unit

# 질문의 지표 뒤에 붙는 '계산해서 만드는 값' 말 — 지표 자체가 아니다 ('혼인건수 증감률' 의 지표는 혼인건수). 항목 이름에는 적용하지 않는다
_DERIVED_TAIL = re.compile(r"\s*(?:증감률|증가율|감소율|변화율|변동률|증감|증가|감소|변화|변동|추이|순위)$")
_PAREN = re.compile(r"\(([^()]*)\)|（([^（）]*)）")
_COUNT_TAIL = re.compile(r"(?:건수|자수|아수|수|명|건)$")                 # 인구수 → 인구, 출생아수 → 출생아, 혼인건수 → 혼인
_RATIO_WORDS = ("률", "율", "비율", "구성비", "비중", "성비", "밀도", "지수", "배율", "증가", "감소", "성장")   # 이 말이 있으면 개수가 아니라 비율 · 증가 계열
_HARMLESS_PREFIX = {"추계", "주민등록", "상주", "현재"}                    # 값의 범위를 좁히지 않는 수식어. 남자 · 1인 · 유소년 같은 것은 일부를 뜻한다

# 같은 뜻으로 쓰는 말 (정규화 뒤 비교). 값이 같으면 대응
_SYNONYMS = {"총인구": "인구", "주민등록인구": "인구", "출생": "출생아", "사망": "사망자", "구성비": "비율", "비중": "비율"}


def _split(name: str, derived: bool) -> tuple[str, str]:
    """이름 → (본체, 모집단 설명 괄호). 단위 괄호('(명)')는 먼저 떼고, 남은 괄호('(1세이상)' · '(내국인)')는 설명으로 따로 둔다"""
    t = strip_unit(name or "")
    if derived:
        t = _DERIVED_TAIL.sub("", t)
    desc = "".join(a or b for a, b in _PAREN.findall(t))
    body = _PAREN.sub("", t)
    body = re.sub(r"[\s·,:]+", "", body).replace("구성비", "비율").replace("비중", "비율")
    return body, re.sub(r"\s+", "", desc)


def _stem(body: str) -> str:
    if _is_ratio(body):
        return body                                    # 비율 · 증가 계열은 '수' 를 떼지 않는다 (성장률 ≠ 인구)
    t = _COUNT_TAIL.sub("", body) or body
    t = t[1:] if t.startswith("총") and len(t) > 1 else t
    return _SYNONYMS.get(t, t)


def _is_ratio(text: str) -> bool:
    return any(w in text for w in _RATIO_WORDS)


def matches(item: str | None, indicator: str | None, strict: bool = False) -> bool:
    """항목이 지표에 대응하는가. strict=True 면 수식어 허용 없이 이름이 같을 때만 (View 가 '지표와 맞는 항목 없음' 이라고 한 경우)"""
    if not item or not indicator:
        return True                                   # 비교할 것이 없으면 막지 않는다
    ib, idesc = _split(item, derived=False)
    for derived in (True, False):          # 계산어를 뗀 지표('인구') 와 그대로인 지표('인구 증가율' = 표에 미리 계산된 항목) 둘 다 본다
        pb, pdesc = _split(indicator, derived=derived)
        a, b = _stem(ib), _stem(pb)
        if idesc and pdesc and idesc != pdesc:
            continue                                  # 인구(내국인) ≠ 인구(외국인)
        if not b or a == b:
            return True
        if strict or _is_ratio(a) or _is_ratio(b):
            continue                                  # 비율 계열은 같은 이름일 때만 (인구성장률 ≠ 인구수)
        if a.endswith(b) and a[:-len(b)] in _HARMLESS_PREFIX:
            return True
    return False


def matches_any(item: str | None, indicators: list[str], strict: bool = False) -> bool:
    return not indicators or any(matches(item, i, strict) for i in indicators)


def is_count_indicator(indicator: str | None) -> bool:
    """개수 · 크기를 묻는 지표인가 (가구수 · 인구수 · 혼인건수). 비율 · 증가 계열(인구성장률)이면 False"""
    body, _ = _split(indicator or "", derived=True)
    return bool(body) and not _is_ratio(body)


def corresponds(item: str | None, indicators: list[str], targets: list[str], strict: bool = False) -> bool:
    """항목이 요청한 지표에 대응하는가. 지표가 개수(가구수)이면 항목이 **대상**(1인가구)의 이름이어도 된다 (Q25 — 항목이 곧 대상을 센 값).
    지표가 비율 · 증가(인구성장률)이면 대상 이름(인구)이 맞아도 지표가 아니므로 통과시키지 않는다 (검토 11)"""
    if not indicators:
        return True
    return any(matches(item, i, strict) or (is_count_indicator(i) and any(matches(item, t, strict) for t in targets)) for i in indicators)


_CATEGORY_LABELS = {"계", "합계", "전체", "남자", "여자", "남", "여", "남성", "여성", "소계"}


def is_category_label(item: str | None) -> bool:
    """항목 값이 지표 이름이 아니라 구분 값(나이 · 성별 · 총계)인가. 항목 열에 0세 · 남자 같은 값이 든 표는 항목으로 지표를 알 수 없다 → 검사하지 않는다"""
    t = re.sub(r"\s+", "", _PAREN.sub("", item or ""))
    return t in _CATEGORY_LABELS or bool(re.fullmatch(r"\d+(?:[-~]\d+)?세(?:이상)?", t))
