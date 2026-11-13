"""
계획 자동 보정 — LLM 계획의 '기계적인' 빈칸을 결정론적으로 채운다 (숫자는 만들지 않음, 모든 보정은 기록)

실데이터(HCX) 진단에서 탈락의 대부분이 추론이 아니라 좌표 표기 문제였다:
  ① 고정하지 않은 분류가 남음 (스칼라인데 N행 / 키당 여러 행)  → 그 분류에 총계 코드가 하나뿐이면 총계로 고정
     (통계표에서 따로 말하지 않은 분류는 '계' 가 기본 — 질문 조건 라벨은 총계를 요구하지 않으므로 질문과도 맞음)
  ② group_by_level 을 coordinates 에도 넣음                   → coordinates 에서 뺌 (그룹 기준이 우선)
  ③ 없는 코드 ('000' · 코드 대신 이름 · '전국')               → 이름 일치 · 숫자 같음(0 채움 차이) · 총계 별칭으로 하나만 맞으면 교체
  ④ 그룹 레벨의 말단 코드 깊이가 섞였는데 depth 없음          → 말단 코드가 가장 많은 깊이로 지정
보정할 수 없으면 그대로 두고 기존 검증이 오류(재시도)로 돌려준다.
"""
from __future__ import annotations

import re
from collections import Counter

from synthetic_gold_pipeline.schemas.planning import OperationPlan

TOTAL_ALIASES = {"전국", "계", "총계", "합계", "전체", "총", "소계", "t", "total", "all"}
TOTAL_NAMES = {"전국", "계", "총계", "합계", "전체", "소계"}
AREA_SPLIT = re.compile(r"^\s*(동|읍|면)\s*부\s*$")        # 시도 안의 동부·읍부·면부 = 지역이 아니라 도시/농촌 구분


def is_total_code(dc) -> bool:
    return bool(dc.is_total or _nospace(dc.name) in TOTAL_NAMES)


def leaf_depths(vm, level) -> Counter:
    return Counter(c.depth for c in vm.dimension_codes.get(level, [])
                   if not (c.is_total or c.has_children) and not AREA_SPLIT.match(c.name or ""))


def _nospace(s) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def match_code(code: str, cm: dict) -> str | None:
    """없는 코드 → 유일하게 맞는 실제 코드 (없거나 여럿이면 None)"""
    code = str(code).strip()
    by_name = [c for c, dc in cm.items() if _nospace(dc.name) == _nospace(code)]
    if len(by_name) == 1:
        return by_name[0]
    if code.isdigit():
        num = [c for c in cm if str(c).isdigit() and int(c) == int(code)]
        if len(num) == 1:
            return num[0]
    if code.lower() in TOTAL_ALIASES or (code.isdigit() and int(code) == 0):
        tot = [c for c, dc in cm.items() if dc.is_total]
        if len(tot) == 1:
            return tot[0]
    return None


def repair_plan(plan: OperationPlan, index) -> tuple[OperationPlan, list[str]]:
    notes: list[str] = []
    new_ops = []
    for o in plan.operands:
        try:
            vm = index.view(o.view_id)
        except KeyError:
            new_ops.append(o)
            continue
        levels = {d.level: d for d in vm.dimension_definitions}
        coords = {str(k): str(v) for k, v in o.coordinates.items()}
        upd = {}
        g = o.group_by_level
        if g and g in coords:                                                    # ②
            coords.pop(g)
            notes.append(f"{o.operand_id}: group_by_level {g} 를 coordinates 에서 뺌")
        for lv in list(coords):                                                  # ③
            if lv in levels and coords[lv] not in vm.code_map(lv):
                fix = match_code(coords[lv], vm.code_map(lv))
                if fix:
                    notes.append(f"{o.operand_id}: {lv} 코드 {coords[lv]!r} → {fix}({vm.code_map(lv)[fix].name})")
                    coords[lv] = fix
        if o.include_codes and g in levels:
            cm = vm.code_map(g)
            fixed = [c if c in cm else (match_code(c, cm) or c) for c in o.include_codes]
            if fixed != list(o.include_codes):
                notes.append(f"{o.operand_id}: include_codes {o.include_codes} → {fixed}")
                upd["include_codes"] = fixed
        try:                                                                     # ①
            sub = index.load_frame(o.view_id)
            sub = sub[(sub["ITM_ID"].astype(str) == str(o.itm_id)) & (sub["PRD_DE"].astype(str) == str(o.prd_de))]
            for lv, c in coords.items():
                if lv in sub.columns:
                    sub = sub[sub[lv].astype(str) == c]
        except Exception:  # noqa: BLE001  (프레임을 못 읽으면 보정 생략 — 계산 단계가 오류를 냄)
            sub = None
        if sub is not None and len(sub) > 1:
            for lv, d in levels.items():
                if lv == g or lv in coords or lv not in sub.columns:
                    continue
                vals = list(dict.fromkeys(sub[lv].astype(str)))
                if len(vals) <= 1:
                    continue
                cm = vm.code_map(lv)
                tot = [v for v in vals if cm.get(v) is not None and is_total_code(cm[v])]
                if len(tot) == 1:
                    coords[lv] = tot[0]
                    sub = sub[sub[lv].astype(str) == tot[0]]
                    notes.append(f"{o.operand_id}: 고정 안 된 분류 {d.obj_nm}({lv}) → 총계 {cm[tot[0]].name}({tot[0]})")
        if coords != {str(k): str(v) for k, v in o.coordinates.items()}:
            upd["coordinates"] = coords
        new_ops.append(o.model_copy(update=upd) if upd else o)
    new_ops = _align_depths(new_ops, index, notes)                                          # ④
    if not notes:
        return plan, []
    return plan.model_copy(update={"operands": new_ops}), notes


def _align_depths(ops, index, notes):
    """그룹 레벨의 말단 깊이가 섞인 operand 에 depth 지정. 서로 연결되는 operand 는 '같은 깊이' 로 맞춤
    (시군구 261개 operand 와 읍면동 3,766개 operand 를 각자 다수 깊이로 고르면 공통 코드가 없어 근거 없는 View 가 됨)"""
    need = {}
    for i, o in enumerate(ops):
        if not o.group_by_level or o.depth is not None or o.include_codes:
            continue
        try:
            vm = index.view(o.view_id)
        except KeyError:
            continue
        if o.group_by_level not in {d.level for d in vm.dimension_definitions}:
            continue
        dep = leaf_depths(vm, o.group_by_level)
        if dep:
            need[i] = dep
    if not need:
        return ops
    grouped = [i for i, o in enumerate(ops) if o.group_by_level]
    mixed = [i for i in need if len(need[i]) > 1]
    if not mixed:
        return ops
    common = set.intersection(*(set(need[i]) for i in need)) if len(need) > 1 else set(need[mixed[0]])
    out = list(ops)
    if common:
        d0 = max(common, key=lambda d: (min(need[i][d] for i in need), -d))   # 모두에게 있는 깊이 중 가장 많이 겹치는 것
        targets = list(need)
    else:
        targets = mixed
        d0 = None
    for i in targets:
        d = d0 if d0 is not None else max(need[i], key=lambda x: (need[i][x], -x))
        if len(need[i]) > 1 or (d0 is not None and len(grouped) > 1 and set(need[i]) != {d}):
            out[i] = out[i].model_copy(update={"depth": d})
            notes.append(f"{ops[i].operand_id}: {ops[i].group_by_level} 말단 코드 깊이 {dict(need[i])} → depth={d}"
                         + (" (연결된 operand 와 같은 깊이)" if d0 is not None and len(need) > 1 else ""))
    return out
