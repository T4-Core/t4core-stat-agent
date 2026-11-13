"""2-2. 코드 추출 (HCX 호출 전): 상대 시점·연도 범위 변환, 시도·성별·연령·국적·출생연도 추출
노트북 user_question_rewrite_v3.ipynb '2-2' 셀의 코드를 그대로 옮김 (확인용 출력 부분은 뺌)
대응표 파일: dictionary/rule_dict.json (dictionary/build_dicts.py 가 만듦). 경로는 config.RULE_PATH"""
import json

from .config import RULE_PATH
from .terms import TERM_INDEX, _glued_number, _nospace                # 2-1 (일상어 사전 단어 가리기)

# ============= 2-2. 코드 추출 (HCX 호출 전) ================
# HCX 없이 정규식 + 대응표로 확실한 값만 뽑음: 시점, 지역(시도), 성별, 연령, 국적, 조건(출생연도)
# 백업 노트북(user_question_rewrite_v2_backup.ipynb)의 IN-4·슬롯 1 함수를 옮기고, 평가 질문 80개에서 나온 문제를 고침
import re
from datetime import date

MAX_RANGE_YEARS = 50     # 연도 범위는 이 길이까지 개별 연도로 펼침 (3단계 문장에서 다시 '2000~2025년'으로 묶음)
MAX_RANGE_MONTHS = 36    # 월 범위도 이 길이까지 펼침
YEAR = r"(?:19|20)\d{2}"


# ---- 1) 상대 시점 → 연도 ----
def resolve_relative_time(question, today=None):
    """'작년', '최근 5년', '2010년대', '지난달' 등을 기준일 기준 연도로 바꿈.
    '요즘', '코로나 전후'처럼 기준이 애매한 표현은 질문을 바꾸지 않음 (rule_extract 가 시점 값만 넣음). '최근 N년'은 올해 자료가 아직 없을 수 있어 작년까지.
    반환: (바뀐 질문, 바꾼 내역)"""
    today = today or date.today()
    Y, M = today.year, today.month
    q, notes = question, []

    def sub(pattern, repl):
        nonlocal q
        def _r(m):
            new = repl(m)
            notes.append(f"{m.group(0).strip()} → {new}")
            return new
        q = re.sub(pattern, _r, q)

    # 'N년 전/후'는 1~2자리 숫자만 ('2025년 전국'을 '2025년 전(前)'으로 읽지 않게). '전국·전체·후반' 등도 제외
    sub(r"최근\s*(\d{1,2})\s*년(간)?", lambda m: f"{Y - int(m.group(1))}년~{Y - 1}년")
    sub(r"(?<!\d)(\d{1,2})\s*년\s*전(?![국체년반부])", lambda m: f"{Y - int(m.group(1))}년")
    sub(r"(?<!\d)(\d{1,2})\s*년\s*(뒤|후)(?!반)", lambda m: f"{Y + int(m.group(1))}년")
    sub(r"(?<!\d)((?:19|20)\d)0\s*년대", lambda m: f"{m.group(1)}0년~{m.group(1)}9년")
    sub(r"지난\s*달", lambda m: f"{Y if M > 1 else Y - 1}년 {M - 1 if M > 1 else 12}월")
    sub(r"이번\s*달", lambda m: f"{Y}년 {M}월")
    sub(r"재작년", lambda m: f"{Y - 2}년")
    sub(r"작년|지난\s*해", lambda m: f"{Y - 1}년")
    sub(r"올해|금년", lambda m: f"{Y}년")
    sub(r"내년", lambda m: f"{Y + 1}년")
    return q, notes


# ---- 2) 범위 → 개별 연도·월 ----
# '2020년~2024년', '2000 년 부터 2025 년까지', '2016년에서 2025년까지' ('에서'는 '까지'가 있을 때만 범위)
# 'YYYY년생'(출생연도)은 범위로 보지 않음
RANGE_RE = re.compile(rf"(?<!\d)({YEAR})\s*년?\s*(?:~|-|–|부터|에서(?=\s*{YEAR}\s*년?\s*까지))\s*({YEAR})(?!\d)(?!\s*년?\s*생)\s*년?\s*(?:까지)?")
MONTH_RANGE_RE = re.compile(rf"(?<!\d)({YEAR})\s*년\s*(\d{{1,2}})\s*월\s*(?:부터|~|-|–)\s*(?:({YEAR})\s*년\s*)?(\d{{1,2}})\s*월\s*(?:까지)?")


def expand_year_ranges(text, max_years=MAX_RANGE_YEARS):
    """'2020년~2024년' → '2020년 2021년 2022년 2023년 2024년'. max_years보다 길면 'a년~b년' 그대로. 반환: (바뀐 텍스트, 내역)"""
    notes = []

    def _r(m):
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        new = " ".join(f"{y}년" for y in range(a, b + 1)) if b - a + 1 <= max_years else f"{a}년~{b}년"
        notes.append(f"{m.group(0).strip()} → {a}~{b}년 ({b - a + 1}개 연도)")
        return new + (" " if m.group(0).endswith(" ") else "")

    return RANGE_RE.sub(_r, text), notes


def expand_month_ranges(text, max_months=MAX_RANGE_MONTHS):
    """'2024년 7월부터 9월까지' → '2024년 7월 2024년 8월 2024년 9월'. 반환: (바뀐 텍스트, 내역)"""
    notes = []

    def _r(m):
        y1, m1 = int(m.group(1)), int(m.group(2))
        y2, m2 = int(m.group(3) or y1), int(m.group(4))
        a, b = y1 * 12 + m1 - 1, y2 * 12 + m2 - 1
        if not (1 <= m1 <= 12 and 1 <= m2 <= 12) or b < a or b - a + 1 > max_months:
            return m.group(0)
        new = " ".join(f"{k // 12}년 {k % 12 + 1}월" for k in range(a, b + 1))
        notes.append(f"{m.group(0).strip()} → {b - a + 1}개월")
        return new + (" " if m.group(0).endswith(" ") else "")

    return MONTH_RANGE_RE.sub(_r, text), notes



# ---- 3) 대응표: 시도, 성별, 연령, 국가 ----
# 표현 통일. HCX 호출 전에 코드가 질문에서 슬롯값을 직접 찾아서 쓸 때 사용 (2-4 검증에서도 같은 표를 씀)
# 찾는 규칙(공통): 긴 표기부터 찾고, 찾은 부분은 지워서 두 번 세지 않음 → '인도네시아' 안의 '인도', '충청북도' 안의 '충청'은 따로 안 잡힘

# 대응표는 dictionary/rule_dict.json 에서 읽음 (dictionary/build_dicts.py 가 만듦. 고칠 때는 build_dicts.py 를 고치고 다시 실행)
RULE_DICT = json.loads(RULE_PATH.read_text(encoding="utf-8"))

# (1) 시도: {정식 이름(슬롯에 넣는 값): [정식 이름, 다른 표기 ...]}. '전국' 포함
#     옛 이름도 같이 둠: 강원도(→ 2023.6 강원특별자치도), 전라북도(→ 2024.1 전북특별자치도)
SIDO = RULE_DICT["지역"]
SIDO_ALIASES = {full: names[1:] for full, names in SIDO.items() if full != "전국"}   # 시도 17개 (정식 이름 제외한 표기)

# (2) 권역: 여러 시도를 묶어 부르는 말 → 시도 정식 이름 여러 개로 풀어서 지역 슬롯에 넣음 {표기: [시도]}
SIDO_GROUPS = {n: g["값"] for g in RULE_DICT["지역_묶음"].values() for n in g["표기"]}

# (3) 시도 이름 뒤에 이런 말이 오면 지역이 아님 (정규식 lookahead) — '경기 침체'
SIDO_BLOCK = {k: r"(?!\s*(?:" + "|".join(map(re.escape, words)) + "))" for k, words in RULE_DICT["지역_제외"].items()}

# (4) 성별: {슬롯 값: [질문 표기]}. '남중생'처럼 다른 뜻이 붙은 말은 일상어 사전(2-1)에 있음 → HCX 가 채움
SEX = RULE_DICT["성별"]
SEX_BOTH = RULE_DICT["성별_묶음"]["남녀"]["표기"]                # 남자·여자 둘 다
# '성별로', '성별 비교'는 값이 아니라 나눠 보는 축(비교축: 성별)이라 여기 넣지 않음

# (5) 연령 단어: 질문에 연령을 뜻하는 말이 있는지만 봄 (2-4 에서 HCX 연령 값을 남길지 판단)
#     숫자 연령('30대', '65세 이상', '삼십대')은 아래 AGE_RES 정규식이 따로 찾음
AGE_WORDS = [
    "노인", "어르신", "고령", "노년", "노령", "실버",                  # 65세 이상
    "신생아", "영아", "유아", "영유아", "미취학",                      # 0~6세
    "어린이", "아동", "유소년", "초등학생", "학령",                    # 0~14세 · 학령인구(6~21세)
    "청소년", "미성년", "중학생", "고등학생",                          # 9~24세 · 19세 미만
    "청년", "젊은층", "청장년",                                         # 19~34세 (청년기본법)
    "중년", "장년", "중장년", "베이비붐", "베이비부머",                # 40~64세 등
    "생산연령", "생산가능",                                             # 15~64세
]
# 한글 숫자 연령 ('삼십대'): {한글: 숫자}. 긴 것부터 ('구십'을 '십'보다 먼저)
KOR_TENS = dict(sorted(((n, int(v)) for v, names in RULE_DICT["연령_한글숫자"].items() for n in names if n != v),
                       key=lambda x: -len(x[0])))

# (6) 국적: {슬롯 값(대표 이름): [대표 이름, 질문 표기 ...]}
COUNTRY_ALIASES = RULE_DICT["국적"]
COUNTRIES = list(COUNTRY_ALIASES)                           # 대표 이름 목록
COUNTRY_NAMES = sorted(((n, c) for c, names in COUNTRY_ALIASES.items() for n in names), key=lambda x: -len(x[0]))


def _mask(text, span):
    """찾은 부분을 같은 길이의 '|'로 지움 (다른 값으로 다시 잡히지 않게, 위치는 유지)"""
    a, b = span
    return text[:a] + "|" * (b - a) + text[b:]


# 규칙 사전 표기 전체 (띄어쓰기 없앤 것). 일상어 사전 단어 중 이것과 같은 것은 가리지 않음
RULE_WORDS = {_nospace(n) for slot, d in RULE_DICT.items() if slot != "지역_제외"
              for v, names in d.items() for n in [v, *(names["표기"] if isinstance(names, dict) else names)]}


def mask_terms(text, index=None):
    """2-1 일상어 사전 단어 자리를 '|'로 가린 사본. 규칙 대응표가 단어 안의 글자를 잡지 않게 함
    ('세대구성' 안의 '대구', '평균초혼연령' 안의 '초혼'). 긴 단어부터, 띄어쓰기는 무시
    가리지 않는 것: 규칙 사전 표기와 같은 단어, 숫자가 든 단어('65세 이상', '1인가구'), 앞 숫자에 붙은 단어('삼십대'의 '십대')
                    → 코드가 그 값을 찾아야 함"""
    index = TERM_INDEX if index is None else index
    for alias in sorted(index, key=lambda a: -len(_nospace(a))):
        a = _nospace(alias)
        if a in RULE_WORDS or re.search(r"\d", _kor_tens_to_digit(a)):    # 숫자·한글 숫자 연령('십대')은 코드가 찾음
            continue
        text = re.sub(r"\s*".join(map(re.escape, a)),
                      lambda m: m.group(0) if _glued_number(m.string, m.start(), a) else "|" * len(m.group(0)), text)
    return text


def norm_sido(text):
    """'서울', '서울시' → '서울특별시'. 시도가 아니면 None (권역 이름도 None) (2-4 검증에서도 사용)"""
    t = str(text).strip()
    return next((full for full, names in SIDO.items() if t in names), None)


def norm_country(text):
    """'타이완' → '대만', '조선족' → '한국계 중국'. 표에 없으면 None (2-4 검증에서 사용)"""
    t = str(text).strip()
    return next((c for c, names in COUNTRY_ALIASES.items() if t == c or t in names), None)


# 시도 표기 + 권역 이름 → [시도 정식 이름]. 긴 표기부터 ('비수도권'을 '수도권'보다 먼저)
SIDO_LOOKUP = sorted([(n, [full]) for full, names in SIDO.items() for n in names] + list(SIDO_GROUPS.items()),
                     key=lambda x: -len(x[0]))


def find_sido(q):
    """질문에 나온 시도 (나온 순서). 권역('수도권')은 시도 여러 개로 풀어 넣음. 긴 표기부터 찾고 찾은 부분은 지움.
    이름 바로 뒤에 시·군·구가 붙으면 시군구 이름이므로 건너뜀 ('제주시', '광주시'). SIDO_BLOCK 에 걸리면 건너뜀 ('경기 침체')"""
    found = []
    for n, fulls in SIDO_LOOKUP:
        # [CHANGED 11-12] 이름 뒤에 1~2글자 + 구·군이 이어지면 시군구 이름의 앞부분 ('부산진구' 의 '부산') → 건너뜀
        #   이전: (?![시군구]) 만 봐서 '부산진구' 를 부산광역시로 읽던 문제
        for m in list(re.finditer(re.escape(n) + r"(?![시군구])(?![가-힣]{1,2}[구군])" + SIDO_BLOCK.get(n, ""), q)):
            found += [(m.start(), i, full) for i, full in enumerate(fulls)]
            q = _mask(q, m.span())
    return list(dict.fromkeys(full for *_, full in sorted(found)))


# [NEW 11-12] 시군구 이름 ('가평군', '부산진구', '수원시 권선구' 의 '수원시'·'권선구')
#   코드가 시도만 찾고 시군구는 HCX 에 맡겨, 질문 속 시군구 38곳 중 16곳이 슬롯에서 빠지던 문제 (144문항 비교)
#   이름 뒤는 끝·기호·공백이거나 조사로 시작해야 함 ('화성군의', '가평군에서'). 아래 말로 끝나면 지역이 아님
SGG_RE = re.compile(r"(?<![가-힣0-9])((?:[가-힣]{2,4}(?:시|군|구))|(?:[중동서남북]구))"
                    r"(?=$|[^가-힣]|의|에|은|는|이|가|과|와|도|를|을|로|으로|내|까지|부터|보다|지역|민|만|별)")
SGG_NOT = ("인구", "가구", "지구", "연구", "친구", "입구", "출구", "항구", "요구", "도구", "기구", "시군구", "행정구",
           "선거구", "자치구", "당시", "동시", "역시", "도시", "특별시", "광역시", "자치시", "출생시", "사망시", "혼인시",
           "이혼시", "조사시", "입국시", "출국시")


def find_sigungu(q):
    """질문에 나온 시군구 이름 (나온 순서). 시도 이름('대구시')·통계 용어('고령자가구')·일반어('출생시')는 뺌"""
    out, last_end = [], None
    for m in SGG_RE.finditer(q):
        t = m.group(1)
        if t.endswith(SGG_NOT) or norm_sido(t) or _nospace(t) in TERM_INDEX:
            continue
        if out and last_end is not None and q[last_end:m.start()].strip() == "" and out[-1].endswith("시"):
            out[-1] = f"{out[-1]} {t}"                    # '수원시 권선구' → 값 하나 (프롬프트 규칙: 이어서 값 하나로)
        else:
            out.append(t)
        last_end = m.end()
    return list(dict.fromkeys(out))


def _kor_tens_to_digit(text):
    """'삼십대' → '30대' (한글 숫자 연령)"""
    for k, v in KOR_TENS.items():
        text = re.sub(rf"(?<![가-힣]){k}(\s*)대", lambda m: f"{v}{m.group(1)}대", text)
    return text


def norm_age(text):
    """연령 표기 통일 (2-4 검증에서도 사용)
    '30대' → '30~39세', '80대 이상' → '80세 이상', '삼십대' → '30~39세', '30-34세' → '30~34세', '65세이상' → '65세 이상'"""
    t = re.sub(r"\s+", "", _kor_tens_to_digit(str(text)))
    if m := re.fullmatch(r"(\d+)대(이상|이하)", t):
        return f"{m.group(1)}세 {m.group(2)}"
    if m := re.fullmatch(r"(\d+)대", t):
        return f"{m.group(1)}~{int(m.group(1)) + 9}세"
    if m := re.fullmatch(r"(\d+)[~\-](\d+)세?", t):
        return f"{m.group(1)}~{m.group(2)}세"
    if m := re.fullmatch(r"(\d+)세(이상|이하|미만|초과)", t):
        return f"{m.group(1)}세 {m.group(2)}"
    return str(text).strip()


AGE_RES = [  # 긴 패턴부터. 찾은 부분은 지워서 두 번 세지 않음
    re.compile(r"(?<!\d)\d{1,3}\s*세\s*(?:이상|이하|미만|초과)"),
    re.compile(r"(?<!\d)\d{1,3}\s*[~\-]\s*\d{1,3}\s*세"),
    re.compile(r"(?<!\d)[1-9]0\s*대(?:\s*(?:이상|이하))?"),        # 10대~90대만 ('3대 도시' 같은 것은 제외)
    re.compile(r"(?<!\d)\d{1,3}\s*세(?!\s*(?:이상|이하|미만|초과))"),
]
YEAR_RE = re.compile(rf"(?<!\d)({YEAR})(?!\d)(?!\s*(?:만|억|천|원|명|호|건|개|%|세|대))")   # '2000만 원'은 연도 아님
MONTH_RE = re.compile(rf"(?<!\d)({YEAR})\s*년\s*(\d{{1,2}})\s*월")
COHORT_RE = re.compile(rf"(?<!\d)({YEAR})(?:\s*[~\-]\s*({YEAR}))?\s*년?\s*생")

# 기준이 애매한 시점 → 시점 값 (2-3 프롬프트의 시점 규칙과 같음). 질문에 연도가 없을 때만 씀
FUZZY_TIMES = [
    (re.compile(r"코로나\s*전후"), lambda Y: ["2019년", "2021년"]),
    (re.compile(r"가장\s*최근|최근|최신|요즘"), lambda Y: [f"{Y - 1}년"]),   # 기준일의 직전 연도 하나
]


# ---- 4) 모두 적용 ----
def rule_extract(question, today=None):
    """반환: (변환된 질문, rule_found, 변환 내역)
    rule_found 키: 시점, 지역, 성별, 연령, 국적, 조건 (찾은 것만)"""
    q, notes = resolve_relative_time(question, today or date.today())
    q, n2 = expand_month_ranges(q)
    q, n3 = expand_year_ranges(q)
    notes += n2 + n3
    found, rest = {}, mask_terms(q)              # rest: 찾은 부분을 지워 가며 쓰는 사본. 일상어 사전 단어는 먼저 가림

    # 조건: 출생연도 ('1983~1995년생') — 시점으로 잡히지 않게 먼저 지움
    cohort = []
    for m in list(COHORT_RE.finditer(rest)):
        cohort.append(f"출생연도={m.group(1)}~{m.group(2)}년생" if m.group(2) else f"출생연도={m.group(1)}년생")
        rest = _mask(rest, m.span())
    if cohort:
        found["조건"] = cohort

    # 시점: 'YYYY년 M월'을 먼저 찾아 지우고, 남은 곳에서 연도만 있는 것. 둘 다 남김 (나온 순서)
    times = []
    for m in list(MONTH_RE.finditer(rest)):
        if 1 <= int(m.group(2)) <= 12:
            times.append((m.start(), f"{m.group(1)}년 {int(m.group(2))}월"))
            rest = _mask(rest, m.span())
    times += [(m.start(), f"{m.group(1)}년") for m in YEAR_RE.finditer(rest)]
    if not times:                                # 연도가 없을 때만 '요즘'·'최신'·'코로나 전후'를 시점으로 (질문 문장은 그대로)
        Y = (today or date.today()).year
        for rx, to_years in FUZZY_TIMES:
            for m in list(rx.finditer(rest)):
                years = to_years(Y)
                times += [(m.start(), y) for y in years]
                notes.append(f"{m.group(0)} → {', '.join(years)}")
                rest = _mask(rest, m.span())
    if times:
        found["시점"] = list(dict.fromkeys(t for _, t in sorted(times)))

    sido, sgg = find_sido(rest), find_sigungu(rest)      # [CHANGED 11-12] 시군구도 (시도 뒤에 붙여 나온 순서)
    if sido or sgg:
        found["지역"] = list(dict.fromkeys(sido + sgg))

    sex = [k for k, names in SEX.items() if any(n in rest for n in names)]
    if any(w in rest for w in SEX_BOTH):
        sex = list(SEX)
    if sex:
        found["성별"] = sex

    age_text, ages = _kor_tens_to_digit(rest), []               # '삼십대' → '30대' (사본에서만 바꿈)
    for rx in AGE_RES:
        for m in list(rx.finditer(age_text)):
            ages.append((m.start(), norm_age(m.group(0))))
            age_text = _mask(age_text, m.span())
    if ages:
        found["연령"] = list(dict.fromkeys(a for _, a in sorted(ages)))

    nat, nat_text = [], rest                                     # 긴 표기부터 ('인도네시아' 안의 '인도'는 제외)
    for n, c in COUNTRY_NAMES:                                   # 표기 → 대표 이름 ('타이완' → '대만')
        for m in list(re.finditer(re.escape(n), nat_text)):
            nat.append((m.start(), c))
            nat_text = _mask(nat_text, m.span())
    if nat:
        found["국적"] = list(dict.fromkeys(c for _, c in sorted(nat)))
    return q, found, notes
