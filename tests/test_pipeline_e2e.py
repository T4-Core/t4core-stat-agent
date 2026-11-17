"""통합 파이프라인 (HCX·네트워크 없음, 가짜 KOSIS 데이터, Swagger 와 같은 HTTP 경로)

경로 해석 → ⓪ 준비 → ① 분석 → ② 검색·View → ③ 답변 → ★ /chat (이어서 진행 포함) → 좌표 재조회 → 판단
"""
from pathlib import Path

from tests import fake_kosis
from tests.helpers import ROOT, env, run


def test_pipeline_e2e(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    r = run(["-m", "tests.e2e_scenario"], environ=env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"E2E": "PASS"' in r.stdout


def test_kosis_data_next_to_repo_is_found(tmp_path):
    """storage 에 데이터가 없고 실행 폴더에 kosis_data/ 가 있으면 그쪽을 씀"""
    fake_kosis.build(tmp_path / "kosis_data")
    r = run(["-c", "from backend.core.config import KOSIS_DATA_DIR; print(KOSIS_DATA_DIR)"], tmp_path,
            env(STORAGE_DIR=str(tmp_path / "empty_storage")), 60)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == tmp_path / "kosis_data"


def test_env_override(tmp_path):
    d = fake_kosis.build(tmp_path / "anywhere" / "my_kosis")
    r = run(["-c", "from backend.core.config import KOSIS_DATA_DIR; print(KOSIS_DATA_DIR)"], ROOT,
            env(KOSIS_DATA_DIR=str(d)), 60)
    assert Path(r.stdout.strip()) == d, r.stderr
