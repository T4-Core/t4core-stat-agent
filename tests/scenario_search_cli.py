"""검색 시나리오 — 가짜 KOSIS 저장소에서 색인 → (값 사전 없이 / 있을 때) 검색 → 비교·튜닝 도구 → View 단계까지
tests/test_search_fixes.py 가 STORAGE_DIR 을 임시 폴더로 두고 별도 프로세스로 실행한다 (HCX·네트워크 없음)"""
import json
import sys
import tempfile
from pathlib import Path

import backend.core.llm as llm
from tests import fake_kosis

llm._post = fake_kosis.fake_hcx_post


def main():
    from backend.rag.ingestion.meta_profile import build_all
    from backend.rag.ingestion.table_text import build_index
    build_all()
    build_index(progress=lambda m: None)

    import backend.rag.search.engine as R
    from backend.rag.search import get_search, search_fn
    s = get_search(dense="none")
    assert set(f.source for f in s.facets.values()) == {"meta"}, "값 사전이 없으면 메타 프로필"
    r = s.search("혼인 이혼", None, 5, question="2023년 대구에서 결혼한 커플 수와 헤어진 부부 수")
    assert r["hits"][0]["tbl_id"] == "DT_X003", r["hits"][:3]
    assert r["parsed"]["years"] == [2023] and r["parsed"]["sido"] == ["대구"]
    r = s.search("인구", {"시점": [2020], "성별": ["여자"]}, 5, question="2020년 대전 20대 후반 여자 인구")
    assert r["hits"][0]["tbl_id"] == "DT_1IN1503", r["hits"][:3]          # 2020 은 5년 주기 표에만
    assert "cost" in r["hits"][0]

    # CSV 값 사전을 만들면 실제 수록 연도·값 전체를 씀
    from backend.rag.csv_index.store import build_index as build_csv
    build_csv(scope="all", workers=1, log=lambda *a: None)
    R._cache.clear()
    s2 = get_search(dense="none")
    assert "csv" in {f.source for f in s2.facets.values()}
    f = s2.facets["DT_1IN1503"]
    assert f.years == frozenset({2015, 2020, 2025}), f.years              # 메타의 범위(2015~2025)가 아니라 실제 연도
    r = s2.search("인구", None, 5, question="2022년 대전 여자 인구")
    assert r["hits"][0]["tbl_id"] != "DT_1IN1503", r["hits"][:3]          # 2022 는 그 표에 없음

    # 비교 도구
    from backend.rag.search.tuning.compare import main as compare
    gold = Path(tempfile.mkdtemp()) / "golden.jsonl"
    rows = [{"qid": "T1", "split": "dev", "qtype": "concept", "question": "2023년 대구에서 결혼한 커플 수", "required": [["101_DT_X003"]]},
            {"qid": "T2", "split": "dev", "qtype": "exact_name", "question": "시도별 평균 초혼연령", "required": [["101_DT_X011"]]},
            {"qid": "T3", "split": "test", "qtype": "multi_table", "question": "2024년 서울 출생아수와 사망자수",
             "required": [["101_DT_X001"], ["101_DT_X002"]]}]
    gold.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    out = compare(["--golden", str(gold), "--dense", "none", "--analyze", "none",
                   "--out", str(gold.parent / "run")])
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summ_all = next(t for t in summ["table"] if t["config"] == "search[none]" and t["group"] == "ALL")
    assert summ_all["hit@3"] == 1.0 and summ_all["groups@5"] == 1.0, summ_all

    # 남은 실패 점검표: 만들기 → 판정 → 판정 반영 지표
    from backend.rag.search.tuning import audit
    per_q = out / "per_query.csv"
    with per_q.open(encoding="utf-8-sig") as fh:
        prow = list(__import__("csv").DictReader(fh))
    prow[0].update({"hit@1": "0", "rank": "2", "top5": "DT_X002 DT_X003"})            # 일부러 놓친 문항 하나
    with per_q.open("w", encoding="utf-8-sig", newline="") as fh:
        w = __import__("csv").DictWriter(fh, fieldnames=list(prow[0]))
        w.writeheader()
        w.writerows(prow)
    sheet = audit.make(str(per_q), out=str(gold.parent / "audit.csv"), config="search[none]")
    arows = list(__import__("csv").DictReader(open(sheet, encoding="utf-8-sig")))
    assert len(arows) == 1 and arows[0]["top1_name"], arows
    arows[0]["판정"] = "C"
    with open(sheet, "w", encoding="utf-8-sig", newline="") as fh:
        w = __import__("csv").DictWriter(fh, fieldnames=list(arows[0]))
        w.writeheader()
        w.writerows(arows)
    sc = audit.score(str(per_q), sheet, config="search[none]")
    assert sc["ALL"]["C"] == 1 and sc["ALL"]["hit@1_judged"] == 1.0, sc

    # 가중치 맞추기 (dev 문항)
    from backend.rag.search.tuning.tune import main as tune
    tuned = tune(["--golden", str(gold), "--analyze", "none", "--rounds", "1", "--out", str(gold.parent / "tuned.yaml")])
    assert tuned["after"]["score"] >= tuned["before"]["score"]

    # 여러 표 상한 실험: 근거 그룹 설명을 하위 단위로 (분석은 캐시에서 — HCX 없음)
    from backend.rag.search.tuning.oracle_groups import main as oracle
    syn = gold.parent / "synthetic.jsonl"
    q = "2024년 서울에서 태어난 아이 수는 세상을 떠난 사람 수의 몇 배인가?"
    syn.write_text(json.dumps({"dataset_id": "SG-T1", "answerability_type": "ANSWERABLE", "hop_type": "MULTI_TABLE_MULTI_VIEW",
                               "question_original": q, "retrieval_eval": {
                                   "golden_table_ids": ["101_DT_X001", "101_DT_X002"],
                                   "required_evidence_groups": {
                                       "R1": {"description": "2024년 출생아수 (서울특별시)", "acceptable_table_ids": ["101_DT_X001"]},
                                       "R2": {"description": "2024년 사망자수 (서울특별시)", "acceptable_table_ids": ["101_DT_X002"]}}}},
                              ensure_ascii=False), encoding="utf-8")
    cache = gold.parent / "cache.jsonl"
    cache.write_text(json.dumps({"key": "x", "question": q, "units": [
        {"unit": "main", "text": q, "search_query": q, "filters": {"시점": [2024], "지역": ["서울특별시"]}}]},
        ensure_ascii=False), encoding="utf-8")
    o = oracle(["--golden", str(syn), "--cache", str(cache), "--dense", "none", "--variants", "O", "--out", str(gold.parent / "oracle")])
    rows = list(__import__("csv").DictReader((o / "per_query.csv").open(encoding="utf-8-sig")))
    assert rows[0]["groups@5_oracle"] == "1" and int(rows[0]["n_units_oracle"]) == 3, rows

    # View 단계: run_query 가 원문을 넘겨 줌
    from backend.rag.view.run import run_query
    res = run_query({"query_id": "t1", "original": "2025년 대전 인구 수", "search_text": "인구수",
                     "filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["인구수"]}}, 5, 1, search_fn=search_fn(dense="none"))
    u = res["units"][0]
    assert u["candidates"] and u["views"], u["notes"]
    print(json.dumps({"SEARCH_CLI": "PASS", "summary": summ_all, "tuned": tuned["after"]}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()


SIDO = fake_kosis.SIDO
EXTRA = [  # (tbl_id, tbl_nm, category, items[(id, 이름, 단위)])
    ("DT_X001", "시도별 출생아수 및 합계출산율", "인구동향조사", [("T1", "출생아수", "명"), ("T2", "합계출산율", "가임여성 1명당 명")]),
    ("DT_X002", "시도별 사망자수", "인구동향조사", [("T1", "사망자수", "명")]),
    ("DT_X003", "시도별 혼인·이혼 건수", "인구동향조사", [("T1", "혼인건수", "건"), ("T2", "이혼건수", "건")]),
    ("DT_X004", "시도별 1인가구 수", "인구총조사", [("T1", "1인가구", "가구")]),
    ("DT_X005", "가구원수별 가구", "인구총조사", [("T1", "일반가구", "가구"), ("T2", "1인가구", "가구"), ("T3", "2인가구", "가구")]),
    ("DT_X006", "시도별 외국인 주민 수", "지방자치단체외국인주민현황", [("T1", "외국인주민수", "명")]),
    ("DT_X007", "시도별 고령인구 비율", "주민등록인구현황", [("T1", "65세이상인구비율", "%")]),
    ("DT_X008", "시도별 주택 수", "주택총조사", [("T1", "주택수", "호")]),
    ("DT_X009", "시도별 경제활동인구", "경제활동인구조사", [("T1", "경제활동인구", "천명"), ("T2", "취업자", "천명"), ("T3", "실업자", "천명")]),
    ("DT_X010", "시도별 실업률", "경제활동인구조사", [("T1", "실업률", "%")]),
    ("DT_X011", "시도별 평균 초혼연령", "인구동향조사", [("T1", "평균초혼연령", "세")]),
    ("DT_X012", "시도별 인구밀도", "주민등록인구현황", [("T1", "인구밀도", "명/㎢")]),
    ("DT_X013", "시도별 순이동자수", "국내인구이동통계", [("T1", "순이동", "명"), ("T2", "전입자수", "명")]),
    ("DT_X014", "시도별 다문화 출생아수", "다문화인구동태통계", [("T1", "다문화출생아수", "명")]),
    ("DT_X015", "시도별 장래인구추계", "장래인구추계", [("T1", "추계인구", "명")]),
]


def extra_tables():
    return [{"org_id": "101", "tbl_id": t, "tbl_nm": nm, "category": cat, "section": nm, "josa": cat,
             "levels": [("A", "행정구역(시도)별", SIDO)], "items": items, "prd_se": "A", "prd_meta": "년",
             "periods": [str(y) for y in range(2021, 2026)]} for t, nm, cat, items in EXTRA]


