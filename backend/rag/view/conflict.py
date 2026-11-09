"""[NEW v4] 2-3 Point 충돌 판정 — 같은 검색 단위의 View 들이 같은 교차점에서 다른 값을 내는가

  1) View 마다 필수 메타(시점·지역·대상/지표 + 질문에 있던 성별·연령)를 실제로 썼는지 — judge 의 슬롯 판정을 그대로
     - match · not_requested → 씀.  conflict_allow_partial 에 든 슬롯(기본 시점)은 partial(대체 적용)도 씀
     - unknown → 씀 (메모).  partial · missing · unsupported → 못 씀 → 비교에서 빼고 view 의 usable=False
  2) 쓸 수 있는 View 들을 Point 로 펼쳐 같은 key 끼리 비교. 값이 다르면(허용 오차 밖) 충돌
  3) 상태
     ok         비교할 것이 하나뿐이거나 겹치는 교차점 값이 모두 같음 (같으면 '교차 확인' 메모)
     ambiguous  같은 교차점 값이 다른 표가 있음 → 선택지(옵션) + 선택 토큰
     partial    View 는 있으나 필수 메타를 다 쓴 View 가 없음 (비교 안 함, 기존처럼 notes 와 함께 전달)
     empty      View 가 없음
  선택지 = 서로 값이 같은 표끼리 묶은 무리 (A·B 같고 C 다르면 [A,B] / [C])
"""
from __future__ import annotations

from backend.rag.judge.extract import extract_contents
from backend.rag.judge.slots import check_slots
from backend.rag.view.points import key_str, record_points

USED, MISSING = {"match", "not_requested"}, {"missing", "unsupported"}
TARGET_SLOTS = ("지표", "대상")


def _status(x):
    s = getattr(x, "status", None) or (x.get("status") if isinstance(x, dict) else None)
    return getattr(s, "value", s)


def view_usage(record, filters, allow_partial=("시점",)):
    """View 하나가 필수 메타를 썼는가 → {usable, used{slot: bool}, checks{slot: {status, evidence}}, notes}"""
    f = filters or {}
    checks = check_slots(f, extract_contents(record))
    used, info, notes = {}, {}, []
    for slot, ck in checks.items():
        st = _status(ck)
        ev = getattr(ck, "evidence", "") if not isinstance(ck, dict) else ck.get("evidence", "")
        info[slot] = {"status": st, "evidence": ev}
        if st == "not_requested" or slot in ("의도", "비교축"):
            continue
        if st in USED:
            used[slot] = True
        elif st == "partial" and slot in allow_partial:
            used[slot] = True
            notes.append(f"{slot} 대체 적용: {ev}")
        elif st == "unknown":
            used[slot] = True
            notes.append(f"{slot} 확인 불가: {ev}")
        else:
            used[slot] = False
    # 대상 = 지표 또는 대상 중 하나 (Step 2 결정과 같음)
    tg = {s: used[s] for s in TARGET_SLOTS if s in used}
    if len(tg) == 2 and any(tg.values()):
        for s in TARGET_SLOTS:
            used[s] = True
    rec = record if isinstance(record, dict) else record.model_dump(mode="json")
    n_points = int((rec.get("metadata") or {}).get("n_points") or 0)
    rows = (rec.get("table") or {}).get("rows") or []
    empty = not rows or n_points == 0 and not any(r and r[-1] is not None for r in rows)
    if empty:
        notes.append("값이 없는 View")
    return {"usable": all(used.values()) and not empty, "used": used, "checks": info, "notes": notes}


def _differ(a, b, rel, abs_):
    return abs(a - b) > max(abs_, rel * max(abs(a), abs(b)))


def detect(views, filters, settings, unit_id="main"):
    """views: [{record, rank, tbl_id, …}] (run_query 의 units[].views) → 충돌 판정 dict"""
    rel, abs_ = settings.conflict_rel_tol, settings.conflict_abs_tol
    per = []
    for v in views:
        u = view_usage(v["record"], filters, tuple(settings.conflict_allow_partial))
        pts, pnotes = record_points(v["record"], filters) if u["usable"] else ([], [])
        per.append({"record_id": v["record"]["id"], "tbl_id": v["tbl_id"], "rank": v.get("rank"), **u,
                    "n_points": sum(p.value is not None for p in pts), "point_notes": pnotes, "_pts": pts})
    out = {"unit_id": unit_id, "status": "empty", "views": [], "n_compared_keys": 0, "n_agree": 0,
           "differing_points": [], "clusters": [], "notes": []}
    if not views:
        return out
    usable = [p for p in per if p["usable"]]
    index = {}
    for p in usable:
        for pt in p["_pts"]:
            if pt.value is not None:
                index.setdefault(pt.key_str(), {}).setdefault(p["record_id"], pt)
    shared = {k: d for k, d in index.items() if len(d) >= 2}
    diffs = []
    for k, d in shared.items():
        vals = list(d.values())
        if any(_differ(a.value, b.value, rel, abs_) for i, a in enumerate(vals) for b in vals[i + 1:]):
            diffs.append({"key": vals[0].key, "key_str": k,
                          "values": [{"record_id": rid, "tbl_id": pt.tbl_id, "value": pt.raw_value, "unit": pt.unit,
                                      "base_value": pt.value, "labels": pt.labels} for rid, pt in d.items()]})
    out.update(n_compared_keys=len(shared), n_agree=len(shared) - len(diffs), differing_points=diffs,
               views=[{k: v for k, v in p.items() if k != "_pts"} for p in per])
    if not usable:
        out["status"] = "partial"
        out["notes"].append("필수 조건을 모두 담은 View 가 없어 값 비교를 하지 않음 (각 View 의 checks 참고)")
        return out
    if not diffs:
        out["status"] = "ok"
        if shared:
            n_tbl = len({rid for d in shared.values() for rid in d})
            out["notes"].append(f"표 {n_tbl}개가 교차점 {len(shared)}개에서 같은 값 (교차 확인)")
        return out
    out["status"] = "ambiguous"
    out["clusters"] = clusters(usable, index, diffs, rel, abs_)
    out["notes"].append(f"같은 교차점 {len(diffs)}개에서 표마다 값이 다름 → 선택 필요")
    return out


def clusters(usable, index, diffs, rel, abs_):
    """충돌에 걸린 View 들을 '공유 교차점 값이 모두 같은' 무리로 묶음 (검색 순위 순)"""
    involved = {v["record_id"] for d in diffs for v in d["values"]}
    order = [p["record_id"] for p in sorted(usable, key=lambda p: p.get("rank") or 99) if p["record_id"] in involved]
    groups = []
    for rid in order:
        for g in groups:
            ok = True
            for d in index.values():
                if rid in d and g[0] in d and _differ(d[rid].value, d[g[0]].value, rel, abs_):
                    ok = False
                    break
            if ok and any(rid in d and g[0] in d for d in index.values()):
                g.append(rid)
                break
        else:
            groups.append([rid])
    return groups


__all__ = ["detect", "view_usage", "clusters", "key_str"]
