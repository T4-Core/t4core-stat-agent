"""2-2. 코드 추출 (HCX 호출 전): 상대 시점·연도 범위 변환, 시도·성별·연령·국적·출생연도 추출
노트북 user_question_rewrite_v2.ipynb '2-2' 셀의 코드를 그대로 옮김 (확인용 출력 부분은 뺌)"""

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
    '요즘', '코로나 전후'처럼 기준이 애매한 표현은 그대로 둠. '최근 N년'은 올해 자료가 아직 없을 수 있어 작년까지.
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
SIDO_ALIASES = {
    "서울": ["서울특별시", "서울"], "부산": ["부산광역시", "부산"], "대구": ["대구광역시", "대구"],
    "인천": ["인천광역시", "인천"], "광주": ["광주광역시", "광주"], "대전": ["대전광역시", "대전"],
    "울산": ["울산광역시", "울산"], "세종": ["세종특별자치시", "세종"], "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"], "충북": ["충청북도", "충북"], "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"], "전남": ["전라남도", "전남"], "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"], "제주": ["제주특별자치도", "제주도", "제주"],
}
# 'OO시' 표기 추가. '광주시'(경기도 광주시), '제주시'(시군구)는 시도가 아니므로 넣지 않음
SIDO_EXTRA = {"서울특별시": ["서울시"], "부산광역시": ["부산시"], "대구광역시": ["대구시"], "인천광역시": ["인천시"],
              "대전광역시": ["대전시"], "울산광역시": ["울산시"], "세종특별자치시": ["세종시"]}
SIDO = {names[0]: list(dict.fromkeys(names + SIDO_EXTRA.get(names[0], []))) for names in SIDO_ALIASES.values()}
SIDO["전국"] = ["전국"]

SEX = {"남자": ["남자", "남성"], "여자": ["여자", "여성"]}
SEX_BOTH = ["남녀", "남·여", "남/여"]                    # 남자·여자 둘 다
AGE_WORDS = ["노인", "고령", "어린이", "아동", "청소년", "청년", "중년", "유소년", "생산연령", "영유아", "신생아"]
KOR_TENS = {"구십": 90, "팔십": 80, "칠십": 70, "육십": 60, "오십": 50, "사십": 40, "삼십": 30, "이십": 20, "십": 10}

COUNTRIES = ["베트남", "중국", "일본", "미국", "필리핀", "태국", "우즈베키스탄", "캄보디아", "몽골", "네팔",
             "인도네시아", "러시아", "대만", "캐나다", "호주", "카자흐스탄", "미얀마", "스리랑카", "방글라데시",
             "파키스탄", "인도", "키르기스스탄", "영국", "프랑스", "독일"]


def _mask(text, span):
    """찾은 부분을 같은 길이의 '|'로 지움 (다른 값으로 다시 잡히지 않게, 위치는 유지)"""
    a, b = span
    return text[:a] + "|" * (b - a) + text[b:]


def norm_sido(text):
    """'서울', '서울시' → '서울특별시'. 시도가 아니면 None (2-4 검증에서도 사용)"""
    t = str(text).strip()
    return next((full for full, names in SIDO.items() if t in names), None)


def find_sido(q):
    """질문에 나온 시도 (나온 순서). 긴 표기부터 찾고 찾은 부분은 지움.
    이름 바로 뒤에 시·군·구가 붙으면 시군구 이름이므로 건너뜀 ('제주시', '광주시')"""
    found = []
    for n, full in sorted(((n, full) for full, names in SIDO.items() for n in names), key=lambda x: -len(x[0])):
        for m in list(re.finditer(re.escape(n) + r"(?![시군구])", q)):
            found.append((m.start(), full))
            q = _mask(q, m.span())
    return list(dict.fromkeys(full for _, full in sorted(found)))


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


# ---- 4) 모두 적용 ----
def rule_extract(question, today=None):
    """반환: (변환된 질문, rule_found, 변환 내역)
    rule_found 키: 시점, 지역, 성별, 연령, 국적, 조건 (찾은 것만)"""
    q, notes = resolve_relative_time(question, today or date.today())
    q, n2 = expand_month_ranges(q)
    q, n3 = expand_year_ranges(q)
    notes += n2 + n3
    found, rest = {}, q                          # rest: 찾은 부분을 지워 가며 쓰는 사본

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
    if times:
        found["시점"] = list(dict.fromkeys(t for _, t in sorted(times)))

    if sido := find_sido(rest):
        found["지역"] = sido

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

    nat, nat_text = [], rest                                     # 긴 이름부터 ('인도네시아' 안의 '인도'는 제외)
    for c in sorted(COUNTRIES, key=len, reverse=True):
        for m in list(re.finditer(re.escape(c), nat_text)):
            nat.append((m.start(), c))
            nat_text = _mask(nat_text, m.span())
    if nat:
        found["국적"] = list(dict.fromkeys(c for _, c in sorted(nat)))
    return q, found, notes
