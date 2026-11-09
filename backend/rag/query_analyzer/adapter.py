"""
[NEW] 입출력 맞추기: 재작성 모듈 QueryBundle → View 모듈 QueryBundle

두 모듈은 따로 만들어져 같은 이름(QueryBundle)인데 모양이 다르다. 그대로 넘기면 View 모듈이
  - 시점 '2025년'(문자열)을 int 로 기대 → Filters 검증 오류(422)
  - 연령 ['20~29세'](목록)을 {from, to} 로 기대 → 검증 오류
  - 비교축 ['시도'](목록)을 문자열로 기대 → 검증 오류
  - 의도를 filters['의도'] 에서 읽음 (재작성 모듈은 intent 에만 둠) → View 종류(trend/value)가 항상 value
가 된다. 두 모듈 코드는 고치지 않고 이 파일에서만 변환한다.

  재작성 모듈 (RewriterBundle)                     View 모듈 (QueryBundle)
  ─────────────────────────────────────────────    ──────────────────────────────────────────
  filters.시점  ['2024년', '2024년 9월']            시점 [2024]          (월은 연도로, notes 에 기록)
  filters.지역  ['대구광역시', '전국']              지역 ['대구광역시']   ('전국'은 빼면 View 모듈 기본값=전국)
  filters.연령  ['20~24세', '25~29세']              연령 {from:20, to:29} (query_bundle.parse_ages 로 병합)
  filters.대상  ['고령자']  (v3: 노인 → 고령자)      대상 ['인구'] + 연령 {from:65, to:null}  (AGE_TARGETS, 연령이 비었을 때만 채움)
  filters.비교축 ['시도']                           비교축 '시도'
  intent (v3 의도 9종)                              의도 4종 (VIEW_INTENT: 증감·증감률 → 추이, 구성비 → 비교, 합계 → 값 조회)
  sub_filters[i] (v3: 하위 질문마다 의도 하나)       sub_filters[i].의도 = 그 하위 질문의 의도 (sub_intents)
  intent '범위 밖' (통계 수치를 묻지 않는 질문)      filters None + notes '[의도] 범위 밖' → 통합 파이프라인은 검색하지 않음
  filters.전출지·전입지·국적·조건·이동             (View 모듈 슬롯 없음 → notes)
  rewritten '2025년 전국 1인가구 가구수'            rewritten 그대로 + search_text (검색 문장)

[CHANGED v3] 하위 질문 의도
  v3 재작성 모듈은 하위 질문마다 의도를 따로 정한다 ('2023년 충남 인구랑 시군구별 고령인구비율 순위'
  → 하위 1 '값 조회', 하위 2 '순위'). 그런데 QueryBundle.sub_filters 에는 의도가 빠져 있어(노트북 4단계 형식),
  예전처럼 원 질문 의도를 모든 하위 질문에 넣으면 '순위' 하위 질문이 값 조회 View 가 된다.
  → run_pipeline() 결과가 있으면 sub_intents_of(res["valid"]) 로 하위 의도를 받아 넣고,
    저장된 bundle 만 있으면(query-adapt) 하위 문장 끝의 의도어('… 순위')로 되살린다 (없으면 원 질문 의도).
"""
import re
import uuid
from dataclasses import asdict, is_dataclass

from backend.rag.ingestion.normalize import std_geo_name
from .query_bundle import parse_ages                    # v2: from backend.rag.query_analyzer.query_bundle (같은 모듈, 상대 경로로)
from .sentence import INTENT_WORD, slots_to_sentence
from .slots import INTENTS

# v3 의도 9개 → View 모듈이 아는 4종 (증감률 → 추이, 합계·범위 밖 → 값 조회 추가)
VIEW_INTENT = {"값 조회": "값 조회", "추이": "추이", "비교": "비교", "순위": "순위", "구성비": "비교", "증감": "추이",
               "증감률": "추이", "합계": "값 조회", "범위 밖": "값 조회"}
VIEW_INTENTS = ("값 조회", "추이", "비교", "순위")       # View 모듈(build_view.VIEW_TYPE)이 아는 의도
OUT_OF_SCOPE = "범위 밖"
UNSUPPORTED = ("전출지", "전입지", "국적", "조건", "이동")
TIME_RE = re.compile(r"^((?:19|20)\d{2})\s*년?(?:\s*(\d{1,2})\s*월)?$")
# v3 용어 사전은 연령이 뜻에 들어 있는 말을 대상 용어로 바꾼다 ('노인' → '고령자'). View 모듈은 연령 분류로
# 표를 자르므로 연령으로 풀어 준다. 정의가 법·조사마다 다른 말(청년·아동·청소년)은 넣지 않음 (HCX 가 연령을 채울 때만 씀)
AGE_TARGETS = {"고령자": "65세 이상", "영유아": "0~5세", "유소년인구": "0~14세", "생산연령인구": "15~64세"}
_WORD_INTENT = {w: k for k, w in INTENT_WORD.items() if w}   # '순위' → '순위' (하위 문장 끝 의도어 → 의도)

assert set(VIEW_INTENT) == set(INTENTS), "slots.INTENTS 와 VIEW_INTENT 가 다름 (의도를 추가했으면 여기도)"


def _as_dict(b):
    if is_dataclass(b):
        return asdict(b)
    if hasattr(b, "model_dump"):
        return b.model_dump()
    return dict(b)


def _intents(intent):
    """의도 → 목록 (원 질문 의도는 v3 검증 슬롯에서 목록, QueryBundle.intent 는 문자열 하나)"""
    return [intent] if isinstance(intent, str) else [x for x in (intent or []) if x]


def is_out_of_scope(bundle):
    """재작성 결과가 '범위 밖'(통계 수치를 묻지 않는 질문)인가"""
    b = _as_dict(bundle) if bundle is not None else {}
    return OUT_OF_SCOPE in _intents(b.get("intent"))


def sub_intents_of(valid):
    """run_pipeline() 결과의 valid(2-4) → 하위 질문 의도 목록 (QueryBundle.sub_questions 와 같은 순서)
    make_bundle 과 같은 기준으로 문장이 빈 하위 슬롯은 뺀다"""
    return [s.get("의도") for s in (valid or {}).get("sub_slots", []) if slots_to_sentence(s)]


def _intent_from_sentence(text):
    """하위 질문 문장 끝 의도어 → 의도 ('2023년 충청남도 고령인구비율 시군구별 순위' → '순위'). 없으면 None
    sentence.slots_to_sentence 가 끝에 붙인 말이라 값 조회·구성비·범위 밖은 되살릴 수 없음"""
    words = str(text or "").split()
    return _WORD_INTENT.get(words[-1]) if words else None


def resolve_sub_intents(bundle, sub_intents=None):
    """하위 질문마다 의도 하나 (v3 의도 9종 값). 순서: 넘겨받은 sub_intents → 하위 문장 끝 의도어 → 원 질문 의도"""
    b = _as_dict(bundle)
    given, subs = list(sub_intents or []), list(b.get("sub_questions") or [])
    main = next(iter(_intents(b.get("intent"))), None)
    return [(given[i] if i < len(given) else None) or _intent_from_sentence(subs[i] if i < len(subs) else "") or main
            for i in range(len(b.get("sub_filters") or []))]


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
    regions = [std_geo_name(r) for r in f.get("지역") or []]
    if "전국" in regions:
        regions = [r for r in regions if r != "전국"]
        if regions:
            notes.append(f"{tag}[지역] '전국'과 다른 지역이 함께 있어 '전국'은 뺌 (지역 지정 시 전국 합계는 따로 나오지 않음)")
    if regions:
        out["지역"] = regions
    for k in ("대상", "성별", "지표"):
        if f.get(k):
            out[k] = list(f[k])
    ages = list(f.get("연령") or [])
    age_terms = [t for t in out.get("대상", []) if t in AGE_TARGETS]
    if age_terms:                                        # [NEW v3] '고령자' → 대상 '인구' + 연령 65세 이상
        out["대상"] = list(dict.fromkeys("인구" if t in AGE_TARGETS else t for t in out["대상"]))
        if not ages:
            ages = [AGE_TARGETS[age_terms[0]]]
        notes.append(f"{tag}[대상] {age_terms} → 대상 '인구' + 연령 {ages} (View 모듈은 연령 분류로 자름)")
    if ages:
        age = parse_ages(ages, notes)
        if age:
            out["연령"] = age
    if f.get("비교축"):
        out["비교축"] = f["비교축"][0]
        if len(f["비교축"]) > 1:
            notes.append(f"{tag}[비교축] 여러 개 {f['비교축']} 중 첫 번째만 사용 (View 모듈 Filters.비교축 은 하나)")
    intents = _intents(intent)                            # v3: 원 질문 의도는 목록
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


def to_view_bundle(bundle, query_id=None, search_with="rewritten", sub_intents=None):
    """재작성 QueryBundle(dataclass·dict·pydantic) → (View 모듈 QueryBundle dict, notes)
    sub_intents: 하위 질문 의도 목록 (sub_intents_of(run_pipeline 결과["valid"])). None 이면 하위 문장에서 되살림"""
    b = _as_dict(bundle)
    notes = []
    intent = b.get("intent")
    if is_out_of_scope(b):                                # [NEW v3] 범위 밖: 슬롯이 모두 비는 것이 정상 (재작성 실패 아님)
        notes.append(f"[의도] {OUT_OF_SCOPE} — 통계 수치를 묻는 질문이 아님 (통합 파이프라인은 표를 검색하지 않음)")
        return {"query_id": query_id or uuid.uuid4().hex[:8], "original": b["original"], "rewritten": b.get("rewritten"),
                "intent": intent, "filters": None, "sub_questions": [], "sub_filters": None,
                "search_text": b["original"]}, notes
    filters = to_view_filters(b.get("filters"), intent, notes)
    subs = list(b.get("sub_questions") or [])
    sfs = [to_view_filters(sf, si, notes, f"하위 {i}") or {}
           for i, (sf, si) in enumerate(zip(b.get("sub_filters") or [], resolve_sub_intents(b, sub_intents)), 1)]
    rewritten_ok = bool(b.get("filters"))                 # 재작성 실패 시 rewritten == original, filters None
    search_text = b.get("rewritten") if (search_with == "rewritten" and rewritten_ok) else b["original"]
    if search_with == "rewritten" and not rewritten_ok:
        notes.append("재작성 슬롯이 비어 원 질문으로 검색")
    return {"query_id": query_id or uuid.uuid4().hex[:8], "original": b["original"], "rewritten": b.get("rewritten"),
            "intent": intent, "filters": filters, "sub_questions": subs,
            "sub_filters": sfs or None, "search_text": search_text}, notes
