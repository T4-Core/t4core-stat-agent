"""재작성 충실도 — 분석 단계 전체 (HCX·네트워크 없음, 가짜 KOSIS 데이터)"""
from tests import fake_kosis
from tests.helpers import env, run


def test_rewrite_fidelity(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    r = run(["-m", "tests.scenario_rewrite_fidelity"], environ=env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"REWRITE_FIDELITY": "PASS"' in r.stdout
