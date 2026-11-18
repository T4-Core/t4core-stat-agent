"""View 의 지역·시점 자르기 — 전국 + 다른 지역, 해끼리 비교 (scenario_view_filters.py 를 별도 프로세스로)"""
from tests import fake_kosis
from tests.helpers import env, run


def test_view_filters(tmp_path):
    fake_kosis.build(tmp_path / "storage" / "kosis_data")
    r = run(["-m", "tests.scenario_view_filters"], environ=env(STORAGE_DIR=str(tmp_path / "storage")))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"VIEW_FILTERS": "PASS"' in r.stdout
