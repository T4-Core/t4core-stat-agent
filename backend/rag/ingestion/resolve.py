"""
[엔드포인트 3-1] resolve — 검색 후보 표가 슬롯 조건을 담고 있는지 메타 프로필로 확인 → 조건을 많이 맞춘 표부터

  1) search_query : 검색 문장 다듬기
       A. 지역·시점 단어를 뺀다 ('작년 대구 인구 수' → '인구 수'). 슬롯에 연령이 있으면 연령 표현도 ('20대' → 뺌)
          — '20대' 는 kiwi 가 '20'·'대' 로 쪼개 '대' 한 글자가 엉뚱한 표 점수를 올리던 문제 (resolve.md 남은 약점 ①)
          — 지역·시점은 표를 고르는 단어가 아니라 View 를 자르는 조건. 옛 표 설명문에만 시도 이름이 있어서
            '대구' 가 옛 표를 끌어올리던 문제 (search.md 진단)
       C. 슬롯의 지표·대상 단어를 더한다 ('신생아 수 발생 건수' + '출생아수')
          — 쿼리 모듈이 구어체를 표 용어로 바꿔 준 단어를 그대로 씀 (동의어 사전을 따로 두지 않음)
  2) unmet : 표 하나 × 슬롯 dict → 못 맞춘 조건 목록 (원본 CSV 는 읽지 않음, 메타 프로필만)
       시점 : 요청 연도가 표 기간 안에 있나 / 연도를 안 물었으면 LATEST_FROM 년 이후 자료가 있나
       지역 : 요청 시도가 분류 코드나 항목 이름에 있나 / '시도별' 이면 시도 코드가 있나
       성별·연령 : 그 구분이 분류나 항목에 있나
       지표 : 지표·대상 단어가 표 이름·항목·분류 코드 이름에 있나
  3) rerank : 못 맞춘 조건 수가 적은 표부터, 같으면 원래 순위

원칙
  - 표를 버리지 않고 순서만 바꾼다. 못 맞춘 조건은 후보의 unmet 에 남겨 판단 모듈이 볼 수 있게
  - 메타는 "정의된 코드·시점" 이라 실제 데이터와 다를 수 있음 → View 를 만들 때(build_view) 실제 프로필로 다시 확인
"""
import re

from backend.rag.ingestion.build_view import SEX_ALIAS, full_names, has_sex, note, squash, term_stems
from backend.rag.ingestion.meta_profile import load_meta_profiles
from backend.rag.ingestion.normalize import SIDO, SIDO_ALIAS

LATEST_FROM = 2024       # 연도를 안 물었을 때 "최신 표" = 이 해 이후 자료가 있는 표 (최신 시점 2024·2025)
POOL = 50                # BM25 1단계 후보 수 (이 안에서 조건 확인 → 상위 DENSE_POOL 만 dense 재정렬)
DENSE_POOL = 20          # [NEW 11-12] 조건 확인 뒤 dense 로 넘기는 후보 수 (최종은 top_k). 이전: top_k(10) 로 바로 잘라
                         #   정답이 조건 단계에서 11~20위로 밀리면 dense 가 볼 기회가 없던 문제 (144문항 중 29건)

# [NEW 11-12] 지표 조건 확인에서 빼는 계산 단어 — 표의 항목 이름이 아니라 계산 방법 ('보증부월세비율' → '보증부월세')
#   긴 말부터 지움 ('증감률' 을 '증감' 보다 먼저)
MEASURE_TOKENS = sorted(["구성비", "비율", "비중", "평균", "합계", "총합계", "총계", "증감률", "증감량", "증감", "증가율",
                         "감소율", "증가량", "감소량", "변화폭", "변화량", "변화율", "차이", "순위", "인구천명당", "천명당",
                         "%p", "(%p)", "(%)", "%"], key=len, reverse=True)
# [NEW 11-12] 수를 세는 일반 지표 → 표의 단위로 충족 여부를 봄 (항목 이름에 '인구수' 가 없는 표가 대부분이라
#   이름으로 보면 정답 표 88% 가 '지표 없음' 이 되던 문제)
GENERIC_UNITS = {"인구수": ("명", "인"), "인구": ("명", "인"), "인원": ("명", "인"), "인원수": ("명", "인"),
                 "명수": ("명", "인"), "가구수": ("가구",), "가구": ("가구",), "건수": ("건",), "호수": ("호",),
                 "세대수": ("세대",)}
STEM_SUFFIXES = ("건수", "자수", "아수", "인수", "수", "율", "률", "별")

# 검색 문장에서 뺄 시점 표현 ('작년', '최근 5년간', '2023년', '연도별' …)
TIME_RE = re.compile(r"(최근\s*\d+\s*(년간|년|개월)?|\d{4}\s*년(도)?(\s*(부터|까지|이후|이전|~))?|\d{4}|작년|올해|금년|전년|내년|"
                     r"지난\s*해|연도별|년도별|월별|분기별|연간|최근)")
# [NEW v4] 기간·월 표현 ('2022~2026년', '1983~1995년생', '7~9월', '9월') — TIME_RE 가 연도만 지워 '~'·'생' 이 남던 문제
RANGE_RE = re.compile(r"\d{4}\s*(?:년도?)?\s*[~\-–]\s*\d{4}\s*(?:년도|년간|년생|년)?")
MONTH_RE = re.compile(r"\d{1,2}\s*[~\-–]\s*\d{1,2}\s*월|(?<!\d)\d{1,2}\s*월(?!\s*\d)")
# [NEW v4] 지역·시점을 지운 뒤 홀로 남은 조사·기호 토큰 ('로 전입한', ', 한부모가구', '~ 인구수')
LONE_TOKENS = {"의", "에", "에서", "로", "으로", "은", "는", "이", "가", "과", "와", "및", "을", "를", "까지", "부터", "도", "생"}
EDGE_SYMBOLS = "~-–·,.;:/"
# [NEW 11-12] 검색 문장에서 뺄 의도 단어 — 재작성 문장 끝에 붙는 의도어('… 증감', '… 순위')는 표를 고르는 말이 아님
#   (sentence.INTENT_WORD). '구성비'·'비율'·'평균' 은 표 이름에도 쓰여 남김
INTENT_TOKENS = {"추이", "비교", "순위", "증감", "증감률", "증감량", "합계", "증가", "감소", "변화", "변화량", "변화폭",
                 "증가율", "감소율", "차이", "값", "조회"}
# 슬롯에 연령이 있을 때 뺄 연령 표현 ('20대', '65세 이상', '20~29세'). '노인'·'고령' 처럼 숫자 없는 말은 남김
AGE_RE = re.compile(r"\d+\s*(?:대|세)?\s*[~\-]\s*\d+\s*세?|\d+\s*세\s*(?:이상|이하|미만|초과)?|\d+\s*대")
SHORT_OF = {canon: [canon, *aliases] for _, canon, aliases in SIDO}
OLD_SIDO_RE = re.compile(r"(특별시|광역시|직할시|특별자치시|특별자치도)$")
AGE_NAME_RE = re.compile(r"\d+\s*세|\d+\s*[~\-]\s*\d+")

_prof = {}


def profile(tbl_id):
    if not _prof:
        _prof.update({p["tbl_id"]: p for p in load_meta_profiles()})
    return _prof.get(tbl_id)


# ── 1) 검색 문장 ────────────────────────────────────────────────
def search_query(text, f):
    # 자연어 + 슬롯 dict → BM25·dense 에 넣을 검색 문장
    f = f or {}
    q = AGE_RE.sub(" ", text) if f.get("연령") else text      # 연령은 슬롯 {from, to} 가 맡음 → 검색어에서 뺌
    q = MONTH_RE.sub(" ", RANGE_RE.sub(" ", q))           # [NEW v4] 기간·월 먼저 (연도만 지우면 '~' 가 남음)
    q = TIME_RE.sub(" ", q)
    names = sorted({n for r in (f.get("지역") or []) for n in SHORT_OF.get(r, [r])} | {"전국"}, key=len, reverse=True)
    for n in names:                                      # 긴 이름부터 ('대구광역시' 를 '대구' 보다 먼저)
        q = re.sub(re.escape(n) + r"(에서의|에서|에게|으로|로|까지|부터|의|에|은|는|이|가)?", " ", q)
        # [CHANGED v4] 이전: (의|에서|에|은|는|이|가)? — '경기도로' 의 '로' 가 남던 문제
    toks = clean_tokens(q.split())                        # [CHANGED v4] 이전: " ".join(q.split())
    q = " ".join(t for t in toks if t not in INTENT_TOKENS) or " ".join(toks)   # [NEW 11-12] 의도 단어 빼기
    have = squash(q)
    extra = [t for t in (f.get("지표") or []) + (f.get("대상") or []) if squash(t) not in have and t not in INTENT_TOKENS]
    return " ".join([q, *dict.fromkeys(extra)]).strip() or text


def clean_tokens(toks):
    # [NEW v4] 앞뒤 기호를 떼고, 기호만·조사만 남은 토큰은 버림 ('70~79세' 처럼 안쪽 기호는 그대로)
    out = []
    for t in toks:
        t = t.strip(EDGE_SYMBOLS)
        if t and t not in LONE_TOKENS and re.search(r"\w", t):
            out.append(t)
    return out


# ── 2) 조건 확인 ────────────────────────────────────────────────
def short(name):
    # '대구광역시'·'대구직할시'·'대구' → '대구' (옛 명칭도 같은 시도로 보기 위함)
    n = squash(name)
    canon = SIDO_ALIAS.get(n)
    return SHORT_OF[canon][1] if canon else OLD_SIDO_RE.sub("", n)


def all_names(p):
    # 분류 코드 이름 + 항목 이름 (메타 프로필은 분류마다 최대 300개, 시도는 sido 에 전부)
    out = full_names([i["name"] for i in p.get("items") or []])
    for l in p.get("levels") or []:
        out += full_names(l.get("names") or []) + list(l.get("sido") or [])   # '-' 줄은 윗줄 이름 이어받기
    return out


def sido_names(p):
    return {short(n) for n in all_names(p) if SIDO_ALIAS.get(squash(n)) or OLD_SIDO_RE.search(squash(n))}


def spans(p):
    return [(x["year_from"], x["year_to"]) for x in p.get("periods") or [] if x.get("year_to")]


def period_cover(p, f):
    # 요청 연도 중 표 기간 안에 든 비율 (0~1). 연도를 안 물었으면 1
    want = (f or {}).get("시점")
    if not want:
        return 1.0
    years = spans(p)
    return sum(any(a <= y <= b for a, b in years) for y in want) / len(want)


def unmet(p, f):
    # 표 메타 프로필 × 슬롯 dict → 못 맞춘 조건 메모 목록 (빈 목록 = 다 맞춤)
    f, out = f or {}, []
    years = spans(p)
    last = max((t for _, t in years), default=None)
    want = f.get("시점")
    # 반환 모양은 build_view 의 notes 와 같음: {slot, dim, type, requested, applied, text}
    if want:
        miss = [y for y in want if not any(a <= y <= b for a, b in years)]
        if miss:
            note(out, "시점", "missing", f"시점 {miss} 없음 (수록 ~{last})", requested=miss)
    elif last is None or last < LATEST_FROM:
        note(out, "시점", "missing", f"최신 자료 없음 (끝 연도 {last})", requested="최신", applied=last)

    names = all_names(p)
    sidos = sido_names(p)
    regions = [r for r in (f.get("지역") or []) if r != "전국"]
    if regions:
        miss = [r for r in regions if not region_ok(p, r, names, sidos)]
        # [CHANGED 11-12] 이전: [r for r in regions if short(r) not in sidos] — 시군구('고성군')·동부 등은
        #   시도 목록에 있을 수 없어 시군구 표도 늘 '지역 없음' 이 되던 문제
        if miss:
            note(out, "지역", "missing", f"지역 {miss} 없음", requested=miss)
    elif f.get("비교축") in ("시도", "지역") and len(sidos) < 10:
        note(out, "지역", "missing", "시도별 코드 없음", requested=f.get("비교축"))

    sexes = {SEX_ALIAS.get(s, s) for s in (f.get("성별") or [])}
    if sexes and not any(l["kind"] == "sex" for l in p.get("levels") or []) \
            and not all(any(has_sex(n, s) for n in names) for s in sexes):
        note(out, "성별", "missing", f"성별 {sorted(sexes)} 구분 없음", requested=sorted(sexes))
    if f.get("연령") and not any(l["kind"] == "ages" for l in p.get("levels") or []) \
            and not any(AGE_NAME_RE.search(str(n)) for n in names):
        note(out, "연령", "missing", "연령 구분 없음", requested=f.get("연령"))

    if not indicator_ok(p, f.get("지표") or [], names):
        note(out, "지표", "missing", f"지표 {f.get('지표')} 없음", requested=f.get("지표"))
    # [CHANGED 11-12] 이전: term_stems(지표) 중 하나가 표 이름·분류·항목에 글자 그대로 있어야 함
    #   → '구성비'·'인구수'·'혼인건수' 같은 지표로 정답 표 대부분이 불일치가 되던 문제 (indicator_ok)
    return out


def indicator_core(term):
    """[NEW 11-12] 지표 값에서 계산 단어를 뺀 핵심 ('보증부월세비율' → '보증부월세', '구성비' → '')"""
    t = squash(term)
    for w in MEASURE_TOKENS:
        t = t.replace(squash(w) or w, "")
    return t


def indicator_stems(core):
    """[NEW 11-12] 핵심 말 → 찾을 어간 ('혼인건수' → {'혼인건수', '혼인'}, '출생아수' → {'출생아수', '출생아', '출생'})"""
    out, t = {core}, core
    for _ in range(2):                                   # 두 번까지 ('사망자수' → '사망자' → '사망')
        for suf in STEM_SUFFIXES + ("자", "아"):
            if t.endswith(suf) and len(t) - len(suf) >= 2:
                t = t[:-len(suf)]
                out.add(t)
                break
    return {s for s in out if len(s) >= 2}


def indicator_ok(p, terms, names):
    """[NEW 11-12] 지표 조건 충족 여부. 지표 값 하나라도 맞으면 충족
    - 계산 단어만인 값('구성비'·'증감률')은 조건에서 뺌 (모두 그런 값이면 충족)
    - 수를 세는 일반 지표('인구수'·'가구수'·'건수')는 표 단위로 (단위 정보가 없으면 충족으로 봄)
    - 나머지는 어간이 표 이름·분류·항목 이름에 있는지"""
    cores = [c for c in (indicator_core(t) for t in terms) if c]
    if not cores:
        return True
    units = {squash(u) for u in p.get("units") or []}
    hay = squash(p["tbl_nm"]) + "|" + "|".join(squash(n) for n in names)
    for c in cores:
        if c in GENERIC_UNITS and (not units or any(w in u for u in units for w in GENERIC_UNITS[c])):
            return True
        if any(s in hay for s in indicator_stems(c)):
            return True
    return False


def region_ok(p, region, names, sidos):
    """[NEW 11-12] 지역 하나가 표에 있는지
    - 시도('대구'·'대구광역시'·옛 직할시) → 표의 시도 목록에 있는지 (예전과 같음)
    - '서울특별시 강남구' 처럼 시도가 앞에 붙은 값 → 시도는 시도 목록으로, 나머지는 아래처럼
    - 시군구·읍면동('고성군'·'권선구') → 이름이 분류 이름에 있거나, 표에 시군구·읍면동 수준 분류가 있으면 충족
      (메타 프로필은 시군구 이름을 다 담지 않으므로 '그 수준이 있는가' 로 봄. 정확한 확인은 View 단계)
    - '동부'·'읍부'·'면부' → 이름이 분류에 있는지"""
    parts = str(region).split()
    sub = parts
    if len(parts) > 1 and (SIDO_ALIAS.get(squash(parts[0])) or OLD_SIDO_RE.search(squash(parts[0]))):
        if short(parts[0]) not in sidos:
            return False
        sub = parts[1:]
    elif SIDO_ALIAS.get(squash(region)) or OLD_SIDO_RE.search(squash(region)):
        return short(region) in sidos
    want = squash(sub[-1]) if sub else ""
    if not want:
        return True
    flat = {squash(n) for n in names}
    if want in flat or re.sub(r"(시|군|구|읍|면|동)$", "", want) in flat:
        return True
    if want in ("동부", "읍부", "면부"):
        return False
    geo = {}
    for lv in p.get("levels") or []:
        if lv.get("kind") == "regions":
            for k, v in (lv.get("geo_types") or {}).items():
                geo[k] = geo.get(k, 0) + (v or 0)
    return bool(geo.get("시군구") or geo.get("읍면동"))


# ── 3) 다시 줄 세우기 ───────────────────────────────────────────
def cost(un, cover):
    # 못 맞춘 정도 = 시점 외 못 맞춘 조건 수 + 시점은 못 담은 비율 (6개 중 4개 담음 → 0.33)
    # '예/아니오' 로만 세면 4/6 담은 표와 0/6 표가 똑같이 1 → 추이 질의에서 옛 표가 올라오던 문제
    # 요청 연도 목록이 있는 시점 메모는 cover 로 대신 셈 ('최신 자료 없음' 은 연도 목록이 없으므로 1 로 셈)
    return sum(not (u["slot"] == "시점" and isinstance(u["requested"], list)) for u in un) + (1 - cover)


def dense_pool(top_k):
    """[NEW 11-12] 조건 확인 뒤 dense 재정렬에 넘길 후보 수 (최종은 top_k 로 자름)"""
    return max(int(top_k or 0), DENSE_POOL)


def rerank(cands, f):
    # 후보 목록(각 dict 에 tbl_id) → unmet·cover·cost 를 붙이고 (cost, 원래 순서) 로 정렬
    for c in cands:
        p = profile(c["tbl_id"])
        c["unmet"] = unmet(p, f) if p else [{"slot": None, "dim": None, "type": "missing", "requested": None,
                                             "applied": None, "text": "메타 프로필 없음"}]
        c["cover"] = round(period_cover(p, f), 2) if p else 0.0
        c["cost"] = round(cost(c["unmet"], c["cover"]), 3)
    return sorted(cands, key=lambda c: c["cost"])           # sorted 는 안정 정렬 → 같은 값이면 원래 순서
