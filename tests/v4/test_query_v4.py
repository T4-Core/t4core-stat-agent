"""[NEW v4] 쿼리 모듈 v4 + CSV 값 사전 (HCX·네트워크 없음, 가짜 KOSIS 데이터, Swagger 와 같은 HTTP 경로)"""
from tests import fake_kosis
from tests.test_pipeline_e2e import ROOT, _env, _run


def test_query_v4(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    r = _run(["-m", "tests.v4.scenario_v4"], ROOT, _env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key",
                                                         CSV_INDEX_DIR="", RUNS_DIR="", QUERY_V4_CONFIG=""))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"V4": "PASS"' in r.stdout
