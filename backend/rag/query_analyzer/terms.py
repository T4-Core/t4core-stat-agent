"""2-1. KOSIS 통계 용어 사전 (HCX 호출 없음)
추후 내용 추가할 예정
노트북 user_question_rewrite_v2.ipynb '2-1' 셀의 코드를 그대로 옮김 (확인용 출력 부분은 뺌)"""


# ============= 2-1. KOSIS 통계 용어 사전 ================
# 형식: {"대표 KOSIS 용어": ["일상어 표현", ...]}
# - 대표 용어 자체도 자동으로 사전에 들어감 → 질문에 '합계출산율'이 있으면 그 안의 '출산율'을 따로 잡지 않음
# - 긴 표현부터 찾고, 찾은 부분은 지워서 두 번 세지 않음 → '결혼이민자' 안의 '결혼'을 혼인건수로 잡지 않음
# - 띄어쓰기는 무시하고 비교 ('가구 수' = '가구수', '혼자사는' = '혼자 사는')
import json
import re
from pathlib import Path

TERM_DICT = {
    # ---- 인구·연령 ----
    "65세 이상":      ["노인", "어르신", "늙은이", "노년층", "고령자"],
    "고령인구비율":        ["노인 비율", "고령자 비율", "늙은이 비율", "고령화율", "고령화"],
    "유소년인구":          ["어린이 인구", "아이 인구"],
    "생산연령인구":        ["일하는 나이 인구", "생산가능인구"],
    "평균연령":            ["평균 나이"],
    "성비":                ["남녀 비율", "여초", "남초"],
    "인구밀도":            ["사람 밀도"],
    "지방소멸위험지수":    ["지방소멸", "소멸위험"],
    "기대수명":            ["평균 수명", "오래 사는", "수명"],
    # ---- 출생·사망 ----
    "출생아수":            ["애 낳는 사람", "애 낳는", "아기 태어", "애기 태어", "태어난 아이", "신생아 수", "출생 수"],
    "합계출산율":          ["출산율", "애 낳는 비율"],
    "사망자수":            ["죽은 사람", "사망 수"],
    "자연증가건수":        ["자연감소", "자연증가"],
    # ---- 혼인·이혼 ----
    "혼인건수":            ["결혼", "시집", "장가", "결혼 건수"],
    "조혼인율":            ["결혼율", "혼인율"],
    "평균초혼연령":        ["결혼 나이", "결혼 연령", "초혼 나이"],
    "이혼건수":            ["이혼", "갈라서", "갈라선"],
    "조이혼율":            ["이혼율"],
    "외국인과의 혼인건수": ["국제결혼"],
    # ---- 가구 ----
    "가구수":              ["세대 수", "집 몇 채"],
    "1인가구":             ["혼자 사는", "나홀로 가구", "독신 가구", "싱글 가구"],
    "다문화가구":          ["다문화 가정"],
    "평균가구원수":        ["평균 가구원", "한 집에 몇 명"],
    # ---- 인구 이동 ----
    "전출":                ["빠져나가", "빠져나간", "이사 가", "이사가", "떠난 사람", "유출"],
    "전입":                ["이사 온", "이사온", "들어온 사람", "유입"],
    "순이동":              ["순유입", "순유출"],
    "인구이동":            ["이사", "이주"],
    # ---- 외국인 ----
    "외국인근로자":        ["외노자", "외국인 노동자", "이주노동자"],
    "결혼이민자":          ["결혼 이민자", "결혼이주여성", "결혼 이주민"],
    "체류외국인":          ["머무는 외국인", "사는 외국인"],
    # ---- 미래 시점 ----
    "장래인구추계":        ["인구 전망", "미래 인구", "인구 예측", "앞으로 인구"],
    "장래가구추계":        ["가구 전망", "미래 가구", "가구 예측"],
}

MIN_ALIAS_LEN = 2      # 한 글자 표현은 다른 단어 안에서 잘못 잡히므로 뺌 (test1 p2_dictionary 와 같은 기준)


def _nospace(s):
    return re.sub(r"\s+", "", str(s))


def load_term_dict(path=None, fmt="alias"):
    """사전을 {일상어: [대표 용어, ...]} 색인으로 만듦
    path=None : 노트북의 TERM_DICT ({대표 용어: [일상어]}) 사용
    path 지정 : JSON 파일. fmt="alias"  → {"일상어": ["대표 용어"]}  (test1 alias_dict.json 형식)
                             fmt="term"   → {"대표 용어": ["일상어"]}  (TERM_DICT 형식)"""
    if path is None:
        raw, fmt = TERM_DICT, "term"
    else:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    index = {}

    def add(alias, term):
        alias, term = str(alias).strip(), str(term).strip()
        if len(_nospace(alias)) < MIN_ALIAS_LEN or not term:
            return
        index.setdefault(alias, [])
        if term not in index[alias]:
            index[alias].append(term)

    for k, vals in raw.items():
        vals = [vals] if isinstance(vals, str) else list(vals or [])
        if fmt == "term":                      # {대표 용어: [일상어]} → 대표 용어 자체도 등록
            add(k, k)
            for v in vals:
                add(v, k)
        else:                                  # {일상어: [대표 용어]} → 대표 용어 자체도 등록
            for v in vals:
                add(k, v)
                add(v, v)
    return index


TERM_INDEX = load_term_dict()                 # 파일로 바꿀 때: TERM_INDEX = load_term_dict("…/alias_dict.json")


def lookup_terms(q, index=None):
    """질문에 나온 일상어 → 대표 용어. 반환: [(일상어, [대표 용어, ...]), ...] (질문에 나온 순서)
    대표 용어가 질문에 그대로(띄어쓰기만 다르게) 있으면 바꿀 필요가 없으므로 결과에서 뺌"""
    index = TERM_INDEX if index is None else index
    s, hits = _nospace(q), []
    for alias in sorted(index, key=lambda a: -len(_nospace(a))):      # 긴 표현부터
        a = _nospace(alias)
        pos = s.find(a)
        if pos < 0:
            continue
        s = s.replace(a, "|" * len(a))                                 # 찾은 부분 지우기 (길이는 유지)
        terms = [t for t in index[alias] if _nospace(t) != a]
        if terms:
            hits.append((pos, alias, terms))
    return [(alias, terms) for _, alias, terms in sorted(hits)]


def build_term_block(hits):
    """2-3 user 프롬프트에 넣을 조각. 찾은 것이 없으면 빈 문자열"""
    if not hits:
        return ""
    return "[용어 사전] 질문의 일상어는 아래 통계 용어로 바꾼다.\n" + \
           "\n".join(f"- {alias} → {', '.join(terms)}" for alias, terms in hits)


def to_canonical(value, index=None):
    """슬롯 값 하나를 대표 용어로 (2-4 apply_terms 에서 사용). 값 전체가 사전 표현과 같을 때만 바꿈
    대표 용어가 여러 개인 표현은 하나로 정할 수 없으므로 그대로 둠. 반환: (바뀐 값, 바뀌었는지)"""
    index = TERM_INDEX if index is None else index
    v = _nospace(value)
    for alias, terms in index.items():
        if _nospace(alias) == v and len(terms) == 1:
            return terms[0], terms[0] != value
    return value, False
