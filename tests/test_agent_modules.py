"""검색·View → 모듈 2·3·5·6 연결 (scenario_agent_modules.py 를 별도 프로세스로)"""
from tests import fake_kosis
from tests.helpers import env, run


def test_agent_modules(tmp_path):
    fake_kosis.build(tmp_path / "storage" / "kosis_data")
    r = run(["-m", "tests.scenario_agent_modules"], environ=env(STORAGE_DIR=str(tmp_path / "storage")))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"AGENT_MODULES": "PASS"' in r.stdout
