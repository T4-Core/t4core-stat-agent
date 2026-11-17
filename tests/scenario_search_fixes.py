"""검색 품질 수정 확인 — 가짜 KOSIS 저장소 (형제 표 · 분모 인구 표 · 오염 함정 값)
tests/test_search_fixes.py 가 STORAGE_DIR 을 임시 폴더로 두고 별도 프로세스로 실행 (HCX 없음)

  P0  원문 표현은 낱말 경계 + 같은 이름만 · 검색 문장의 숫자 조각·반복 · 기준 해 = 자료의 최신 연도
  P1  형제 표((계)/(남)/(여), 전국판/시도판) 중 질문 좌표에 맞는 표가 1위
  P2  분모('…중 몇 퍼센트')·조건('…가 N명 이상') 단위 · 분모 단위는 단순한 인구 표
  P3  LLM 재정렬 카드에 형제 표시, LLM 이 형제를 잘못 골라도 무리 안의 선택은 좌표 규칙
  P5  개념 카탈로그를 읽어 LLM 카드에 '같은 값 묶음' 표시 (P4 는 tests/test_tuning.py)
"""
import json
import sys

FOREIGN = "지방자치단체외국인주민현황"
REG = [("00", "전국", ""), ("11", "서울특별시", "00"), ("11320", "도봉구", "11"),
       ("31", "경기도", "00"), ("31030", "동두천시", "31"), ("31240", "과천시", "31"),
       ("38", "경상남도", "00"), ("38090", "거제시", "38"), ("47", "경상북도", "00"), ("47830", "의성군", "47")]
SIDO = [("00", "전국", ""), ("11", "서울특별시", "00"), ("31", "경기도", "00"), ("38", "경상남도", "00")]
Y = [str(y) for y in range(2015, 2026)]


def _t(tid, nm, survey, levels, items, periods=Y, org="110"):
    return {"org_id": org, "tbl_id": tid, "tbl_nm": nm, "category": survey, "section": "s", "josa": survey,
            "levels": levels, "items": items, "prd_se": "A", "prd_meta": "년", "periods": periods}


TABLES = [
    _t("TX_A002_A", "한국국적을 가지지 않은 자(계)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "한국국적을 가지지 않은 자", "명")]),
    _t("TX_A003_A", "한국국적을 가지지 않은 자(남)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "한국국적을 가지지 않은 자", "명")]),
    _t("TX_A004_A", "한국국적을 가지지 않은 자(여)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "한국국적을 가지지 않은 자", "명")]),
    _t("TX_A010_A", "한국국적을 가지지 않은 자-유학생(계)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "유학생", "명")]),
    _t("TX_A011_A", "한국국적을 가지지 않은 자-유학생(남)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "유학생", "명")]),
    _t("TX_A012_A", "한국국적을 가지지 않은 자-유학생(여)", FOREIGN, [("A", "행정구역별(시군구)", REG)], [("T1", "유학생", "명")]),
    _t("DT_BZ011", "가구주의 성/연령별 추계가구-전국", "장래가구추계",
       [("A", "가구주의 성별", [("0", "계", ""), ("1", "남자", "0"), ("2", "여자", "0")])], [("T1", "추계가구", "가구")],
       [str(y) for y in range(2030, 2041)], org="101"),
    _t("DT_BZ041", "가구주의 성/연령별 추계가구-시도", "장래가구추계",
       [("A", "시도별", SIDO), ("B", "가구주의 성별", [("0", "계", ""), ("1", "남자", "0"), ("2", "여자", "0")])],
       [("T1", "추계가구", "가구")], [str(y) for y in range(2030, 2041)], org="101"),
    _t("DT_POP01", "행정구역(시군구)별 주민등록인구", "주민등록인구현황", [("A", "행정구역(시군구)별", REG)],
       [("T1", "총인구수", "명")], org="101"),
    _t("DT_MOV01", "시군구별 이동자수", "국내인구이동통계", [("A", "행정구역(시군구)별", REG),
       ("B", "이동유형별", [("0", "총전입", ""), ("1", "총전출", ""), ("2", "순이동", "")])], [("T1", "이동자수", "명")], org="101"),
    _t("DT_MOV02", "시군구/성/연령별 이동자수", "국내인구이동통계", [("A", "행정구역(시군구)별", REG),
       ("B", "성별", [("0", "계", ""), ("1", "남자", "0"), ("2", "여자", "0")]),
       ("C", "연령별", [("0", "계", ""), ("1", "0~4세", "0"), ("2", "5~9세", "0"), ("3", "10~14세", "0")])],
       [("T1", "순이동자수", "명")], org="101"),
    # P0 함정: 부분 일치로 잡히던 이름들 ('…까지 하락' 의 '지하', '변화했는가' 의 '변화', '영주시' 의 '영주', '99,000명' 의 '0명')
    _t("DT_TRAP1", "(반)지하 및 옥탑 가구 - 시군구", "인구총조사", [("A", "행정구역별", REG),
       ("B", "거처유형별", [("0", "계", ""), ("1", "(반)지하", "0"), ("2", "옥탑", "0")])], [("T1", "가구", "가구")], org="101"),
    _t("DT_TRAP2", "체류자격별 외국인 변화", FOREIGN, [("A", "체류자격별", [("0", "계", ""), ("1", "영주(F-5)", "0"),
       ("2", "(t+3년)변화", "0"), ("3", "0명", "0")])], [("T1", "외국인", "명")]),
]


def state(question, rewritten, slots, intent="값 조회"):
    return {"state": {"bundle": {"original": question, "rewritten": rewritten, "intent": intent, "sub_questions": []},
                      "raw_slots": slots, "sub_slots": [], "intents": [intent], "sub_intents": [], "hcx_ok": True}}


def main():
    from backend.rag.csv_index.store import build_index as build_csv
    from backend.rag.ingestion.meta_profile import build_all
    from backend.rag.ingestion.table_text import build_index
    build_all()
    build_index(progress=lambda m: None)
    build_csv(scope="all", workers=1, log=lambda *a: None)

    # ── P0 ──
    from backend.rag.csv_index.store import load_index
    from backend.rag.query_analyzer.lexicon import get_lexicon
    idx = load_index()
    lex = get_lexicon()
    qt = lambda q, cov=(): lex.question_terms(q, list(cov), max_share=0.5)     # 가짜 저장소는 표가 13개뿐
    assert qt("과천시에 사는 유학생들이 2011년과 비교해서 2012년에는 몇 퍼센트 줄었나요?", ["외국인", "인구수"]) == ["유학생"]
    for q in ("동두천시 인구가 2024년까지 하락했나요", "국제결혼 이주자의 수는 2015년에 비해 얼마나 변화했는가?",
              "영주시 외국인 인구", "가구원수가 99,000명 이상인 지역", "의성군 외국인 수", "경기도 유학생 수"):
        got = qt(q)
        assert not set(got) & {"(반)지하", "(t+3년)변화", "영주(F-5)", "0명", "의성", "경기도"}, (q, got)
    assert qt("반지하 말고 (반)지하 가구") == ["(반)지하"], qt("반지하 말고 (반)지하 가구")   # 같은 이름은 그대로 잡음
    assert lex.token_terms("국제결혼가정 자녀수가 330명 이상", exact=False) is not None
    from backend.rag.search.resolve import tidy_query
    assert tidy_query("0 가구 평균 가구원수 2인 가구수 지역별 0명") == "평균 가구원수 2인 가구수 지역별", \
        tidy_query("0 가구 평균 가구원수 2인 가구수 지역별 0명")
    assert tidy_query("남자 여자 인구수 시도별 인구 인구수 0명") == "남자 여자 인구수 시도별"
    assert tidy_query("5가구 호수 33,000") == "5가구 호수"                 # 숫자가 뜻의 일부인 말은 남김
    assert tidy_query("이동 통계 인구이동") == "이동 통계 인구이동"        # 다른 복합어 안의 말은 남김 ('말+수' 만 뺌)
    assert idx.latest_year(upto=2026) == 2025, idx.latest_year(upto=2026)  # 추계(2030~2040)는 표 수가 적어 빠짐
    from backend.rag.query_analyzer.analyze import analyze
    a = analyze("요즘 동두천시 인구", today="2026-11-16", overrides={"base_year_mode": "data", "clarify_mode": "soft"},
                previous=state("요즘 동두천시 인구", "동두천시 인구수", {"지역": ["동두천시"], "지표": ["인구수"]}))
    assert a["view_bundle"]["filters"]["시점"] == [2025], a["view_bundle"]["filters"]
    a = analyze("1985년 안동군의 주택 총계", today="2026-11-16", overrides={"clarify_mode": "soft"},
                previous=state("1985년 안동군의 주택 총계", "1985년 안동군 주택", {"시점": ["1985년"], "지역": ["안동군"]}))
    assert "안동" not in (a["view_bundle"]["filters"].get("지표") or []), a["view_bundle"]["filters"]
    print("[P0] 원문 표현·검색 문장·기준 해 OK")

    # ── P1 ──
    import backend.rag.search.engine as R
    from backend.rag.search import get_search
    from backend.rag.search.siblings import core_title, table_sex
    assert core_title("한국국적을 가지지 않은 자-기타(계)(2007~2015)") == core_title("한국국적을 가지지 않은 자-기타(남)")
    assert core_title("가구주의 성/연령별 추계가구-전국") == core_title("가구주의 성/연령별 추계가구-시도")
    assert table_sex("…(여)") == "여" and table_sex("…(계)") == "계" and table_sex("주민등록인구") is None
    R._cache.clear()
    s = get_search(dense="none")
    assert s.sib.info()["groups"] >= 3, s.sib.info()
    top1 = lambda q, query, f=None, **kw: s.search(query, f, 5, question=q, **kw)["hits"][0]["tbl_id"]
    q = "거제시의 한국 국적을 가지지 않은 자의 인구 수가 2015년 대비 2018년에 얼마나 변화했는가?"
    assert top1(q, "한국국적을 가지지 않은 자 인구수", {"시점": [2015, 2018], "지역": ["거제시"]}) == "TX_A002_A"
    q = "거제시 한국 국적을 가지지 않은 여성 수는 2018년에 몇 명?"
    assert top1(q, "한국국적을 가지지 않은 자 여자", {"시점": [2018], "지역": ["거제시"], "성별": ["여자"]}) == "TX_A004_A"
    q = "서대문구에 사는 외국인 유학생 남성 수가 2018년에 비해 2024년에 얼마나 증가했나요?"
    assert top1(q, "유학생 남자", {"시점": [2018, 2024]}) == "TX_A011_A"
    q = "2033년과 2039년의 가구주 여자의 총 추계가구의 증감률을 구하시오."
    assert top1(q, "가구주 여자 추계가구", {"시점": [2033, 2039]}) == "DT_BZ011"
    q = "2035년 서울 가구주가 여자인 추계가구"
    assert top1(q, "가구주 여자 추계가구", {"시점": [2035], "지역": ["서울특별시"]}) == "DT_BZ041"
    r = s.search("한국국적을 가지지 않은 자 인구수", {"시점": [2015, 2018]}, 5,
                 question="거제시의 한국 국적을 가지지 않은 자의 인구 수가 2015년 대비 2018년에 얼마나 변화했는가?")
    assert "siblings" in r
    print("[P1] 형제 표 OK")

    # ── P2 ──
    from backend.rag.query_analyzer.roles import find_roles
    assert find_roles("2025년 동두천시 인구 중 순이동이 몇 퍼센트일까?", lex) == [("분모", "인구")]
    assert find_roles("국제결혼가정 자녀 수가 330명 이상인 행정구역(시군구) 중에서 외국인 근로자 증가율", lex) == \
        [("조건", "국제결혼가정 자녀 수")]
    assert find_roles("1985년에 안동군에서는 인구 천 명당 주택이 몇 호나 있었을까?", lex) == [("분모", "인구")]
    assert find_roles("2023년 서울 출생아 수", lex) == []
    assert find_roles("포천시 출생 인구 중 계의 2018년 대비 2021년의 증감률(%)", lex) == []     # 'X 중 계' 는 합계 행
    q = "2025년 동두천시 인구 중 순이동이 몇 퍼센트일까?"
    a = analyze(q, today="2026-11-16", overrides={"clarify_mode": "soft"},
                previous=state(q, "2025년 동두천시 순이동 인구수 비율", {"시점": ["2025년"], "지역": ["동두천시"], "지표": ["순이동"]},
                               "구성비"))
    vb = a["view_bundle"]
    roles = [(t, (f or {}).get("역할")) for t, f in zip(vb["sub_questions"], vb["sub_filters"] or [])]
    assert ("인구", "분모") in roles and roles[0][1] is None, roles             # 첫 단위 = 본 질의, 다음 = 분모
    assert len(a["sub_queries"]) == len(vb["sub_questions"]), (a["sub_queries"], vb["sub_questions"])
    den = s.search("인구", {"시점": [2025], "지역": ["동두천시"], "역할": "분모"}, 5, question=q, unit="S2")
    assert den["hits"][0]["tbl_id"] == "DT_POP01", den["hits"][:3]
    gen = s.search("인구", {"시점": [2025], "지역": ["동두천시"]}, 5, question=q, unit="S2")   # 역할이 없어도 '인구' 뿐이면 분모
    assert gen["hits"][0]["tbl_id"] == "DT_POP01", gen["hits"][:3]
    main = s.search("순이동 인구수", {"시점": [2025], "지역": ["동두천시"]}, 5, question=q)
    assert main["hits"][0]["tbl_id"] in ("DT_MOV01", "DT_MOV02"), main["hits"][:3]
    print("[P2] 역할 분해 OK")

    # ── P3 ──
    seen = {}

    def fake_chat(msgs, schema=None, max_tokens=None):
        seen["user"] = msgs[-1]["content"]
        cards = [l for l in seen["user"].splitlines() if l.startswith("[")]
        n_f = next(int(l[1:l.index("]")]) for l in cards if "(여)" in l)   # 일부러 (여) 를 1위로 (질문에 성별 없음)
        return {"order": [n_f] + [i for i in range(1, len(cards) + 1) if i != n_f]}

    R._cache.clear()
    s3 = R.TableSearch(s.corpus, "search+llm", None, llm_rerank=True, chat_fn=fake_chat)
    q = "거제시의 한국 국적을 가지지 않은 자의 인구 수가 2015년 대비 2018년에 얼마나 변화했는가?"
    r = s3.search("한국국적을 가지지 않은 자 인구수", {"시점": [2015, 2018], "지역": ["거제시"]}, 5, question=q)
    assert "형제 A" in seen["user"] and "성별 여" in seen["user"], seen["user"][:800]
    assert r["hits"][0]["tbl_id"] == "TX_A002_A", [(h["tbl_id"], h.get("stages", {}).get("llm")) for h in r["hits"]]
    assert r["llm"] == "llm"
    # 끼워 넣는 형제·같은 개념 표는 상위 top_n 뒤에 붙음 (앞 순위를 밀어내지 않음)
    final = __import__("numpy").ones(len(s3.docs))
    head = ["TX_A010_A", "DT_POP01", "DT_MOV01"]
    got = s3._with_siblings(head + ["DT_MOV02"], 2, 2, final)
    assert got[:2] == head[:2] and set(got[2:4]) == {"TX_A011_A", "TX_A012_A"} and got[4:] == ["DT_MOV01", "DT_MOV02"], got
    # 분모 단위는 LLM 을 건너뛰고, 하위 단위는 그 단위 문장을 [찾는 것] 으로
    seen.clear()
    q = "2025년 동두천시 인구 중 순이동이 몇 퍼센트일까?"
    den = s3.search("인구", {"시점": [2025], "지역": ["동두천시"], "역할": "분모"}, 5, question=q, unit="S2")
    assert den["llm"].startswith("건너뜀") and not seen and den["hits"][0]["tbl_id"] == "DT_POP01", den["llm"]
    sub = s3.search("순이동", {"시점": [2025], "지역": ["동두천시"]}, 5, question=q, unit="S1")
    assert "[찾는 것] 순이동" in seen["user"] and f"[원래 질문] {q}" in seen["user"], seen["user"][:300]
    print("[P3] LLM 카드·형제 규칙·후보 위치·하위 단위 OK")

    # ── P5 ── 개념 카탈로그 (같은 값을 주는 표 묶음): LLM 후보에 끌어오고 카드에 표시. 무리 안 바꿔치기에는 안 씀
    import tempfile
    from pathlib import Path
    cat = Path(tempfile.mkdtemp()) / "concepts.json"
    cat.write_text(json.dumps({"concepts": [{"id": "C001", "name": "x", "tables": ["TX_A010_A", "DT_POP01"]}]}), encoding="utf-8")
    s5 = R.TableSearch(s.corpus, "search+llm", None, settings={"concepts": {"path": str(cat)}}, llm_rerank=True, chat_fn=fake_chat)
    assert s5.concept_of == {"TX_A010_A": 0, "DT_POP01": 0}
    q = "과천시 유학생 수는 2020년에 몇 명?"
    r = s5.search("유학생", {"시점": [2020], "지역": ["과천시"]}, 5, question=q)
    assert "같은 값 묶음 C1" in seen["user"], seen["user"][:1500]
    assert r["hits"][0]["tbl_id"].startswith("TX_A01"), r["hits"][:3]
    print("[P5] 개념 카탈로그 OK")
    print(json.dumps({"SEARCH_FIXES": "PASS"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        import traceback
        traceback.print_exc()
        print("FAIL", e)
        sys.exit(1)
