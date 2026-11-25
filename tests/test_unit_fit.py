"""요청 단위 ↔ 표의 항목 단위 (engine._unit_fit) — 수를 묻는데 율 표 · '건' 을 묻는데 '명' 뿐인 표를 뒤로 (HCX·저장소 없음)"""
from types import SimpleNamespace

import numpy as np

from backend.rag.search.engine import TableSearch, rate_unit, want_unit


def test_want_unit():
    assert want_unit("2024년 이혼 건수는?") == "건" and want_unit("이혼건수") == "건"
    assert want_unit("이동건수는 2022년에 비해 몇 퍼센트 증가했나") == "건"      # 증감률 = 원자료는 수
    assert want_unit("2023년 서울 1인가구 수") == "수" and want_unit("출생아수") == "수"
    assert want_unit("합계출산율은?") is None and want_unit("인구 천 명당 이혼율") is None
    assert want_unit("2020년 남녀 성비") is None and want_unit("") is None


def test_rate_unit():
    assert all(rate_unit(u) for u in ("%", "천명당", "십만명당", "여자백명당남자수", "세"))
    assert not any(rate_unit(u) for u in ("명", "건", "가구", "명 건", "명/㎢", ""))
    assert not rate_unit("명 가임여자 1명당 명")      # 출생아수 + 합계출산율 — 수 단위로 시작하면 율 표가 아님


def _search(units, rate=0.7, cnt=0.8):
    facets = [SimpleNamespace(units=u, items=[]) for u in units]
    return SimpleNamespace(s={"feas": {"rate_miss": rate, "count_miss": cnt}}, ch=SimpleNamespace(facets=facets))


def test_unit_fit():
    s = _search([["천명당"], ["건"], ["명"], [], ["명 가임여자 1명당 명"]])
    feas, why = TableSearch._unit_fit(s, np.ones(5), [None] * 5, "2023년 이혼 건수")
    assert list(np.round(feas, 2)) == [0.7, 1.0, 0.8, 1.0, 1.0] and "율 표 (수를 물음)" in why[0]
    feas, _ = TableSearch._unit_fit(s, np.ones(5), [None] * 5, "2023년 출생아 수")
    assert list(np.round(feas, 2)) == [0.7, 1.0, 1.0, 1.0, 1.0]           # '수' 면 명 표는 그대로
    feas, _ = TableSearch._unit_fit(s, np.ones(5), [None] * 5, "2023년 이혼율")
    assert list(feas) == [1.0] * 5                                          # 율을 물으면 아무것도 안 함
    off = _search([["천명당"], ["명"]], rate=1.0, cnt=1.0)
    feas, _ = TableSearch._unit_fit(off, np.ones(2), [None] * 2, "이혼 건수")
    assert list(feas) == [1.0, 1.0]


def test_want_unit_rate_context():
    # 율·률·천 명당을 직접 묻는 질문은 '몇 건' 이 붙어도 율 요청 (원자료 율 표를 깎지 않음)
    assert want_unit("인천의 조이혼율은 인구 천 명당 몇 건인가요?") is None
    assert want_unit("2025년 인구 사망률은 몇 퍼센트 증가했나요?") is None
    assert want_unit("인구 조출생률") is None
    # '조건이' 의 '건이' 는 건수 요청이 아님
    assert want_unit("조회 조건이 2025년이라면 이혼율은 얼마인가요?") is None
    assert want_unit("조회 조건이 2025년이라면 이혼 건수는?") == "건"


def test_count_miss_skips_count_items_with_person_unit():
    # KOSIS 는 사건 건수 항목에도 단위 '명' 을 붙이기도 함 (DT_1B8000K 출생건수·혼인건수) → 항목명에 '건' 이 있으면 깎지 않음
    facets = [SimpleNamespace(units=["명"], items=["출생건수", "사망건수"]), SimpleNamespace(units=["명"], items=["이동자수"])]
    s = SimpleNamespace(s={"feas": {"rate_miss": 0.7, "count_miss": 0.8}}, ch=SimpleNamespace(facets=facets))
    feas, _ = TableSearch._unit_fit(s, np.ones(2), [None] * 2, "읍면동별 출생 건수")
    assert list(np.round(feas, 2)) == [1.0, 0.8]


def test_pop_basis():
    # 기준 없는 '인구' → 총조사·추계 인구 표를 뒤로 (주민등록 기본) · 기준을 말하거나 외국인 질문이면 그대로
    facets = [SimpleNamespace(survey_nm="인구총조사", tbl_nm="연령 및 성별 인구"), SimpleNamespace(survey_nm="주민등록인구현황", tbl_nm="성별 인구수"),
              SimpleNamespace(survey_nm="장래인구추계", tbl_nm="성 및 연령별 추계인구"), SimpleNamespace(survey_nm="인구총조사", tbl_nm="가구 및 주택")]
    s = SimpleNamespace(s={"feas": {"pop_basis": 0.8}}, ch=SimpleNamespace(facets=facets))  # 기본값과 같게
    f, why = TableSearch._pop_basis(s, np.ones(4), [None] * 4, "2025년 서울 인구는?", "2025년 서울 인구는?")
    assert list(np.round(f, 2)) == [0.8, 1.0, 0.8, 1.0] and "주민등록 우선" in why[0][0]
    for q in ("2025년 서울 인구총조사 인구", "2030년 서울 추계 인구", "2025년 서울 외국인 인구", "2025년 서울 1인가구 수",
              "2025년 서초구의 연령별 인구 테이블에서 합계는?"):
        f, _ = TableSearch._pop_basis(s, np.ones(4), [None] * 4, q, q)
        assert list(f) == [1.0] * 4, q
    off = SimpleNamespace(s={"feas": {"pop_basis": 1.0}}, ch=SimpleNamespace(facets=facets))
    assert list(TableSearch._pop_basis(off, np.ones(4), [None] * 4, "서울 인구", "서울 인구")[0]) == [1.0] * 4


def test_table_move_ignores_scenario_values():
    # 장래추계 시나리오 이름('…국제이동-중위 / 국내이동-중위')은 가정 설명 — 국제 이동 표로 보지 않음 (S2-P08 순이동률이 '국내 이동 없음' 으로 깎이던 것)
    from backend.rag.search.movement import move_factor, table_move
    f = SimpleNamespace(tbl_nm="장래 성 및 연령별 순이동률/시도", items=["순이동률"],
                        dims=[("시나리오별", "scenario", ["중위 추계(출산율-중위 / 국제이동-중위 / 국내이동-중위)"]),
                              ("시도별", "regions", ["서울특별시"])])
    tm = table_move(f)
    assert "국제" not in tm["codes"] and "순이동" in tm["codes"]
    fac, why = move_factor({"scope": None, "dir": "순이동", "intl": False}, tm, {"move_miss": 0.6, "move_derived": 0.9})
    assert fac == 1.0, why


def test_proj_fit():
    # 추계를 묻지 않은 실측 시점 질문 → 장래추계 표를 뒤로 · 추계 말이 있거나 미래 연도면 그대로
    facets = [SimpleNamespace(survey_nm="장래인구추계"), SimpleNamespace(survey_nm="인구동향조사")]
    s = SimpleNamespace(s={"feas": {"proj_miss": 0.7, "proj_last_actual": 2026}}, ch=SimpleNamespace(facets=facets))
    f, why = TableSearch._proj_fit(s, np.ones(2), [None] * 2, SimpleNamespace(years=[2025]), "2025년 경기도 출생아 수")
    assert list(np.round(f, 2)) == [0.7, 1.0] and "추계 표" in why[0][0]
    for years, q in (([2025], "2025년 추계 출생아 수"), ([2040], "2040년 경기도 출생아 수"), ([2030], "중위 시나리오 출생아")):
        f, _ = TableSearch._proj_fit(s, np.ones(2), [None] * 2, SimpleNamespace(years=years), q)
        assert list(f) == [1.0, 1.0], q


def test_foreign_basis():
    # 기준 없는 '외국인' → 출입국·인구총조사의 외국인 표를 뒤로 (외국인주민현황 기본) · 등록·체류·총조사 등을 말하면 그대로
    facets = [SimpleNamespace(survey_nm="인구총조사", tbl_nm="성 및 연령별 외국인"), SimpleNamespace(survey_nm="지방자치단체외국인주민현황", tbl_nm="외국인주민 현황"),
              SimpleNamespace(survey_nm="출입국자및체류외국인통계", tbl_nm="등록외국인 현황"), SimpleNamespace(survey_nm="인구총조사", tbl_nm="연령 및 성별 인구")]
    s = SimpleNamespace(s={"feas": {"foreign_basis": 0.8}}, ch=SimpleNamespace(facets=facets))
    f, _ = TableSearch._foreign_basis(s, np.ones(4), [None] * 4, "창녕군 외국인 여성 수", "창녕군 외국인 여성 수")
    assert list(np.round(f, 2)) == [0.8, 1.0, 0.8, 1.0]
    for q in ("세종시 등록외국인 수", "2020년 인구총조사 외국인", "체류 외국인 수", "2025년 서울 인구"):
        f, _ = TableSearch._foreign_basis(s, np.ones(4), [None] * 4, q, q)
        assert list(f) == [1.0] * 4, q


def test_want_unit_mid_sentence_su():
    assert want_unit("몇 년 전 출생아 수 알려줘") == "수" and want_unit("수원시 이혼율") is None


def test_want_unit_su_itda():
    assert want_unit("육아휴직 쓰면 아이를 더 낳는지 알 수 있는 통계") is None    # '알 수 있는' 은 개수 요청이 아님
