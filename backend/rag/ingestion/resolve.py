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
POOL = 50                # BM25 1단계 후보 수 (이 안에서 조건 확인 → 상위 top_k 만 dense 재정렬)

# 검색 문장에서 뺄 시점 표현 ('작년', '최근 5년간', '2023년', '연도별' …)
TIME_RE = re.compile(r"(최근\s*\d+\s*(년간|년|개월)?|\d{4}\s*년(도)?(\s*(부터|까지|이후|이전|~))?|\d{4}|작년|올해|금년|전년|내년|"
                     r"지난\s*해|연도별|년도별|월별|분기별|연간|최근)")
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
    q = TIME_RE.sub(" ", q)
    names = sorted({n for r in (f.get("지역") or []) for n in SHORT_OF.get(r, [r])} | {"전국"}, key=len, reverse=True)
    for n in names:                                      # 긴 이름부터 ('대구광역시' 를 '대구' 보다 먼저)
        q = re.sub(re.escape(n) + r"(의|에서|에|은|는|이|가)?", " ", q)
    q = " ".join(q.split())
    have = squash(q)
    extra = [t for t in (f.get("지표") or []) + (f.get("대상") or []) if squash(t) not in have]
    return " ".join([q, *dict.fromkeys(extra)]).strip() or text


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
        miss = [r for r in regions if short(r) not in sidos]
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

    stems = term_stems(f.get("지표") or [])
    if stems:
        hay = squash(p["tbl_nm"]) + "|" + "|".join(squash(n) for n in names)
        if not any(s in hay for s in stems):
            note(out, "지표", "missing", f"지표 {f.get('지표')} 없음", requested=f.get("지표"))
    return out


# ── 3) 다시 줄 세우기 ───────────────────────────────────────────
def cost(un, cover):
    # 못 맞춘 정도 = 시점 외 못 맞춘 조건 수 + 시점은 못 담은 비율 (6개 중 4개 담음 → 0.33)
    # '예/아니오' 로만 세면 4/6 담은 표와 0/6 표가 똑같이 1 → 추이 질의에서 옛 표가 올라오던 문제
    # 요청 연도 목록이 있는 시점 메모는 cover 로 대신 셈 ('최신 자료 없음' 은 연도 목록이 없으므로 1 로 셈)
    return sum(not (u["slot"] == "시점" and isinstance(u["requested"], list)) for u in un) + (1 - cover)


def rerank(cands, f):
    # 후보 목록(각 dict 에 tbl_id) → unmet·cover·cost 를 붙이고 (cost, 원래 순서) 로 정렬
    for c in cands:
        p = profile(c["tbl_id"])
        c["unmet"] = unmet(p, f) if p else [{"slot": None, "dim": None, "type": "missing", "requested": None,
                                             "applied": None, "text": "메타 프로필 없음"}]
        c["cover"] = round(period_cover(p, f), 2) if p else 0.0
        c["cost"] = round(cost(c["unmet"], c["cover"]), 3)
    return sorted(cands, key=lambda c: c["cost"])           # sorted 는 안정 정렬 → 같은 값이면 원래 순서
