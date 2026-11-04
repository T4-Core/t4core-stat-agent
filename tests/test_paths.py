"""[NEW] 데이터 경로: storage/kosis_data · storage/test_data 를 가리키는지 (.env 에 예전 값이 남아 있어도)"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ("from backend.core.config import KOSIS_DATA_DIR, TEST_DATA_DIR, CONFIG_WARNINGS\n"
        "print(KOSIS_DATA_DIR); print(TEST_DATA_DIR); print(len(CONFIG_WARNINGS))")


def test_storage_paths_win_over_stale_env(tmp_path):
    st = tmp_path / "storage"
    (st / "kosis_data").mkdir(parents=True)
    (st / "kosis_data" / "catalog.csv").write_text("x", encoding="utf-8")
    (st / "test_data").mkdir()
    (st / "test_data" / "kosis_rag_eval_80_queries.csv").write_text("id,question\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "STORAGE_DIR": str(st),
           "KOSIS_DATA": "kosis_data", "KOSIS_DATA_DIR": "", "TEST_DATA_DIR": str(tmp_path / "nope")}   # 예전·잘못된 값
    r = subprocess.run([sys.executable, "-c", CODE], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    kd, td, nw = r.stdout.strip().splitlines()
    assert Path(kd) == st / "kosis_data", r.stdout + r.stderr
    assert Path(td) == st / "test_data"
    assert int(nw) == 2                                       # 무시한 환경변수 2개 → 경고
