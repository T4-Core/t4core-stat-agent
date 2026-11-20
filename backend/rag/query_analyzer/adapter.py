"""
재작성 슬롯(문자열) → View 입력 슬롯 (view_bundle)

  재작성 (RewriteBundle)                            View 입력 (schemas.query.QueryBundle)
  ─────────────────────────────────────────────    ──────────────────────────────────────────
  filters.시점  ['2024년', '2024년 9월']            시점 [2024]          (월은 연도로, notes 에 기록)
  filters.지역  ['전국']                            (지역 없음)           (전국만 물으면 View 기본값 = 전국 합계)
  filters.지역  ['전국', '서울특별시']              지역 ['전국', '서울특별시']  (다른 지역과 함께면 전국 합계 행도 조회)
  filters.연령  ['20~24세', '25~29세']              연령 {from:20, to:29} (values.parse_ages 로 병합)
  filters.대상  ['고령자']  (노인 → 고령자)          대상 ['인구'] + 연령 {from:65, to:null}  (AGE_TARGETS, 연령이 비었을 때만)
  filters.비교축 ['시도']                           비교축 '시도'
  intent (의도 9종)                                 의도 4종 (VIEW_INTENT: 증감·증감률 → 추이, 구성비 → 비교, 합계 → 값 조회)
  sub_filters[i] (하위 질문마다 의도 하나)           sub_filters[i].의도 = 그 하위 질문의 의도 (sub_intents)
  intent '범위 밖' (통계 수치를 묻지 않는 질문)      filters None + notes '[의도] 범위 밖' → 검색하지 않음
  filters.전출지·전입지·이동                        (View 슬롯 없음 → notes)
  rewritten '2025년 전국 1인가구 가구수'            rewritten 그대로 + search_text (검색 문장)
"""
import re
import uuid
from dataclasses import asdict, is_dataclass

from backend.rag.ingestion.normalize import std_geo_name

from .sentence import INTENT_WORD, slots_to_sentence
from .slots import INTENTS
from .values import parse_ages

# 의도 9종 → View 가 아는 4종 (증감률 → 추이, 합계·범위 밖 → 값 조회 추가)
VIEW_INTENT = {"값 조회": "값 조회", "추이": "추이", "비교": "비교", "순위": "순위", "구성비": "비교", "증감": "추이",
               "증감률": "추이", "합계": "값 조회", "범위 밖": "값 조회"}
VIEW_INTENTS = ("값 조회", "추이", "비교", "순위")  # View 모듈(build_view.VIEW_TYPE)이 아는 의도
OUT_OF_SCOPE = "범위 밖"
UNSUPPORTED = ("전출지", "전입지", "이동")
COHORT_COND_RE = re.compile(r"출생연도\s*=\s*((?:19|20)\d{2})(?:\s*~\s*((?:19|20)\d{2}))?")
# [NEW 11-20] '열 연산자 값' 형식의 조건. 연산자 없는 문자열('보증부월세')은 열 없는 '=' 조건이다
COND_EXPR_RE = re.compile(r"^\s*([^<>=!]*?)\s*(>=|<=|!=|>|<|=)\s*(.+?)\s*$")
NUM_UNIT_RE = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)\s*([^\d\s].*)?$")
CMP_OPS = (">", ">=", "<", "<=")
TIME_RE = re.compile(r"^((?:19|20)\d{2})\s*년?(?:\s*(\d{1,2})\s*월)?$")
# 용어 사전은 연령이 뜻에 들어 있는 말을 대상 용어로 바꾼다 ('노인' → '고령자'). View 모듈은 연령 분류로
# 표를 자르므로 연령으로 풀어 준다. 정의가 법·조사마다 다른 말(청년·아동·청소년)은 넣지 않음 (HCX 가 연령을 채울 때만 씀)
AGE_TARGETS = {"고령자": "65세 이상", "영유아": "0~5세", "유소년인구": "0~14세", "생산연령인구": "15~64세"}
_WORD_INTENT = {w: k for k, w in INTENT_WORD.items() if w}  # '순위' → '순위' (하위 문장 끝 의도어 → 의도)

assert set(VIEW_INTENT) == set(INTENTS), "slots.INTENTS 와 VIEW_INTENT 가 다름 (의도를 추가했으면 여기도)"


def _as_dict(b):
    if is_dataclass(b):
        return asdict(b)
    if hasattr(b, "model_dump"):
        return b.model_dump()
    return dict(b)


def _intents(intent):
    """의도 → 목록 (원 질문 의도는 검증 슬롯에서 목록, RewriteBundle.intent 는 문자열 하나)"""
    return [intent] if isinstance(intent, str) else [x for x in (intent or []) if x]


def is_out_of_scope(bundle):
    """재작성 결과가 '범위 밖'(통계 수치를 묻지 않는 질문)인가"""
    b = _as_dict(bundle) if bundle is not None else {}
    return OUT_OF_SCOPE in _intents(b.get("intent"))


def sub_intents_of(valid):
    """run_pipeline() 결과의 valid(검증 결과) → 하위 질문 의도 목록 (QueryBundle.sub_questions 와 같은 순서)
    make_bundle 과 같은 기준으로 문장이 빈 하위 슬롯은 뺀다"""
    return [s.get("의도") for s in (valid or {}).get("sub_slots", []) if slots_to_sentence(s)]


def _intent_from_sentence(text):
    """하위 질문 문장 끝 의도어 → 의도 ('2023년 충청남도 고령인구비율 시군구별 순위' → '순위'). 없으면 None
    sentence.slots_to_sentence 가 끝에 붙인 말이라 값 조회·구성비·범위 밖은 되살릴 수 없음"""
    words = str(text or "").split()
    return _WORD_INTENT.get(words[-1]) if words else None


def resolve_sub_intents(bundle, sub_intents=None):
    """하위 질문마다 의도 하나 (의도 9종 값). 순서: 넘겨받은 sub_intents → 하위 문장 끝 의도어 → 원 질문 의도"""
    b = _as_dict(bundle)
    given, subs = list(sub_intents or []), list(b.get("sub_questions") or [])
    main = next(iter(_intents(b.get("intent"))), None)
    return [(given[i] if i < len(given) else None) or _intent_from_sentence(subs[i] if i < len(subs) else "") or main
            for i in range(len(b.get("sub_filters") or []))]


def parse_condition(text):
    """조건 문자열 → Condition dict. '혼인상태=미혼' · '가구원수>=5' · '가구원수 >= 99,000명' · '보증부월세'(열·연산자 없음)"""
    t = str(text).strip()
    m = COND_EXPR_RE.match(t)
    if not m:
        return {"field": None, "op": "=", "value": t, "unit": None, "text": t, "source": "slot"}
    field, op, value = m[1].strip() or None, m[2], m[3].strip()
    unit = None
    if op in CMP_OPS:
        n = NUM_UNIT_RE.match(value)
        if n:
            value, unit = n[1].replace(",", ""), (n[2] or "").strip() or None
    return {"field": field, "op": op, "value": value, "unit": unit, "text": t, "source": "slot"}


def threshold_conditions(thresholds):
    """분석 state 의 thresholds([{말, 값, 단위, op, 표기}]) → Condition dict 목록. 비교 연산이 아닌 것은 건너뛴다"""
    out = []
    for t in thresholds or []:
        if t.get("op") not in CMP_OPS or t.get("값") is None:
            continue
        out.append({"field": t.get("말") or None, "op": t["op"], "value": str(t["값"]), "unit": t.get("단위") or None,
                    "text": f"{t.get('말', '')} {t.get('표기', '')}".strip(), "source": "threshold"})
    return out


def to_view_filters(f, intent=None, notes=None, label=""):
    """재작성 filters(dict[str, list[str]]) + intent → View 모듈 Filters(dict). 둘 다 비면 None"""
    notes = notes if notes is not None else []
    tag = f"({label}) " if label else ""
    f = f or {}
    if not f and not intent:
        return None
    out = {}
    years = []
    for v in f.get("시점") or []:
        m = TIME_RE.match(str(v).strip())
        if not m:
            notes.append(f"{tag}[시점] View 모듈이 읽을 수 없는 값: '{v}'")
            continue
        years.append(int(m[1]))
        if m[2]:
            notes.append(f"{tag}[시점] '{v}' → {m[1]} (View 모듈은 연도 단위)")
    if years:
        out["시점"] = sorted(set(years))
    regions = list(dict.fromkeys(std_geo_name(r) for r in f.get("지역") or []))
    if "전국" in regions:
        if regions == ["전국"]:      # 전국만 → 지역을 비워 View 기본값(전국 합계)으로
            regions = []
        else:                        # 전국과 다른 지역을 함께 → 전국 합계 행도 같이 조회 ('전국과 서울 비교')
            notes.append(f"{tag}[지역] '전국'과 다른 지역을 함께 물음 → 전국 합계 행도 같이 조회")
    if regions:
        out["지역"] = regions
    for k in ("대상", "성별", "지표"):
        if f.get(k):
            out[k] = list(f[k])
    ages = list(f.get("연령") or [])
    age_terms = [t for t in out.get("대상", []) if t in AGE_TARGETS]
    if age_terms:  # '고령자' → 대상 '인구' + 연령 65세 이상
        out["대상"] = list(dict.fromkeys("인구" if t in AGE_TARGETS else t for t in out["대상"]))
        if not ages:
            ages = [AGE_TARGETS[age_terms[0]]]
        notes.append(f"{tag}[대상] {age_terms} → 대상 '인구' + 연령 {ages} (View 모듈은 연령 분류로 자름)")
    if ages:
        age = parse_ages(ages, notes)
        if age:
            out["연령"] = age
    # 조건·국적·원문표현 → View 의 보조 단어. '출생연도=1983년생' 은 출생연도(코호트) 분류를 자르는 값으로
    conds, cohort, exprs = [], [], []
    for c in f.get("조건") or []:
        m = COHORT_COND_RE.search(str(c))
        if m:
            a, b = int(m[1]), int(m[2] or m[1])
            cohort += list(range(a, b + 1)) if 0 <= b - a <= 60 else [a]
            continue
        expr = parse_condition(c)
        exprs.append(expr)
        # [CHANGED 11-20] 이전: '=' 가 있으면 오른쪽만 남겼다 → '가구원수>=5' 가 검색어 '5' 가 됐다. 비교 연산은 검색어로 쓰지 않는다 (조건식 으로만)
        if expr["op"] in ("=", "!="):
            conds.append(expr["value"])
    if cohort:
        out["출생연도"] = sorted(set(cohort))
    if conds:
        out["조건"] = list(dict.fromkeys(conds))
    if exprs:
        out["조건식"] = exprs
    for k in ("국적", "원문표현"):
        if f.get(k):
            out[k] = list(f[k])
    if f.get("비교축"):
        out["비교축"] = f["비교축"][0]
        if len(f["비교축"]) > 1:
            notes.append(f"{tag}[비교축] 여러 개 {f['비교축']} 중 첫 번째만 사용 (View 모듈 Filters.비교축 은 하나)")
    intents = _intents(intent)  # 원 질문 의도는 목록
    if intents:
        out["의도"] = VIEW_INTENT.get(intents[0], "값 조회")
        if len(intents) > 1:
            notes.append(f"{tag}[의도] 여러 개 {intents} 중 첫 번째만 사용 (View 모듈 Filters.의도 는 하나)")
        if out["의도"] != intents[0] and intents[0] != OUT_OF_SCOPE:
            notes.append(f"{tag}[의도] '{intents[0]}' → View 종류 '{out['의도']}'")
    for k in UNSUPPORTED:
        if f.get(k):
            notes.append(f"{tag}[{k}] {f[k]} — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)")
    return out


def to_view_bundle(bundle, query_id=None, search_with="rewritten", sub_intents=None, thresholds=None):
    """재작성 QueryBundle(dataclass·dict·pydantic) → (View 모듈 QueryBundle dict, notes)
    sub_intents: 하위 질문 의도 목록 (sub_intents_of(run_pipeline 결과["valid"])). None 이면 하위 문장에서 되살림
    thresholds: 분석 state 의 숫자 기준 ('가구원수 99,000명 이상'). 조건식 으로 상위 filters 와 역할이 없는 모든 하위 필터에 넣는다
    (조건 조회 단위(역할=조건)에는 넣지 않는다 — split_roles 가 그 단위를 지우므로 거기 두면 조건을 받아야 할 본 질문에서 조건이 사라진다)"""
    b = _as_dict(bundle)
    notes = []
    intent = b.get("intent")
    if is_out_of_scope(b):  # 범위 밖: 슬롯이 모두 비는 것이 정상 (재작성 실패 아님)
        notes.append(f"[의도] {OUT_OF_SCOPE} — 통계 수치를 묻는 질문이 아님 (통합 파이프라인은 표를 검색하지 않음)")
        return {"query_id": query_id or uuid.uuid4().hex[:8], "original": b["original"], "rewritten": b.get("rewritten"),
                "intent": intent, "filters": None, "sub_questions": [], "sub_filters": None,
                "search_text": b["original"]}, notes
    filters = to_view_filters(b.get("filters"), intent, notes)
    subs = list(b.get("sub_questions") or [])
    sfs = [to_view_filters(sf, si, notes, f"하위 {i}") or {}
           for i, (sf, si) in enumerate(zip(b.get("sub_filters") or [], resolve_sub_intents(b, sub_intents)), 1)]
    if tconds := threshold_conditions(thresholds):
        for f_ in [filters, *sfs]:
            if f_ is not None and not f_.get("역할"):
                f_["조건식"] = [*(f_.get("조건식") or []), *[c for c in tconds if c not in (f_.get("조건식") or [])]]
        notes.append("조건 기준(조건식): " + ", ".join(c["text"] for c in tconds))
    rewritten_ok = bool(b.get("filters"))  # 재작성 실패 시 rewritten == original, filters None
    search_text = b.get("rewritten") if (search_with == "rewritten" and rewritten_ok) else b["original"]
    if search_with == "rewritten" and not rewritten_ok:
        notes.append("재작성 슬롯이 비어 원 질문으로 검색")
    return {"query_id": query_id or uuid.uuid4().hex[:8], "original": b["original"], "rewritten": b.get("rewritten"),
            "intent": intent, "filters": filters, "sub_questions": subs,
            "sub_filters": sfs or None, "search_text": search_text}, notes
