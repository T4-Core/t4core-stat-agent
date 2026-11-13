"""
규칙 모음 — 글 다듬기 · 사전 매칭 · 지표 추론 · 모집단 · 주석 정리 · 지역 이름

table_card(step1_split.py) 의 규칙을 출발점으로 삼고, 검토에서 찾은 문제를 고쳤다 (table_cards 코드는 수정하지 않음)
  ① 지표 추론 오탐   '출생연도별 인구' → 출생아수, '% 비율 표' → 가구수·주택수, '평균 가구원수' → 인구수
                     → 항목마다 측정 종류(개수·비율·평균)를 단위·이름으로 먼저 정하고, 개수 항목에서만 개수 지표를 추론
  ② 지역 이름        상위 코드가 없는 '중구' 가 시도 없이 남음 → 코드 앞자리로 시도·시를 이어 붙임
  ③ 제목 정리        '제주4·3' 이 '4·3' 으로 잘림 → 시도 이름 뒤에 숫자·가운뎃점이 붙으면 지역으로 보지 않음
  ④ 주석             한 문장이 여러 CMMT 줄로 쪼개져 옴 → 이어 붙이고, '☞'·'~란' 정의를 용어 정의로 분리
  ⑤ 모집단           '(12세이상)', '(내국인)', '외국인 제외', '집단가구 포함' 처럼 같은 주제 표를 가르는 범위를 따로 기록
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from backend.core.utils import norm_space
from backend.rag.ingestion.normalize import SIDO, SIDO_ALIAS, SIDO_CANON, std_geo_name

REPO_ROOT = Path(__file__).resolve().parents[1]
DICT_DIR = REPO_ROOT / "backend" / "rag" / "query_analyzer" / "dictionary"


def nospace(s):
    return re.sub(r"\s+", "", str(s or ""))


# ── 지역 이름 탐지 (③ 수정: 뒤에 숫자·가운뎃점이 붙으면 지역 아님) ─────────────
SIDO_SHORT = sorted({a for a in SIDO_ALIAS if len(a) >= 2}, key=len, reverse=True)
SIDO_RE = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, SIDO_SHORT)) + r"|[가-힣]{2}직할시)(?![가-힣0-9·])")
SIDO_CODE = {code: canon for code, canon, _ in SIDO}


def sido_std(name):
    """시도 표기 → 표준 이름 (옛 표기 포함). 시도가 아니면 None"""
    n = re.sub(r"직할시$", "광역시", norm_space(name))
    if n == "광주시":
        return "광주광역시"
    s = std_geo_name(n)
    return s if s in SIDO_CANON else None


# ── 제목·경로·분류·항목 다듬기 (table_card 와 같은 규칙 + ③) ───────────────
YEAR_PAREN = re.compile(r"\([^()]*(\d{4}|년|연도|읍면동|시군구|시도|전국)[^()]*\)")
TAIL = re.compile(r"\s*[–\-－]\s*(읍면동|시군구|시도|전국|구시군)[^|]*$")
BRACKET = re.compile(r"\[[^\]]*\]")
UNIT_PAREN = re.compile(r"\((명|가구|호|개|%|천명|건|세|년|원|천원|만원|㎡|인|쌍|가구원|None)\)")
LEVEL = r"(?:시도|시군구|구시군|읍면동|동읍면|행정구역)"
LEVEL_SEG = re.compile(rf"{LEVEL}별?|전국")
LEVEL_HEAD = re.compile(rf"^{LEVEL}별?[\s,]+")
LEVEL_TAIL = re.compile(rf"\s*[/_]\s*(?:{LEVEL}별?|전국)\s*$")
GENERIC_SEG = re.compile(r"^(전수|표본|기본표|전수기본표|표본기본표|전수부문|표본부문|주요\s*지표|통계표|주제별통계)$")


def clean_title(t):
    t = norm_space(t)
    before = t
    t = TAIL.sub("", t)
    t = YEAR_PAREN.sub("", t)
    t = SIDO_RE.sub("", t)
    t = re.sub(r"\(\s*[,\s]+", "(", t)
    t = re.sub(r"[,\s]+\)", ")", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"^[\s,·\-–_]+|[\s,·\-–_]+$", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\(구시군\)", "", t)
    t = "/".join(s.strip() for s in t.split("/") if not LEVEL_SEG.fullmatch(s.strip()))
    t = LEVEL_TAIL.sub("", t)
    t = LEVEL_HEAD.sub("", t).strip()
    return t or before


def title_core(t):
    """괄호·기호를 뺀 제목 뼈대 (같은 표의 다른 연도판·다른 모집단판을 묶을 때)"""
    return re.sub(r"[\s()（）,·/\-–_]+", "", re.sub(r"\([^()]*\)", "", t))


def clean_path(path, survey):
    segs = []
    for s in str(path or "").split(">"):
        s = YEAR_PAREN.sub("", s).strip()
        s = re.sub(r"\(\s*\d+\s*%\s*\)", "", s)
        s = re.sub(r"\d{4}\s*년?\s*(이후|이전)?", "", s).strip()
        s = SIDO_RE.sub("", s).strip()
        s = re.sub(r"\(\s*\)", "", s).strip()
        if not s or s == survey or GENERIC_SEG.match(s) or s in segs or s == "인구":
            continue
        segs.append(s)
    return segs[:-1] if len(segs) > 1 else segs          # 마지막 칸은 표 이름 자체


def clean_axis(obj_nm):
    n = YEAR_PAREN.sub("", obj_nm)
    n = re.sub(r"\(.*?\)", "", n)
    return re.sub(r"별$", "", n.strip()).strip()


def clean_item(name):
    n = BRACKET.sub("", name)
    n = UNIT_PAREN.sub("", n)
    n = re.sub(r"_계$|^계$", "", n)
    return n.replace("_", " ").strip()


# ── 사전 (질의 쪽과 같은 사전으로 표를 번역 — table_card 와 같은 방식) ─────────
@lru_cache(maxsize=1)
def load_dict():
    d = json.loads((DICT_DIR / "dictionary_표명.json").read_text(encoding="utf-8"))
    groups = {}
    for key, grp in [("TARGET_ALIASES", "대상"), ("INDICATOR_ALIASES", "지표"),
                     ("AXIS_ALIASES", "축"), ("MOVE_ALIASES", "이동")]:
        m = {}
        for canon, aliases in d.get(key, {}).items():
            for a in [canon, *aliases]:
                if nospace(a):
                    m[nospace(a)] = canon
        groups[grp] = m
    groups["나이표현"] = {nospace(a): canon for canon, al in d.get("AGE_TITLE_WORDS", {}).items()
                       for a in [canon, *al] if re.search(r"\d", a)}
    rd = json.loads((DICT_DIR / "rule_dict.json").read_text(encoding="utf-8"))
    groups["값"] = {nospace(a): canon for key in ("성별", "성별_묶음") for canon, al in rd.get(key, {}).items()
                   for a in [canon, *al] if nospace(a)}
    groups["값"].update({"남": "남자", "여": "여자"})
    t = json.loads((DICT_DIR / "term_dict.json").read_text(encoding="utf-8"))
    groups["_지표목록"] = set(d.get("INDICATOR_ALIASES", {})) | ({"출생아수"} & set(t))
    return groups


_alias_re = {}


def alias_pattern(a):
    if a not in _alias_re:
        p = re.escape(a)
        if a[0].isdigit():
            p = r"(?<![\d~\-])" + p + r"(?!\d|이상|미만|이하)"
        _alias_re[a] = re.compile(p)
    return _alias_re[a]


def find_terms(text, alias_map):
    """text 속 사전 말 → 표준어 (긴 말 먼저, 한 글자 별칭은 쓰지 않음)"""
    s = nospace(text)
    found = []
    for a in sorted(alias_map, key=len, reverse=True):
        if len(a) < 2:
            continue
        pat = alias_pattern(a)
        if pat.search(s):
            found.append(alias_map[a])
            s = pat.sub("\u0000", s)
    return list(dict.fromkeys(found))


# ── ① 측정 종류 · 지표 추론 ─────────────────────────────────────
COUNT_UNITS = {"명", "천명", "만명", "가구", "천가구", "호", "천호", "건", "천건", "개", "개소", "세대", "쌍", "인", "가구원"}
RATIO_UNITS = {"%", "‰", "퍼센트", "비율", "배", "%p"}
RATIO_NAME = re.compile(r"(비율|비중|구성비|율$|률$|율\(|률\(|지수|밀도|성비|당\s*\S*수|백분율|%)")
AVG_NAME = re.compile(r"(평균|중위|중앙값)")
AVG_UNITS = {"세", "년", "개월", "㎡", "명/가구", "인/가구"}
PERSON_SPECIFIC = {"출생아수", "사망자수", "이동자수", "외국인수"}
COUNTS_RATES = {"혼인건수", "이혼건수", "이동건수", "인구동태건수", "평균초혼연령", "평균재혼연령", "성비",
                "인구밀도", "부양비", "노령화지수", "합계출산율", "출산율", "사망률", "혼인율", "이혼율", "이동률", "인구성장률"}
NOT_BIRTH = re.compile(r"출생(연도|년도|지|국|시|순위|아\s*체중|코호트)")


def measure_kind(name, unit):
    """항목 하나가 무엇을 쟀는가: count(개수) | ratio(비율·지수) | average(평균) | other"""
    u, n = norm_space(unit), norm_space(name)
    if u in RATIO_UNITS or "%" in u or RATIO_NAME.search(n) or re.search(r"당$", u):
        return "ratio"
    if AVG_NAME.search(n) or u in AVG_UNITS:
        return "average"
    if u in COUNT_UNITS or not u:
        return "count"
    return "other"


def infer_indicators(title, items, target, vocab):
    """제목·항목(이름·단위·측정 종류) → [(지표, 근거)]
    개수 지표는 '그 단위의 개수 항목'이 있을 때만: 명 → 인구수(더 구체적인 사람 지표가 없을 때), 가구 → 가구수, 호 → 주택수
    단위가 비어 있는 개수 항목은 제목으로 보조 판단. 비율·평균 항목만 있는 표에는 개수 지표를 붙이지 않음"""
    t = nospace(title)
    names = [nospace(i["name"]) for i in items]
    blob = " ".join([t, *names])
    counts = [i for i in items if i["kind"] == "count"]
    has_count = bool(counts) or not items
    units = {norm_space(i["unit"]) for i in counts}
    person = bool(units & {"명", "천명", "만명", "인"}) or (("" in units or not items) and not units - {""})
    t_words = [w for w in re.split(r"[,/·및\s]+", re.sub(r"\(.*?\)", "", title)) if w]
    birth_title = t.startswith("출생") and not NOT_BIRTH.match(t)
    out = []

    def add(ind, ok, why):
        if ok:
            out.append((ind, why))

    if has_count:
        add("출생아수", person and ("출생아" in blob or birth_title or any(n.startswith("출생아") for n in names)),
            "제목·항목이 출생아(출생연도·출생지·북한출생 등 제외)")
        add("사망자수", person and ("사망자" in blob or t.startswith("사망") or any(n.startswith("사망") for n in names)),
            "제목·항목이 사망")
        add("이동자수", person and ("이동자" in blob or "이동인구" in blob or "이동" in t) and "이동건" not in blob,
            "제목·항목이 이동(사람)")
        add("이동건수", "이동건" in blob, "항목이 이동건")
        add("혼인건수", "혼인" in t and ("건" in units or "건수" in blob), "혼인 + 건")
        add("이혼건수", "이혼" in t and ("건" in units or "건수" in blob), "이혼 + 건")
        add("세대수", "세대" in units or "세대수" in blob, "단위·항목이 세대")
        add("가구수", bool(units & {"가구", "천가구"}) or (person and "1인가구" in t) or (
            not units - {""} and any(re.search(r"가구$", w) for w in t_words)),
            "개수 단위가 가구 (1인가구 표는 사람 수 = 가구 수)")
        add("주택수", bool(units & {"호", "천호"}) or (not units - {""} and "주택" in t_words), "개수 단위가 호")
    if any(i["kind"] == "average" for i in items) or "평균" in t:
        add("평균초혼연령", "초혼" in blob and "연령" in blob, "평균 + 초혼연령")
        add("평균재혼연령", "재혼" in blob and "연령" in blob, "평균 + 재혼연령")
    add("성비", "성비" in blob or any("백명당남자" in nospace(i["unit"]) for i in items), "성비")
    got = {x for x, _ in out}
    if has_count and person and not got & (PERSON_SPECIFIC | COUNTS_RATES) and \
            (units & {"명", "천명", "만명"} or "인구" in t or "인구" in target):
        out.append(("인구수", "개수 단위가 명이고 더 구체적인 사람 지표 없음"))
    seen, res = set(), []
    for ind, why in out:
        if ind in vocab and ind not in seen:
            seen.add(ind)
            res.append((ind, why))
    return res


# ── ⑤ 모집단 ──────────────────────────────────────────────────
POP_RULES = [
    (re.compile(r"(\d+)\s*세\s*이상"), lambda m: f"{m.group(1)}세 이상"),
    (re.compile(r"(\d+)\s*세\s*(이하|미만)"), lambda m: f"{m.group(1)}세 {m.group(2)}"),
    (re.compile(r"내국인"), lambda m: "내국인"),
    (re.compile(r"외국인\s*(포함|제외)"), lambda m: f"외국인 {m.group(1)}"),
    (re.compile(r"일반가구"), lambda m: "일반가구"),
    (re.compile(r"집단가구\s*(포함|제외)"), lambda m: f"집단가구 {m.group(1)}"),
    (re.compile(r"외국인가구\s*(포함|제외)"), lambda m: f"외국인가구 {m.group(1)}"),
    (re.compile(r"특별조사구[^.。]*?(포함|제외)"), lambda m: f"특별조사구 {m.group(1)}"),
    (re.compile(r"(\d+)\s*%\s*(표본|부문)"), lambda m: f"{m.group(1)}% 표본"),
]


def population(title, items, notes):
    """제목 괄호 · 합계 항목 · 짧은 표 주석 → 모집단 표현 목록 (질의 쪽 나이 표현과 같은 모양: '12세 이상')"""
    srcs = re.findall(r"\(([^()]*)\)", title) + [i["name"] for i in items[:2]] + [n for n in notes if len(n) <= 60]
    out = []
    for s in srcs:
        for rx, fmt in POP_RULES:
            for m in rx.finditer(s):
                out.append(fmt(m))
    return list(dict.fromkeys(out))


# ── ④ 주석 ────────────────────────────────────────────────────
END_RE = re.compile(r"([.。]|다|음|함|임|\))\s*$")


def merge_notes(cmmt):
    """CMMT(통계표) 줄 → 문장 단위로 이어 붙인 주석 목록. 앞이 공백으로 시작하거나 앞 줄이 끝나지 않았으면 이어 붙임"""
    out = []
    prev_open = False
    for c in cmmt or []:
        if not isinstance(c, dict) or c.get("CMMT_NM") not in ("통계표", None):
            continue
        raw = str(c.get("CMMT_DC") or "")
        txt = norm_space(raw)
        if not txt:
            continue
        if out and (prev_open or raw[:1].isspace()):
            out[-1] = f"{out[-1]} {txt}"
        else:
            out.append(txt)
        prev_open = not END_RE.search(txt)
    return list(dict.fromkeys(out))


DEF_ARROW = re.compile(r"^(.{1,40}?)\s*☞\s*(.+)$")
DEF_RAN = re.compile(r"^(?:[\-·※*]\s*)?([가-힣A-Za-z0-9·()\s]{2,20}?)(?:이|)란\s+(.+)$")


def definitions(notes, limit=6):
    """'통근·통학인구 ☞ 통근인구란 …' / '가구주란 …' → [{용어, 정의}] (정의는 150자까지)"""
    out = []
    for n in notes:
        m = DEF_ARROW.match(n)
        if m:
            term, body = m.group(1).strip(), m.group(2).strip()
        else:
            m = DEF_RAN.match(n)
            if not m:
                continue
            term, body = m.group(1).strip(), n
        if SIDO_RE.search(term) or not re.search(r"[가-힣]", term):
            continue
        out.append({"용어": term, "정의": body[:150]})
    return out[:limit]


# ── ② 지역 이름 (위 단계부터 이어 붙임) ────────────────────────────
GEO_LABEL = {0: "전국", 1: "시도", 2: "시군구", 3: "읍면동"}


def region_full_names(rows):
    """build_level_dims 의 지역 행 → (표준 전체 이름 목록, 옛 이름 {표준: 원래}, 상위 없이 남은 이름 목록)
    상위 코드가 없으면 코드 앞자리로 찾음: 앞 2자리 = 시도 코드 행, 앞 4자리 = 같은 시(구가 있는 시)"""
    rows = [dict(r) for r in rows]
    for r in rows:                       # 옛 시도 이름 ('부산직할시') 이 시군구로 판정된 경우 → 시도
        if r["geo_type"] in ("시군구", "기타") and sido_std(r["name"]) and len(str(r["code"])) <= 2:
            r["geo_type"], r["std"] = "시도", sido_std(r["name"])
    by_code = {r["code"]: r for r in rows}
    sido_rows = {r["code"][:2]: r for r in rows if r["geo_type"] == "시도"}
    city_rows = {r["code"][:4]: r for r in rows if r["geo_type"] == "시군구" and r["name"].endswith("시")
                 and len(r["code"]) >= 5}

    def parent_of(r):
        p = by_code.get(r["parent"]) if r.get("parent") else None
        if p is not None and p["geo_type"] not in ("전국", "동읍면부", "기타"):
            return p
        code = str(r["code"])
        if r["geo_type"] == "시군구" and r["name"].endswith("구") and code[:4] in city_rows \
                and city_rows[code[:4]]["code"] != code:
            return city_rows[code[:4]]
        if r["geo_type"] in ("시군구", "읍면동") and code[:2] in sido_rows:
            return sido_rows[code[:2]]
        return None

    def chain(r, seen=()):
        if r["geo_type"] == "전국":
            return "전국"
        if r["geo_type"] == "시도":
            return r["std"]
        p = parent_of(r)
        if p is None or r["code"] in seen:
            sd = SIDO_CODE.get(str(r["code"])[:2]) if r["geo_type"] != "기타" else None
            return f"{sd} {r['name']}" if sd and len(str(r["code"])) >= 5 else r["name"]
        return f"{chain(p, seen + (r['code'],))} {r['name']}"

    full, orig, bare = [], {}, []
    for r in rows:
        if r["geo_type"] in ("동읍면부", "기타"):
            continue
        n = chain(r)
        full.append(n)
        if r["geo_type"] in ("시군구", "읍면동") and " " not in n:
            bare.append(n)
        if r["geo_type"] == "시도" and r["std"] != r["name"]:
            orig[r["std"]] = r["name"]
    return list(dict.fromkeys(full)), orig, list(dict.fromkeys(bare))


def region_levels(names):
    found = sorted({min(n.count(" ") + (0 if n == "전국" else 1), 3) for n in names})
    return [GEO_LABEL[x] for x in found]
