"""0-1·0-3. 환경설정 + HCX 호출 확인  (구 Rewritten_fastapi/rewriter/config.py)

[CHANGED] 이전: 같은 폴더의 kosis_rag_qa.py '복사본'을 파일 경로로 불러와(chat 재사용) HCX_HOST·CHAT_MODEL 을 다시 설정
          이후: backend.core.llm (원본 kosis_rag_qa.py 의 HCX 부분을 옮긴 공용 모듈) 을 그대로 import
[CHANGED] 이전: .env 를 이 폴더에서 상위로 올라가며 찾아 load_dotenv(override=True)
          이후: backend.core.config 가 저장소 루트 기준으로 한 번 읽음
[CHANGED] 경로: Rewritten_fastapi/{data,outputs,dashboard} → eval/query_rewrite/{data,outputs,dashboard}"""
import os
import time

from backend.core import llm as kq                     # [CHANGED] 이전: kq = _load_kosis_qa()  (kosis_rag_qa.py 복사본)
from backend.core.config import ENV_PATH, REWRITE_EVAL_DIR, TEST_DATA_DIR

ROOT = REWRITE_EVAL_DIR                                # [CHANGED] 이전: ROOT = Path(__file__).resolve().parent.parent  (Rewritten_fastapi)
DATA_DIR = TEST_DATA_DIR                               # [CHANGED] 이전: DATA_DIR = ROOT / "data"  (평가 질문 CSV — storage/test_data 우선, 없으면 eval/query_rewrite/data)
OUTPUT_DIR = ROOT / "outputs"
DASHBOARD_DIR = ROOT / "dashboard"

# [CHANGED] 아래 코드는 삭제 (복사본 로딩·.env 재설정이 더 이상 필요 없음)
#   def find_env(start=ROOT): ...                         → backend.core.config.find_env
#   ENV_PATH = find_env(); load_dotenv(ENV_PATH, override=True)
#   def _load_kosis_qa(): importlib 로 kosis_rag_qa.py 복사본을 'kosis_rag_qa_copy' 모듈로 로드
#   kq.HCX_HOST = kq._host(os.getenv("HCX_BASE_URL")); kq.CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")

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
