"""
표 데이터 재정의 [1] 나누기 + [2] 사전 매핑률

목적  표마다 "조건표(지역·시점 — 정확 비교용)" 와 "카드 재료(대상·지표·축 — 검색용)" 를 나눈다
      기존 설명문에서 검색을 방해하던 지역 이름·연도·형식 찌꺼기는 카드 재료에서 뺀다

입력 (읽기만)
  private/output/meta_profiles.jsonl           이미 풀어 둔 메타 (meta_profile.py 결과)
  storage/kosis_data/meta/<기관>_<표>.json      지역 위아래 관계(parent)를 다시 계산하려고 읽음
  backend/rag/query_analyzer/dictionary/dictionary_표명.json   질의 쪽 사전 (같은 사전으로 표를 번역)

출력  table_cards/full/
  conditions.jsonl   조건표   {tbl_id, 시점, 지역, 지역_원래이름, 조사구분, 단위}
  pieces.jsonl       카드 재료 {tbl_id, 조사명, 제목, 주제, 축, 항목, 대상, 지표, 축_표준, 주석}
  unmapped.csv       사전에 없는 말 (종류, 말, 표 수, 예시 표) → 사전 보강 후보
  report.txt         매핑률 요약

실행  저장소 루트에서:  python table_cards/scripts/step1_split.py
"""
import collections
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.config import KOSIS_DATA_DIR, VIEW_OUT_DIR                                   # noqa: E402
from backend.core.utils import norm_space                                        # noqa: E402
from backend.rag.ingestion.normalize import (SIDO, SIDO_ALIAS, SIDO_CANON,        # noqa: E402
                                             build_level_dims, parse_meta, std_geo_name)

PROFILES = VIEW_OUT_DIR / "meta_profiles.jsonl"
META_DIR = KOSIS_DATA_DIR / "meta"
DICT = ROOT / "backend" / "rag" / "query_analyzer" / "dictionary" / "dictionary_표명.json"
OUT = ROOT / "table_cards" / "full"
# CARD_SET=sample 이면 입력·출력을 표본 표 폴더로 (기본은 기존 992개)
CARD_SET = os.environ.get("CARD_SET", "")
if CARD_SET == "sample":
    _base = ROOT / "table_cards" / "sample"
    PROFILES, META_DIR, OUT = _base / "out" / "meta_profiles.jsonl", ROOT / "table_cards" / "sample_meta", ROOT / "table_cards" / "sample_cards"

# 지역이 아닌 분류의 종류 → 사전의 표준 축 이름
SEX_CODE_NAMES = {"남자", "여자", "남", "여", "남성", "여성", "계", "합계", "전체", "남녀"}
KIND_AXIS = {"sex": "성별", "ages": "연령", "nationality": "국적", "cohort": "출생연도", "scenario": "추계 가정"}
SIDO_SHORT = sorted({a for a in SIDO_ALIAS if len(a) >= 2}, key=len, reverse=True)
# 앞뒤가 다른 한글로 이어지면 지역 아님 ('세대구성' 의 '대구' 는 지역이 아님)
SIDO_RE = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, SIDO_SHORT)) + r"|[가-힣]{2}직할시)(?![가-힣])")


def nospace(s):
    return re.sub(r"\s+", "", str(s or ""))


# ── 사전 ───────────────────────────────────────────────────────
def load_dict():
    d = json.loads(DICT.read_text(encoding="utf-8"))
    groups = {}
    for key, grp in [("TARGET_ALIASES", "대상"), ("INDICATOR_ALIASES", "지표"),
                     ("AXIS_ALIASES", "축"), ("MOVE_ALIASES", "이동")]:
        m = {}
        for canon, aliases in d.get(key, {}).items():
            for a in [canon, *aliases]:
                if nospace(a):
                    m[nospace(a)] = canon
        groups[grp] = m
    # 분류 값(남자·여자 …) — 대상·지표는 아니지만 사전에 있는 말 (rule_dict)
    rd = json.loads((DICT.parent / "rule_dict.json").read_text(encoding="utf-8"))
    groups["값"] = {nospace(a): canon for key in ("성별", "성별_묶음") for canon, al in rd.get(key, {}).items()
                   for a in [canon, *al] if nospace(a)}
    groups["값"].update({"남": "남자", "여": "여자"})           # 항목이 통째로 '남'/'여' 인 경우만 (아래 exact 비교)
    return groups


_alias_re = {}


def alias_pattern(a):
    """표 쪽 매칭 규칙 (질의보다 글이 길어서 더 엄격하게)
    - 숫자로 시작하는 별칭('0세','1세')은 앞에 숫자가 붙으면 안 됨('60세' 의 '0세' X), 뒤에 이상·미만·이하 X('1세이상')"""
    if a not in _alias_re:
        p = re.escape(a)
        if a[0].isdigit():
            p = r"(?<![\d~\-])" + p + r"(?!\d|이상|미만|이하)"
        _alias_re[a] = re.compile(p)
    return _alias_re[a]


def indicator_vocab():
    """붙일 수 있는 지표 = 원본 사전 지표 32개 + term_dict 의 출생아수 (쿼리 모듈이 실제로 보내는 말)"""
    d = json.loads(DICT.read_text(encoding="utf-8"))
    t = json.loads((DICT.parent / "term_dict.json").read_text(encoding="utf-8"))
    return set(d.get("INDICATOR_ALIASES", {})) | ({"출생아수"} & set(t))


# 단위·대상·글자로 지표 추론 — (조건, 지표). 위에서부터 보고, 사람 수 계열은 구체적인 것이 있으면 '인구수' 를 붙이지 않음
PERSON_SPECIFIC = {"출생아수", "사망자수", "이동자수", "외국인수"}
VOCAB = set()                              # main() 에서 indicator_vocab() 로 채움


def infer_indicators(title, items, units, target, vocab):
    """단위가 비어 있는 표가 많아서 글자로도 판단 — 단, 항목 '값' 속 글자('다문화가구 내국인(출생)', '주택 아파트')에
    끌려가지 않게 가구수·주택수는 '제목의 단어', 출생·사망은 '제목 또는 그 말로 시작하는 항목' 으로만 봄"""
    blob = nospace(" ".join([title, *items]))
    t_words = [w for w in re.split(r"[,/·및\s]+", re.sub(r"\(.*?\)", "", title)) if w]
    starts = lambda w: w in nospace(title) or any(nospace(i).startswith(w) for i in items)
    u = set(units)
    person = "명" in u or not u            # 단위가 없으면 글자로만 판단
    rules = [
        ("출생아수", starts("출생") and person and "출생지" not in blob),
        ("사망자수", starts("사망") and person),
        ("이동자수", ("이동자" in blob or "이동" in nospace(title)) and person and "이동건" not in blob),
        ("이동건수", "이동건" in blob),
        ("혼인건수", "혼인" in blob and ("건" in u or "건수" in blob or "동태" in blob)),
        ("이혼건수", "이혼" in blob and ("건" in u or "건수" in blob or "동태" in blob)),
        ("평균초혼연령", "초혼" in blob and "연령" in blob and ("세" in u or "평균" in blob)),
        ("평균재혼연령", "재혼" in blob and "연령" in blob and ("세" in u or "평균" in blob)),
        ("성비", "성비" in blob or "여자백명당남자수" in u),
        ("세대수", "세대" in u or "세대수" in blob),
        ("가구수", "가구" in u or any(re.search(r"가구$", w) for w in t_words)),       # '…가구' 로 끝나는 제목 단어
        ("주택수", "호" in u or "주택" in t_words),                                     # 제목에 '주택' 이 따로 있을 때
    ]
    out = [ind for ind, ok in rules if ok]
    counts_rates = {"혼인건수", "이혼건수", "이동건수", "인구동태건수", "평균초혼연령", "평균재혼연령"}
    if person and not (set(out) & (PERSON_SPECIFIC | counts_rates)) and \
            ("명" in u or "인구" in blob or "인구" in target):
        out.append("인구수")
    return [x for x in dict.fromkeys(out) if x in vocab]


def find_terms(text, alias_map):
    """text 안에 들어 있는 사전 말을 표준어로 (긴 말 먼저 — '1인가구' 를 찾으면 그 자리의 '가구' 는 다시 세지 않음)
    한 글자 별칭('성','대','집')은 표 쪽에서는 쓰지 않음 — '세대구성' 의 '성', '세대' 의 '대' 오매칭"""
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


# ── [1] 나누기: 잡음 지우기 ─────────────────────────────────────
YEAR_PAREN = re.compile(r"\([^()]*(\d{4}|년|연도|읍면동|시군구|시도|전국)[^()]*\)")
TAIL = re.compile(r"\s*[–\-－]\s*(읍면동|시군구|시도|전국|구시군)[^|]*$")
BRACKET = re.compile(r"\[[^\]]*\]")
UNIT_PAREN = re.compile(r"\((명|가구|호|개|%|천명|건|세|년|원|천원|만원|㎡|인|쌍|가구원|None)\)")


LEVEL = r"(?:시도|시군구|구시군|읍면동|동읍면|행정구역)"
LEVEL_SEG = re.compile(rf"{LEVEL}별?|전국")                    # '/' 로 나뉜 조각 전체가 지역 수준 단어일 때
LEVEL_HEAD = re.compile(rf"^{LEVEL}별?[\s,]+")                 # '시도별 평균초혼연령', '행정구역별, 성별 인구수'
LEVEL_TAIL = re.compile(rf"\s*[/_]\s*(?:{LEVEL}별?|전국)\s*$")  # '… 추계가구_시도', '… / 전국'


def clean_title(t):
    t = TAIL.sub("", t)
    t = YEAR_PAREN.sub("", t)
    t = SIDO_RE.sub("", t)                          # 제목의 지역 이름 → 조건표로 옮김
    t = re.sub(r"\(\s*[,\s]+", "(", t)              # 지역을 지운 자리의 쉼표 ('(, )', '(,12세이상)')
    t = re.sub(r"[,\s]+\)", ")", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"^[\s,·\-–_]+|[\s,·\-–_]+$", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # [11-11] 지역 수준 단어도 제거 — 일부 표 제목에만 있어서 검색이 치우침 (수준은 조건표의 지역이 맡음)
    before = t
    t = re.sub(r"\(구시군\)", "", t)
    t = "/".join(s.strip() for s in t.split("/") if not LEVEL_SEG.fullmatch(s.strip()))
    t = LEVEL_TAIL.sub("", t)
    t = LEVEL_HEAD.sub("", t).strip()
    return t or before                              # 제목 전체가 수준 단어면 원래대로


GENERIC_SEG = re.compile(r"^(전수|표본|기본표|전수기본표|전수부문|주요\s*지표|통계표)$")


def clean_path(path, survey):
    segs = []
    for s in str(path or "").split(">"):
        s = YEAR_PAREN.sub("", s).strip()
        s = re.sub(r"\d{4}\s*년?\s*(이후|이전)?", "", s).strip()
        s = SIDO_RE.sub("", s).strip()
        if not s or s == survey or GENERIC_SEG.match(s) or s in segs:
            continue
        segs.append(s)
    return segs


def clean_axis(obj_nm):
    n = YEAR_PAREN.sub("", obj_nm)
    n = re.sub(r"\(.*?\)", "", n)
    return re.sub(r"별$", "", n.strip()).strip()


def clean_item(name):
    n = BRACKET.sub("", name)
    n = UNIT_PAREN.sub("", n)
    n = re.sub(r"_계$|^계$", "", n)
    return n.replace("_", " ").strip()


# ── [1] 나누기: 조건표 만들기 ──────────────────────────────────
def region_names(rows):
    """build_level_dims 의 지역 행 → 위 단계부터 이어 붙인 표준 이름 ('대구광역시 수성구')"""
    by_code = {r["code"]: r for r in rows}
    full, orig = [], {}

    def chain(r, seen=()):
        if r["geo_type"] == "전국":
            return "전국"
        if r["geo_type"] == "시도":
            return r["std"]
        p = by_code.get(r["parent"])
        if p is None or r["code"] in seen or p["geo_type"] in ("전국", "동읍면부", "기타"):
            return r["std"]
        return f"{chain(p, seen + (r['code'],))} {r['name']}"

    for r in rows:
        if r["geo_type"] in ("동읍면부", "기타"):
            continue
        n = chain(r)
        full.append(n)
        if r["geo_type"] == "시도" and r["std"] != r["name"]:
            orig[r["std"]] = r["name"]               # 옛 이름 보관 (대구광역시 ← 대구직할시)
    return list(dict.fromkeys(full)), orig


NOT_REGION_AXIS = re.compile(r"항구|공항|성씨|본관|국적")     # 시도 이름이 섞여 있어도 지역 분류가 아님


def sido_std(name):
    """시도 표기 → 표준 이름 (옛 표기 포함). 시도가 아니면 None
    '부산직할시' → 부산광역시, '대전시' → 대전광역시, '광주시' → 광주광역시 (시도 목록 안에서만 쓰므로 경기 광주시와 혼동 없음)"""
    n = norm_space(name)
    n2 = re.sub(r"직할시$", "광역시", n)
    if n2 == "광주시":
        return "광주광역시"
    s = std_geo_name(n2)
    return s if s in SIDO_CANON else None


GEO_AXIS = re.compile(r"거주지|목적지|주소|전입지|전출지|통근|통학|행정구역|지역")
CITY_RE = re.compile(r"[가-힣]{1,5}[시군구]")


def title_sido(tbl_nm):
    """제목에 시도가 딱 하나면 그 표준 이름 ('…통근·통학인구(전남,12세이상)' → 전라남도)"""
    found = {SIDO_ALIAS[m] for m in SIDO_RE.findall(tbl_nm) if m in SIDO_ALIAS}
    return next(iter(found)) if len(found) == 1 else None


SIDO_CODE = {code: canon for code, canon, _ in SIDO}


def city_names(rows, home):
    """시·군·구 코드 → 위 단계부터 이어 붙인 이름. 코드 앞 2자리 = 시도, 앞 4자리가 같은 구 = 그 시의 구
    ('24010 동구' → 광주광역시 동구, '37011 남구' → 경상북도 포항시 남구)"""
    names, cur = [], None
    for r in rows:
        n, code = r["name"], str(r["code"])
        s = sido_std(n)
        if s and (len(code) <= 2 or not code[2:].strip("0")):     # 시도 행 ('36', '00000 전라남도')
            names.append(s)
            cur = None
            continue
        if r["is_total"] or not CITY_RE.fullmatch(n):
            continue
        sd = SIDO_CODE.get(code[:2]) or home
        if not sd:
            continue
        if n.endswith("구") and cur and code[:4] == cur[0][:4]:
            names.append(f"{sd} {cur[1]} {n}")
        else:
            names.append(f"{sd} {n}")
            cur = (code, n) if n.endswith("시") else None
    return list(dict.fromkeys(names))


def region_like_levels(dims, tbl_nm=""):
    """normalize.level_kind 가 지역으로 못 본 분류를 지역으로 보정 → [(obj_id, 분류 이름, 표준 지역 목록, {표준: 원래})]
    ① 시도 이름이 3개 이상 ('현거주지별', '출생지별', '전출지별' …)
    ② 한 도 전용 표에서 거주지·목적지 축의 값이 시·군 이름 3개 이상 ('목포시, 여수시 …' → '전라남도 여수시')"""
    out = []
    home = title_sido(tbl_nm)
    for info, rows in dims:
        if info["kind"] == "regions" or NOT_REGION_AXIS.search(info["obj_nm"]):
            continue
        sido = [(r["name"], sido_std(r["name"])) for r in rows if sido_std(r["name"])]
        if len(sido) < 3:
            cities = [r["name"] for r in rows if not r["is_total"] and CITY_RE.fullmatch(r["name"])]
            if (home or sido) and GEO_AXIS.search(info["obj_nm"]) and len(cities) >= 2:
                out.append((info["obj_id"], clean_axis(info["obj_nm"]), city_names(rows, home), {}))
            continue
        names = (["전국"] if any(r["is_total"] or r["name"] == "전국" for r in rows) else []) + \
            list(dict.fromkeys(s for _, s in sido))
        orig = {s: o for o, s in sido if s != o}
        out.append((info["obj_id"], clean_axis(info["obj_nm"]), names, orig))
    return out


def item_regions(items):
    """항목이 지역 목록인지 (시도 이름 3개 이상) → (역할, 표준 이름 목록, 지역인 항목 이름 집합)
    예) DT_1PB1608 항목 '1년 전 거주지 전국, 서울, 부산 …' → 역할 '1년 전 거주지'"""
    def base(n):                                      # '1년 전 거주지 : 전국-계' → '전국', '부산-구부' → '부산'
        return re.split(r"[-–]", re.sub(r"^.*[:：]\s*", "", norm_space(n)))[0].strip()

    sido = [(i["name"], sido_std(base(i["name"]))) for i in items if sido_std(base(i["name"]))]
    if len({s for _, s in sido}) < 3:
        return None, [], set()
    role, names, used = "", [], {n for n, _ in sido}
    for i in items:                                   # 전국 항목 → 앞부분이 역할 ('1년 전 거주지 전국', '1년 전 거주지 : 전국-계')
        m = re.match(r"^(.*?)\s*[:：]?\s*전국(?:[-–].*)?$", norm_space(i["name"]))
        if m:
            used = used | {i["name"]}
            role = role or m.group(1).strip(" _-:：")
            if "전국" not in names:
                names.append("전국")
    names += list(dict.fromkeys(s for _, s in sido))
    return role or "항목", names, used


def conditions(p, levels_dims, items):
    reg = [rows for info, rows in levels_dims if info["kind"] == "regions"]
    like = region_like_levels(levels_dims, p["tbl_nm"])  # [NEW] 지역인데 '기타' 로 판정된 분류
    role2, names2, _ = item_regions(items)
    src = "분류"
    if reg:
        names, orig = region_names(reg[0])
        if like and not names2:                          # 지역 분류 + 지역 같은 분류 → 두 번째 지역
            role2, names2 = like[0][1], like[0][2]
    elif like:
        _, _, names, orig = like[0]
        src = f"분류({like[0][1]}, 지역 판정 보정)"
        if len(like) > 1 and not names2:
            role2, names2 = like[1][1], like[1][2]
            orig = {**orig, **like[1][3]}
    else:
        item_sido = names2
        title_sido = [SIDO_ALIAS[m] for m in SIDO_RE.findall(p["tbl_nm"]) if m in SIDO_ALIAS]
        if len(item_sido) >= 3:                       # 항목이 지역인 표
            names, orig, src = item_sido, {}, "항목"
            role2, names2 = None, []
        elif title_sido:                              # 그 지역 전용 표 (DT_1IN0001_22 대구광역시)
            names, orig, src = list(dict.fromkeys(title_sido)), {}, "제목"
        else:
            names, orig, src = ["전국"], {}, "없음(전국으로 봄)"
    return {"tbl_id": p["tbl_id"], "org_id": p["org_id"],
            "시점": [{"주기": x["se_raw"], "시작": x["year_from"], "끝": x["year_to"]} for x in p["periods"]],
            "지역": names, "지역_출처": src, "지역_원래이름": orig,
            "지역2": {"역할": role2, "이름": names2} if names2 else None,     # 항목에 숨은 두 번째 지역 (전출지 등)
            "조사구분": p.get("survey_type"), "단위": p.get("units") or []}


# ── 실행 ───────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    D = load_dict()
    global VOCAB
    VOCAB = indicator_vocab()
    profs = [json.loads(l) for l in PROFILES.open(encoding="utf-8")]

    unmapped = collections.defaultdict(lambda: [0, ""])   # (종류, 말) → [표 수, 예시 표]
    stat = collections.Counter()
    leak = []
    conds, pieces = [], []

    for p in profs:
        mp = META_DIR / f"{p['org_id']}_{p['tbl_id']}.json"
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        levels, items = parse_meta(meta)
        dims = [build_level_dims(i + 1, l) for i, l in enumerate(levels)]

        c = conditions(p, dims, items)
        conds.append(c)

        title = clean_title(p["tbl_nm"])
        topic = clean_path(p.get("path"), p.get("survey_nm"))
        axes_raw = []
        like_ids = {oid for oid, _, _, _ in region_like_levels(dims, p["tbl_nm"])}
        for info, rows in dims:
            if info["kind"] == "regions":
                continue
            kind = info["kind"]
            if info["obj_id"] in like_ids:               # [NEW] 지역 같은 분류: 축 이름만 남기고 값(지역 이름)은 조건표로
                axes_raw.append((clean_axis(info["obj_nm"]), "regions_like", info["role"], []))
                continue
            # normalize.level_kind 의 SEX_RE('성별$') 가 '특성별'·'세대구성별' 을 성별로 판정하는 문제 우회:
            # 코드 값(합계 제외)이 실제로 남자·여자일 때만 성별로 인정
            if kind == "sex" and not {r["name"] for r in rows if not r["is_total"]} <= SEX_CODE_NAMES:
                kind = "other"
            vals = list(dict.fromkeys(r["name"] for r in rows if not r["is_total"]))
            axes_raw.append((clean_axis(info["obj_nm"]), kind, info["role"], vals))
        _, _, region_items = item_regions(items)
        item_names = list(dict.fromkeys(x for x in (clean_item(i["name"]) for i in items
                                                    if i["name"] not in region_items) if x))
        if c["지역2"]:                                   # 지역 항목 대신 역할 이름만 남김 ('1년 전 거주지')
            item_names = [c["지역2"]["역할"], *item_names]

        # [2] 사전으로 표준어 찾기
        small_vals = [v for _, k, _, vals in axes_raw if k not in ("ages", "cohort") and len(vals) <= 40 for v in vals]
        body = " ".join([title, *item_names, *[a for a, _, _, _ in axes_raw]])
        # 대상: 제목·항목 + 분류 값(작은 분류만 — '1인가구', '내국인' 같은 값이 대상인 경우)
        target = find_terms(f"{title} {' '.join(item_names)} {' '.join(small_vals)}", D["대상"])
        if "가구" in title and any(re.fullmatch(r"1\s*인(\s*가구)?", v) for v in [*small_vals, *item_names]) \
                and "1인가구" not in target:
            target.append("1인가구")                      # 가구원수 값 '1인' → 1인가구 (사전 별칭으로는 못 잡는 형태)
        indic = find_terms(" ".join([title, *item_names]), D["지표"])     # [11-10] 제목도 봄 ('시도/일반혼인율')
        # [NEW 11-10] 사전 이름이 항목에 그대로 없으면 단위·대상·글자로 추론 (쿼리 모듈 filters.지표 와 맞추려고)
        indic_inferred = [x for x in infer_indicators(title, item_names, c["단위"], target, VOCAB) if x not in indic]
        indic = indic + indic_inferred
        move = find_terms(body, D["이동"])
        axes_std = []
        for a, kind, role, vals in axes_raw:
            std = KIND_AXIS.get(kind) or D["축"].get(nospace(a)) or (find_terms(a, D["축"]) or [None])[0]
            if std is None and kind == "sex":
                std = "성별"
            axes_std.append({"원래": a, "표준": std, "역할": role, "값_수": len(vals),
                             "값": [v for v in vals if not SIDO_RE.search(v)][:20]})
            if std is None:
                k = ("축", a)
                unmapped[k][0] += 1
                unmapped[k][1] = unmapped[k][1] or p["tbl_id"]
        mapped_item = lambda n: bool(find_terms(n, {**D["지표"], **D["대상"], **D["이동"], **D["값"]})
                                     or nospace(n) in D["값"])
        for n in item_names:
            if not mapped_item(n):
                k = ("항목", n)
                unmapped[k][0] += 1
                unmapped[k][1] = unmapped[k][1] or p["tbl_id"]
        if not (target or indic or move):
            k = ("제목(대상·지표·이동 모두 못 찾음)", title)
            unmapped[k][0] += 1
            unmapped[k][1] = unmapped[k][1] or p["tbl_id"]

        stat["표"] += 1
        stat["대상 1개 이상"] += bool(target)
        stat["대상·지표·이동 중 하나"] += bool(target or indic or move)
        stat["지표 1개 이상"] += bool(indic)
        stat["축 전체"] += len(axes_std)
        stat["축 매핑"] += sum(a["표준"] is not None for a in axes_std)
        stat["항목 전체"] += len(item_names)
        stat["항목 매핑"] += sum(mapped_item(n) for n in item_names)
        stat[f"지역출처:{c['지역_출처'].split('(')[0] + ('(보정)' if '보정' in c['지역_출처'] else '')}"] += 1
        stat["옛 지역 이름 있는 표"] += bool(c["지역_원래이름"])
        stat["지역2 있는 표"] += bool(c["지역2"])

        # 누출 검사: 카드 재료 전체(제목·주제·항목·축 이름·축 값)에 시도 이름이 남았는지 — 옛 표기·'광주시' 포함
        piece_words = [title, *topic, *item_names, *[a["원래"] for a in axes_std],
                       *[v for a in axes_std for v in a["값"]]]
        left = sorted({w for w in re.findall(r"[가-힣]+", " ".join(piece_words)) if sido_std(w)} |
                      set(SIDO_RE.findall(" ".join(piece_words))))
        if left:
            leak.append((p["tbl_id"], left[:5]))

        pieces.append({"tbl_id": p["tbl_id"], "조사명": p.get("survey_nm"), "제목": title, "제목_원래": p["tbl_nm"],
                       "주제": topic, "축": axes_std, "항목": item_names[:60], "항목_수": len(item_names),
                       "대상": target, "지표": indic, "지표_추론": indic_inferred, "이동": move,
                       "주석": p.get("notes") or []})

    with (OUT / "conditions.jsonl").open("w", encoding="utf-8") as f:
        for c in conds:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (OUT / "pieces.jsonl").open("w", encoding="utf-8") as f:
        for x in pieces:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with (OUT / "unmapped.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["종류", "말", "표_수", "예시_표"])
        for (kind, word), (n, ex) in sorted(unmapped.items(), key=lambda x: (x[0][0], -x[1][0])):
            w.writerow([kind, word, n, ex])

    n = stat["표"]
    pct = lambda a, b: f"{a}/{b} ({a / b * 100:.0f}%)" if b else "0"
    lines = [
        f"표 {n}개",
        f"대상 1개 이상 찾은 표 : {pct(stat['대상 1개 이상'], n)}",
        f"지표 1개 이상 찾은 표 : {pct(stat['지표 1개 이상'], n)}",
        f"대상·지표·이동 중 하나라도 : {pct(stat['대상·지표·이동 중 하나'], n)}",
        f"축(분류) 매핑         : {pct(stat['축 매핑'], stat['축 전체'])}",
        f"항목 매핑             : {pct(stat['항목 매핑'], stat['항목 전체'])}",
        "지역 출처             : " + ", ".join(f"{k.split(':')[1]} {v}" for k, v in stat.items() if k.startswith("지역출처:")),
        f"시도 표기 다른 표     : {stat['옛 지역 이름 있는 표']}  (대구직할시·강원도·서울 → 표준 이름으로 바꿈)",
        f"항목에 두 번째 지역   : {stat['지역2 있는 표']}  (전출지·1년 전 거주지 등 → 조건표 지역2)",
        f"카드 재료에 지역 이름 남음 : {len(leak)}개 표",
        *[f"   {t} {w}" for t, w in leak[:15]],
        f"사전에 없는 말 (종류별 개수): " + ", ".join(
            f"{k} {v}" for k, v in collections.Counter(k for k, _ in unmapped).items()),
    ]
    (OUT / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
