"""질의 분석 + CSV 값 사전 (HCX·네트워크 없음, 가짜 KOSIS 데이터, Swagger 와 같은 HTTP 경로)"""
from tests import fake_kosis
from tests.helpers import env, run


def test_query_analysis(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    r = run(["-m", "tests.scenario_query"], environ=env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"QUERY": "PASS"' in r.stdout
