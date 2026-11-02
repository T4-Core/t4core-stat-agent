"""3. 슬롯 → 문장 (코드 템플릿, HCX 호출 없음)
노트북 user_question_rewrite_v2.ipynb '3' 셀의 코드를 그대로 옮김 (실행·예시 출력 부분은 뺌)"""

# ============= 3. 슬롯 → 문장 (코드 템플릿, HCX 호출 없음) ================
# 검증된 슬롯 값을 정해진 순서로 이어 붙여 검색용 명사구를 만듦. 슬롯에 없는 말은 끼어들지 않음
# 순서: 시점 → 지역 → 전출지→전입지 → 국적 → 성별 → 연령 → 조건 → 대상 → 이동 → 지표 → 비교축 → 의도어
import re

INTENT_WORD = {"값 조회": "", "구성비": "", "추이": "추이", "비교": "비교", "순위": "순위", "증감": "증감"}


def _ranges(nums):
    """정렬된 숫자 목록 → 연속 구간 [(시작, 끝), ...]"""
    out = []
    for n in sorted(set(nums)):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [tuple(x) for x in out]


def format_time(values):
    """시점 목록 → 문장 조각. 연속 연도는 '2020~2024년', 떨어진 연도는 '2019년, 2023년'
    같은 해의 연속 월은 '2024년 7~9월'. 연도만 있는 값과 월 값이 섞이면 각각 만든 뒤 이어 붙임"""
    years, months = [], {}
    for v in values:
        m = re.fullmatch(r"(\d{4})년(?: (\d{1,2})월)?", v)
        if not m:
            continue
        if m.group(2):
            months.setdefault(int(m.group(1)), []).append(int(m.group(2)))
        else:
            years.append(int(m.group(1)))
    parts = [f"{a}년" if a == b else f"{a}~{b}년" for a, b in _ranges(years)]
    for y in sorted(months):
        parts += [f"{y}년 {a}월" if a == b else f"{y}년 {a}~{b}월" for a, b in _ranges(months[y])]
    return ", ".join(parts)


def _ns(s):
    return re.sub(r"\s+", "", str(s))


def slots_to_sentence(slots, intent=None):
    """검증된 슬롯 → 검색용 명사구. 슬롯이 모두 비면 빈 문자열"""
    s = slots or {}
    intent = intent if intent is not None else s.get("의도", "값 조회")
    parts = [format_time(s.get("시점", []))]
    parts += s.get("지역", [])

    frm, to = s.get("전출지", []), s.get("전입지", [])                      # 전출지→전입지
    if frm and to:
        parts.append(f"{' '.join(frm)}→{' '.join(to)}")
    else:
        parts += frm + to

    parts += s.get("국적", []) + s.get("성별", []) + s.get("연령", [])
    parts += [c.split("=", 1)[1].strip() if "=" in c else c for c in s.get("조건", [])]   # '혼인상태=미혼' → '미혼'

    # 대상과 지표가 겹치면 한 번만 ('출생아' + '출생아수' → '출생아수', '인구' + '인구' → '인구')
    indicators = s.get("지표", [])
    targets = [t for t in s.get("대상", []) if not any(_ns(i).startswith(_ns(t)) for i in indicators)]
    parts += targets + s.get("이동", []) + indicators
    parts += [a if a.endswith("별") else f"{a}별" for a in s.get("비교축", [])]   # '시도' → '시도별', '성별'은 그대로

    word = INTENT_WORD.get(intent, "")
    words = [p for p in parts if p]
    if word and (not words or words[-1] != word):
        words.append(word)
    return " ".join(dict.fromkeys(words))                                   # 같은 말이 두 번 나오지 않게


def build_sentences(v):
    """2-4 validate_slots() 결과 → {"rewritten", "sub_questions"}"""
    subs = [slots_to_sentence(x) for x in v.get("sub_slots", [])]
    return {"rewritten": slots_to_sentence(v["slots"]), "sub_questions": [x for x in subs if x]}
