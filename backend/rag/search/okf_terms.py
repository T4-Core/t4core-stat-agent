"""
OKF 지식 카탈로그 → 검색 — 개념의 승인된 별칭을 그 개념이 묶인 표의 검색 텍스트에

  table_aliases()    지금 빌드(storage/okf_build/CURRENT)의 개념 → {tbl_id: [{alias, canon, dim, concept}]}
  rerank_notes()     LLM 재정렬 카드에 붙일 표 정의(KOSIS 주석) · 질문에 걸린 개념 (search.yaml llm_rerank.okf)
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


def rerank_notes(tbl_ids, *texts, settings=None, max_chars=220) -> dict:
    """LLM 재정렬 카드에 붙일 OKF 정보 → {tbl_id: [줄]} (빌드가 없거나 오류면 {})
      정의   표의 KOSIS 주석 중 정의·집계 대상·산식 (catalog.json 'definitions' — okf build 2 부터)
      개념   질문·재작성에 제목·별칭·같은 뜻 아님·묶인 이름이 나온 개념(초안·폐기 제외) 중 이 표에 묶인 것
             (질문의 별칭이면 '질문의 X = 이 개념', 같은 뜻 아님이면 '주의: 질문의 X 는 이 개념과 다른 말')"""
    try:
        from backend.core.settings import get_settings
        from backend.rag.okf.catalog import Catalog
        cat = Catalog.current(settings or get_settings())
    except Exception:  # noqa: BLE001  (재정렬은 보조 단계 — OKF 가 없어도 계속)
        return {}
    if cat is None:
        return {}
    ids = [str(t) for t in tbl_ids]
    out = {}
    for t in ids:
        defs = (cat.table(t) or {}).get("definitions") or []
        if defs:
            line, n = [], 0
            for d in defs:
                if n + len(d) > max_chars and line:
                    break
                line.append(d)
                n += len(d)
            out.setdefault(t, []).append("정의: " + " / ".join(line))
    try:
        hits = cat.concepts_for(ids, *texts, limit=10)
    except Exception:  # noqa: BLE001
        hits = []
    for c in hits:
        if ((cat.concept(c["id"]) or {}).get("status") or "stable") in ("draft", "deprecated"):
            continue  # _inbox 초안은 사람이 보기 전 — 카드에 넣지 않음
        why, word = next(iter((c.get("matched") or {}).items()), ("", ""))
        desc = str(c.get("description") or "")
        desc = "" if desc.startswith("(초안)") else desc[:90]
        txt = f"개념 '{c['title']}'" + (f" — {desc}" if desc else "")
        if why == "같은 뜻 아님":
            txt += f" · 주의: 질문의 '{word}' 는 이 개념과 같은 뜻이 아님"
        elif why == "별칭":
            txt += f" · 질문의 '{word}' = 이 개념"
        if c.get("calc"):
            txt += f" · 산식: {c['calc'][0][:80]}"
        for b in c.get("binds") or []:
            tid = str(b.get("tbl_id") or "")
            if tid in ids and txt not in out.get(tid, []):
                out.setdefault(tid, []).append(txt)
    return out
