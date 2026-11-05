"""
[NEW] 슬롯 판정 → View → 단위 → 질문 전체 점수·판정·사유  (4단계)

  judge_record(record, filters, config, upstream, view_notes)  → RecordJudge   View 하나
  judge_unit(unit, config, upstream)                           → UnitJudge     단위 하나 (가장 잘 맞는 View)
  judge_question(query_id, units, config, extra_reasons)       → JudgeResult   질문 전체

  점수 = Σ status_score[상태] × tier_weights[등급]  ÷  Σ tier_weights[등급]   (not_requested·등급 없는 슬롯은 제외)
  기준값·가중치는 전부 JudgeConfig 에서 읽는다 (여기에는 숫자를 고정하지 않음)
"""
from backend.rag.judge.adapters import UnitInput, view_note_slots
from backend.rag.judge.extract import extract_contents
from backend.rag.judge.slots import check_slots
from backend.schemas.judge import (JudgeConfig, JudgeResult, ReasonCode, RecordJudge, SlotCheck, SlotTier, UnitJudge,
                                   Verdict)
from backend.schemas.judge import SlotStatus as S

# 판정 등급의 순위 — 큰 값이 더 좋다. '가장 좋은 View', '가장 나쁜 단위' 를 고를 때 쓴다
VERDICT_RANK = {Verdict.fail: 0, Verdict.partial: 1, Verdict.pass_: 2}

# 슬롯 상태의 심각도 — 큰 값이 더 나쁘다. View 판정과 '변환 단계' 판정을 합칠 때 더 나쁜 쪽을 고른다
SEVERITY = {S.not_requested: 0, S.match: 1, S.unknown: 2, S.partial: 3, S.unsupported: 4, S.missing: 5}


# ═════════════════════════════ 작은 도우미 ═════════════════════════════

def ordered_reasons(reasons) -> list[ReasonCode]:
    """중복 제거 + ReasonCode 에 정의된 순서로 정렬 (순서가 고정되어야 오케스트레이터·테스트가 예측 가능)
    for r in ReasonCode → Enum 은 정의된 순서대로 돈다 (자바 enum 의 values() 와 같음)"""
    have = set(reasons)
    return [r for r in ReasonCode if r in have]


def to_verdict(score: float, config: JudgeConfig) -> Verdict:
    """점수 → 판정 (기준값은 config)"""
    if score >= config.pass_threshold:
        return Verdict.pass_
    if score >= config.partial_threshold:
        return Verdict.partial
    return Verdict.fail


def merge_check(view_check: SlotCheck | None, up: SlotCheck) -> SlotCheck:
    """같은 슬롯에 대한 View 판정과 '변환 단계' 판정을 하나로 — 더 나쁜 상태 + 근거 이어 붙이기.
    예) View 에는 2024 가 있어 match 지만, 원래 질문은 '2024년 9월' → partial (+ slot_dropped_upstream)"""
    if view_check is None or view_check.status == S.not_requested:
        return up                                   # View 쪽에는 이 슬롯이 없음 (국적 등) → 변환 단계 판정 그대로
    worse = up if SEVERITY[up.status] > SEVERITY[view_check.status] else view_check
    evidence = " / ".join(e for e in (view_check.evidence, up.evidence) if e)
    # model_copy(update=…): pydantic 객체를 복사하면서 일부 필드만 바꾼다 (원본은 그대로 → 다른 곳에 영향 없음)
    return view_check.model_copy(update={"status": worse.status, "evidence": evidence,
                                         "reason": view_check.reason or up.reason})


def slot_tier(name: str, check: SlotCheck, config: JudgeConfig) -> SlotTier | None:
    """슬롯의 등급. slot_tiers 에 있으면 그것, 없는데 '변환 단계에서 빠진 슬롯' 이면 upstream_tier, 아니면 None(점수 제외)"""
    tier = config.slot_tiers.get(name)
    if tier is None and check.reason == ReasonCode.slot_dropped_upstream:
        tier = config.upstream_tier
    return tier


def weighted_score(slots: dict[str, SlotCheck], config: JudgeConfig) -> float:
    """요청된 슬롯의 가중 평균 점수 (0~1). 점수에 넣을 슬롯이 하나도 없으면 1.0 (감점할 기준이 없음)"""
    num = den = 0.0                                 # 분자(점수×가중치 합), 분모(가중치 합)
    for name, chk in slots.items():
        if chk.status == S.not_requested:          # 묻지 않은 슬롯 → 분자·분모 모두에서 빠짐
            continue
        tier = slot_tier(name, chk, config)
        weight = config.tier_weights.get(tier, 0.0) if tier is not None else 0.0
        if weight <= 0:                             # 등급이 없거나 가중치 0 → 판정만 남기고 점수 제외 (예: 비교축)
            continue
        num += config.status_score.get(chk.status, 0.0) * weight
        den += weight
    return round(num / den, 4) if den else 1.0


# ═════════════════════════════ ③ View 하나 ═════════════════════════════

def judge_record(record, filters, config: JudgeConfig, upstream: dict[str, SlotCheck] | None = None,
                 view_notes: list[str] | None = None) -> RecordJudge:
    c = extract_contents(record)                    # 2단계: View 에 실제로 담긴 것
    slots = check_slots(filters, c, config)         # 3단계: 슬롯별 판정

    # 변환 단계에서 빠지거나 바뀐 슬롯 반영 (국적 → 새 슬롯, 시점 → 기존 판정과 합침)
    for name, up in (upstream or {}).items():
        slots[name] = merge_check(slots.get(name), up)

    # build_view notes 는 판정에 쓰지 않고 근거 문장에만 덧붙인다 ([P1] 처럼 notes 가 비어 있는 경우가 있어 믿지 않음)
    for note in view_notes or []:
        for name in view_note_slots(note):
            chk = slots.get(name)
            if chk is not None and chk.status != S.not_requested:
                ev = f"{chk.evidence} | View 메모: {note}" if chk.evidence else f"View 메모: {note}"
                slots[name] = chk.model_copy(update={"evidence": ev})

    reasons = [chk.reason for chk in slots.values() if chk.reason is not None]

    # 빈 View: 값이 하나도 없으면 다른 슬롯이 맞아도 쓸 수 없다 → 0점, fail
    if c.is_empty:
        return RecordJudge(record_id=c.record_id, tbl_id=c.tbl_id, verdict=Verdict.fail, score=0.0, slots=slots,
                           reasons=ordered_reasons(reasons + [ReasonCode.empty_view]))

    score = weighted_score(slots, config)
    # core 슬롯이 missing 이면 평균 점수와 관계없이 fail (평균이 치명적 오류를 희석하지 않도록)
    core_missing = [n for n, chk in slots.items()
                    if chk.status == S.missing and config.slot_tiers.get(n) == SlotTier.core]
    if core_missing and config.core_missing_is_fail:
        verdict = Verdict.fail
        reasons.append(ReasonCode.core_slot_missing)
    else:
        verdict = to_verdict(score, config)
        if core_missing:                            # 규칙을 껐어도 사유는 남긴다
            reasons.append(ReasonCode.core_slot_missing)
    return RecordJudge(record_id=c.record_id, tbl_id=c.tbl_id, verdict=verdict, score=score, slots=slots,
                       reasons=ordered_reasons(reasons))


# ═════════════════════════════ ④ 단위 하나 ═════════════════════════════

def judge_unit(unit: UnitInput, config: JudgeConfig, upstream: dict[str, SlotCheck] | None = None) -> UnitJudge:
    """단위의 View 들을 모두 판정하고, 가장 잘 맞는 View 를 단위의 대표로"""
    notes_list = unit.view_notes or [[] for _ in unit.records]     # notes 가 없으면 View 수만큼 빈 목록
    records = [judge_record(rec, unit.filters, config, upstream, notes)
               for rec, notes in zip(unit.records, notes_list)]   # zip: 두 목록을 같은 순서로 짝지어 돈다

    if not records:                                 # View 가 하나도 없음
        reasons = [ReasonCode.no_views]
        if upstream:
            reasons.append(ReasonCode.slot_dropped_upstream)
        return UnitJudge(unit_id=unit.unit_id, query=unit.query, verdict=Verdict.fail, score=0.0,
                         records=[], reasons=ordered_reasons(reasons))

    # 대표 View = (판정 등급, 점수) 가 가장 큰 것. 같으면 먼저 나온 것 (= 검색 순위가 높은 것)
    #   key 에 튜플을 주면 첫 값으로 먼저 비교하고, 같을 때만 두 번째 값으로 비교한다
    best = max(records, key=lambda r: (VERDICT_RANK[r.verdict], r.score))
    return UnitJudge(unit_id=unit.unit_id, query=unit.query, verdict=best.verdict, score=best.score,
                     best_record_id=best.record_id, records=records, reasons=best.reasons)


# ═════════════════════════════ ⑤ 질문 전체 ═════════════════════════════

def judge_question(query_id: str, units: list[UnitJudge], config: JudgeConfig,
                   extra_reasons: list[ReasonCode] | None = None) -> JudgeResult:
    """단위 판정들을 config.unit_aggregate 규칙으로 합친다
      all  : 가장 나쁜 단위의 판정, 점수는 최솟값  (모든 단위가 통과해야 통과)
      any  : 가장 좋은 단위의 판정, 점수는 최댓값
      mean : 점수 평균을 기준값으로 판정"""
    reasons = [r for u in units for r in u.reasons] + list(extra_reasons or [])
    if not units:
        return JudgeResult(query_id=query_id, verdict=Verdict.fail, score=0.0, units=[], config_used=config,
                           reasons=ordered_reasons(reasons + [ReasonCode.no_views]))

    scores = [u.score for u in units]
    if config.unit_aggregate == "any":
        verdict = max((u.verdict for u in units), key=VERDICT_RANK.get)
        score = max(scores)
    elif config.unit_aggregate == "mean":
        score = sum(scores) / len(scores)
        verdict = to_verdict(score, config)
    else:                                           # "all" (기본)
        verdict = min((u.verdict for u in units), key=VERDICT_RANK.get)
        score = min(scores)
    return JudgeResult(query_id=query_id, verdict=verdict, score=round(score, 4), units=units,
                       reasons=ordered_reasons(reasons), config_used=config)
