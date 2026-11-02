"""[NEW] 통합 파이프라인 연결 테스트 (HCX·네트워크 없음, 가짜 KOSIS 데이터)

경로 동적 해석 → ⓪ 준비 → ① 재작성 → ② View → ③ 답변 → ★ /chat → 좌표 재조회 → legacy 하이브리드 까지
Swagger 와 같은 HTTP 경로(TestClient)로 확인. 저장소 위치를 환경변수로 바꾸려고 별도 프로세스로 실행한다.
"""
import os
import subprocess
import sys
from pathlib import Path

from tests import fake_kosis

ROOT = Path(__file__).resolve().parent.parent


DATA_KEYS = ("KOSIS_DATA_DIR", "KOSIS_DATA", "VIEW_OUT_DIR", "RAG_INDEX_DIR", "RAG_VIEWS_DIR", "TABLE_INDEX_DIR",
             "VIEW_EMBED_CACHE", "ANSWERS_DIR", "STORAGE_DIR")


def _env(**kw):
    # 경로 변수는 "" 로 둠: pop 하면 저장소의 실제 .env 값이 load_dotenv 로 다시 채워질 수 있음 (override=False 라 "" 는 유지됨)
    env = {**os.environ, **{k: "" for k in DATA_KEYS}, "PYTHONPATH": str(ROOT),
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}   # Windows 콘솔 기본(cp949)에 없는 문자(⓪ 등) 출력 오류 방지
    env.update(kw)
    return env


def _run(args, cwd, env, timeout=900):
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def test_pipeline_e2e(tmp_path):
    storage = tmp_path / "storage"
    fake_kosis.build(storage / "kosis_data")
    env = _env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key")
    r = _run(["-m", "tests.e2e_scenario"], ROOT, env)
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert '"E2E": "PASS"' in r.stdout


def test_legacy_location_is_found(tmp_path):
    """storage 에 데이터가 없고 실행 폴더에 예전처럼 kosis_data/ 가 있으면 그쪽을 씀"""
    fake_kosis.build(tmp_path / "kosis_data")
    env = _env(STORAGE_DIR=str(tmp_path / "empty_storage"))
    r = _run(["-c", "from backend.core.config import KOSIS_DATA_DIR; print(KOSIS_DATA_DIR)"], tmp_path, env, 60)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == tmp_path / "kosis_data"


def test_env_override(tmp_path):
    d = fake_kosis.build(tmp_path / "anywhere" / "my_kosis")
    env = _env(KOSIS_DATA_DIR=str(d))
    r = _run(["-c", "from backend.core.config import KOSIS_DATA_DIR; print(KOSIS_DATA_DIR)"], ROOT, env, 60)
    assert Path(r.stdout.strip()) == d, r.stderr
