"""
[NEW] 주의사항(caveats) — 사용자가 알아야 할 '못 맞춘 조건'과 '계산하지 못한 이유'를 규칙으로 모은다

  출처 3가지
    view_note     Record.notes · Record.match.unmet  (예: 2025년을 물었는데 표에 2024년까지만 있어 2024년으로 대체)
    calc_note     CalcResult.note                    (계산하지 못한 이유, truncated 등)
    view_missing  계산 결과가 가리키는 View 가 records 에 없음
  이 목록은 HCX 프롬프트에도 들어가 답변 문장이 한 번 언급하게 하고, 출력에는 그대로 남는다 (문장이 빠뜨려도 화면이 보여 줄 수 있게).
"""
import re

from backend.agent.answer_compose.facts import Facts, has_value, josa
from backend.agent.answer_compose.reasons import humanize
from backend.schemas.answer import Caveat
from backend.schemas.record import Note, Record


# 표에서 찾는 지표가 아니라 모듈 3 이 **계산해서 만드는 값**을 뜻하는 말. '혼인건수 증감률' 이라는 지표는 표에 없는 것이 당연하다.
# ('비율' · '율' 은 넣지 않는다: '고령인구비율' 처럼 표에 실제로 있는 지표 이름이다)
_DERIVED = re.compile("증감률|증가율|감소율|변화율|변동률|성장률|증감|증가|감소|변화|변동|추이|순위")


def _is_derived_indicator_missing(n: Note) -> bool:
    """'View 조건 지표 [혼인건수 증감률] 없음' — 계산해서 만드는 값을 표에서 못 찾았다는 뜻이라 자료 부족이 아니다.
    답변에 넣으면 HCX 가 증감률을 이미 답하고도 '증감률 정보는 제공되지 않았다'고 덧붙인다 (실제 HCX 시험에서 확인)"""
    if n.slot != "지표" or n.type != "missing":
        return False
    wanted = n.requested if isinstance(n.requested, (list, tuple)) else [n.requested]
    return bool(wanted) and all(_DERIVED.search(str(v)) for v in wanted if v)


def _note_text(n: Note) -> str:
    return n.text.strip()


def used_record_ids(f: Facts) -> list[str]:
    """계산이 쓴 View 의 Record.id (처음 나온 순서)"""
    ids: list[str] = []
    for r in f.req.calc_results:
        for rid in [*r.record_ids, *(i.record_id for i in r.inputs)]:
            if rid not in ids:
                ids.append(rid)
    return ids


def build_caveats(f: Facts) -> list[Caveat]:
    by_id: dict[str, Record] = {rec.id: rec for rec in f.req.records}
    out: list[Caveat] = []
    seen: set[str] = set()

    def add(source: str, ref: str, text: str) -> None:
        if text and text not in seen:         # 같은 문장이 View 마다 반복되면 한 번만
            seen.add(text)
            out.append(Caveat(source=source, ref=ref, text=text))

    for text in f.req.plan_warnings:          # 모듈 3 이 계산을 보류한 사유가 가장 먼저 (왜 답이 없는지)
        add("plan_warning", "plan", text)
    for rid in used_record_ids(f) or list(by_id):
        rec = by_id.get(rid)
        if rec is None:
            add("view_missing", rid, f"계산에 쓴 자료({rid})를 찾을 수 없습니다.")
            continue
        for n in [*rec.notes, *(rec.match.unmet if rec.match else [])]:
            if not _is_derived_indicator_missing(n):
                add("view_note", rid, _note_text(n))

    for r in f.req.calc_results:
        if not has_value(r):
            add("calc_note", r.step_id, f"{josa(f.label(r), '을')} 계산하지 못했습니다" + (f": {humanize(r.note, r.inputs)}" if r.note else "."))
        elif r.note:
            add("calc_note", r.step_id, f"{f.label(r)}: {humanize(r.note, r.inputs)}")
    return out
