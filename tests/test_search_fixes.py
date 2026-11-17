"""검색 품질 수정 · 검색 도구 시나리오 — 가짜 저장소, 별도 프로세스"""
from tests import fake_kosis
from tests.helpers import env, run


def _build(storage, tables):
    saved = list(fake_kosis.TABLES)
    try:
        fake_kosis.TABLES[:] = tables
        fake_kosis.build(storage / "kosis_data")
    finally:
        fake_kosis.TABLES[:] = saved


def test_search_fixes(tmp_path):
    from tests.scenario_search_fixes import TABLES
    _build(tmp_path / "storage", TABLES)
    r = run(["-m", "tests.scenario_search_fixes"], environ=env(STORAGE_DIR=str(tmp_path / "storage"), HCX_API_KEY="test-key"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-5000:]
    assert '"SEARCH_FIXES": "PASS"' in r.stdout


def test_search_cli(tmp_path):
    from tests.scenario_search_cli import extra_tables
    _build(tmp_path / "storage", list(fake_kosis.TABLES) + extra_tables())
    r = run(["-m", "tests.scenario_search_cli"], environ=env(STORAGE_DIR=str(tmp_path / "storage"), HCX_API_KEY="test-key"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert '"SEARCH_CLI": "PASS"' in r.stdout
