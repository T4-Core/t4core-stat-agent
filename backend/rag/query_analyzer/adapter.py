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
  filters.비교축 ['시도']                           비교축 '시도'
  intent '증감' / '구성비'                          의도 '추이' / '비교'  (View 모듈이 아는 4종으로. 목록이 들어오면 첫 번째 값)
  filters.전출지·전입지·국적·조건·이동             (View 모듈 슬롯 없음 → notes)
  rewritten '2025년 전국 1인가구 가구수'            rewritten 그대로 + search_text (검색 문장)
  sub_questions / sub_filters                      그대로 (sub_filters 에 의도 채움)
"""
import re
import uuid
from dataclasses import asdict, is_dataclass

from backend.rag.ingestion.normalize import std_geo_name
from .query_bundle import parse_ages                    # v2: from backend.rag.query_analyzer.query_bundle (같은 모듈, 상대 경로로)

# v3 의도 9개 → View 모듈이 아는 4종 (증감률 → 추이, 합계·범위 밖 → 값 조회 추가)
VIEW_INTENT = {"값 조회": "값 조회", "추이": "추이", "비교": "비교", "순위": "순위", "구성비": "비교", "증감": "추이",
               "증감률": "추이", "합계": "값 조회", "범위 밖": "값 조회"}
UNSUPPORTED = ("전출지", "전입지", "국적", "조건", "이동")
TIME_RE = re.compile(r"^((?:19|20)\d{2})\s*년?(?:\s*(\d{1,2})\s*월)?$")


def _as_dict(b):
    if is_dataclass(b):
        return asdict(b)
    if hasattr(b, "model_dump"):
        return b.model_dump()
    return dict(b)


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
    if f.get("연령"):
        age = parse_ages(list(f["연령"]), notes)
        if age:
            out["연령"] = age
    if f.get("비교축"):
        out["비교축"] = f["비교축"][0]
        if len(f["비교축"]) > 1:
            notes.append(f"{tag}[비교축] 여러 개 {f['비교축']} 중 첫 번째만 사용 (View 모듈 Filters.비교축 은 하나)")
    intents = [intent] if isinstance(intent, str) else list(intent or [])   # v3: 원 질문 의도는 목록
    if intents:
        out["의도"] = VIEW_INTENT.get(intents[0], "값 조회")
        if len(intents) > 1:
            notes.append(f"{tag}[의도] 여러 개 {intents} 중 첫 번째만 사용 (View 모듈 Filters.의도 는 하나)")
        if out["의도"] != intents[0]:
            notes.append(f"{tag}[의도] '{intents[0]}' → View 종류 '{out['의도']}'")
    for k in UNSUPPORTED:
        if f.get(k):
            notes.append(f"{tag}[{k}] {f[k]} — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)")
    return out


def to_view_bundle(bundle, query_id=None, search_with="rewritten"):
    """재작성 QueryBundle(dataclass·dict·pydantic) → (View 모듈 QueryBundle dict, notes)"""
    b = _as_dict(bundle)
    notes = []
    filters = to_view_filters(b.get("filters"), b.get("intent"), notes)
    subs = list(b.get("sub_questions") or [])
    sfs = [to_view_filters(sf, b.get("intent"), notes, f"하위 {i}") or {}
           for i, sf in enumerate(b.get("sub_filters") or [], 1)]
    rewritten_ok = bool(b.get("filters"))                 # 재작성 실패 시 rewritten == original, filters None
    search_text = b.get("rewritten") if (search_with == "rewritten" and rewritten_ok) else b["original"]
    if search_with == "rewritten" and not rewritten_ok:
        notes.append("재작성 슬롯이 비어 원 질문으로 검색")
    return {"query_id": query_id or uuid.uuid4().hex[:8], "original": b["original"], "rewritten": b.get("rewritten"),
            "intent": b.get("intent"), "filters": filters, "sub_questions": subs,
            "sub_filters": sfs or None, "search_text": search_text}, notes
