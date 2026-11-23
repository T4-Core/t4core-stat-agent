"""시계열 묶음 후보 뽑기 (scenario_series.py 를 별도 프로세스로) + 규칙 단위 확인"""
from backend.rag.ingestion.series import _pair, _unit_rel, diff_terms, structural_mismatch, title_core
from tests import fake_kosis
from tests.helpers import env, run

SIDO = fake_kosis.SIDO


def _births(tid, nm, years, category="인구동향조사", item=("T1", "출생아수", "명")):
    return {"org_id": "101", "tbl_id": tid, "tbl_nm": nm, "category": category, "section": "출생", "josa": category,
            "levels": [("A", "행정구역(시도)별", SIDO)], "items": [item], "prd_se": "A", "prd_meta": "년",
            "periods": [str(y) for y in years]}


SPLIT = [
    _births("DT_S1", "시도별 출생아수(1993~2004)", range(1993, 2005)),
    _births("DT_S2", "시도별 출생아수", range(2004, 2026)),
    _births("DT_S3", "출생아수 시도편(구 자료)", range(1980, 1993), item=("T9", "출생아수(명)", "명")),
    _births("DT_S4", "시도별 출생아수(확정)", range(1993, 2026)),          # 같은 기간을 덮음 → 기간판 아님
    _births("DT_S5", "시도별 출생아수(남)", range(2005, 2026)),             # 성별이 다름 → DT_S1 과 짝이 아님
]


def test_series_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(fake_kosis, "TABLES", fake_kosis.TABLES + SPLIT)
    fake_kosis.build(tmp_path / "storage" / "kosis_data")
    r = run(["-m", "tests.scenario_series"], environ=env(STORAGE_DIR=str(tmp_path / "storage")))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"SERIES": "PASS"' in r.stdout


def _p(tid, a, b, nm="x"):
    return {"tbl_id": tid, "tbl_nm": nm, "periods": [{"se": "Y", "year_from": a, "year_to": b}]}


def test_pair_rules():
    a, b = _p("A", 1970, 2004), _p("B", 2005, 2025)
    assert _pair(b, a, 2, 10)[:2] == (a, b)                      # 먼저 시작하는 표가 앞
    assert _pair(a, _p("C", 1980, 2025), 2, 10) is None          # 한쪽이 다른 쪽을 덮지는 않지만 겹침 25년 > 10
    assert _pair(a, _p("D", 2010, 2025), 2, 10) is None          # 틈 5년 > 2
    assert _pair(_p("E", 1990, 2025), _p("F", 2000, 2010), 2, 10) is None   # 덮음
    assert title_core("시도별 출생아수(1970~2004)") == title_core("시도별 출생아수(구)") == title_core("시도별 출생아수")
    assert _unit_rel(["명"], ["천명"]) == "multiple" and _unit_rel(["명"], ["건"]) == "diff"


def test_structural_mismatch_and_diff_terms():
    nm = lambda n, survey="": {"tbl_nm": n, "survey_nm": survey}
    # 성별이 다른 짝은 빼고 (괄호가 없으면 계), 같으면 둠
    assert structural_mismatch(nm("한국국적을 가지지 않은 자(계)(2007~2015)"), nm("한국국적을 가지지 않은 자(남)")) == "성별"
    assert structural_mismatch(nm("한국국적을 가지지 않은 자(남)(2007~2015)"), nm("한국국적을 가지지 않은 자(남)")) is None
    assert structural_mismatch(nm("시도별 외국인주민 현황(2006)"), nm("시도별 외국인주민 현황(계)")) is None
    # 연령 구간 · 실적↔추계
    assert structural_mismatch(nm("시군구/성/연령(1세)별 주민등록연앙인구"), nm("시군구/성/연령(5세)별 주민등록연앙인구(2023~)")) == "연령 구간"
    assert structural_mismatch(nm("시도/성/연령(5세)별 사망률(1996~)", "인구동향조사"),
                               nm("장래 성 및 연령별 사망률 / 전국", "장래인구추계")) == "실적·추계"
    # 제목에서 양쪽에만 있는 말 → 다른 통계일 가능성 (지역 수준·연도·괄호는 비교에서 뺌)
    assert diff_terms("시도/직업별(~2007) 혼인", "시도/직업별(2008~) 이혼") == "혼인 / 이혼"
    assert diff_terms("한국국적을 가지지 않은 자-외국인 근로자(계)(2006~2015)", "한국국적을 가지지 않은 자-기타 외국인(계)") == "근로자 / 기타"
    assert diff_terms("시도별 외국인주민 현황(2007~2015)", "시군구별 외국인주민 현황") == ""
    assert diff_terms("2000년 행정구역 기준 인구 추이(1975~2000)", "2010년 행정구역 기준 인구 추이(2000~2010)") == ""
    assert diff_terms("한국국적을 취득한 자(계)(2006~2015)", "이전국적별 한국국적을 취득한 자(계)") == ""   # 한쪽에만 더해진 말은 괜찮음
