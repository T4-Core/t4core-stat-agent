"""
검색 단위별 View 카드 — view_bundle → 단위마다 표 검색 → 상위 n_views 개 표를 슬롯대로 잘라 Record

  검색 단위 = 본 질의(main) + 서브쿼리 각각 (서브쿼리가 있으면 skip_main 으로 본 질의를 건너뛸 수 있음)
  결과 = {query_id, original, filters, units: [{unit_id, query, search_query, filters, candidates, views, notes}]}
  카드 id = view::표key::주기::질문ID-순위::종류  (서브쿼리는 질문ID 자리에 서브 ID, 예: q1-2)
  fill=True (설정 view_records_per_unit) = 상위 n_views 개를 '시도' 하는 대신 쓸 수 있는 View 가 n_views 개가 될 때까지
    다음 후보로 넘어감. View 생성 실패는 건너뛰고, 요청 지표가 없는 표의 View 는 남기되(지표 없음 안내에 씀) 세지 않음
  본 질의 복사본(roles.py — 역할 단위를 더할 때 본 질의가 빠지지 않게 넣은 하위 단위)은 단위 이름·순서는 그대로 두고
    검색만 본 질의 방식(unit="main")으로 (main_copy). 하위 단위 검색은 그 문장이 주 신호이고 원 질문은 약하게만 써서,
    같은 문장이라도 본 질의(원 질문이 주 신호)로 찾는 쪽이 정확함. 단위 목록을 바꾸지 않는 것은 답변 모듈이
    하위 질문과 단위를 문장·순서로 짝짓기 때문 (backend/agent)
  survey_options: 조사를 지정하지 않았는데 상위 후보가 여러 조사로 갈리고 점수가 비슷하면 조사별 대표 표 (search/surveys.py).
    선택은 filters['조사'] 로 다시 검색 (검색 엔진이 그 조사 밖 표를 survey_miss 로 뒤로)
"""
import time
import uuid

from backend.data_engine.duckdb_client import connect
from backend.rag.search.resolve import search_query
from backend.rag.view.build import build_view

TOP_K = 10
N_VIEWS = 3


def units_of(b, sub_ids=None):
    """view_bundle(dict) → [(unit_id, 자연어, 슬롯 dict)]"""
    qid = b.get("query_id")
    filters = b.get("filters") or {}
    units = [("main", b.get("search_text") or b["original"], filters)]
    subs, sfs = b.get("sub_questions") or [], b.get("sub_filters") or []
    for i, text in enumerate(subs):
        uid = (sub_ids[i] if sub_ids and i < len(sub_ids) else f"{qid}-{i + 1}")
        units.append((uid, text, (sfs[i] if i < len(sfs) else None) or filters))
    return units


def main_copy(units):
    """[(unit_id, 자연어, 슬롯)] → 본 질의 복사본의 번호 (없으면 None). 복사본 = roles.py 가 하위 질의 없던 질문에 역할 단위를
    더하며 넣은 것: 역할(분모·조건) 단위가 있고, 역할 없는 하위 단위가 하나뿐이며 그 문장·슬롯이 본 질의와 같음
    (지표마다 나눈 하위 질의가 우연히 본 질의 문장과 같은 경우는 아님 — 그때 main 은 다른 지표까지 담은 문장)"""
    main = next((i for i, u in enumerate(units) if u[0] == "main"), None)
    if main is None or len(units) < 2:
        return None
    norm = lambda t: " ".join(str(t or "").split())  # noqa: E731
    subs = [i for i in range(len(units)) if i != main]
    plain = [i for i in subs if not (units[i][2] or {}).get("역할")]
    same_f = lambda a, b: {k: v for k, v in (a or {}).items() if k != "원문표현"} ==         {k: v for k, v in (b or {}).items() if k != "원문표현"}  # noqa: E731  (슬롯이 다르면 다른 질문)
    if len(plain) == 1 and len(plain) < len(subs) and norm(units[plain[0]][1]) == norm(units[main][1])             and same_f(units[plain[0]][2], units[main][2]):
        return plain[0]
    return None


def searched_units(units, skip_main=True):
    """[(unit_id, 자연어, 슬롯)] → 앱이 검색하는 '결과' 의 단위 번호 (평가용 — compare 의 앱 기준 지표).
    skip_main 이면 하위 질의가 있을 때 본 질의를 건너뜀. 본 질의 복사본은 본 질의 방식으로 검색하므로 그 결과 = main 의 결과"""
    idx = list(range(len(units)))
    if not skip_main or len(units) < 2:
        return idx
    main = next((i for i, u in enumerate(units) if u[0] == "main"), None)
    if main is None:
        return idx
    copy = main_copy(units)
    return [main if i == copy else i for i in idx if i != main]


def run_query(b, top_k=TOP_K, n_views=N_VIEWS, sub_ids=None, progress=None, search_fn=None, skip_main=False, fill=False):
    """view_bundle 하나 → 단위별 결과 (카드는 units[].views[].record)
    search_fn(query, top_k, filters=, question=, unit=) 를 바꿔 끼울 수 있음 (기본 backend.rag.search)
    fill: 쓸 수 있는 View 가 n_views 개가 될 때까지 후보를 더 봄 (top_k 안에서)"""
    from backend.rag.view.conflict import indicator_missing
    if search_fn is None:
        from backend.rag.search import search_fn as default
        search_fn = default()
    b = dict(b)
    b["query_id"] = b.get("query_id") or uuid.uuid4().hex[:8]
    con = connect()
    out_units = []
    try:
        units = units_of(b, sub_ids)
        copy = main_copy(units) if skip_main else None  # main 도 검색하면 복사본은 하위 단위 그대로 (평가와 같게)
        for i, (uid, text, f) in enumerate(units):
            if skip_main and uid == "main" and len(units) > 1:
                continue
            label = b["query_id"] if uid == "main" else uid
            notes = []
            sq = search_query(text, f)                     # 지역·시점 단어를 빼고 지표·대상 단어를 더함
            cands = search_fn(sq, top_k, filters=f, question=b.get("original"), unit="main" if i == copy else uid)
            views, good = [], 0
            for c in (cands if fill else cands[:n_views]):
                if fill and good >= n_views:
                    break
                t0 = time.time()
                try:
                    rec, vnotes = build_view(c["tbl_id"], f, f"{label}-{c['rank']}", con)
                except Exception as e:  # noqa: BLE001  (View 하나 실패해도 나머지는 계속)
                    notes.append(f"{c['tbl_id']} View 생성 실패: {e.__class__.__name__}: {str(e)[:150]}")
                    continue
                rec["match"] = {"rank": c["rank"], "cover": c.get("cover"), "unmet": c.get("unmet") or []}
                views.append({"record": rec, "notes": [n["text"] for n in vnotes], "rank": c["rank"], "tbl_id": c["tbl_id"]})
                if fill and indicator_missing(rec):
                    notes.append(f"{c['tbl_id']} 는 요청 지표가 없어 세지 않고 다음 후보로")
                else:
                    good += 1
                if progress:
                    progress(f"  [{label}] #{c['rank']} {c['tbl_id']} → {len(rec['table']['rows'])}행 ({time.time() - t0:.1f}초)")
            done = {v["tbl_id"] for v in views}
            for c in cands:
                c["has_view"] = c["tbl_id"] in done
            unit = {"unit_id": uid, "query": text, "search_query": sq, "filters": f, "candidates": cands,
                    "views": views, "notes": notes}
            if not (f or {}).get("조사"):   # 조사를 지정하지 않았고 상위 후보가 여러 조사로 갈리면 → 앱이 물을 수 있는 선택지
                from backend.rag.search.surveys import survey_options
                opts = survey_options(cands[:max(n_views, 5)])
                if opts:
                    unit["survey_options"] = opts
            out_units.append(unit)
    finally:
        con.close()
    return {"query_id": b["query_id"], "original": b["original"], "filters": b.get("filters"), "units": out_units}


def records_of(results):
    """결과(들) → 카드 목록 하나"""
    results = results if isinstance(results, list) else [results]
    return [v["record"] for r in results for u in r["units"] for v in u["views"]]
