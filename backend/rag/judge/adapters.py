"""
[NEW] 판단 모듈 입력 변환 — 다른 모듈이 준 모양을 '판정하기 좋은 모양' 으로 바꾼다  (4단계)

  units_from_view_result(views, bundle)  ViewResult → [UnitInput]   단위(main·서브질문)별 (슬롯, Record 목록)
  upstream_checks(notes)                 adapter notes → 단위별 '위 단계에서 빠진 슬롯' SlotCheck
  view_note_slots(note)                  build_view notes 한 줄 → 관련 슬롯 이름 (근거 문장에 덧붙이기용)

  나중에 검색 모듈의 SearchResult 가 정해지면 units_from_search_result() 만 여기에 추가하면 된다.
  판정 로직(slots.py, aggregate.py)은 UnitInput 만 알면 되므로 고칠 필요가 없다.
"""
import re
from dataclasses import dataclass, field

from backend.core.utils import norm_space
from backend.schemas.judge import ReasonCode, SlotCheck
from backend.schemas.judge import SlotStatus as S

# adapter.py(재작성 → View 입력 변환) 가 남기는 notes 의 모양
#   "[국적] ['베트남'] — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)"
#   "(하위 2) [시점] '2024년 9월' → 2024 (View 모듈은 연도 단위)"
# 정규식 그룹: 1 = 서브질문 번호(없으면 main), 2 = 슬롯 이름, 3 = 나머지 설명
NOTE_RE = re.compile(r"^(?:\(하위 (\d+)\)\s*)?\[([^\]]+)\]\s*(.*)$")
REWRITE_FAILED = "재작성 슬롯이 비어"     # 재작성 자체가 실패해 원 질문으로 검색한 경우 (질문 전체 문제)

# build_view notes 에 나오는 단어 → 관련 슬롯. build_view notes 는 [슬롯] 태그가 없어서 단어로 찾는다
#   예) "시점 2024 은 이 표에 없음", "행정구역별: 지역 ['세종'] 없음", "항목: 지표·대상과 맞는 항목 없음 → '계'"
VIEW_NOTE_WORDS = {"시점": ("시점", "최신"), "지역": ("지역",), "성별": ("성별",), "연령": ("연령",),
                   "지표": ("항목",), "대상": ("항목",)}


@dataclass
class UnitInput:
    """검색 단위 하나 (main 또는 서브질문) — 판정에 필요한 것만"""
    index: int                       # 0 = main, 1.. = 서브질문 순서 (adapter notes 의 '(하위 N)' 과 맞춤)
    unit_id: str
    query: str
    filters: dict                    # 이 단위의 슬롯 (서브질문이면 그 서브질문의 슬롯)
    records: list = field(default_factory=list)            # 이 단위의 View(Record dict) 목록. 0개일 수 있음
    view_notes: list[list[str]] = field(default_factory=list)   # records 와 같은 순서의 build_view notes


def _as_dict(x) -> dict:
    """pydantic 이면 dict 로. by_alias=True → 연령 'from' 별칭 유지, mode='json' → Enum 을 문자열로"""
    if x is None:
        return {}
    if hasattr(x, "model_dump"):
        return x.model_dump(by_alias=True, mode="json")
    return dict(x)


def units_from_view_result(views, bundle=None) -> list[UnitInput]:
    """ViewResult → UnitInput 목록.
    View 모듈(views.run_query)은 이미 단위마다 그 단위의 슬롯을 units[].filters 에 넣어 준다
    (서브질문 단위 = sub_filters). 그래서 '부산 출생아 View 를 대구 슬롯으로 채점' 하는 일이 생기지 않는다."""
    v = _as_dict(views)
    b = _as_dict(bundle)
    base = v.get("filters") or b.get("filters") or {}       # 단위에 슬롯이 없을 때 쓸 질문 전체 슬롯
    out = []
    for i, u in enumerate(v.get("units") or []):
        items = u.get("views") or []                          # [{record, notes, rank, tbl_id}, …]
        out.append(UnitInput(
            index=i,
            unit_id=str(u.get("unit_id") or i),
            query=str(u.get("query") or ""),
            filters=u.get("filters") or base,
            records=[it["record"] for it in items if it.get("record")],
            view_notes=[list(it.get("notes") or []) for it in items if it.get("record")],
        ))
    return out


def _upstream_status(body: str):
    """adapter note 설명 → 슬롯 상태. 정보가 줄지 않은 '안내성' 메모면 None (무시)"""
    if "아직 없는 슬롯" in body or "읽을 수 없는" in body:
        return S.unsupported         # 조건이 통째로 빠짐 (국적, 읽지 못한 시점 …)
    if "View 모듈은 연도 단위" in body or "첫 번째만" in body:
        return S.partial             # 조건이 넓어지거나 일부만 남음 (9월 → 2024년, 비교축 여러 개 → 1개)
    return None                      # 예: "[지역] '전국'과 다른 지역이 함께 있어 '전국'은 뺌", "[의도] '증감' → '추이'"


def upstream_checks(notes) -> tuple[dict[int, dict[str, SlotCheck]], list[ReasonCode]]:
    """adapter notes → ({단위 index: {슬롯: SlotCheck}}, 질문 전체 사유 목록)
    반환값이 두 개(튜플)다. 받는 쪽에서 per_unit, reasons = upstream_checks(notes) 처럼 나눠 받는다."""
    per_unit: dict[int, dict[str, SlotCheck]] = {}
    question_reasons: list[ReasonCode] = []
    for note in notes or []:
        note = norm_space(note)
        if REWRITE_FAILED in note:
            question_reasons.append(ReasonCode.slot_dropped_upstream)
            continue
        m = NOTE_RE.match(note)
        if not m:
            continue
        unit = int(m.group(1)) if m.group(1) else 0         # '(하위 N)' 이 없으면 main
        slot, body = m.group(2), m.group(3)
        status = _upstream_status(body)
        if status is None:
            continue
        slots = per_unit.setdefault(unit, {})                # setdefault: 없으면 {} 를 넣고 그것을 돌려줌
        prev = slots.get(slot)
        if prev is not None:                                 # 같은 슬롯 메모가 또 있으면 더 나쁜 쪽 + 근거 합치기
            if prev.status == S.unsupported:
                status = S.unsupported
            body = f"{prev.evidence.removeprefix('변환 단계: ')} / {body}"
        slots[slot] = SlotCheck(status=status, evidence=f"변환 단계: {body}",
                                reason=ReasonCode.slot_dropped_upstream)
    return per_unit, question_reasons


def view_note_slots(note: str) -> list[str]:
    """build_view notes 한 줄 → 관련 슬롯 이름들 (판정에는 쓰지 않고 근거 문장에만 덧붙인다)"""
    return [slot for slot, words in VIEW_NOTE_WORDS.items() if any(w in note for w in words)]
