"""앞단 수정 (09) — 분기 표현 · 이동 범위·방향 · 조건 누락 · 읍면동 표 · 하위 질문 검증 · compare arms
실제 실패 사례(합성 셋 hard)를 작은 코퍼스로 (HCX·저장소 파일 없음)"""
from datetime import date

import pytest

from backend.rag.ingestion.table_text import table_text
from backend.rag.query_analyzer.subcheck import clean_text, clean_value, prune_sub_slots, prune_units
from backend.rag.search.engine import TableSearch
from backend.rag.search.index import Doc
from backend.rag.search.movement import move_factor, question_move, table_move
from backend.rag.search.query import parse_question
from tests.test_search import PROFILES, P, SEX, _dim, _regions

EMD = {"kind": "regions", "obj_nm": "행정구역(읍면동)별", "names": ["전국", "서울특별시", "장안구", "파장동"],
       "sido": ["서울특별시"], "n_codes": 4, "geo_types": {"전국": 1, "시도": 1, "시군구": 1, "읍면동": 1}}
SGG = {"kind": "regions", "obj_nm": "행정구역(시군구)별", "names": ["전국", "서울특별시", "장안구"],
       "sido": ["서울특별시"], "n_codes": 3, "geo_types": {"전국": 1, "시도": 1, "시군구": 1}}
MOVE = [
    P("MV_SGG", "시군구별 이동자수", "국내인구이동통계", (2015, 2025), ["총전입", "총전출", "순이동"], [_regions("시군구")], se="월"),
    P("MV_REASON", "시도/전입사유별 이동건수", "국내인구이동통계", (2015, 2025), ["총전입", "시도내-시군구간", "시도간"],
      [_regions("시도"), _dim("전입사유별", ["계", "직업", "가족", "주택"])], unit="건"),
    P("MV_OD", "전출지/전입지(시도)별 이동자수", "국내인구이동통계", (2015, 2025), ["이동자수"],
      [_dim("전출지별", ["전국", "서울특별시", "부산광역시"]), _dim("전입지별", ["전국", "서울특별시", "부산광역시"])], se="분기"),
    P("FR_CHILD_M", "시군구별 연령별 외국인주민 자녀(남)", "지방자치단체외국인주민현황", (2015, 2024), ["외국인주민 자녀수"],
      [SGG, _dim("연령별", ["계", "만6세 이하", "만7~12세"], "ages")]),
    P("FR_CHILD_T", "시군구별 연령별 외국인주민 자녀(계)", "지방자치단체외국인주민현황", (2015, 2024), ["외국인주민 자녀수"],
      [SGG, _dim("연령별", ["계", "만6세 이하", "만7~12세"], "ages")]),
    P("FR_EMD", "읍면동별 외국인주민 자녀 현황", "지방자치단체외국인주민현황", (2015, 2024), ["외국인주민 자녀수"], [EMD]),
]


class Corpus:
    name = "test-front"

    def __init__(self):
        self._docs = [Doc(p["tbl_id"], table_text(p), {"tbl_nm": p["tbl_nm"], "survey_nm": p["survey_nm"], "profile": p})
                      for p in PROFILES + MOVE]

    def docs(self):
        return self._docs

    def signature(self):
        import hashlib
        return "test:front:" + hashlib.sha1("|".join(d.text for d in self._docs).encode()).hexdigest()[:12]


@pytest.fixture(scope="module")
def s():
    return TableSearch(Corpus(), facets_source="meta", llm_rerank=False)


def hits(s, question, rewrite=None, filters=None, k=5):
    return s.search(rewrite or question, filters, k, question=question, today="2026-11-18")["hits"]


def ids(s, *a, **kw):
    return [h["tbl_id"] for h in hits(s, *a, **kw)]


def feas_off(s, **kw):
    from backend.rag.search.tuning.compare import with_feas
    return with_feas(s, kw)


# ── 분기 ──
def test_quarter_words():
    for q in ("2021년 네 번째 분기에 이동자수", "2021년 4/4분기 이동자수", "2021년 Q4 이동자수", "2021년 4분기 이동자수"):
        v = parse_question(q)
        assert v.cycle == {"Q"} and "분기" not in v.lex and "번째" not in v.lex and v.years == [2021], q
    assert "분기별" in parse_question("분기별 인구이동률").lex          # 주기를 묻는 말은 남김


def test_quarter_prefers_native_cycle(s):
    h = {x["tbl_id"]: x for x in hits(s, "2021년 네 번째 분기에 전국 이동자수", "이동자수", k=10)}
    assert "주기 계산" in h["MV_SGG"]["feas_notes"]                    # 월 자료 (분기는 계산) → 조금 뒤로
    assert "주기 계산" not in (h.get("MV_OD", {}).get("feas_notes") or [])


# ── 이동 범위·방향 ──
def test_question_move():
    assert question_move("2017년에 국내에서 다른 시도로 이사 간 총 건수") == {"scope": "시도간", "dir": "전출", "intl": False}
    assert question_move("2019년에 다른 시도에서 전라남도로 이사 온 사람") == {"scope": "시도간", "dir": "전입", "intl": False}
    assert question_move("2021년 4분기 전출지와 전입지의 이동자수") is None   # 전출지·전입지 = 행렬 축, 방향 아님
    assert question_move("2023년 출국자 수")["intl"] and question_move("2023년 혼인 건수") is None


def test_table_move(s):
    f = {x.tbl_id: x for x in s.ch.facets}
    assert table_move(f["MV_REASON"])["codes"] >= {"시도간", "전입"}
    assert table_move(f["MV_OD"])["od"] and not table_move(f["MV_SGG"])["od"]
    assert not table_move(f["DT_1B81A23"])["move"]                    # 이동 표가 아니면 계수 없음
    fz = {"move_miss": 0.6, "move_derived": 0.9}
    qm = question_move("다른 시도로 이사 간 사람")
    assert move_factor(qm, table_move(f["MV_SGG"]), fz)[0] == 0.6
    assert move_factor(qm, table_move(f["MV_OD"]), fz)[0] == 0.9       # 행렬에서 계산
    assert move_factor(qm, table_move(f["MV_REASON"]), fz) == (1.0, None)
    assert move_factor(qm, table_move(f["DT_1B81A23"]), fz) == (1.0, None)


def test_move_scope_reorders(s):
    q = "2017년에 국내에서 다른 시도로 이사 간 총 건수는 얼마나 되나요?"
    new = ids(s, q, "인구 전출 이동자수", k=12)
    old = ids(feas_off(s, move_miss=1.0, move_derived=1.0), q, "인구 전출 이동자수", k=12)
    assert new.index("MV_REASON") < new.index("MV_SGG")
    assert new.index("MV_SGG") > old.index("MV_SGG")                  # '시도간' 이 없는 일반 이동 표는 뒤로
    h = {x["tbl_id"]: x for x in hits(s, q, "인구 전출 이동자수", k=12)}
    assert "이동 시도간 없음" in h["MV_SGG"]["feas_notes"] and "이동 시도간 계산" in h["MV_OD"]["feas_notes"]


# ── 조건 누락 ──
def test_condition_penalty(s):
    q = "2025년 서울특별시에서 쌍태아 이상을 포함한 총 출생 수가 2020년에 비해 얼마나 증가했나요?"
    h = {x["tbl_id"]: x for x in hits(s, q, "출생아수 쌍태아", {"시점": [2020, 2025], "원문표현": ["쌍태아"]}, k=10)}
    assert any("조건 없음(쌍태아" in n for n in h["DT_1B81A23"]["feas_notes"])
    assert not any("조건 없음" in n for n in h["DT_1B81A13"]["feas_notes"])
    other = [x for x in h.values() if x["survey_nm"] != "인구동향조사"]
    assert all(not any("조건 없음" in n for n in (x["feas_notes"] or [])) for x in other)  # 다른 조사 표는 그대로


def test_condition_terms_skip_regions_and_added_words(s):
    narrow = feas_off(s, cond_df=3)
    t = narrow.specific_terms(s.ch.value.link("총전입남자서울특별시"), {"원문표현": ["쌍태아", "남자"], "조건": ["서울특별시"]})
    assert set(t) == {"쌍태아"}                                        # 총전입은 이동 표 4개 (cond_df 3 보다 많음 → 아님)
    # 일상어 사전이 더한 말은 조건으로 쓰지 않음 ('남자가' 의 '자가' → 자기집 이던 문제도 함께)
    v = parse_question("가구주 남자가 미혼인 5인 이상 가구")
    assert "자기집" not in v.added


# ── 읍면동까지 나뉜 표 ──
def test_geo_finer(s):
    h = {x["tbl_id"]: x for x in hits(s, "장안구에서 외국인 주민의 자녀 수가 2020년에 비해 2023년에 얼마나 증가했나요?",
                                      "외국인 주민의 자녀 수", {"시점": [2020, 2023], "지역": ["장안구"]}, k=10)}
    assert "읍면동까지 나뉨" in h["FR_EMD"]["feas_notes"]
    assert "읍면동까지 나뉨" not in (h["FR_CHILD_M"]["feas_notes"] or [])


# ── 하위 질문 검증 ──
def test_clean_value():
    assert clean_value("수(水)") == "수" and clean_text("모든 교육 수준 남편 수 수(水)") == "모든 교육 수준 남편 수"


def _u(uid, q, **f):
    return {"unit": uid, "text": q, "search_query": q, "filters": f or None}


def test_prune_units_denominator_like():
    q = "2017년에 국내에서 다른 시도로 이사 간 총 건수는 얼마나 되나요?"
    units = [_u("main", "인구 전출 이동자수", 시점=[2017], 대상=["인구"], 지표=["이동자수"]),
             _u("k-1", "이동자수", 시점=[2017], 지표=["이동자수"]), _u("k-2", "인구", 시점=[2017], 대상=["인구"])]
    out, log = prune_units(q, units)
    assert [u["unit"] for u in out] == ["main"] and len(log) == 2


def test_prune_units_hanja_and_single():
    q = "2025년에 실시된 인구동향조사에서 전체 연령대와 모든 교육 수준을 포함한 남편의 수는 몇 건인가요?"
    units = [_u("main", "모든 교육 수준 남편 수 수(水)", 대상=["남편"], 지표=["수"]),
             _u("k-1", "수(水)", 지표=["수(水)"]), _u("k-2", "남편", 대상=["남편"])]
    out, _ = prune_units(q, units)
    assert [u["unit"] for u in out] == ["main"] and out[0]["search_query"] == "모든 교육 수준 남편 수"


def test_prune_units_keeps_real_splits():
    # 비율 질문 · 역할 단위 · 자리가 다른 일반 말 · 지표가 둘
    q = "2022년 연수구 총인구 중 시도간 전입 인구의 비율"
    units = [_u("main", "시도간 전입 인구", 지표=["시도간 전입"]), _u("k-1", "시도간 전입", 지표=["시도간 전입"]),
             _u("k-2", "인구", 지표=["인구"], 역할="분모")]
    out, _ = prune_units(q, units)
    assert "k-2" in [u["unit"] for u in out]
    q = "2020년 서울 출생아수와 2023년 부산 인구"
    units = [_u("main", "출생아수 인구", 지표=["출생아수", "인구"]),
             _u("k-1", "출생아수", 시점=[2020], 지역=["서울"], 지표=["출생아수"]),
             _u("k-2", "인구", 시점=[2023], 지역=["부산"], 지표=["인구"])]
    assert len(prune_units(q, units)[0]) == 3
    q = "2023년 혼인 건수와 출생아 수"
    units = [_u("main", "혼인건수 출생아수", 지표=["혼인건수", "출생아수"]), _u("k-1", "혼인건수", 지표=["혼인건수"]),
             _u("k-2", "출생아수", 지표=["출생아수"])]
    assert len(prune_units(q, units)[0]) == 3


def test_prune_sub_slots_and_validate():
    main = {"대상": ["인구"], "지표": ["이동자수"], "시점": ["2017년"]}
    subs = [{"지표": ["이동자수"], "대상": [], "시점": ["2017년"]}, {"대상": ["인구"], "지표": [], "시점": ["2017년"]}]
    kept, log = prune_sub_slots("2017년에 다른 시도로 이사 간 총 건수", main, subs)
    assert kept == [] and log
    from backend.rag.query_analyzer.extract import rule_extract
    from backend.rag.query_analyzer.terms import lookup_terms
    from backend.rag.query_analyzer.validate import validate_slots
    q = "2025년 인구동향조사에서 모든 교육 수준을 포함한 남편의 수는 몇 건인가요?"
    q2, found, _ = rule_extract(q, date(2026, 11, 18))
    v = validate_slots({"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
                        "hcx_slots": {"대상": ["남편"], "지표": ["수(水)"], "의도": "값 조회"},
                        "hcx_subs": [{"지표": ["수(水)"], "의도": "값 조회"}, {"대상": ["남편"], "의도": "값 조회"}]})
    assert v["slots"]["지표"] == [] and v["sub_slots"] == []


# ── compare arms ──
def test_arms(s):
    from backend.rag.search.tuning.compare import ARMS, arm_settings, evaluate_one, with_feas
    assert arm_settings("all") == ({}, True) and arm_settings("off")[1] is False
    off = with_feas(s, {**arm_settings("off")[0], "rate_miss": 1.0, "count_miss": 1.0})  # 이후에 더한 단위 계수도 끔 (앞단 수정의 몫만 보게)
    assert off.s["feas"]["move_miss"] == 1.0 and s.s["feas"]["move_miss"] == 0.6 and off.ch is s.ch
    assert set(ARMS) >= {"off", "units", "move", "cond", "cycle", "geo", "all"}
    row = {"question": "2017년에 국내에서 다른 시도로 이사 간 총 건수는 얼마나 되나요?", "gold": ["MV_REASON"],
           "groups": {"R1": ["MV_REASON"]}}
    units = [_u("main", "인구 전출 이동자수", 시점=[2017])]
    assert evaluate_one(s, row, units, 10, 50)["rank"] < evaluate_one(off, row, units, 10, 50)["rank"]


# ── 대체 정답: 항목 이름이 다른 같은 값 (alt_gold --loose-items) ──
def test_alt_gold_loose_items():
    from decimal import Decimal

    from backend.rag.search.tuning.alt_gold import Judge

    class Idx:
        v = {"name": ["전국", "총전입", "이동자수"], "std": [None] * 3, "slot": ["지역", "지표", "지표"],
             "kind": ["dim", "item", "item"], "tbl_id": ["A01", "A01", "A03"]}
        tables = {
            "A03": {"tbl_nm": "전출지/전입지(시도)별 이동자수", "survey_nm": "국내인구이동통계", "periods": {"Q": ["202104"]},
                    "dims": [{"obj_nm": "전출지별", "kind": "regions", "level": 1}]},
            "A01": {"tbl_nm": "시군구별 이동자수", "survey_nm": "국내인구이동통계", "periods": {"Q": ["202104"]},
                    "dims": [{"obj_nm": "행정구역(시군구)별", "kind": "regions", "level": 1}]},
            "X": {"tbl_nm": "다른 조사 표", "survey_nm": "주민등록인구현황", "periods": {"Q": ["202104"]},
                  "dims": [{"obj_nm": "행정구역별", "kind": "regions", "level": 1}]},
        }

        def table(self, t):
            return self.tables.get(t)

    rows = {"A01": [{"PRD_DE": "202104", "C1_NM": "전국", "ITM_NM": "총전입", "UNIT_NM": "명", "DT": "1712000"},
                    {"PRD_DE": "202104", "C1_NM": "전국", "ITM_NM": "순이동", "UNIT_NM": "명", "DT": "0"}],
            "X": [{"PRD_DE": "202104", "C1_NM": "전국", "ITM_NM": "인구", "UNIT_NM": "명", "DT": "1712000"}]}
    j = Judge(Idx(), loose_items=True, log=lambda *a: None)
    j._rows = lambda t, periods: rows.get(t, [])
    spec = {"prd_de": "202104", "item": "이동자수", "region": "전국", "labels": [], "value": Decimal("1712000"), "unit": "명",
            "digits": 0}
    assert j.candidates([spec], ["A03"]) == []                         # 항목 이름이 달라 보통 후보에 없음
    assert j.candidates([spec], ["A03"], loose=True, surveys={"국내인구이동통계"}) == ["A01"]  # 같은 조사만
    assert j.fact_in_table("A01", spec, loose=True) == "loose"
    assert j.fact_in_table("A01", {**spec, "value": Decimal("12")}, loose=True) is None  # 작은 값은 우연일 수 있어 안 봄


def test_label_suspect(s):
    from backend.rag.search.tuning.compare import label_suspect
    row = {"question": "장안구에서 외국인 주민의 자녀 수가 2020년에 비해 2023년에 얼마나 증가했나요?"}
    assert label_suspect(s, row, ["FR_CHILD_M"]) == "FR_CHILD_T"     # 정답 (남) · 질문에 성별 없음 → (계) 형제
    assert label_suspect(s, {"question": "장안구 남자 외국인 주민 자녀 수"}, ["FR_CHILD_M"]) == ""
    assert label_suspect(s, row, ["FR_CHILD_T"]) == ""


def test_prune_units_keeps_main_copy_with_role_units():
    # roles.py 는 하위 질의가 없던 질문에 역할 단위를 더할 때 본 질의를 첫 하위 단위로 복사한다 (앱이 main 을 건너뛰어도 검색되게)
    # → 캐시에 하위 질문 검증을 다시 적용해도 그 복사본은 남아야 함 (앱 경로에서는 검증이 역할 단위보다 먼저라 남음)
    q = "1990년 화성군의 일반가구 중 보증부월세가 차지하는 비율은?"
    units = [_u("main", "일반가구 가구수 보증부월세", 지표=["일반가구", "가구수"]),
             _u("k-1", "일반가구 가구수 보증부월세", 지표=["일반가구", "가구수"]),
             _u("k-2", "일반가구", 지표=["일반가구"], 역할="분모")]
    out, _ = prune_units(q, units)
    assert [u["unit"] for u in out] == ["main", "k-1", "k-2"]
