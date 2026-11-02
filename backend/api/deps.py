"""[NEW] 라우터 공통: 모듈 예외 → HTTP 응답

모듈 코드는 CLI 용으로 만들어져 SystemExit(키 없음·인덱스 없음)을 던지는 곳이 있다.
API 서버에서 SystemExit 이 그대로 올라가면 요청 하나가 서버 프로세스를 끝낼 수 있으므로 여기서 잡는다.
"""
from contextlib import contextmanager

from fastapi import HTTPException


@contextmanager
def guard(what=""):
    try:
        yield
    except HTTPException:
        raise
    except FileNotFoundError as e:                       # 색인·프로필·원본 없음 → 준비 단계 먼저
        raise HTTPException(409, f"{what}준비 데이터 없음: {e}")
    except ValueError as e:                              # 카탈로그에 없는 표 등
        raise HTTPException(404, f"{what}{e}")
    except SystemExit as e:                              # .env 키 없음 등 (CLI 용 종료)
        raise HTTPException(503, f"{what}{e}")
    except Exception as e:  # noqa: BLE001
        name = e.__class__.__name__
        code = 502 if name in ("HcxError", "ConnectionError", "Timeout", "RequestException") else 500
        raise HTTPException(code, f"{what}{name}: {str(e)[:300]}")
