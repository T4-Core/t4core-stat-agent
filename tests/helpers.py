"""시나리오 테스트 공통 — 저장소 위치를 환경변수로 바꾸려고 시나리오는 별도 프로세스로 실행한다"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_KEYS = ("KOSIS_DATA_DIR", "VIEW_OUT_DIR", "TABLE_INDEX_DIR", "CSV_INDEX_DIR", "EMBED_CACHE", "RUNS_DIR",
             "ANSWERS_DIR", "STORAGE_DIR", "PIPELINE_CONFIG")


def env(**kw):
    """경로 변수는 "" 로 둠 (pop 하면 저장소의 실제 .env 값이 다시 채워질 수 있음 — override=False 라 "" 는 유지).
    시나리오는 되묻기 왕복·기준 해 2026 을 확인하므로 strict · fixed 로 실행"""
    e = {**os.environ, **{k: "" for k in DATA_KEYS}, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8",
         "PYTHONUTF8": "1", "PIPELINE_CLARIFY_MODE": "strict", "PIPELINE_BASE_YEAR_MODE": "fixed"}
    e.update(kw)
    return e


def run(args, cwd=ROOT, environ=None, timeout=900):
    return subprocess.run([sys.executable, *args], cwd=cwd, env=environ, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
