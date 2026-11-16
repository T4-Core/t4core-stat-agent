"""질문 원문 → 검색에 쓰는 단면 (LLM 재작성에 기대지 않는 부분)

재작성 문장만으로 검색하면 표를 가르는 단어가 사라진다 ('유학생' → '외국인 인구수 증감률 추이').
그래서 원문에서 규칙으로 뽑을 수 있는 것은 원문에서 뽑는다.

  years     조회 시점 (출생연도 '1983년생'·'생년 1983' 은 cohort 로 따로 — 시점 조건으로 쓰면 정답 표가 탈락)
  cycle     '분기'·'월' 을 물었는가
  sido      시도 (짧은 이름)                 subs  시도 아래 지역 ('부산진구'·'안동군'·'동부')
  lex       어휘 검색용 문장: 시점·지역·임계값('99,000명 이상')을 빼고, 일상어 사전의 통계어를 더함
  link      값 연결용 정규화 문자열 (공백·구두점 없음)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from backend.rag.search.facets import URBAN
from backend.rag.search.text import norm

YEAR = r"(?:19|20)\d{2}"
COHORT_RE = re.compile(rf"(?:생년(?:별)?\s*({YEAR})\s*년?(?:생)?|({YEAR})\s*년?\s*생|({YEAR})\s*년(?:에|도에)?\s*(?:태어난|출생한)|"
                       rf"출생\s*연도(?:별|가)?\s*({YEAR})|태어난\s*해가?\s*({YEAR}))")
YEAR_RE = re.compile(rf"(?<![\d,\.])({YEAR})(?![\d,]|\.\d)")
RANGE_RE = re.compile(rf"({YEAR})\s*년?\s*(?:~|-|–|부터|에서)\s*({YEAR})\s*년?\s*(?:까지|사이)?")
THRESH_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:명/㎢|명|가구|건|호|세대|개|%|퍼센트|㎡)?\s*(?:이상|이하|초과|미만)")
BIGNUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
JOSA = r"(?:에서의|에서는|에서|에게|에는|으로|로|까지|부터|의|에|은|는|이|가|을|를|도|과|와)?"
TOKEN_JOSA = re.compile(r"(에서의|에서는|에서|에게|에는|으로|까지|부터|의|에|은|는|이|가|을|를|도|과|와|로)$")
SUB_RE = re.compile(r"^[가-힣]{1,5}(시|군|구)$")
# 시·군·구로 끝나지만 지역이 아닌 말 (지역 사전이 없을 때의 안전장치). 뒤쪽 일치 / 낱말 전체 일치를 나눔 ('제시' ≠ '거제시')
NOT_REGION = re.compile(r"(인구|가구|도시|특별시|광역시|자치시|직할시|시군구|자치구|행정구|일반구)$")
NOT_REGION_WORDS = set("다시 동시 역시 당시 실시 표시 제시 명시 일시 수시 상시 임시 즉시 혹시 감시 무시 중시 공시 고시 전시 게시 개시 "
                       "출시 입시 누구 야구 축구 농구 친구 요구 도구 욕구 출구 입구 항구 연구 기구 지구 출생시 사망시 혼인시 이혼시 "
                       "조사시 필요시 결혼시 입국시 출국시".split())
WANT_AGE_RE = re.compile(r"\d+\s*세|[1-9]0\s*대|연령|나이|몇\s*살|고령|노인|어르신|청년|청소년|영유아|아동|유소년|생산연령|노년")
WANT_SEX_RE = re.compile(r"남자|여자|남성|여성|성별|남녀|엄마|아빠|남편|아내")
ANY_REGION_RE = re.compile(r"어느\s*(?:지역|시도|곳|도시)|지역은|지역별|지역들|곳은\s*어디|어디일까|어디인가|어디야|어디인지|행정구역별")
AXIS_RE = re.compile(r"(읍면동|시군구|시도)\s*(?:별|단위|마다|\s)")
# 표를 가르지 못하는 군말 — 긴 설문 문항 이름('… 이야기 나눌 수 있는 사람 수')과 우연히 겹쳐 엉뚱한 표가 올라오는 것을 막음
FILLER_RE = re.compile(r"알\s*수\s*있는|알고\s*싶어요?|보고\s*싶어요?|확인할\s*수\s*있는|보여\s*주는|보여줘|알려\s*줘|알려주세요|찾아\s*줘|"
                       r"어디서\s*봐|어떻게\s*되나요|어떻게\s*돼|얼마나\s*(?:돼|되나요|될까요?)?|몇\s*(?:명|가구|건|호|살)?(?:이야|이에요|인가요|야|이나)?|"
                       r"인지|일까요?|인가요|이에요|이야|같이|함께|주로|제일|가장|많은\s*게|뭐야|무엇|자료|통계표|통계|결과|"
                       r"우리나라(?:에)?|(?<![가-힣])한국에?(?=\s)|요즘|사람들이|사람들|사람")
REL_YEAR = {"작년": -1, "지난해": -1, "전년": -1, "올해": 0, "금년": 0, "재작년": -2, "내년": 1}


@dataclass
class QueryView:
    question: str
    years: list = field(default_factory=list)
    cohort: list = field(default_factory=list)
    cycle: set = field(default_factory=set)
    sido: list = field(default_factory=list)
    subs: list = field(default_factory=list)
    lex: str = ""
    link: str = ""
    added: list = field(default_factory=list)            # 일상어 사전으로 더한 통계어
    want_age: bool = False                               # 연령을 물었는가 (→ 연령 분류가 있는 표)
    want_sex: bool = False
    axis: str | None = None                              # '시군구별'·'읍면동 단위' → 그 수준의 지역 분류가 있는 표


def _term_index():
    try:
        from backend.rag.query_analyzer.terms import load_term_dict
        return {norm(a): ts for a, ts in load_term_dict().items()}
    except Exception:  # noqa: BLE001  (사전이 없어도 검색은 계속)
        return {}


_TERMS = None
_COLLOQUIAL = None


def _colloquial():
    """configs/colloquial.yaml: [정규식, [통계어…]] 목록"""
    from pathlib import Path
    f = Path(__file__).resolve().parent / "configs" / "colloquial.yaml"
    if not f.exists():
        return []
    import yaml
    return [(re.compile(pat), list(terms)) for pat, terms in yaml.safe_load(f.read_text(encoding="utf-8")) or []]


def synonyms(text):
    """일상어 → 통계어. ① configs/colloquial.yaml (구어 정규식) ② term_dict.json ('결혼' → '혼인')
    긴 표현부터 찾고, 이미 문장에 있는 통계어는 더하지 않는다"""
    global _TERMS, _COLLOQUIAL
    if _TERMS is None:
        _TERMS = _term_index()
    if _COLLOQUIAL is None:
        _COLLOQUIAL = _colloquial()
    t, out = norm(text), []
    for pat, terms in _COLLOQUIAL:
        if pat.search(str(text)):
            out += [x for x in terms if norm(x) not in t and x not in out]
    for alias in sorted(_TERMS, key=len, reverse=True):
        if len(alias) >= 2 and alias in t:
            for term in _TERMS[alias]:
                if norm(term) not in t and term not in out:
                    out.append(term)
            t = t.replace(alias, "|")
    return out


def parse_question(question, filters=None, today=None, region_dict=None) -> QueryView:
    """filters = 쿼리 모듈 슬롯 (있으면 시점·지역을 합침 — '최근 5년' 같은 상대 표현은 쿼리 모듈이 풀어 줌)"""
    from backend.rag.ingestion.normalize import SIDO_ALIAS
    from backend.rag.ingestion.resolve import short
    q = str(question or "")
    f = filters or {}
    v = QueryView(q)
    today = date.fromisoformat(str(today)) if today else date.today()

    v.cohort = sorted({int(y) for m in COHORT_RE.finditer(q) for y in m.groups() if y})
    body = COHORT_RE.sub(" ", q)
    try:                                                  # '1995년부터 5년마다' → 1995·2000·…·기준 해 (쿼리 모듈과 같은 규칙)
        from backend.rag.query_analyzer.extract import expand_open_range
        body = expand_open_range(body, today)[0]
    except Exception:  # noqa: BLE001
        pass
    years = {int(y) for y in YEAR_RE.findall(THRESH_RE.sub(" ", BIGNUM_RE.sub(" ", body)))}
    for a, b in RANGE_RE.findall(body):
        if 0 < int(b) - int(a) <= 60 and re.search(r"추이|매년|연도별|해마다|변화\s*추이", q):
            years |= set(range(int(a), int(b) + 1))
    for w, d in REL_YEAR.items():
        if w in q:
            years.add(today.year + d)
    years |= {int(y) for y in f.get("시점") or [] if str(y).isdigit()}
    v.years = sorted(y for y in years if y not in v.cohort)
    if re.search(r"분기", q):
        v.cycle.add("Q")
    if re.search(r"상반기|하반기|반기", q):                # 반기 값은 월·분기 자료로 계산
        v.cycle.add("H")
    v.want_age = bool(f.get("연령")) or bool(WANT_AGE_RE.search(q))
    v.want_sex = bool(f.get("성별")) or bool(WANT_SEX_RE.search(q))
    m = AXIS_RE.search(q + " ")
    ax = (m.group(1) if m else None) or str(f.get("비교축") or "")
    v.axis = next((g for g in ("읍면동", "시군구", "시도") if g in ax), None)
    if v.axis is None and (ANY_REGION_RE.search(q) or any(w in ax for w in ("지역", "행정구역"))):
        v.axis = "지역"                                   # 수준은 말하지 않았지만 지역끼리 비교 → 지역 분류가 있는 표
    if re.search(r"월별|월간|매월|(?<!\d)\d{1,2}\s*월(?!\s*세)|지난달|이번\s*달", q):
        v.cycle.add("M")

    # 지역: 시도는 별칭 사전, 그 아래는 낱말 모양 + (있으면) 지역 사전
    text = body
    sido = []
    for a in sorted(SIDO_ALIAS, key=len, reverse=True):
        m = re.search(rf"(?<![가-힣]){re.escape(a)}{JOSA}(?![가-힣])", text)
        if m:
            sido.append(short(a))
            text = text.replace(m.group(0), " ")
    for r in f.get("지역") or []:
        if r != "전국" and SIDO_ALIAS.get(norm(r)):
            sido.append(short(r))
    v.sido = list(dict.fromkeys(sido))
    subs, keep = [], []
    for tok in text.split():
        bare = tok.strip(",.?!()[]「」'\"")
        core = TOKEN_JOSA.sub("", bare) if len(bare) > 2 else bare
        n = norm(core)
        is_sub = (n in URBAN or (SUB_RE.match(core) and not NOT_REGION.search(core) and core not in NOT_REGION_WORDS
                                 and (region_dict is None or n in region_dict)))
        if is_sub and not (n in URBAN and region_dict is not None and n not in region_dict):
            subs.append(n)
        else:
            keep.append(tok)
    for r in f.get("지역") or []:                          # 쿼리 모듈이 준 시군구 ('수원시 권선구')
        n = norm(str(r).split()[-1])
        if not SIDO_ALIAS.get(norm(r)) and r != "전국" and (SUB_RE.match(n) or n in URBAN):
            subs.append(n)
    v.subs = list(dict.fromkeys(subs))

    lex = " ".join(keep)
    lex = THRESH_RE.sub(" ", BIGNUM_RE.sub(" ", lex))
    lex = re.sub(rf"{YEAR}\s*년?(?:도)?{JOSA}|전국적?{JOSA}|(?<!\d)\d{{1,2}}\s*분기|작년|올해|지난해|금년|전년", " ", lex)
    v.added = synonyms(lex)                               # 일상어 → 통계어 (군말을 지우기 전에: '사는 사람' → 인구)
    core = FILLER_RE.sub(" ", lex)
    core = core if len(norm(core)) >= 2 else lex          # 다 지워지면 원래 문장
    v.lex = " ".join((core + " " + " ".join(v.added)).split())
    v.link = norm(core) + "|" + "|".join(norm(a) for a in v.added)
    return v
