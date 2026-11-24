"""답변 문장의 claim 추출 — 숫자 + 단위 + 부호 + 방향어 + 지역 · 연도 · 항목 레이블을 한 묶음으로

한국어 수량은 한 숫자로 합친다: `23만 8,317` → 238317, `934만` → 9340000, `1억 2천만` → 120000000.
연도 · 월 · 분기 · 순위(`2024년`, `3월`, `1위`)는 수치 claim 이 아니라 기간 · 순위 레이블이다.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

SIGN_NEG = {"-", "−", "–", "▽", "▼"}
MAG = {"조": Decimal(10) ** 12, "억": Decimal(10) ** 8, "천만": Decimal(10) ** 7, "백만": Decimal(10) ** 6, "만": Decimal(10) ** 4}
_NUM = re.compile(r"(?P<sign>[-−–▽▼+△]\s?)?(?P<num>\d[\d,]*(?:\.\d+)?)(?P<mag>\s?(?:조|억|천만|백만|만)(?!\s?명당))?")
# 단위는 긴 것부터. '만 명' 은 MAG 로 처리하고 단위는 '명'
UNITS = ["%p", "％p", "%포인트", "퍼센트포인트", "%", "％", "퍼센트", "명/㎢", "천명당", "천명", "천가구", "가구", "개사", "개소", "개",
         "호", "백만원", "천원", "억원", "원", "㎢", "㎡", "배", "건", "명", "세", "톤", "대"]
_UNIT = re.compile(r"\s?(" + "|".join(re.escape(u) for u in UNITS) + ")")
UNIT_ALIAS = {"％p": "%p", "%포인트": "%p", "퍼센트포인트": "%p", "％": "%", "퍼센트": "%"}
_PERIOD_AFTER = re.compile(r"\s?(?:년(?!\s?간)|월|분기|반기|위\b|위(?=[,.\s)]|$)|번째|일\b|차\b)")
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")

REGIONS = ("전국", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "충청북도",
           "충청남도", "전북", "전남", "전라북도", "전라남도", "경북", "경남", "경상북도", "경상남도", "제주")
_YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?=\s?년|\D|$)")
# 월 단위 기간: '2024-12' · '2024.12' · '2024년 12월'. 연도만 있으면 연도로 둔다
_PERIOD = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?:\s?년\s?(\d{1,2})\s?월|[-./](\d{1,2})(?!\d))?")
_YM_PREFIX = re.compile(r"(?:1[89]\d{2}|20\d{2})[-./]$")
# 분모 · 비교 기준 위치의 지역은 그 숫자의 대상이 아니다 ('전국 대비 17.5%', '전국 중 서울')
_DENOM_AFTER = re.compile(r"^\s?(?:의\s)?(?:대비|중에서|중|에서\s?차지|기준|보다|에\s?비해)")
NEG_WORDS = ("감소", "하락", "줄었", "줄어", "순유출", "적자", "마이너스", "떨어", "축소")
POS_WORDS = ("증가", "상승", "늘었", "늘어", "순유입", "흑자", "올랐", "확대")


@dataclass
class Claim:
    value: Decimal
    unit: str | None
    decimals: int
    start: int
    end: int
    text: str
    sentence: str
    is_period: bool = False
    region: str | None = None          # 숫자 앞(같은 문장)의 가장 가까운 지역. 분모 위치는 제외
    year: str | None = None
    regions_in_sentence: set = field(default_factory=set)
    years_in_sentence: set = field(default_factory=set)
    direction: str | None = None       # pos · neg · None (같은 문장의 방향어)
    resolution: Decimal = Decimal(0)   # 표기 정밀도의 반 단위: '23.8만' → 500, '0.75' → 0.005, '238,317' → 0.5
    period: str | None = None          # [NEW] 숫자 앞 가장 가까운 기간. 월이 있으면 'YYYY-MM'


def sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def region_key(name: str | None, extra: tuple[str, ...] = ()) -> str | None:
    if not name:
        return None
    n = re.sub(r"\s+", "", str(name))
    short = {"충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남"}
    for full, s in short.items():
        if n.startswith(full) or n.startswith(s):
            return s
    for r in REGIONS + extra:
        if n.startswith(r):
            return r
    return n


def _labels(text: str, a: int, start: int, extra_regions: tuple[str, ...]) -> tuple[str | None, set, str | None, set]:
    before = text[a:start]
    names = REGIONS + extra_regions
    regs = []
    for m in re.finditer("|".join(re.escape(r) for r in sorted(names, key=len, reverse=True)), before):
        tail = re.match(r"[가-힣]*", before[m.end():]).group(0)       # '서울특별시', '부산광역시' 같은 꼬리
        rest = before[m.end() + len(tail):]
        regs.append((m.start(), region_key(m.group(0), extra_regions), bool(_DENOM_AFTER.match(rest))))
    yrs = [(m.start(), m.group(1)) for m in _YEAR.finditer(before)]
    target = [r for r in regs if not r[2]]
    return (target[-1][1] if target else None, {r for _, r, _ in regs}, yrs[-1][1] if yrs else None, {y for _, y in yrs})


def period_key(text: str) -> str | None:
    """'2024-1' · '2024년 1월' → '2024-01', '2024' → '2024'"""
    m = _PERIOD.fullmatch(str(text).strip()) or _PERIOD.search(str(text))
    if not m:
        return None
    mon = m.group(2) or m.group(3)
    return f"{m.group(1)}-{int(mon):02d}" if mon and 1 <= int(mon) <= 12 else m.group(1)


def _nearest_period(text: str, a: int, start: int) -> str | None:
    ms = list(_PERIOD.finditer(text[a:start]))
    return period_key(ms[-1].group(0)) if ms else None


def extract(text: str, extra_regions: tuple[str, ...] = ()) -> list[Claim]:
    text = text or ""
    spans = sentences(text)
    raw = list(_NUM.finditer(text))
    out: list[Claim] = []
    i = 0
    while i < len(raw):
        m = raw[i]
        sign = (m.group("sign") or "").strip()
        num = m.group("num")
        mag = (m.group("mag") or "").strip()
        value = Decimal(num.replace(",", "")) * (MAG[mag] if mag else 1)
        end = m.end()
        decimals = len(num.split(".")[1]) if "." in num else 0
        step = Decimal(10) ** -decimals * (MAG[mag] if mag else 1)
        # 한국어 수량 이어 붙이기: 큰 자리 다음에 바로 작은 수가 오면 합친다 (23만 8,317 · 1억 2천만)
        while mag and i + 1 < len(raw) and re.fullmatch(r"\s?", text[end:raw[i + 1].start()]) and not raw[i + 1].group("sign"):
            nxt = raw[i + 1]
            nmag = (nxt.group("mag") or "").strip()
            if nmag and MAG[nmag] >= MAG[mag]:
                break
            nnum = nxt.group("num")
            value += Decimal(nnum.replace(",", "")) * (MAG[nmag] if nmag else 1)
            step = Decimal(10) ** -(len(nnum.split(".")[1]) if "." in nnum else 0) * (MAG[nmag] if nmag else 1)
            end, mag, i = nxt.end(), nmag, i + 1
            if not nmag:
                break
        if sign in SIGN_NEG and not re.match(r"[\d~]", text[max(0, m.start() - 1):m.start()] or " "):
            value = -value
        um = _UNIT.match(text, end)
        unit = UNIT_ALIAS.get(um.group(1), um.group(1)) if um else None
        unit_end = um.end() if um else end
        is_period = not unit and (bool(_PERIOD_AFTER.match(text, end)) or bool(re.fullmatch(r"(1[89]|20)\d{2}", num) and not mag))
        # 월은 1~2자리 정수다. 콤마 · 소수점이 있는 숫자('2024-1,234')를 Decimal 로 바꾸면 예외가 난다
        if not unit and num.isdigit() and len(num) <= 2 and int(num) <= 12 \
                and _YM_PREFIX.search(text[max(0, m.start("num") - 5):m.start("num")]):
            is_period = True                                           # '2024-12' 의 '12' 는 월이다
        if unit == "명" and text[unit_end:unit_end + 1] == "당":      # '여성 1명당 0.748명' 의 '1명당' 은 기준 단위 표기다
            is_period = True
        s = next(((a, b) for a, b in spans if a <= m.start() < max(b, a + 1)), spans[-1])
        reg, regs, yr, yrs = _labels(text, s[0], m.start(), extra_regions)
        sent = text[s[0]:s[1]]
        per = _nearest_period(text, s[0], m.start())
        neg = any(w in sent for w in NEG_WORDS)
        pos = any(w in sent for w in POS_WORDS)
        out.append(Claim(value, unit, decimals, m.start(), unit_end, text[m.start():unit_end].strip(), sent, is_period,
                         reg, yr, regs, yrs, "neg" if neg and not pos else "pos" if pos and not neg else None, step / 2, per))
        i += 1
    return out


def numeric_claims(text: str, extra_regions: tuple[str, ...] = ()) -> list[Claim]:
    return [c for c in extract(text, extra_regions) if not c.is_period]
