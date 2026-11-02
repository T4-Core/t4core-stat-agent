"""0-1·0-3. 환경설정 + HCX 호출 확인
- .env: Rewritten_fastapi 폴더에서 상위 폴더로 올라가며 처음 찾은 .env 를 읽음 (지금은 exercises/.env)
- 베이스 코드: 같은 폴더의 kosis_rag_qa.py (원본 복사본, 수정 금지)를 불러와 chat() 을 그대로 씀
  kosis_rag_qa.py 는 import 할 때 현재 폴더의 .env 만 읽으므로, 찾은 .env 값으로 HCX_HOST·CHAT_MODEL 을 다시 설정
  (노트북 0-3 셀과 같은 방식. 파일 자체는 고치지 않음)"""
import importlib.util
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # Rewritten_fastapi
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
DASHBOARD_DIR = ROOT / "dashboard"
KOSIS_QA_PATH = ROOT / "kosis_rag_qa.py"               # 베이스 코드 복사본


# ---- .env 찾기 (상위 폴더로 올라가며) ----
def find_env(start=ROOT):
    for d in [start, *start.parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return None


ENV_PATH = find_env()
if ENV_PATH:
    load_dotenv(ENV_PATH, override=True)


# ---- 베이스 코드 불러오기: 폴더 안의 복사본을 경로로 직접 불러옴 (sample_test 원본과 섞이지 않게) ----
def _load_kosis_qa():
    name = "kosis_rag_qa_copy"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, KOSIS_QA_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


kq = _load_kosis_qa()
kq.HCX_HOST = kq._host(os.getenv("HCX_BASE_URL"))     # 0-3 셀과 같음: 찾은 .env 값으로 다시 설정
kq.CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")

chat = kq.chat                                         # 베이스 코드 chat() (with_retry, _post 포함)
HcxError = kq.HcxError


def chat_model():
    return kq.CHAT_MODEL


def settings():
    """현재 설정 (키 값은 넣지 않음)"""
    return {"env_path": str(ENV_PATH) if ENV_PATH else None, "hcx_host": kq.HCX_HOST, "model": kq.CHAT_MODEL,
            "app_type": os.getenv("HCX_APP_TYPE", "testapp"), "has_api_key": bool(os.getenv("HCX_API_KEY", "").strip())}


def check_hcx():
    """0-3. HCX 호출 확인 (1회). 반환: {"ok", "elapsed_s", "response" 또는 "error"}"""
    if not settings()["has_api_key"]:
        return {"ok": False, "elapsed_s": 0, "error": "API 키 없음 (.env 의 HCX_API_KEY 확인)"}
    t0 = time.time()
    try:
        out = chat([{"role": "user", "content": "'확인'이라고만 답해."}], max_tokens=50)
        return {"ok": True, "elapsed_s": round(time.time() - t0, 2), "response": out}
    except HcxError as e:
        return {"ok": False, "elapsed_s": round(time.time() - t0, 2), "error": f"HTTP {e.http} / 코드 {e.code}: {e}"}
    except (Exception, SystemExit) as e:                # noqa: BLE001  (네트워크, 키 없음)
        return {"ok": False, "elapsed_s": round(time.time() - t0, 2), "error": f"{e.__class__.__name__}: {e}"}
