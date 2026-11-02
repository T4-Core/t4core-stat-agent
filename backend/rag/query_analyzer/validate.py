"""2-4. 슬롯 검증 (코드, HCX 호출 없음)
노트북 user_question_rewrite_v2.ipynb '2-4' 셀의 코드를 그대로 옮김 (실행·예시 출력 부분은 뺌)"""
from .extract import AGE_WORDS, COUNTRIES, norm_age, norm_sido         # 2-2
from .slots import INTENTS, SLOT_KEYS                                  # 2-3
from .terms import to_canonical                                        # 2-1

# ============= 2-4. 슬롯 검증 (코드, HCX 호출 없음) ================
# 2-3의 HCX 슬롯(검증 전)을 2-2 코드 추출 결과(rule_found)와 질문으로 검사·정리
# 순서: clean_slots(형식 통일) → apply_terms(대표 용어) → fix_slots(근거 확인·보완)
# 메인 슬롯: 코드가 찾은 값 중 빠진 것을 채움 / 하위 슬롯: 근거 없는 값만 삭제, 시점만 '질문 전체 시점이 하나뿐'일 때 채움
import re

REGION_KEYS = ["지역", "전출지", "전입지"]
MOVE_VALUES = ["전입", "전출", "순이동", "입국", "출국", "국제순이동"]
AGE_WORD_MAP = {"노인": "65세 이상", "고령자": "65세 이상", "고령": "65세 이상", "어르신": "65세 이상"}
AGE_FORMAT = re.compile(r"\d+~\d+세|\d+세 (?:이상|이하|미만|초과)|\d+세")
TERM_AGE = re.compile(r"^(\d+~\d+세|\d+세 (?:이상|이하|미만|초과))\s*(.+)$")   # '65세 이상 인구' → 연령 + 대상


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return list(dict.fromkeys(str(x).strip().rstrip("?") for x in v if str(x).strip()))


# ---- 1) 형식 통일 ----
def clean_slots(slots):
    """모든 슬롯 키를 list[str]로, 의도는 정해진 6개 값 중 하나로. 반환: (슬롯, 내역)"""
    slots = slots if isinstance(slots, dict) else {}
    s = {k: _as_list(slots.get(k)) for k in SLOT_KEYS}
    log = [f"모르는 키 무시: {k}" for k in slots if k not in SLOT_KEYS + ["의도"]]
    intent = str(slots.get("의도") or "").strip()
    if intent not in INTENTS:
        log.append(f"의도 기본값: {intent!r} → '값 조회'")
        intent = "값 조회"
    s["의도"] = intent
    return s, log


# ---- 2) 사전 대표 용어 ----
def apply_terms(s):
    """대상·지표 값을 2-1 사전의 대표 용어로.
    대표 용어가 연령 자체면('노인' → '65세 이상') 연령 슬롯으로 옮기고, 그 때문에 대상이 비면 '인구'를 넣음
    '65세 이상 인구'처럼 연령이 붙은 용어는 연령 + 나머지('인구')로 나눔"""
    log, moved = [], False
    for k in ("대상", "지표"):
        out = []
        for v in s[k]:
            new, changed = to_canonical(v)
            if changed:
                log.append(f"{k} 대표 용어: {v} → {new}")
            if AGE_FORMAT.fullmatch(new):                     # 연령 값 자체 → 연령 슬롯으로 이동
                s["연령"].append(new); moved = True
                log.append(f"{k}→연령 이동: {new}")
                continue
            m = TERM_AGE.match(new)
            if m:                                             # 연령이 붙은 용어 → 연령 + 나머지
                s["연령"].append(m.group(1))
                new = m.group(2).strip()
                log.append(f"{k} 연령 분리: {m.group(1)} / {new}")
            out.append(new)
        s[k] = list(dict.fromkeys(out))
    if moved and not s["대상"]:
        s["대상"] = ["인구"]; log.append("대상 채움: 연령만 남아 '인구'")
    s["연령"] = list(dict.fromkeys(s["연령"]))
    return s, log


# ---- 3) 근거 확인·보완 ----
def _age_word_in(q, term_hits):
    """질문에 연령을 뜻하는 단어가 있는지 ('노인', 사전 대표 용어에 'N세'가 들어간 표현 등)"""
    return any(w in q for w in AGE_WORDS + list(AGE_WORD_MAP)) or \
        any(re.search(r"\d+세", t) for _, terms in term_hits for t in terms)


def fix_slots(s, q, rule_found, term_hits=(), main=True):
    """q = 2-2에서 변환된 질문. main=True면 메인 슬롯(빠진 값 채움), False면 하위 슬롯(삭제만). 반환: (슬롯, 내역)"""
    s = {k: (list(v) if isinstance(v, list) else v) for k, v in s.items()}
    log, tag = [], "" if main else "(하위) "

    # 시점: 'YYYY년' / 'YYYY년 M월' 형식으로. 코드가 찾은 시점에 없는 값은 삭제 (코드가 연도를 놓치지 않으므로 코드 기준)
    allowed, keep = rule_found.get("시점", []), []
    for v in s["시점"]:
        m = re.fullmatch(r"((?:19|20)\d{2})\s*년?(?:\s*(\d{1,2})\s*월)?", v.strip())
        v2 = (f"{m.group(1)}년" + (f" {int(m.group(2))}월" if m.group(2) else "")) if m else v
        if v2 in allowed:
            keep.append(v2)
        else:
            log.append(f"{tag}시점 삭제({'형식' if not m else '질문에 없음'}): {v}")
    s["시점"] = list(dict.fromkeys(keep))
    if main and allowed and set(s["시점"]) != set(allowed):
        log.append(f"시점 채움(코드 기준): {s['시점']} → {allowed}")
        s["시점"] = list(allowed)

    # 국적 칸에 시도가 들어갔으면 지역으로 이동
    for v in list(s["국적"]):
        if norm_sido(v):
            s["국적"].remove(v); s["지역"].append(v); log.append(f"{tag}국적→지역 이동: {v}")

    # 지역·전출지·전입지: 시도는 정식 이름 + 코드가 찾은 것만. 시군구 등은 질문에 이름이 있을 때만
    for k in REGION_KEYS:
        out = []
        for v in s[k]:
            full = norm_sido(v)
            if full and full in rule_found.get("지역", []):
                out.append(full)
                if full != v:
                    log.append(f"{tag}{k} 정식 이름: {v} → {full}")
            elif not full and (v in q or re.sub(r"(시|군|구|읍|면|동)$", "", v) in q):
                out.append(v)
            else:
                log.append(f"{tag}{k} 삭제(질문에 없음): {v}")
        s[k] = list(dict.fromkeys(out))
    if main:
        used = set(s["지역"] + s["전출지"] + s["전입지"])
        for full in rule_found.get("지역", []):
            if full not in used:
                s["지역"].append(full); log.append(f"지역 채움(코드가 찾음): {full}")

    # 국적: 질문에 있는 국가만
    nat = []
    for v in s["국적"]:
        if v in q or any(c in v and c in q for c in COUNTRIES):
            nat.append(v)
        else:
            log.append(f"{tag}국적 삭제(질문에 없음): {v}")
    s["국적"] = nat
    if main:
        for c in rule_found.get("국적", []):
            if not any(c in v for v in s["국적"]):
                s["국적"].append(c); log.append(f"국적 채움(코드가 찾음): {c}")

    # 성별: 남자/여자로 통일, 코드가 찾은 것만
    sex = []
    for v in s["성별"]:
        k = "남자" if v in ("남", "남자", "남성") else "여자" if v in ("여", "여자", "여성") else None
        if k and k in rule_found.get("성별", []):
            sex.append(k)
        else:
            log.append(f"{tag}성별 삭제(질문에 없음): {v}")
    s["성별"] = list(dict.fromkeys(sex))
    if main:
        for k in rule_found.get("성별", []):
            if k not in s["성별"]:
                s["성별"].append(k); log.append(f"성별 채움(코드가 찾음): {k}")

    # 연령: 표기 통일 → 형식 확인 → 근거 확인 (숫자 연령은 코드 기준, 연령 단어가 있으면 HCX 값 유지)
    code_ages, word = rule_found.get("연령", []), _age_word_in(q, term_hits)
    ages = []
    for v in s["연령"]:
        v2 = AGE_WORD_MAP.get(v, norm_age(v))
        if not AGE_FORMAT.fullmatch(v2):
            log.append(f"{tag}연령 삭제(형식): {v}")
        elif v2 in code_ages or word:
            ages.append(v2)
        else:
            log.append(f"{tag}연령 삭제(질문에 없음): {v}")
    s["연령"] = list(dict.fromkeys(ages))
    if main:
        for a in code_ages:
            if a not in s["연령"]:
                s["연령"].append(a); log.append(f"연령 채움(코드가 찾음): {a}")

    # 조건: 코드가 찾은 출생연도 채움 / 이동: 정해진 값만 / 비교축: '시도별' → '시도'
    if main:
        for c in rule_found.get("조건", []):
            if c not in s["조건"]:
                s["조건"].append(c); log.append(f"조건 채움(코드가 찾음): {c}")
    for v in [v for v in s["이동"] if v not in MOVE_VALUES]:
        log.append(f"{tag}이동 삭제(정해진 값 아님): {v}")
    s["이동"] = [v for v in s["이동"] if v in MOVE_VALUES]
    s["비교축"] = list(dict.fromkeys(re.sub(r"별$", "", v) for v in s["비교축"]))
    return s, log



def _slots_from_code(rule_found):
    """HCX 응답을 못 읽었을 때: 코드가 찾은 값만으로 슬롯"""
    s = {k: list(rule_found.get(k, [])) for k in SLOT_KEYS}
    s["의도"] = "값 조회"
    return s


# ---- 4) 2-3 결과 하나 검증 ----
def validate_slots(r):
    """r = 2-3 call_slots() 결과. 반환: {"slots", "sub_slots", "log"}"""
    q, found, hits = r["input_question"], r["rule_found"], r.get("term_hits", [])
    log = []
    if r.get("hcx_slots") is None:
        log.append(f"HCX 응답을 읽지 못해 코드 추출 값만 사용 ({r.get('error', '')})")
        return {"slots": _slots_from_code(found), "sub_slots": [], "log": log}

    s, l1 = clean_slots(r["hcx_slots"])
    s, l2 = apply_terms(s)
    s, l3 = fix_slots(s, q, found, hits, main=True)
    log += l1 + l2 + l3

    subs = []
    one_time = found.get("시점", []) if len(found.get("시점", [])) == 1 else []   # 질문 전체 시점이 하나뿐일 때만
    for i, raw in enumerate(r.get("hcx_subs", [])[:3]):
        ss, a = clean_slots(raw)
        ss, b = apply_terms(ss)
        ss, c = fix_slots(ss, q, found, hits, main=False)
        log += [f"(하위 {i}) {x}" for x in a + b] + [x.replace("(하위) ", f"(하위 {i}) ") for x in c]
        if one_time and not ss["시점"]:
            ss["시점"] = list(one_time); log.append(f"(하위 {i}) 시점 채움(질문 전체 시점 하나): {one_time}")
        if not (ss["대상"] or ss["지표"]):
            log.append(f"(하위 {i}) 삭제: 대상·지표가 없음")
            continue
        subs.append(ss)
    if len(subs) == 1:                                   # 하위 질문이 하나면 메인과 같으므로 뺌
        log.append("하위 질문이 1개뿐이라 뺌")
        subs = []
    return {"slots": s, "sub_slots": subs, "log": log}


def _nonempty(s):
    return {k: v for k, v in (s or {}).items() if v not in ([], "", None)}


def show_validated(r, v):
    print("=" * 80)
    print("원 질문 :", r["question"])
    print("HCX 슬롯:", _nonempty(r.get("hcx_slots")) or "(읽지 못함)")
    for j, x in enumerate(r.get("hcx_subs", [])):
        print(f"  HCX 하위[{j}]:", _nonempty(x))
    print("고친 내역:", *(v["log"] or ["없음"]), sep="\n  - ")
    print("검증 슬롯:", _nonempty(v["slots"]))
    for j, x in enumerate(v["sub_slots"]):
        print(f"  검증 하위[{j}]:", _nonempty(x))
