"""
OKF 지식 카탈로그 → 검색 — 개념의 승인된 별칭을 그 개념이 묶인 표의 검색 텍스트에

  table_aliases()    지금 빌드(storage/okf_build/CURRENT)의 개념 → {tbl_id: [{alias, canon, dim, concept}]}
                     별칭은 '쓸 수 있는 것'만 (lint.alias_active: 사람이 쓴 것 · 기계 제안 + human: 승인). 표에 묶인 개념만
                     (dim_kind 규칙 개념 '노인 → 연령 65세 이상' 은 연령 분류가 있는 모든 표라 검색 신호가 되지 않아 뺌)
  쓰는 곳
    값 채널 (channels.ValueChannel)    별칭을 그 표의 값 표현으로 (가중치 search.yaml okf.value_weight).
                                       질문에서 별칭이 맞으면 정규 이름(모+미혼자녀)도 '연결된 값'으로 → '안 쓰는 분류' 감점 없음
    dense 문서 'okf' (index.dense_doc_views)  표 설명문 + '일상어: 싱글맘, … (모+미혼자녀)' 줄 — --dense-docs okf 로 켬

  끄기: configs/search.yaml okf.enabled: false (검색만) · pipeline.yaml okf_use: false (OKF 전체)
  비교: python -m backend.rag.search.tuning.compare … --okf on off  (같은 질의 분석으로 나란히)
"""
from __future__ import annotations


def table_aliases(settings=None) -> dict:
    """→ {"build": 해시 | None, "by_tbl": {tbl_id: [{alias, canon, dim, concept}]}, "n_alias": 수, "n_tables": 수}"""
    empty = {"build": None, "by_tbl": {}, "n_alias": 0, "n_tables": 0}
    try:
        from backend.core.settings import get_settings
        from backend.rag.okf.catalog import Catalog
        cat = Catalog.current(settings or get_settings())
    except Exception:  # noqa: BLE001  (카탈로그가 없거나 깨져도 검색은 계속)
        return empty
    if cat is None:
        return empty
    by, n = {}, 0
    for c in cat.concepts():
        if c.get("status") == "deprecated" or not c.get("aliases"):
            continue
        for b in c.get("binds") or []:
            tid = b.get("tbl_id")
            if not tid or not b.get("name"):
                continue
            lst = by.setdefault(str(tid), [])
            for a in c["aliases"]:
                if not any(x["alias"] == a and x["canon"] == b["name"] for x in lst):
                    lst.append({"alias": a, "canon": b["name"], "dim": b.get("dim") or "", "concept": c["id"]})
                    n += 1
    return {"build": cat.hash, "by_tbl": by, "n_alias": n, "n_tables": len(by)}


def current_build(settings=None) -> str:
    """지금 OKF 빌드 해시 ('' = 없음) — 검색기 캐시 키 (빌드가 바뀌면 값 채널을 다시 만듦)"""
    try:
        from backend.core.settings import get_settings
        from backend.rag.okf.build import build_root, current
        s = settings or get_settings()
        return current(build_root(s)) if getattr(s, "okf_use", True) else ""
    except Exception:  # noqa: BLE001
        return ""


def alias_line(entries) -> str:
    """dense 문서에 붙일 줄: '일상어: 싱글맘, 한부모 엄마 (모+미혼자녀)'"""
    if not entries:
        return ""
    groups = {}
    for e in entries:
        groups.setdefault(e["canon"], []).append(e["alias"])
    return "일상어: " + " · ".join(f"{', '.join(dict.fromkeys(al))} ({canon})" for canon, al in groups.items())
