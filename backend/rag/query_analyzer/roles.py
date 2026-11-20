"""
역할 분해 — 비율·조건 질문에서 '분모' 와 '조건' 을 원문 규칙으로 찾아 검색 단위로 더한다

왜   복합 질문의 Groups@5 실패는 대부분 두 번째 표(분모의 인구 표, 조건을 거는 표)를 못 찾은 경우였다.
     지표별 분리는 '인구'·'인구 인구수' 같은 뜻 없는 하위 질의를 만들고, 그 단위는 본 질의를 다시 찾았다.

  분모   'X 중 … 비율/퍼센트/차지'  'X(으)로 나눈'  '인구 천 명당'  → X
  조건   'X(의 수)가 N명 이상/이하/초과/미만'                        → X   (이 X 로 지역을 고르는 표)

  찾은 말이 이미 다른 검색 단위에 들어 있으면 더하지 않는다. 더하는 단위의 filters 에 '역할' (분모|조건) 을 붙여
  검색(backend.rag.search.engine)이 분모 단위를 '같은 조사·연도·수준의 단순한 인구·가구 표' 로 찾게 한다.
"""
import re

from backend.rag.csv_index.store import norm

UNIT = r"(?:명/㎢|명|가구|건|호|세대|개|%|퍼센트|㎡|원)"
COND_RE = re.compile(rf"(?:가|이)\s*(?:기준값\s*|특정\s*수치\s*)?(\d[\d,\.]*)\s*({UNIT})?\s*(이상|이하|초과|미만|보다\s*(?:많|적|크|작))")
# 조건이 '지역을 고르는' 기준인가 ('99,000명 이상인 지역에서') — 아니면 분류 값 기준일 수 있음 ('가구원수가 5명 이상인 가구')
REGION_PICK_RE = re.compile(r"^\s*(?:인|한|된|이\s*되는|을\s*넘는|를\s*넘는)?\s*(?:지역|곳|시도|시군구|읍면동|행정구역|도시|시|군|구)")
CMP_OP = {"이상": ">=", "이하": "<=", "초과": ">", "미만": "<"}
PER_RE = re.compile(r"(?:(인구|주민|가구)\s*)?(?:천|1,?000|만|10,?000|백|100)\s*(명|가구|호)\s*(?:당|을\s*기준|기준)")
DIV_RE = re.compile(r"([가-힣][가-힣\s]{0,20}?)(?:으로|로)\s*나[눈누]")
SHARE_RE = re.compile(r"(?:비율|퍼센트|%|비중|차지|구성비|몇\s*할)")
AMONG_RE = re.compile(r"([가-힣][가-힣\s]{0,24}?)\s*(?:중에서|중에|가운데|중)(?=\s|$)")
# 고르는 범위('지역 중'·'시군구 중')이지 분모가 아닌 말
NOT_DEN = {"지역", "지역들", "시도", "시군구", "읍면동", "곳", "곳들", "행정구역", "그", "이", "연도", "해", "기간", "도시",
           "사람들", "그중", "이들", "것", "것들"}
STOP_TOKEN = re.compile(r"\d|^년|(?:년|년에|년도|별로|별|에서|에는|에서는|에서의|중에서|중|따르면|이상의|이하의|미만의|초과의|"
                        r"이상인|이하인|미만인|초과인|있는|사는|하는|되는|나눈|대비|비해|보면|결과를|결과|따른|따르면|대상으로)$|[,.?!]$")
SEX_WORDS = {"남자", "여자", "남성", "여성", "남", "여", "남녀"}
LEAD_DROP = re.compile(r"^(?:전체|총|모든|우리나라|전국의?)$")


def _phrase(before, max_tokens=3, lex=None):
    """앞 문장의 끝에서 거꾸로 낱말을 모아 명사구 (숫자·'…별로'·'…에서' 같은 낱말에서 멈춤)"""
    toks = str(before or "").split()
    out = []
    for t in reversed(toks):
        if STOP_TOKEN.search(t) or len(out) >= max_tokens:
            break
        out.append(re.sub(r"(?:들)?(?:의|은|는|이|가|을|를)$", "", t) or t)
    out = list(reversed(out))
    while out and LEAD_DROP.match(out[0]):
        out = out[1:]
    out = [t for t in out if not _is_region(t, lex)]  # 지역 이름은 지역 슬롯이 맡음 ('동두천시 인구' → '인구')
    return " ".join(out)


def _is_region(tok, lex):
    try:
        from backend.rag.query_analyzer.analyze import region_shaped
        if region_shaped(tok) or tok in ("동부", "읍부", "면부"):
            return True
        return lex is not None and bool(lex.idx.find(tok, slots=("지역",), scope="all", variant=False))
    except Exception:  # noqa: BLE001
        return False


def find_thresholds(question, lex=None):
    """'X(의 수)가 N명 이상' → [{"말": X, "값": 99000, "표기": "99,000명 이상", "단위", "비교", "op", "지역_고르기"}]
    재작성 검증이 숫자 조각('99,000')을 조건 칸에서 빼고, 이 구조로 남김 (재작성 문장 · 분석 결과 state.thresholds)"""
    q = str(question or "")
    out = []
    for m in COND_RE.finditer(q):
        p = _phrase(q[:m.start()], lex=lex)
        if len(norm(p)) < 2:
            continue
        word = re.sub(r"\s+", "", m.group(3))
        cmp_ = {"보다많": "초과", "보다크": "초과", "보다적": "미만", "보다작": "미만"}.get(word, word)
        num = m.group(1).replace(",", "")
        try:
            val = float(num) if "." in num else int(num)
        except ValueError:
            continue
        out.append({"말": p, "값": val, "단위": m.group(2) or "", "비교": cmp_, "op": CMP_OP.get(cmp_, cmp_),
                    "표기": f"{m.group(1)}{m.group(2) or ''} {cmp_}",
                    "지역_고르기": bool(REGION_PICK_RE.match(q[m.end():]))})
    return out


def share_denominator(question, lex=None):
    """'X 중 … 비율·비중·차지' 의 X (구성비의 전체). 없으면 None"""
    q = str(question or "")
    if not SHARE_RE.search(q):
        return None
    cands = []
    for m in AMONG_RE.finditer(q):
        p = _phrase(m.group(1), lex=lex)
        head = p.split()[-1] if p else ""
        nxt = (q[m.end():].split() or [""])[0]
        # 'X 중 계의'(합계 행) · 'X 중 영암군의'(지역 고르기) · 'X 비율 중'(비율은 분모가 아님) · 성별은 분모가 아님
        if re.match(r"(?:계|합계|총계|소계|전체)(?:의|는|가|$)", nxt) or _is_region(re.sub(r"(?:의|에서|은|는)$", "", nxt), lex):
            continue
        if re.search(r"(?:비율|현황|율|률|구성비|비중|별)$", head) or norm(p) in SEX_WORDS:
            continue
        if len(norm(p)) >= 2 and head not in NOT_DEN:
            cands.append((("전체" in m.group(1)) or ("총" in m.group(1)), p))
    return sorted(cands, key=lambda x: not x[0])[0][1] if cands else None


# 'X 중 Y가 차지하는 비율' 의 Y (구성비의 부분)
SHARE_PART_RE = re.compile(r"(?:중에서|중에|가운데|중)\s+([가-힣][가-힣\s]{0,20}?)\s*(?:이|가)\s*차지하는\s*(?:비율|비중|구성비|몫)")


def share_part(question):
    m = SHARE_PART_RE.search(str(question or ""))
    return m.group(1).strip() if m else None


def find_roles(question, lex=None):
    """→ [(역할, 말)] 분모·조건 (순서대로, 중복 없이)"""
    q = str(question or "")
    out = [("조건", t["말"]) for t in find_thresholds(q, lex)]
    m = PER_RE.search(q)
    if m:
        out.append(("분모", "가구" if m.group(1) == "가구" else "인구"))
    for m in DIV_RE.finditer(q):
        p = _phrase(m.group(1), lex=lex)
        if len(norm(p)) >= 2:
            out.append(("분모", p))
    den = share_denominator(q, lex)
    if den:
        out.append(("분모", den))
    from backend.rag.search.engine import DEN_BASE
    seen, uniq = set(), []
    for r, p in out:
        k = norm(p)
        base = ("분모", DEN_BASE[k]) if r == "분모" and k in DEN_BASE else None  # '인구'·'총인구' 는 같은 분모
        if k not in seen and (base is None or base not in seen):
            seen.add(k)
            if base:
                seen.add(base)
            uniq.append((r, p))
    return uniq


GENERIC_TAIL = {"수", "건수", "인구수", "가구수", "명수", "호수", "규모", "총수"}


def covered_by(phrase, texts):
    """말의 내용 낱말이 이미 어떤 단위 문장에 모두 들어 있는가"""
    keys = [norm(t) for t in phrase.split() if norm(t) and norm(t) not in GENERIC_TAIL]
    if not keys:
        keys = [norm(phrase)]
    return any(all(k in norm(t) for k in keys) for t in texts)


def _plain(phrase, f):
    """단위 filters 가 '그 말뿐' 인가 — 조건(분류 값)이 더 붙어 있으면 분모·조건 단위로 볼 수 없음
    ('보증부월세 일반가구' 단위는 '일반가구' 를 문장에 담았지만 부분(보증부월세)을 센 단위)"""
    return not (f or {}).get("조건")


def add_role_units(question, vb, lex=None, max_units=4):
    """view_bundle 에 분모·조건 검색 단위를 더함 (제자리 수정) → 더한 [(역할, 말)]
    이미 있는 단위가 그 말을 담았어도, 그 단위에 조건(분류 값)이 더 붙어 있으면 덮였다고 보지 않고 역할 단위를 더함"""
    roles = find_roles(question, lex)
    if not roles or vb.get("filters") is None:
        return []
    subs = list(vb.get("sub_questions") or [])
    sfs = list(vb.get("sub_filters") or [None] * len(subs))
    base_f = {k: v for k, v in (vb.get("filters") or {}).items() if k not in ("대상", "지표", "원문표현", "조건", "역할")}
    own = [t for t, f in zip(subs, sfs) if _plain(t, f)]  # 재작성·분리 단계가 만든 단위 (+ 여기서 더한 말)
    added = []
    for role, p in roles:
        if covered_by(p, own):
            continue
        if not subs:  # 본 질의가 건너뛰어지지 않게 (views.run_query skip_main) 첫 단위로
            subs.append(vb.get("search_text") or question)
            sfs.append(dict(vb.get("filters") or {}))
        if len(subs) >= max_units:
            break
        subs.append(p)
        sfs.append({**base_f, "지표": [p], "역할": role})
        own.append(p)
        added.append((role, p))
    if added:
        vb["sub_questions"], vb["sub_filters"] = subs, sfs
    return added
