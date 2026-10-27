"""
kosis_rag_qa.apply_conditions 개선판 (실험용, 베이스라인 미수정)

베이스라인은 지역·성별·연도만 좌표에 적용하고, 그 밖의 분류 조건은 경고 없이 무시한다 (G-2).
여기서는 베이스라인을 그대로 감싼 뒤 나머지 분류를 처리한다.
  1. "1985년생"을 가려서 넘긴다 → 년생이 시점으로 잡히지 않음 (R-2)
  2. 베이스라인 실행 (지역·성별·연도)
  3. 나머지 분류: 질문에 코드 이름이 있으면 좌표에 적용, 그 분류로 보이는 말이 있는데 못 맞추면 missing,
     언급이 없는데 뷰가 합계 아닌 코드로 고정돼 있으면 missing 에 주의 (B-6)

사용: e2e_eval.py / diagnose.py 의 --conditions v2 (qa.apply_conditions 를 바꿔 끼움)
"""
import copy
import re

from profiling import baseline  # noqa: F401  (저장소 루트를 sys.path 에 추가)
from profiling import config
import kosis_rag_qa as qa  # noqa: E402

qa.VIEWS_DIR = config.VIEWS_DIR
BASE_APPLY = qa.apply_conditions          # 바꿔 끼우기 전에 원본을 잡아 둔다 (재귀 방지)

HANDLED_KINDS = {"geo", "sex"}            # 베이스라인이 처리하는 분류
YEAR_NAME = re.compile(r"^(19|20)\d{2}$")
BIRTH_YEAR = re.compile(r"(?:19|20)\d{2}\s*년?생")
ALIASES = {"첫째": "1아", "둘째": "2아", "셋째": "3아이상", "셋째이상": "3아이상"}   # 질문어 → 정규화된 코드명
HINTS = {                                  # 이 분류를 묻는 것으로 보이는 표현 (못 맞추면 missing)
    "age": re.compile(r"\d+\s*(?:세|살)"),
    "year": re.compile(r"(?:19|20)\d{2}\s*년?생"),
    "order": re.compile(r"(?:첫|둘|셋|넷)째"),
}


def norm(s, strip_paren=False):
    s = str(s)
    if strip_paren:
        s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"[\s·,]", "", s.replace("~", "-").replace("∼", "-"))


def is_year_level(lv):
    names = [c["name"] for c in lv["codes"] if not c["is_total"]]
    return len(names) >= 3 and sum(bool(YEAR_NAME.match(n)) for n in names) >= 0.6 * len(names)


def hint_kind(lv):
    if is_year_level(lv):
        return "year"
    if lv["kind"] == "age":
        return "age"
    if any(norm(c["name"]) in ALIASES.values() for c in lv["codes"]):
        return "order"
    return None


def match_codes(lv, nq):
    """정규화된 질문 nq 에 나온 이 분류의 코드 (합계 제외, 가장 긴 이름 우선)"""
    year = is_year_level(lv)
    alias_targets = {t for w, t in ALIASES.items() if w in nq}
    hits = []
    for c in lv["codes"]:
        if c["is_total"]:
            continue
        n = norm(c["name"], strip_paren=True)
        if year:
            ok = bool(re.search(rf"{n}년?생", nq))
        elif len(n) < 2:
            ok = False
        else:
            ok = bool(re.search(rf"(?<!\d){re.escape(n)}", nq)) or n in alias_targets
        if ok:
            hits.append((n, c))
    hits = [(n, c) for n, c in hits if not any(n != m and n in m for m, _ in hits)]
    return [c for _, c in hits]


def apply_conditions_v2(rec, question):
    src, applied, missing = BASE_APPLY(rec, BIRTH_YEAR.sub("[년생]", question))
    prof = qa._profile(src.get("table_key", ""))
    if not prof:
        return src, applied, missing
    src, applied, missing = copy.deepcopy(src), dict(applied), list(missing)
    nq = norm(question)
    for lv in prof["levels"]:
        if lv["kind"] in HANDLED_KINDS or lv["n_codes"] < 2:
            continue
        key = f"c{lv['level']}"
        hits = match_codes(lv, nq)
        if hits:
            src["dims"][key] = {"codes": [c["code"] for c in hits]}
            applied[lv["obj_nm"]] = [c["name"] for c in hits]
            continue
        hk = hint_kind(lv)
        tok = HINTS[hk].search(question) if hk else None
        if tok:
            missing.append(f"{lv['obj_nm']}: 질문의 '{tok.group(0)}'에 맞는 분류값 없음")
            continue
        fixed = (src["dims"].get(key) or {}).get("codes") or []
        if len(fixed) == 1 and fixed[0] != lv["total_code"]:
            name = next((c["name"] for c in lv["codes"] if c["code"] == fixed[0]), fixed[0])
            missing.append(f"{lv['obj_nm']}: 이 자료는 '{name}'(으)로 고정됨 (질문 대상과 다를 수 있음)")
    return src, applied, missing
