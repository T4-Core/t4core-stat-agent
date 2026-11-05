"""2-1. KOSIS 통계 용어 사전 (HCX 호출 없음)
노트북 user_question_rewrite_v3.ipynb '2-1' 셀의 코드를 그대로 옮김 (확인용 출력 부분은 뺌)
사전 파일: dictionary/term_dict.json (dictionary/build_dicts.py 가 만듦). 경로는 config.TERM_PATH"""
from .config import TERM_PATH

# ============= 2-1. KOSIS 통계 용어 사전 ================
# 형식: {"대표 KOSIS 용어": ["일상어 표현", ...]}
# - 대표 용어 자체도 자동으로 사전에 들어감 → 질문에 '합계출산율'이 있으면 그 안의 '출산율'을 따로 잡지 않음
# - 긴 표현부터 찾고, 찾은 부분은 지워서 두 번 세지 않음 → '결혼이민자' 안의 '결혼'을 혼인건수로 잡지 않음
# - 띄어쓰기는 무시하고 비교 ('가구 수' = '가구수', '혼자사는' = '혼자 사는')
import json
import re
from pathlib import Path

# 일상어를 kosis 통계 용어로. HCX가 슬롯을 뽑을 때 힌트로 참고함
# 사전 파일은 dictionary/build_dicts.py 가 원본 사전(dictionary/test2/results/dictionary_표명.json)에서 만듦
#   term_dict.json : 일상어 → 통계어 {"대표 용어": ["일상어", ...]}  (여기 2-1)
#   rule_dict.json : 확실한 표기 대응표 (2-2 코드 추출, 2-4 검증)
TERM_DICT = json.loads(TERM_PATH.read_text(encoding="utf-8"))

MIN_ALIAS_LEN = 2      # 한 글자 표현은 다른 단어 안에서 잘못 잡히므로 뺌 (test1 p2_dictionary 와 같은 기준)


def _nospace(s):
    return re.sub(r"\s+", "", str(s))


def _glued_number(s, pos, a):
    """s[pos:] 에서 찾은 표현 a 가 앞 숫자에 붙은 일부인지. '15세' 안의 '5세', '삼십대' 안의 '십대' → True"""
    if pos == 0:
        return False
    prev = s[pos - 1]
    return (a[0].isdigit() and prev.isdigit()) or (a[0] == "십" and prev in "이삼사오육칠팔구")


def load_term_dict(path=None, fmt="alias"):
    """사전을 {일상어: [대표 용어, ...]} 색인으로 만듦
    path=None : TERM_DICT (term_dict.json, {대표 용어: [일상어]}) 사용
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


TERM_INDEX = load_term_dict()                 # TERM_DICT(term_dict.json) → {일상어: [대표 용어]} 색인


def lookup_terms(q, index=None):
    """질문에 나온 일상어 → 대표 용어. 반환: [(일상어, [대표 용어, ...]), ...] (질문에 나온 순서)
    대표 용어가 질문에 그대로(띄어쓰기만 다르게) 있으면 바꿀 필요가 없으므로 결과에서 뺌"""
    index = TERM_INDEX if index is None else index
    s, hits = _nospace(q), []
    for alias in sorted(index, key=lambda a: -len(_nospace(a))):      # 긴 표현부터
        a = _nospace(alias)
        # 앞 숫자에 붙은 표현은 건너뜀 → '15세' 안의 '5세', '삼십대' 안의 '십대'를 잡지 않음
        found = [m.start() for m in re.finditer(re.escape(a), s) if not _glued_number(s, m.start(), a)]
        if not found:
            continue
        pos = found[0]
        for p in found:                                                 # 찾은 부분 지우기 (길이는 유지)
            s = s[:p] + "|" * len(a) + s[p + len(a):]
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
