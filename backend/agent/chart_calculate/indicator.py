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
_HARMLESS_PREFIX = {"추계", "주민등록", "상주", "현재", "전체"}                    # 값의 범위를 좁히지 않는 수식어. 남자 · 1인 · 유소년 같은 것은 일부를 뜻한다

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


def _without_prefix(stem: str) -> str:
    """범위를 좁히지 않는 수식어(추계 · 전체 …)를 앞에서 떼고 동의어를 다시 적용한다. 떼고 남는 것이 없으면 그대로"""
    for pre in _HARMLESS_PREFIX:
        if stem.startswith(pre) and len(stem) > len(pre):
            rest = stem[len(pre):]
            return _SYNONYMS.get(rest, rest)
    return stem


def _is_ratio(text: str) -> bool:
    return any(w in text for w in _RATIO_WORDS)


def matches(item: str | None, indicator: str | None, strict: bool = False, modifiers=frozenset()) -> bool:
    """항목이 지표에 대응하는가. strict=True 면 수식어 허용 없이 이름이 같을 때만 (View 가 '지표와 맞는 항목 없음' 이라고 한 경우)
    modifiers: [NEW 11-25] 질문이 요청한 수식어 (성별: 남자 · 남 · 남성 …). 항목 = 수식어 + 지표 이면 대응으로 본다.
      '남녀 인구' 를 물었을 때 표의 '남자인구수' 는 인구수의 일부가 아니라 질문이 요청한 값이다. 수식어가 질문에 없으면 지금처럼 다른 지표"""
    if not item or not indicator:
        return True                                   # 비교할 것이 없으면 막지 않는다
    ib, idesc = _split(item, derived=False)
    for derived in (True, False):          # 계산어를 뗀 지표('인구') 와 그대로인 지표('인구 증가율' = 표에 미리 계산된 항목) 둘 다 본다
        pb, pdesc = _split(indicator, derived=derived)
        a, b = _stem(ib), _stem(pb)
        a = a if strict else _without_prefix(a)       # [NEW 11-20] '전체출생'(전체 출생아수) → '출생아' — 동의어 변환이 접두어 때문에 빗나가지 않게
        if idesc and pdesc and idesc != pdesc:
            continue                                  # 인구(내국인) ≠ 인구(외국인)
        if not b or a == b:
            return True
        if strict or _is_ratio(a) or _is_ratio(b):
            continue                                  # 비율 계열은 같은 이름일 때만 (인구성장률 ≠ 인구수)
        if a.endswith(b) and a[:-len(b)] in _HARMLESS_PREFIX:
            return True
        if a.endswith(b) and a[:-len(b)] in modifiers:      # [NEW 11-25] 남자 + 인구 ↔ 인구 (질문이 성별을 요청했을 때만)
            return True
    return False


def matches_any(item: str | None, indicators: list[str], strict: bool = False, modifiers=frozenset()) -> bool:
    return not indicators or any(matches(item, i, strict, modifiers) for i in indicators)


# [NEW 11-20] 평균 · 1인당 · 밀도는 개수가 아니다 (평균가구원수 2.3 은 개수 지표로 보면 안 된다)
_NOT_COUNT = ("평균", "1인당", "밀도")


def is_count_indicator(indicator: str | None) -> bool:
    """개수 · 크기를 묻는 지표인가 (가구수 · 인구수 · 혼인건수). 비율 · 증가 계열(인구성장률), 평균 · 1인당 · 밀도면 False"""
    body, _ = _split(indicator or "", derived=True)
    return bool(body) and not _is_ratio(body) and not any(w in body for w in _NOT_COUNT) and not body.endswith("당")


# ── 측정 호환 (KOS-26 A-1) ───────────────────────────────────────
# 이름이 같거나 대상 · 분류 값과 같다는 것은 **무엇을 센 값인지**를 보장하지 않는다. '가구원수' 를 물었는데 대상 '가구' 가 항목 '가구수(가구)' 와
# 일치해 승인되거나, 지표 '가구수' 에 '보증부월세(명)' 이 승인되는 오류를 막으려고 지표의 측정 대상(사람 · 가구 · 건)과 항목의 원 단위를 맞춰 본다
PEOPLE_UNITS = {"명", "천명", "만명", "백만명"}
HOUSEHOLD_UNITS = {"가구", "천가구", "만가구", "호", "천호", "세대"}
EVENT_UNITS = {"건", "천건", "만건"}
# (지표 이름 끝, 측정 대상, 허용 원 단위). 위에서부터 먼저 맞는 것. '가구원수' 는 '원수' 로 끝나 가구보다 먼저 본다
_MEASURES: list[tuple[tuple[str, ...], str, set[str]]] = [
    (("가구원수", "원수", "인원수", "인원"), "사람", PEOPLE_UNITS),
    (("가구수", "세대수", "가구"), "가구", HOUSEHOLD_UNITS),
    (("건수",), "건", EVENT_UNITS),
    (("인구수", "인구", "자수", "아수", "명수", "인수"), "사람", PEOPLE_UNITS),
]


def measure_of(indicator: str | None) -> tuple[str, set[str]] | None:
    """지표 이름 → (측정 대상, 허용 원 단위). 개수 지표가 아니거나 표에 없는 이름이면 None"""
    if not is_count_indicator(indicator):
        return None
    body, _ = _split(indicator or "", derived=True)
    for tails, name, units in _MEASURES:
        if body.endswith(tails):
            return name, units
    return None


def measure_compatible(indicator: str | None, source_unit: str | None) -> bool | None:
    """항목의 원 단위가 지표의 측정 대상과 맞는가. True 호환 · False 맞지 않음(가구수 ↔ 명) · None 판정할 수 없음(표에 없는 지표 · 단위 모름)"""
    m = measure_of(indicator)
    if m is None or not source_unit:
        return None
    return source_unit.strip() in m[1]


def correspondence(item: str | None, source_unit: str | None, indicators: list[str], targets: list[str],
                   aliases: list[str] | tuple = (), strict: bool = False, modifiers=frozenset()) -> str | None:
    """항목이 요청한 지표에 대응하는 경로: "name" · "target" · "alias". 대응하지 않으면 None

      name   항목 이름이 지표와 대응. 측정 호환이 **False** 일 때만 거부한다 (표에 없는 지표는 판정할 수 없어 기존대로 승인 — 회귀 방지)
      target 지표가 개수(가구수)일 때 항목이 대상(1인가구)의 이름 (Q25). 측정 호환이 **False** 이면 거부한다 (가구원수 ↔ 가구수 를 막는다)
      alias  지표가 개수일 때 항목이 원문표현 · 조건 값과 같다 (보증부월세, 국제결혼이주자). 측정 호환이 **True** 일 때만 승인한다.
             (View 의 분류 구조 · 조건의 분류 축 확인은 호출한 쪽이 한다)
    지표가 비율 · 증가(인구성장률)이면 대상 · 별칭 이름이 맞아도 지표가 아니므로 통과시키지 않는다 (검토 11)
    modifiers: [NEW 11-25] 질문이 요청한 수식어 (matches 참고). 이름 경로에만 쓴다"""
    if not indicators:
        return "name"
    for i in indicators:
        if matches(item, i, strict, modifiers) and measure_compatible(i, source_unit) is not False:
            return "name"
    counts = [i for i in indicators if is_count_indicator(i)]
    # 대상 경로는 기존 동작이라 판정할 수 없을 때(None)는 승인을 유지하고, 맞지 않을 때(False)만 거부한다 (회귀 방지: 단위를 모르는 View 의 1인가구 ↔ 가구수).
    # 별칭 경로는 새로 여는 경로라 호환이 확인될 때(True)만 승인한다
    if any(matches(item, t, strict) for t in targets) and any(measure_compatible(i, source_unit) is not False for i in counts):
        return "target"
    if any(matches(item, a, strict) for a in aliases) and any(measure_compatible(i, source_unit) is True for i in counts):
        return "alias"
    return None


def corresponds(item: str | None, indicators: list[str], targets: list[str], strict: bool = False,
                source_unit: str | None = None, aliases: list[str] | tuple = ()) -> bool:
    """항목이 요청한 지표에 대응하는가 (correspondence 의 True · False 판). source_unit 을 모르면 별칭 경로는 승인하지 않는다"""
    return correspondence(item, source_unit, indicators, targets, aliases, strict) is not None


_CATEGORY_LABELS = {"계", "합계", "전체", "남자", "여자", "남", "여", "남성", "여성", "소계"}


def is_category_label(item: str | None) -> bool:
    """항목 값이 지표 이름이 아니라 구분 값(나이 · 성별 · 총계)인가. 항목 열에 0세 · 남자 같은 값이 든 표는 항목으로 지표를 알 수 없다 → 검사하지 않는다"""
    t = re.sub(r"\s+", "", _PAREN.sub("", item or ""))
    return t in _CATEGORY_LABELS or bool(re.fullmatch(r"\d+(?:[-~]\d+)?세(?:이상)?", t))
