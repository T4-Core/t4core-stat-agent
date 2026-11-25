"""슬롯 검증 (코드, HCX 호출 없음)

HCX 슬롯(검증 전)을 코드 추출 결과(rule_found)와 질문으로 검사·정리
순서: clean_slots(형식 통일) → apply_terms(대표 용어) → fix_slots(근거 확인·보완)
메인 슬롯: 코드가 찾은 값 중 빠진 것을 채움 / 하위 슬롯: 근거 없는 값만 삭제, 시점만 '질문 전체 시점이 하나뿐'일 때 채움
"""
import re

from .extract import AGE_WORDS, SEX, SIDO_GROUPS, norm_age, norm_country, norm_sido
from .measures import MEASURE_INTENT, concept_groups, is_measure
from .measures import squash as _msq
from .measures import strip_trailing_measure
from .slots import INTENTS, SLOT_KEYS
from .terms import TERM_INDEX, to_canonical

REGION_KEYS = ["지역", "전출지", "전입지"]
MOVE_VALUES = ["전입", "전출", "순이동", "입국", "출국", "국제순이동"]
MAX_SUBS = 10  # 하위 질문 최대 개수 (슬롯 프롬프트 하위 질문 규칙 2와 같음)
AGE_WORD_MAP = {"노인": "65세 이상", "고령자": "65세 이상", "고령": "65세 이상", "어르신": "65세 이상"}
AGE_FORMAT = re.compile(r"\d+~\d+세|\d+세 (?:이상|이하|미만|초과)|\d+세")
TERM_AGE = re.compile(r"^(\d+~\d+세|\d+세 (?:이상|이하|미만|초과))\s*(.+)$")  # '65세 이상 인구' → 연령 + 대상

# 지역 칸 검증: HCX 가 지표('혼인건수')나 의도('추이')를 지역·전출지 칸에 넣는 실수를 바로잡음
REGION_SUFFIX = re.compile(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|읍|면|동|리)$")  # 행정구역 끝말
INDICATOR_SUFFIX = re.compile(r"(?:수|율|률|비율|비중|인구|가구|연령)$")  # 지표처럼 끝나는 말
NOT_REGION_WORDS = {"추이", "추세", "흐름", "변화", "동향", "변동", "비교", "순위", "증감", "증가", "감소", "합계",
                    "차이", "전망", "예측", "구성비", "증감률", "값", "조회", "통계", "현황"} | set(INTENTS)
MOVE_WORD_RE = re.compile(r"전입|전출|이사|이동|유입|유출|옮기|옮긴|옮겨|떠나|떠난|들어온|빠져나|이주|이민|입국|출국")
TREND_WORD_RE = re.compile(r"추이|추세|흐름")



# 비교축 말 → 정해진 축 이름 ('서울 자치구별 …' 의 '자치구', '연령대별' 의 '연령대'). View·검색이 아는 이름으로
AXIS_SYNONYM = {"자치구": "시군구", "구": "시군구", "구군": "시군구", "시군": "시군구", "시·군·구": "시군구", "기초자치단체": "시군구",
                "광역시도": "시도", "시·도": "시도", "광역자치단체": "시도",
                "연령대": "연령", "나이": "연령", "나이대": "연령", "연령층": "연령", "연령구간": "연령", "성": "성별"}

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
    from .subcheck import clean_value, meaningless
    for k in ("대상", "지표"):  # LLM 이 단 한자 주석('수(水)') 은 떼고, 한 글자뿐인 값('수')은 뺌
        vals = [clean_value(v) for v in s[k]]
        bad = [v for v, c in zip(s[k], vals) if not c or meaningless(c)]
        if bad or vals != s[k]:
            log.append(f"{k} 다듬기: {s[k]} → {[c for c in vals if c and not meaningless(c)]}")
        s[k] = list(dict.fromkeys(c for c in vals if c and not meaningless(c)))
    raw = _as_intents(slots.get("의도"))
    intents = list(dict.fromkeys(x for x in raw if x in INTENTS))
    if bad := [x for x in raw if x not in INTENTS]:
        log.append(f"의도 삭제(정해진 값 아님): {bad}")
    if not intents:
        log.append("의도 기본값: '값 조회'")
        intents = ["값 조회"]
    if len(intents) > 1 and "범위 밖" in intents:  # 범위 밖은 다른 의도와 같이 쓰지 않음 (프롬프트 규칙)
        intents.remove("범위 밖"); log.append("의도 삭제: '범위 밖'은 다른 의도와 같이 쓰지 않음")
    if not main and len(intents) > 1:
        log.append(f"하위 질문 의도는 하나만: {intents} → {intents[0]!r}")
    s["의도"] = intents if main else intents[0]
    return s, log


# ---- 2) 사전 대표 용어 ----
def apply_terms(s):
    """대상·지표 값을 용어 사전의 대표 용어로.
    대표 용어가 연령 자체면('노인' → '65세 이상') 연령 슬롯으로 옮기고, 그 때문에 대상이 비면 '인구'를 넣음
    '65세 이상 인구'처럼 연령이 붙은 용어는 연령 + 나머지('인구')로 나눔"""
    log, moved = [], False
    for k in ("대상", "지표"):
        out = []
        for v in s[k]:
            new, changed = to_canonical(v)
            if changed:
                log.append(f"{k} 대표 용어: {v} → {new}")
            if AGE_FORMAT.fullmatch(new):  # 연령 값 자체 → 연령 슬롯으로 이동
                s["연령"].append(new); moved = True
                log.append(f"{k}→연령 이동: {new}")
                continue
            m = TERM_AGE.match(new)
            if m:  # 연령이 붙은 용어 → 연령 + 나머지
                s["연령"].append(m.group(1))
                new = m.group(2).strip()
                log.append(f"{k} 연령 분리: {m.group(1)} / {new}")
            out.append(new)
        s[k] = list(dict.fromkeys(out))
    if moved and not s["대상"]:
        s["대상"] = ["인구"]; log.append("대상 채움: 연령만 남아 '인구'")
    s["연령"] = list(dict.fromkeys(s["연령"]))
    return s, log


# ---- 2-a) 계산 단어 정리 ----
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
    """q = 코드 추출에서 변환된 질문. main=True면 메인 슬롯(빠진 값 채움), False면 하위 슬롯(삭제만). 반환: (슬롯, 내역)"""
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

    # 전출지·전입지는 질문에 이동을 뜻하는 말이 있을 때만. 없으면 지역 칸 값으로 보고 아래에서 같이 검사
    if not MOVE_WORD_RE.search(q):
        for k in ("전출지", "전입지"):
            if s[k]:
                log.append(f"{tag}{k}→지역 이동(질문에 이동 관련 말 없음): {s[k]}")
                s["지역"] += s[k]
                s[k] = []

    # 지역·전출지·전입지: 시도는 정식 이름 + 코드가 찾은 것만. 시군구 등은 질문에 이름이 있을 때만
    for k in REGION_KEYS:
        out = []
        for v in s[k]:
            full = norm_sido(v)
            in_q = v in q or re.sub(r"(시|군|구|읍|면|동)$", "", v) in q
            if v in SIDO_GROUPS:  # 권역('수도권') → 코드가 찾은 시도 정식 이름으로 풀기
                members = [f for f in SIDO_GROUPS[v] if f in rule_found.get("지역", [])]
                out += members
                log.append(f"{tag}{k} 권역 풀기: {v} → {members}" if members else f"{tag}{k} 삭제(질문에 없음): {v}")
            elif full and (full in rule_found.get("지역", []) or (full == "전국" and not rule_found.get("지역"))):  # 지역 없는 질문의 "전국"은 프롬프트 규칙
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
            if full in used or any(_ns(full) in _ns(u) for u in used):
                continue  # HCX 값에 이미 들어 있음
            part = [u for u in s["지역"] if _ns(u) in _ns(full)]
            if part and any(_ns(full).endswith(_ns(u)) for u in part):
                continue  # HCX 가 끝부분('권선구')을 이미 씀
            if part:  # HCX 가 넓은 앞부분('수원시')만 씀 → 코드 값으로
                s["지역"] = [full if u in part else u for u in s["지역"]]
                s["지역"] = list(dict.fromkeys(s["지역"])); log.append(f"지역 바꿈(코드가 찾음): {part} → {full}")
            else:
                s["지역"].append(full); log.append(f"지역 채움(코드가 찾음): {full}")
        if not used and not s["지역"] and (s["대상"] or s["지표"]):  # 프롬프트: 질문에 지역이 없으면 "전국" (찾을 대상·지표가 있을 때만)
            s["지역"] = ["전국"]; log.append("지역 채움(질문에 지역 없음): 전국")

    # 국적: 질문에 있는 국가만
    nat = []
    for v in s["국적"]:
        c = norm_country(v)  # 표기 통일 ('타이완' → '대만'). 표에 없는 국가는 None
        if c and c in rule_found.get("국적", []):
            nat.append(c)
            if c != v:
                log.append(f"{tag}국적 표기 통일: {v} → {c}")
        elif not c and v in q:  # 표에 없는 국가는 질문에 그대로 있을 때만
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
        k = next((k for k, names in SEX.items() if v in (k, k[0], *names)), None)  # '남'·'남성'·'남학생' → '남자'
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
    axes = [re.sub(r"별$", "", v) for v in s["비교축"]]
    for v in [v for v in axes if v in AXIS_SYNONYM]:
        log.append(f"{tag}비교축 '{v}' → '{AXIS_SYNONYM[v]}'")
    s["비교축"] = list(dict.fromkeys(AXIS_SYNONYM.get(v, v) for v in axes))

    # 의도: '연도별'로 연도가 2개 이상이면 추이 (프롬프트 의도 규칙)
    if len(s["시점"]) >= 2 and ("연도" in s["비교축"] or "연도별" in q or TREND_WORD_RE.search(q)):
        if isinstance(s["의도"], list) and "추이" not in s["의도"]:  # 원 질문: 값 조회만 있으면 바꾸고, 다른 의도가 있으면 추가
            new = ["추이"] if s["의도"] == ["값 조회"] else s["의도"] + ["추이"]
            log.append(f"의도: 연도별·추이로 연도 {len(s['시점'])}개 → {s['의도']} → {new}"); s["의도"] = new
        elif s["의도"] == "값 조회":  # 하위 질문: 값 조회 → 추이
            log.append(f"{tag}의도: 연도별·추이로 연도 {len(s['시점'])}개 → '값 조회' → '추이'"); s["의도"] = "추이"
    return s, log


# ---- 3-a) 원문 충실도: 재작성이 바꾸거나 뺀 시점·의도·지표·조건을 원문 규칙으로 되돌림 ----
# (11-19 오답 분석: 8문항 중 5문항의 오답이 재작성에서 시작 — 대상·조건·비율이 바뀌거나 빠짐)
from .extract import TREND_WORD_RE as PERIOD_TREND_RE  # noqa: E402  추이|매년|연도별|해마다|흐름|추세|연평균 …

CHANGE_RE = re.compile(r"증감|변화(?!\s*추이)|변했|변동|달라졌|달라진|늘었|줄었|늘거나|줄거나|늘어났|줄어들|줄어든|늘어난|증가|감소|"
                       r"얼마나\s*(?:변|늘|줄|증가|감소|달라)|몇\s*(?:명|건|가구|호|개|집)\s*(?:이나\s*)?(?:늘|줄|증가|감소|변)")
RATE_RE = re.compile(r"증감률|증가율|감소율|변화율|몇\s*(?:퍼센트|%)|퍼센트|%\s*(?:늘|줄|증가|감소)")
CHANGE_INTENTS = ("증감", "증감률")
RATE_SUFFIX = re.compile(r"(?:비율|비중|구성비)$")
RATE_INDICATOR = re.compile(r"(?:비율|비중|구성비|율|률)$")
NUM_COND = re.compile(r"^[\d][\d,\.]*\s*(?:명|가구|건|호|세대|개|%|퍼센트|천명|만명)?\s*(?:이상|이하|초과|미만)?$")


def restore_spans(s, spans, found_times, tag=""):
    """'최근 N년' 기간(extract.recent_spans)을 HCX 가 양 끝·일부로 줄였으면 기간 전체로 되돌림.
    메인 슬롯은 fix_slots 가 코드 시점으로 이미 채움 → 여기서는 하위 슬롯. 시점이 빈 하위 슬롯은
    질문의 시점이 그 기간뿐일 때만 채움"""
    log = []
    if not spans:
        return s, log
    have = {int(v[:4]) for v in s.get("시점") or [] if re.match(r"\d{4}년$", v)}
    only_span = found_times and all(any(a <= int(t[:4]) <= b for a, b in spans) for t in found_times if t[:4].isdigit())
    for a, b in spans:
        full = set(range(a, b + 1))
        if (have and have <= full and have != full) or (not have and not s.get("시점") and only_span):
            new = [f"{y}년" for y in range(a, b + 1)]
            log.append(f"{tag}시점 되돌림('최근 N년' {a}~{b}년 전체): {s.get('시점') or []} → {a}~{b}년")
            s["시점"] = new
            break
    return s, log


def fix_change_intent(s, q, spans, main=True):
    """변화를 물은 질문의 의도 (모듈 2 는 재작성 문장 끝 의도어로 measure 를 정함)
    - 연도 2개 이상 + 변화 표현('얼마나 변했어'·'몇 명 늘었나') + 추이 표현 없음 → 증감(률)이 의도에 있게
    - 두 해만 비교 → 의도 '추이' · 비교축 '연도' 를 뺌 ('… 증감 추이' 로 끝나 raw 로 읽히던 문제)
    - '최근 N년' 기간 전체의 변화 → [증감, 추이] (기간 값 + 처음 대비 끝 증감)"""
    log, tag = [], "" if main else "(하위) "
    years = [v for v in s.get("시점") or [] if re.match(r"\d{4}년", v)]
    if len(years) < 2 or not CHANGE_RE.search(q) or PERIOD_TREND_RE.search(q):
        return s, log
    chg = "증감률" if RATE_RE.search(q) else "증감"
    span = any(len(years) >= 3 and {int(y[:4]) for y in years} == set(range(a, b + 1)) for a, b in spans)
    if main:
        intents = list(s["의도"])
        if not any(i in CHANGE_INTENTS for i in intents):
            new = [chg] + [i for i in intents if i not in ("값 조회", "추이")] + (["추이"] if "추이" in intents else [])
            log.append(f"의도: 변화 표현 → {intents} → {new}")
            intents = new
        if span and "추이" not in intents:
            intents.append("추이")
            log.append("의도 채움: '최근 N년' 기간 전체의 변화 → '추이' (기간 값과 증감을 함께)")
        if not span and len(years) == 2:
            if "추이" in intents:
                intents = [i for i in intents if i != "추이"]
                log.append("의도 삭제: 두 해 비교의 '추이' (증감으로 계산)")
            if "연도" in s.get("비교축", []):
                s["비교축"] = [a for a in s["비교축"] if a != "연도"]
                log.append("비교축 삭제: 두 해 비교의 '연도'")
        # 계산 의도를 앞에 (분석 단계가 첫 의도를 대표로 넘김)
        s["의도"] = sorted(intents, key=lambda i: i not in CHANGE_INTENTS)
    elif s["의도"] in ("값 조회", "추이"):
        log.append(f"{tag}의도: 변화 표현 → {s['의도']!r} → {chg!r}")
        s["의도"] = chg
    return s, log


def drop_unasked_qualifier(s, q, tag=""):
    """질문에 없는 '평균' 을 지표에 붙였으면 뗌 ('가구원수' → HCX '평균 가구원수' — 뜻이 다른 지표)"""
    log, qq = [], _ns(q)
    if "평균" in qq:
        return s, log
    for k in ("지표", "대상"):
        out = []
        for v in s.get(k) or []:
            rest = re.sub(r"^\s*평균\s*", "", str(v))
            if rest != v and _ns(rest) and _ns(rest) in qq:
                log.append(f"{tag}{k} 되돌림(질문에 '평균' 없음): {v} → {rest}")
                v = rest
            out.append(v)
        s[k] = list(dict.fromkeys(out))
    return s, log


def drop_number_conditions(s, tag=""):
    """조건 칸의 숫자 조각('99,000', '99,000명 이상') — 분류 값이 아니라 기준값 → 뺌 (thresholds 가 맡음)"""
    bad = [v for v in s.get("조건") or [] if NUM_COND.fullmatch(str(v).strip())]
    if not bad:
        return s, []
    s["조건"] = [v for v in s["조건"] if v not in bad]
    return s, [f"{tag}조건 삭제(숫자 기준값 → 조건 기준으로 따로): {bad}"]


def drop_threshold_indicator(s, thresholds, tag=""):
    """'X가 N명 이상인 지역' 의 X 는 지역을 고르는 기준 → 구할 지표가 아님. 메인 지표·대상에서 빼고 (역할 '조건' 단위가 찾음)
    구할 지표가 하나도 안 남으면 빼지 않음"""
    log = []
    picks = {_ns(t["말"]) for t in thresholds if t.get("지역_고르기")}
    if not picks:
        return s, log
    keep = {k: [v for v in s.get(k) or [] if _ns(v) not in picks] for k in ("지표", "대상")}
    if not (keep["지표"] or keep["대상"]):
        return s, log  # 구할 것이 그 기준뿐 → 그대로
    for k, vals in keep.items():
        gone = [v for v in s.get(k) or [] if v not in vals]
        if gone:
            log.append(f"{tag}{k} 삭제(지역을 고르는 기준이라 조건 단위로): {gone}")
            s[k] = vals
    return s, log


def fix_share(s, q, den, part, main=True):
    """'X 중 Y가 차지하는 비율' → 의도 구성비 · 대상 X · 조건 Y · 지표 X 를 세는 말
    ('보증부월세비율' 처럼 표에 없는 'Y비율' 지표를 만들던 문제)
    건드리지 않음: 비율 지표 자체를 물은 질문('인구 중 고령인구비율'), 대상·지표가 비어 있는 슬롯(분석 단계가 CSV 표현으로 채움)
    대상·지표를 새로 채우는 것은 'Y비율' 지표를 조건으로 옮겼을 때만"""
    log, tag = [], "" if main else "(하위) "
    if not (s.get("대상") or s.get("지표")):
        return s, log
    moved = False
    if part:  # 'Y비율' 지표 → 조건 Y
        out = []
        for v in s.get("지표") or []:
            stem = RATE_SUFFIX.sub("", _ns(v))
            if stem != _ns(v) and stem and (stem == _ns(part) or _ns(part).endswith(stem)):
                if not any(stem in _ns(c) for c in s.get("조건") or []):
                    s["조건"] = (s.get("조건") or []) + [part]
                log.append(f"{tag}지표 → 조건(구성비의 부분): {v} → {part}")
                moved = True
                continue
            out.append(v)
        s["지표"] = out
    if any(RATE_INDICATOR.search(_ns(v)) for v in s.get("지표") or []):
        return s, log  # 비율 지표 자체를 물음 → 값 조회
    if moved and den and not any(_ns(den) in _ns(v) or _ns(v) in _ns(den) for v in s.get("대상") or []):
        s["대상"] = [den] + list(s.get("대상") or [])
        log.append(f"{tag}대상 채움(구성비의 전체): {den}")
    if moved and den and not s.get("지표"):
        cnt = "가구수" if _ns(den).endswith("가구") else "인구수" if re.search(r"(?:인구|주민|사람)$", _ns(den)) else None
        if cnt:
            s["지표"] = [cnt]
            log.append(f"{tag}지표 채움(구성비의 전체를 세는 말): {cnt}")
    if main and "구성비" not in s["의도"]:
        new = ["구성비"] + [i for i in s["의도"] if i != "값 조회"]
        log.append(f"의도: 'X 중 … 비율' → {s['의도']} → {new}")
        s["의도"] = new
    elif not main and s["의도"] == "값 조회":
        s["의도"] = "구성비"
        log.append(f"{tag}의도: 'X 중 … 비율' → '구성비'")
    return s, log


def _role_only(ss, words):
    """하위 슬롯이 분모·조건 말뿐인가 (대상·지표가 그 말이나 일반 말뿐 + 조건 없음) → 역할 단위(roles.py)가 따로 찾으므로 뺌"""
    from .subcheck import content, is_generic_value
    vals = content(ss)
    keys = [_ns(w) for w in words if w]
    return bool(vals) and not ss.get("조건") and any(not is_generic_value(v) for v in vals) and \
        all(is_generic_value(v) or any(_ns(v) == k or _ns(v) in k for k in keys) for v in vals)


def dedupe_subs(subs):
    """일반 말을 빼면 대상·지표·조건·자리가 같은 하위 질문 → 하나만 ('보증부월세 일반가구 가구수' · '보증부월세 일반가구')"""
    from .subcheck import content, frame, is_generic_value
    seen, out, log = set(), [], []
    for ss in subs:
        key = (frozenset(_ns(v) for v in content(ss) if not is_generic_value(v)),
               frozenset(_ns(v) for v in ss.get("조건") or []), frame(ss))
        if key[0] and key in seen:
            log.append(f"하위 질문 삭제(앞 하위 질문과 같음): {content(ss)}")
            continue
        seen.add(key)
        out.append(ss)
    return out, log


SPLIT_KEYS = ("시점", "지역", "성별")  # 같은 통계표에서 바꿔 가져올 수 있는 축 (프롬프트 하위 질문 규칙 2)


def _is_cross_split(subs):
    """하위 질문이 시점·지역·성별만 다르고(지표·대상·의도 등은 모두 같음) 모든 조합으로 나뉘었는지
    모든 조합: 같은 지역이 여러 시점과, 또는 같은 시점이 여러 지역과 짝지어 나옴 → 나누지 않아야 함
    '2020년 광주', '2023년 울산'처럼 지역마다 시점이 하나면 짝지어 다른 것 → 나눔 (False)"""
    if len(subs) < 2:
        return False
    rest = {tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(s.items()) if k not in SPLIT_KEYS)
            for s in subs}
    if len(rest) > 1:  # 지표·대상·연령·의도 등이 다르면 다른 질문
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


# ---- 4) HCX 결과 하나 검증 ----
def validate_slots(r):
    """r = call_slots() 결과. 반환: {"slots", "sub_slots", "log"}"""
    q, found, hits = r["input_question"], r["rule_found"], r.get("term_hits", [])
    log = []
    if r.get("hcx_slots") is None:
        log.append(f"HCX 응답을 읽지 못해 코드 추출 값만 사용 ({r.get('error', '')})")
        return {"slots": _slots_from_code(found), "sub_slots": [], "log": log}

    s, l1 = clean_slots(r["hcx_slots"])
    if s["의도"] == ["범위 밖"]:  # 프롬프트: 범위 밖이면 다른 슬롯은 모두 []
        cleared = [k for k in SLOT_KEYS if s[k]]
        log += l1 + ([f"범위 밖이라 슬롯 비움: {cleared}"] if cleared else [])
        return {"slots": {**{k: [] for k in SLOT_KEYS}, "의도": ["범위 밖"]}, "sub_slots": [], "log": log}
    s, l2 = apply_terms(s)
    s, lm = clean_measures(s, main=True)
    s, l3 = fix_slots(s, q, found, hits, main=True)
    log += l1 + l2 + lm + l3
    from .roles import find_thresholds, share_denominator, share_part
    spans, thresholds = r.get("time_spans") or [], find_thresholds(q)
    den, part = share_denominator(q), share_part(q)
    for fn in (lambda x: fix_change_intent(x, q, spans, True), lambda x: drop_unasked_qualifier(x, q),
               drop_number_conditions, lambda x: drop_threshold_indicator(x, thresholds),
               lambda x: fix_share(x, q, den, part, True) if den else (x, [])):
        s, lx = fn(s)
        log += lx

    subs = []
    one_time = found.get("시점", []) if len(found.get("시점", [])) == 1 else []  # 질문 전체 시점이 하나뿐일 때만
    for i, raw in enumerate(r.get("hcx_subs", [])[:MAX_SUBS]):
        ss, a = clean_slots(raw, main=False)  # 하위 질문 의도는 하나
        ss, b = apply_terms(ss)
        ss, bm = clean_measures(ss, main=False)
        ss, c = fix_slots(ss, q, found, hits, main=False)
        log += [f"(하위 {i}) {x}" for x in a + b] + [x.replace("(하위) ", f"(하위 {i}) ") for x in bm + c]
        if one_time and not ss["시점"]:
            ss["시점"] = list(one_time); log.append(f"(하위 {i}) 시점 채움(질문 전체 시점 하나): {one_time}")
        t = f"(하위 {i}) "
        ss, d = restore_spans(ss, spans, found.get("시점", []), t)
        log += d
        for fn in (lambda x: fix_change_intent(x, q, spans, False), lambda x: drop_unasked_qualifier(x, q, t),
                   lambda x: drop_number_conditions(x, t), lambda x: fix_share(x, q, den, part, False) if den else (x, [])):
            ss, lx = fn(ss)
            log += [x.replace("(하위) ", t) for x in lx]
        roles_words = [den] + [th["말"] for th in thresholds if th.get("지역_고르기")]
        if any(roles_words) and _role_only(ss, roles_words):
            log.append(f"(하위 {i}) 삭제: 분모·조건 말뿐 → 역할 단위로 따로 찾음 {roles_words}")
            continue
        if not (ss["지역"] or ss["전출지"] or ss["전입지"]) and s["지역"]:  # 지역을 비운 하위 질문 = 원 질문 지역
            ss["지역"] = list(s["지역"]); log.append(f"(하위 {i}) 지역 채움(원 질문): {s['지역']}")
        if not (ss["대상"] or ss["지표"]):
            log.append(f"(하위 {i}) 삭제: 대상·지표가 없음")
            continue
        subs.append(ss)
    if subs:  # 표를 가르지 못하는 하위 질문 ('수(水)' · 분모처럼 붙은 일반 말 '인구') — subcheck.py
        from .subcheck import prune_sub_slots
        subs, lp = prune_sub_slots(q, s, subs)
        subs, ld = dedupe_subs(subs)
        log += lp + ld
    if _is_cross_split(subs):  # 프롬프트 규칙 2: 모든 연도 × 모든 지역은 나누지 않음
        log.append(f"하위 질문 {len(subs)}개 삭제: 시점·지역·성별만 다른 모든 조합 (한 통계표에서 가져옴)")
        subs = []
    if len(subs) == 1:  # 하위 질문이 하나면 메인과 같으므로 뺌
        log.append("하위 질문이 1개뿐이라 뺌")
        subs = []
    source = "hcx" if subs else ""
    if not subs and (subs := split_by_indicator(s)):  # 프롬프트 규칙 1 을 코드로: HCX 가 나누지 않아도 지표별로
        source = "code"
        log.append(f"하위 질문 채움(지표 {len(subs)}개, HCX 가 나누지 않음): {[(x['지표'] or x['대상'] or ['?'])[0] for x in subs]}")
        # (retrieval_golden 89문항 중 13건이 이 줄에서 죽어 원문 검색으로 넘어감)
    for ss in subs:  # 원 질문 의도에 하위 질문 의도가 모두 들어가게 (프롬프트 규칙 4)
        if ss["의도"] not in s["의도"]:
            s["의도"].append(ss["의도"]); log.append(f"의도 채움(하위 질문): {ss['의도']}")
    # sub_source: hcx = HCX 가 나눈 하위 질문 / code = 코드가 지표별로 나눔 (code 면 분석 단계가 자기 분리 정책을 씀) / "" = 없음
    # thresholds: 'X 가 N명 이상' 기준 (roles.find_thresholds). 재작성 문장에 '가구원수 99,000명 이상' 으로 남기고
    # 분석 결과 state.thresholds 로 넘김 (조건 칸에는 분류 값만)
    return {"slots": s, "sub_slots": subs, "log": log, "sub_source": source, "thresholds": thresholds}


def split_by_indicator(s):
    """메인 슬롯의 개념이 2개 이상이면 개념마다 하위 질문 (프롬프트 하위 질문 규칙 1)
    개념 = measures.concept_groups: 대상과 일반 지표('국제결혼 이주자' + '인구수')는 한 개념, 계산 단어는 개념이 아님
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
