"""데이터 경로: .env 에 없는 경로가 남아 있어도 storage/kosis_data 를 찾는지"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ("from backend.core.config import KOSIS_DATA_DIR, CONFIG_WARNINGS\n"
        "print(KOSIS_DATA_DIR); print(len(CONFIG_WARNINGS))")


def test_storage_paths_win_over_stale_env(tmp_path):
    st = tmp_path / "storage"
    (st / "kosis_data").mkdir(parents=True)
    (st / "kosis_data" / "catalog.csv").write_text("x", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "STORAGE_DIR": str(st), "KOSIS_DATA_DIR": str(tmp_path / "nope")}
    r = subprocess.run([sys.executable, "-c", CODE], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    kd, nw = r.stdout.strip().splitlines()
    assert Path(kd) == st / "kosis_data", r.stdout + r.stderr
    assert int(nw) == 1
