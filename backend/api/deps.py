"""라우터 공통: 모듈 예외 → HTTP 응답 (요청 하나의 오류가 서버를 끝내지 않게)"""
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
    except ValueError as e:                              # 카탈로그에 없는 표, 잘못된 선택 토큰 등
        raise HTTPException(404, f"{what}{e}")
    except SystemExit as e:
        raise HTTPException(503, f"{what}{e}")
    except Exception as e:  # noqa: BLE001
        name = e.__class__.__name__
        if name == "HcxKeyMissing":
            raise HTTPException(503, f"{what}{e}")
        code = 502 if name in ("HcxError", "ConnectionError", "Timeout", "RequestException") else 500
        raise HTTPException(code, f"{what}{name}: {str(e)[:300]}")
