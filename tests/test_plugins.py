"""[NEW] 개인 폴더 파이프라인 플러그인 탐색 (backend/core/plugins.py) — private 폴더 위치를 바꿔도 찾는지"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = """
from backend.core import plugins
from backend.core.config import PRIVATE_DIR
print(PRIVATE_DIR)
print(sorted(plugins.available()))
print(plugins.get("echo")("q")["question"])
"""


def _run(env_extra, cwd):
    env = {**os.environ, "PYTHONPATH": str(ROOT), **env_extra}
    return subprocess.run([sys.executable, "-c", CODE], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def test_private_plugin(tmp_path):
    priv = tmp_path / "somewhere" / "my_private"
    (priv / "pipelines").mkdir(parents=True)
    (priv / "mylib").mkdir()
    (priv / "mylib" / "__init__.py").write_text("NAME = 'echo-lib'\n", encoding="utf-8")
    (priv / "pipelines" / "echo.py").write_text(
        "DESCRIPTION = 'echo'\nfrom mylib import NAME\n\ndef run_chat(question, today=None, top_k=10, n_views=3, **kw):\n"
        "    return {'question': question + ':' + NAME}\n", encoding="utf-8")
    (priv / "pipelines" / "_draft.py").write_text("x = 1\n", encoding="utf-8")          # '_' 로 시작하면 무시
    r = _run({"PRIVATE_DIR": str(priv)}, ROOT)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert Path(lines[0]) == priv
    assert lines[1] == "['default', 'echo']"
    assert lines[2] == "q:echo-lib"                                                        # private 안의 패키지 import 가능


def test_without_private(tmp_path):
    """private/ 없이 clone 한 환경: 기본 파이프라인만, 개인 파이프라인 요청은 400 / CLI 는 안내 후 종료(2)"""
    env = {**os.environ, "PRIVATE_DIR": str(tmp_path / "없음"), "PYTHONPATH": str(ROOT),
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    code = ("import backend.core.plugins as p\n"
            "from fastapi.testclient import TestClient; from backend.main import app\n"
            "r = TestClient(app).post('/api/v1/chat', json={'question': 'q', 'pipeline': 'stat_rag'})\n"
            "print(sorted(p.available()), r.status_code)")
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("['default'] 400"), r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "eval" / "pipeline_review" / "review_80.py"), "run",
                        "--pipeline", "stat_rag"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 2 and "Traceback" not in r.stderr and "없음" in r.stdout, r.stdout + r.stderr
