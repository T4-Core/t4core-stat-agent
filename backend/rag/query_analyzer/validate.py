"""2-4. 슬롯 검증 (코드, HCX 호출 없음)
노트북 user_question_rewrite_v3.ipynb '2-4' 셀의 코드를 그대로 옮김 (실행·예시 출력 부분은 뺌)"""
from .extract import AGE_WORDS, SEX, SIDO_GROUPS, norm_age, norm_country, norm_sido   # 2-2
from .slots import INTENTS, SLOT_KEYS                                  # 2-3
from .measures import MEASURE_INTENT, concept_groups, is_measure, squash as _msq, strip_trailing_measure   # [NEW 11-12]
from .terms import TERM_INDEX, to_canonical                            # 2-1

# ============= 2-4. 슬롯 검증 (코드, HCX 호출 없음) ================
# 2-3의 HCX 슬롯(검증 전)을 2-2 코드 추출 결과(rule_found)와 질문으로 검사·정리
# 순서: clean_slots(형식 통일) → apply_terms(대표 용어) → fix_slots(근거 확인·보완)
# 메인 슬롯: 코드가 찾은 값 중 빠진 것을 채움 / 하위 슬롯: 근거 없는 값만 삭제, 시점만 '질문 전체 시점이 하나뿐'일 때 채움
import re

REGION_KEYS = ["지역", "전출지", "전입지"]
MOVE_VALUES = ["전입", "전출", "순이동", "입국", "출국", "국제순이동"]
MAX_SUBS = 10            # 하위 질문 최대 개수 (2-3 프롬프트 하위 질문 규칙 2와 같음)
AGE_WORD_MAP = {"노인": "65세 이상", "고령자": "65세 이상", "고령": "65세 이상", "어르신": "65세 이상"}
AGE_FORMAT = re.compile(r"\d+~\d+세|\d+세 (?:이상|이하|미만|초과)|\d+세")
TERM_AGE = re.compile(r"^(\d+~\d+세|\d+세 (?:이상|이하|미만|초과))\s*(.+)$")   # '65세 이상 인구' → 연령 + 대상

# [NEW 11-12] 지역 칸 검증: HCX 가 지표('혼인건수')나 의도('추이')를 지역·전출지 칸에 넣는 실수를 바로잡음
REGION_SUFFIX = re.compile(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|읍|면|동|리)$")   # 행정구역 끝말
INDICATOR_SUFFIX = re.compile(r"(?:수|율|률|비율|비중|인구|가구|연령)$")                            # 지표처럼 끝나는 말
NOT_REGION_WORDS = {"추이", "추세", "흐름", "변화", "동향", "변동", "비교", "순위", "증감", "증가", "감소", "합계",
                    "차이", "전망", "예측", "구성비", "증감률", "값", "조회", "통계", "현황"} | set(INTENTS)
MOVE_WORD_RE = re.compile(r"전입|전출|이사|이동|유입|유출|옮기|옮긴|옮겨|떠나|떠난|들어온|빠져나|이주|이민|입국|출국")
TREND_WORD_RE = re.compile(r"추이|추세|흐름")


def _ns(v):
    return re.sub(r"\s+", "", str(v))


TERM_KEYS = {_ns(k) for k in TERM_INDEX}


def _as_indicator(v):
    """지역 칸에 들어온 값이 통계 용어(사전)면 대표 용어, 아니면 None"""
    new, changed = to_canonical(v)
    if changed or _ns(v) in TERM_KEYS:
        return new
    return None


def _region_form(v):
    """실제 지역명 모양인지: 토막 중 하나가 시도 이름이거나 행정구역 끝말(시·군·구·읍·면·동…)로 끝남"""
    toks = str(v).split()
    return any(norm_sido(t) for t in toks) or bool(toks and REGION_SUFFIX.fullmatch(toks[-1]))


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return list(dict.fromkeys(str(x).strip().rstrip("?") for x in v if str(x).strip()))


# ---- 1) 형식 통일 ----
def _as_intents(v):
    """의도 값 → 목록. 문자열은 쉼표·슬래시로 나눠 받음 ('비교, 증감률' → ['비교', '증감률'])"""
    if isinstance(v, str):
        v = re.split(r"[,/]", v)
    return [str(x).strip() for x in (v if isinstance(v, list) else []) if str(x).strip()]


def clean_slots(slots, main=True):
    """모든 슬롯 키를 list[str]로. 의도는 정해진 9개 값만:
    main=True(원 질문)면 목록(여러 개 가능), main=False(하위 질문)면 하나. 반환: (슬롯, 내역)"""
    slots = slots if isinstance(slots, dict) else {}
    s = {k: _as_list(slots.get(k)) for k in SLOT_KEYS}
    log = [f"모르는 키 무시: {k}" for k in slots if k not in SLOT_KEYS + ["의도"]]
    raw = _as_intents(slots.get("의도"))
    intents = list(dict.fromkeys(x for x in raw if x in INTENTS))
    if bad := [x for x in raw if x not in INTENTS]:
        log.append(f"의도 삭제(정해진 값 아님): {bad}")
    if not intents:
        log.append("의도 기본값: '값 조회'")
        intents = ["값 조회"]
    if len(intents) > 1 and "범위 밖" in intents:              # 범위 밖은 다른 의도와 같이 쓰지 않음 (프롬프트 규칙)
        intents.remove("범위 밖"); log.append("의도 삭제: '범위 밖'은 다른 의도와 같이 쓰지 않음")
    if not main and len(intents) > 1:
        log.append(f"하위 질문 의도는 하나만: {intents} → {intents[0]!r}")
    s["의도"] = intents if main else intents[0]
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


# ---- 2-1) [NEW 11-12] 계산 단어 정리 ----
def clean_measures(s, main=True):
    """지표·대상에서 계산 단어를 뺌 (measures.py). 표의 항목 이름이 아니라 구하는 방법이라 검색·조건 확인에 잡음
    - 값 전체가 계산 단어('구성비', '증감률', '변화폭(%p)') → 뺌. 의도가 '값 조회'뿐이고 뜻이 하나면 의도로 옮김
    - 끝에 붙은 의도성 계산 단어('전입 증감률') → 떼어 냄 ('비율'·'구성비'·'평균'은 표 이름에도 쓰여 그대로)
    144문항 비교: 지표에 계산 단어가 든 질문 53개 → 정답 표가 '지표 없음' 으로 밀리던 원인 중 하나"""
    log, tag, moved = [], "" if main else "(하위) ", []
    for k in ("지표", "대상"):
        out = []
        for v in s[k]:
            if is_measure(v):
                moved.append(_msq(v)); log.append(f"{tag}{k} 삭제(계산 단어): {v}")
                continue
            v2 = strip_trailing_measure(v)
            if v2 != v:
                moved.append(_msq(v[len(v2):])); log.append(f"{tag}{k} 계산 단어 떼기: {v} → {v2}")
            out.append(v2)
        s[k] = list(dict.fromkeys(out))
    want = list(dict.fromkeys(MEASURE_INTENT[m] for m in moved if m in MEASURE_INTENT))
    if len(want) == 1:
        if main and s["의도"] == ["값 조회"]:
            s["의도"] = want; log.append(f"의도: 계산 단어 → {want}")
        elif not main and s["의도"] == "값 조회":
            s["의도"] = want[0]; log.append(f"{tag}의도: 계산 단어 → {want[0]!r}")
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

    # [NEW 11-12] 전출지·전입지는 질문에 이동을 뜻하는 말이 있을 때만. 없으면 지역 칸 값으로 보고 아래에서 같이 검사
    if not MOVE_WORD_RE.search(q):
        for k in ("전출지", "전입지"):
            if s[k]:
                log.append(f"{tag}{k}→지역 이동(질문에 이동 관련 말 없음): {s[k]}")
                s["지역"] += s[k]
                s[k] = []

    # 지역·전출지·전입지: 시도는 정식 이름 + 코드가 찾은 것만. 시군구 등은 질문에 이름이 있을 때만
    # [CHANGED 11-12] 시도가 아닌 값은 순서대로: 통계 용어면 지표로 이동 → 지역명 모양이면 통과
    #   → 지표처럼 끝나면('…수'·'…율') 지표로 이동 → 의도·일반어('추이')면 삭제 → 그 밖(약칭 '강남' 등)은 예전처럼 질문에 있을 때만
    #   이전: 질문에 글자가 있으면 무엇이든 통과 → '혼인건수'가 지역, '추이'가 전출지로 남아 하위 질문이 지워지던 문제
    for k in REGION_KEYS:
        out = []
        for v in s[k]:
            full = norm_sido(v)
            in_q = v in q or re.sub(r"(시|군|구|읍|면|동)$", "", v) in q
            if v in SIDO_GROUPS:                                   # 권역('수도권') → 코드가 찾은 시도 정식 이름으로 풀기
                members = [f for f in SIDO_GROUPS[v] if f in rule_found.get("지역", [])]
                out += members
                log.append(f"{tag}{k} 권역 풀기: {v} → {members}" if members else f"{tag}{k} 삭제(질문에 없음): {v}")
            elif full and (full in rule_found.get("지역", []) or (full == "전국" and not rule_found.get("지역"))):   # 지역 없는 질문의 "전국"은 프롬프트 규칙
                out.append(full)
                if full != v:
                    log.append(f"{tag}{k} 정식 이름: {v} → {full}")
            elif full:
                log.append(f"{tag}{k} 삭제(질문에 없음): {v}")
            elif (term := _as_indicator(v)) is not None:
                if term not in s["지표"]:
                    s["지표"].append(term)
                log.append(f"{tag}{k}→지표 이동(통계 용어): {v}" + (f" → {term}" if term != v else ""))
            elif _region_form(v) and in_q:
                out.append(v)
            elif INDICATOR_SUFFIX.search(_ns(v)):
                if v not in s["지표"]:
                    s["지표"].append(v)
                log.append(f"{tag}{k}→지표 이동(지표 모양): {v}")
            elif _ns(v) in NOT_REGION_WORDS:
                log.append(f"{tag}{k} 삭제(지역이 아님): {v}")
            elif in_q and not re.search(r"\d", v):
                out.append(v)
            else:
                log.append(f"{tag}{k} 삭제(질문에 없음): {v}")
        s[k] = list(dict.fromkeys(out))
    if main:
        used = set(s["지역"] + s["전출지"] + s["전입지"])
        for full in rule_found.get("지역", []):
            # [CHANGED 11-12] 이전: u.startswith(full + " ") — 코드가 시군구도 찾게 되어 앞뒤 어느 쪽이든 겹치면 안 넣음
            #   ('제주특별자치도 제주시 구좌읍' 에 '제주시' 가 있음 / HCX '권선구' 와 코드 '수원시 권선구')
            if full in used or any(_ns(full) in _ns(u) for u in used):
                continue                                                   # HCX 값에 이미 들어 있음
            part = [u for u in s["지역"] if _ns(u) in _ns(full)]
            if part and any(_ns(full).endswith(_ns(u)) for u in part):
                continue                                                   # HCX 가 끝부분('권선구')을 이미 씀
            if part:                                                       # HCX 가 넓은 앞부분('수원시')만 씀 → 코드 값으로
                s["지역"] = [full if u in part else u for u in s["지역"]]
                s["지역"] = list(dict.fromkeys(s["지역"])); log.append(f"지역 바꿈(코드가 찾음): {part} → {full}")
            else:
                s["지역"].append(full); log.append(f"지역 채움(코드가 찾음): {full}")
        if not used and not s["지역"] and (s["대상"] or s["지표"]):                    # 프롬프트: 질문에 지역이 없으면 "전국" (찾을 대상·지표가 있을 때만)
            s["지역"] = ["전국"]; log.append("지역 채움(질문에 지역 없음): 전국")

    # 국적: 질문에 있는 국가만
    nat = []
    for v in s["국적"]:
        c = norm_country(v)                                      # 표기 통일 ('타이완' → '대만'). 표에 없는 국가는 None
        if c and c in rule_found.get("국적", []):
            nat.append(c)
            if c != v:
                log.append(f"{tag}국적 표기 통일: {v} → {c}")
        elif not c and v in q:                                   # 표에 없는 국가는 질문에 그대로 있을 때만
            nat.append(v)
        else:
            log.append(f"{tag}국적 삭제(질문에 없음): {v}")
    s["국적"] = list(dict.fromkeys(nat))
    if main:
        for c in rule_found.get("국적", []):
            if c not in s["국적"]:
                s["국적"].append(c); log.append(f"국적 채움(코드가 찾음): {c}")

    # 성별: 남자/여자로 통일, 코드가 찾은 것만
    sex = []
    for v in s["성별"]:
        k = next((k for k, names in SEX.items() if v in (k, k[0], *names)), None)   # '남'·'남성'·'남학생' → '남자'
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

    # 의도: '연도별'로 연도가 2개 이상이면 추이 (프롬프트 의도 규칙)
    # [CHANGED 11-12] 질문에 '추이·추세·흐름'이 있고 연도가 2개 이상이어도 추이 (HCX 가 '값 조회'로 두던 문제)
    if len(s["시점"]) >= 2 and ("연도" in s["비교축"] or "연도별" in q or TREND_WORD_RE.search(q)):
        if isinstance(s["의도"], list) and "추이" not in s["의도"]:              # 원 질문: 값 조회만 있으면 바꾸고, 다른 의도가 있으면 추가
            new = ["추이"] if s["의도"] == ["값 조회"] else s["의도"] + ["추이"]
            log.append(f"의도: 연도별·추이로 연도 {len(s['시점'])}개 → {s['의도']} → {new}"); s["의도"] = new
        elif s["의도"] == "값 조회":                                               # 하위 질문: 값 조회 → 추이
            log.append(f"{tag}의도: 연도별·추이로 연도 {len(s['시점'])}개 → '값 조회' → '추이'"); s["의도"] = "추이"
    return s, log



SPLIT_KEYS = ("시점", "지역", "성별")   # 같은 통계표에서 바꿔 가져올 수 있는 축 (프롬프트 하위 질문 규칙 2)


def _is_cross_split(subs):
    """하위 질문이 시점·지역·성별만 다르고(지표·대상·의도 등은 모두 같음) 모든 조합으로 나뉘었는지
    모든 조합: 같은 지역이 여러 시점과, 또는 같은 시점이 여러 지역과 짝지어 나옴 → 나누지 않아야 함
    '2020년 광주', '2023년 울산'처럼 지역마다 시점이 하나면 짝지어 다른 것 → 나눔 (False)"""
    if len(subs) < 2:
        return False
    rest = {tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(s.items()) if k not in SPLIT_KEYS)
            for s in subs}
    if len(rest) > 1:                                    # 지표·대상·연령·의도 등이 다르면 다른 질문
        return False
    by_region, by_time = {}, {}
    for s in subs:
        t, r = tuple(s["시점"]), tuple(s["지역"])
        by_region.setdefault(r, set()).add(t)
        by_time.setdefault(t, set()).add(r)
    return any(len(v) > 1 for v in by_region.values()) or any(len(v) > 1 for v in by_time.values())


def _slots_from_code(rule_found):
    """HCX 응답을 못 읽었을 때: 코드가 찾은 값만으로 슬롯"""
    s = {k: list(rule_found.get(k, [])) for k in SLOT_KEYS}
    s["의도"] = ["값 조회"]
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
    if s["의도"] == ["범위 밖"]:                                 # 프롬프트: 범위 밖이면 다른 슬롯은 모두 []
        cleared = [k for k in SLOT_KEYS if s[k]]
        log += l1 + ([f"범위 밖이라 슬롯 비움: {cleared}"] if cleared else [])
        return {"slots": {**{k: [] for k in SLOT_KEYS}, "의도": ["범위 밖"]}, "sub_slots": [], "log": log}
    s, l2 = apply_terms(s)
    s, lm = clean_measures(s, main=True)                         # [NEW 11-12]
    s, l3 = fix_slots(s, q, found, hits, main=True)
    log += l1 + l2 + lm + l3

    subs = []
    one_time = found.get("시점", []) if len(found.get("시점", [])) == 1 else []   # 질문 전체 시점이 하나뿐일 때만
    for i, raw in enumerate(r.get("hcx_subs", [])[:MAX_SUBS]):
        ss, a = clean_slots(raw, main=False)                   # 하위 질문 의도는 하나
        ss, b = apply_terms(ss)
        ss, bm = clean_measures(ss, main=False)                  # [NEW 11-12]
        ss, c = fix_slots(ss, q, found, hits, main=False)
        log += [f"(하위 {i}) {x}" for x in a + b] + [x.replace("(하위) ", f"(하위 {i}) ") for x in bm + c]
        if one_time and not ss["시점"]:
            ss["시점"] = list(one_time); log.append(f"(하위 {i}) 시점 채움(질문 전체 시점 하나): {one_time}")
        if not (ss["지역"] or ss["전출지"] or ss["전입지"]) and s["지역"]:     # [NEW 11-12] 지역을 비운 하위 질문 = 원 질문 지역
            ss["지역"] = list(s["지역"]); log.append(f"(하위 {i}) 지역 채움(원 질문): {s['지역']}")
        if not (ss["대상"] or ss["지표"]):
            log.append(f"(하위 {i}) 삭제: 대상·지표가 없음")
            continue
        subs.append(ss)
    if _is_cross_split(subs):                            # 프롬프트 규칙 2: 모든 연도 × 모든 지역은 나누지 않음
        log.append(f"하위 질문 {len(subs)}개 삭제: 시점·지역·성별만 다른 모든 조합 (한 통계표에서 가져옴)")
        subs = []
    if len(subs) == 1:                                   # 하위 질문이 하나면 메인과 같으므로 뺌
        log.append("하위 질문이 1개뿐이라 뺌")
        subs = []
    source = "hcx" if subs else ""
    if not subs and (subs := split_by_indicator(s)):     # [NEW 11-12] 프롬프트 규칙 1 을 코드로: HCX 가 나누지 않아도 지표별로
        source = "code"
        log.append(f"하위 질문 채움(지표 {len(subs)}개, HCX 가 나누지 않음): {[x['지표'][0] for x in subs]}")
    for ss in subs:                                      # 원 질문 의도에 하위 질문 의도가 모두 들어가게 (프롬프트 규칙 4)
        if ss["의도"] not in s["의도"]:
            s["의도"].append(ss["의도"]); log.append(f"의도 채움(하위 질문): {ss['의도']}")
    # sub_source: hcx = HCX 가 나눈 하위 질문 / code = 코드가 지표별로 나눔 (v4 는 code 일 때 자기 분리 정책을 씀) / "" = 없음
    return {"slots": s, "sub_slots": subs, "log": log, "sub_source": source}


def split_by_indicator(s):
    """[NEW 11-12] 메인 슬롯의 개념이 2개 이상이면 개념마다 하위 질문 (프롬프트 하위 질문 규칙 1)
    개념 = measures.concept_groups: 대상과 일반 지표('국제결혼 이주자' + '인구수')는 한 개념, 계산 단어는 개념이 아님
    [CHANGED 11-12 2차] 이전: 지표 값마다 나눔 → 대상('인구')·지표('인구수')가 따로 나뉘어 한 단어 하위 질문이 생기던 문제
    다른 슬롯(시점·지역·성별·연령·조건 …)은 모두 공통. 의도는 메인 의도의 첫 번째"""
    concepts = concept_groups(s["대상"], s["지표"])
    if len(concepts) < 2:
        return []
    intent = (s["의도"] or ["값 조회"])[0]
    subs = []
    for c in concepts[:MAX_SUBS]:
        ss = {k: list(v) for k, v in s.items() if k != "의도"}
        ss["지표"], ss["대상"], ss["의도"] = list(c["지표"]), list(c["대상"]), intent
        subs.append(ss)
    return subs


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
