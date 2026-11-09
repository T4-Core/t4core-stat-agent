"""0-1·0-3. 환경설정 + HCX 호출 확인
노트북 user_question_rewrite_v3.ipynb '0-1'·'0-3'·'1' 셀의 설정 부분 (v2 모듈 config.py 와 같은 형식)

HCX 호출: backend.core.llm (원본 kosis_rag_qa.py 의 HCX 부분. 노트북 0-2 베이스 코드의 chat()·_post()·with_retry() 와 같은 코드)
.env    : backend.core.config 가 저장소 루트 기준으로 한 번 읽음
경로    : 사전은 이 패키지 안 (query_analyzer/dictionary). 결과 파일은 v2 모듈과 같은
          eval/query_rewrite/{outputs,dashboard}"""
import os
import time
from pathlib import Path

from backend.core import llm as kq
from backend.core.config import ENV_PATH, REWRITE_EVAL_DIR, TEST_DATA_DIR

ROOT = REWRITE_EVAL_DIR                                  # eval/query_rewrite (v2 모듈과 같은 위치)
DATA_DIR = TEST_DATA_DIR                                 # 평가 질문 CSV (storage/test_data/kosis_rag_eval_80_queries.csv)
OUTPUT_DIR = ROOT / "outputs"                            # 4단계 query_bundles_YYYYMMDD_HHMMSS.json (실행마다 새 파일)
DASHBOARD_DIR = ROOT / "dashboard"                       # 5단계 rewrite_trace.json/.js (rewrite_pipeline_dashboard.html 과 같은 폴더)
DICT_DIR = Path(__file__).resolve().parent / "dictionary"   # 사전 (dictionary/build_dicts.py 가 만듦)
TERM_PATH = DICT_DIR / "term_dict.json"                  # 2-1 일상어 → 통계어
RULE_PATH = DICT_DIR / "rule_dict.json"                  # 2-2·2-4 확실한 표기 대응표
# [CHANGED] 이전: OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
#                DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
#   → import 시점 생성 제거. 쓰기 폴더가 없는 환경(Docker 등)에서 import 만으로 실패했음
#     폴더는 저장 함수가 쓰기 직전에 만든다 (bundle.save_bundles, trace.save_trace)
chat = kq.chat                                           # 베이스 코드 chat() (with_retry, _post 포함)
HcxError = kq.HcxError


def chat_model():
    return kq.CHAT_MODEL


def settings():
    """현재 설정 (키 값은 넣지 않음)"""
    return {"env_path": str(ENV_PATH) if ENV_PATH else None, "hcx_host": kq.HCX_HOST, "model": kq.CHAT_MODEL,
            "app_type": os.getenv("HCX_APP_TYPE", "testapp"), "has_api_key": bool(os.getenv("HCX_API_KEY", "").strip()),
            "term_dict": str(TERM_PATH), "rule_dict": str(RULE_PATH), "output_dir": str(OUTPUT_DIR)}


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
