"""재작성 단계 설정 — 사전 경로 + HCX 호출 확인 (HCX 호출 자체는 backend.core.llm)"""
import os
import time
from pathlib import Path

from backend.core import llm
from backend.core.config import ENV_PATH

DICT_DIR = Path(__file__).resolve().parent / "dictionary"  # dictionary/build_dicts.py 가 만듦
TERM_PATH = DICT_DIR / "term_dict.json"  # 일상어 → 통계어
RULE_PATH = DICT_DIR / "rule_dict.json"  # 확실한 표기 대응표 (시도·성별·연령 …)
chat = llm.chat


def settings():
    """현재 설정 (키 값은 넣지 않음)"""
    return {"env_path": str(ENV_PATH) if ENV_PATH else None, "hcx_host": llm.HCX_HOST, "model": llm.CHAT_MODEL,
            "app_type": os.getenv("HCX_APP_TYPE", "testapp"), "has_api_key": bool(os.getenv("HCX_API_KEY", "").strip()),
            "term_dict": str(TERM_PATH), "rule_dict": str(RULE_PATH)}


def check_hcx():
    """HCX 호출 확인 (1회) → {"ok", "elapsed_s", "response" 또는 "error"}"""
    if not settings()["has_api_key"]:
        return {"ok": False, "elapsed_s": 0, "error": "API 키 없음 (.env 의 HCX_API_KEY 확인)"}
    t0 = time.time()
    try:
        out = chat([{"role": "user", "content": "'확인'이라고만 답해."}], max_tokens=50)
        return {"ok": True, "elapsed_s": round(time.time() - t0, 2), "response": out}
    except llm.HcxError as e:
        return {"ok": False, "elapsed_s": round(time.time() - t0, 2), "error": f"HTTP {e.http} / 코드 {e.code}: {e}"}
    except Exception as e:  # noqa: BLE001  (네트워크, 키 없음)
        return {"ok": False, "elapsed_s": round(time.time() - t0, 2), "error": f"{e.__class__.__name__}: {e}"}
