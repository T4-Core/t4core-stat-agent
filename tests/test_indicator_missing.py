"""요청 지표가 없는 표의 첫 코드로 답이 나가지 않는가 (scenario_indicator_missing.py 를 별도 프로세스로)"""
from tests import fake_kosis
from tests.helpers import env, run

VITAL = {  # DT_1B8000F 모양: 지표를 나누는 분류에 합계 코드가 없음
    "org_id": "101", "tbl_id": "DT_1B8000F", "tbl_nm": "인구동태건수 및 동태율 추이(출생,사망,혼인,이혼)",
    "category": "인구동향조사", "section": "인구동태", "josa": "인구동향조사",
    "levels": [("A", "기본항목별", [("11", "출생아수(명)", ""), ("12", "사망자수(명)", ""),
                                  ("13", "혼인건수(건)", ""), ("14", "이혼건수(건)", "")])],
    "items": [("T1", "인구동태건수 및 동태율", "명")],
    "prd_se": "A", "prd_meta": "년", "periods": [str(y) for y in range(2016, 2026)],
}


def test_indicator_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(fake_kosis, "TABLES", fake_kosis.TABLES + [VITAL])
    fake_kosis.build(tmp_path / "storage" / "kosis_data")
    r = run(["-m", "tests.scenario_indicator_missing"], environ=env(STORAGE_DIR=str(tmp_path / "storage")))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"INDICATOR_MISSING": "PASS"' in r.stdout
