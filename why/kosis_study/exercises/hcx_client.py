"""
HCX(CLOVA Studio) 호출 도우미  ※ 학습용/정답용 공통 파일 (빈칸 없음)

이 파일은 '인증·재시도' 같은 반복 코드를 숨겨 둔 것입니다.
여러분은 아래 두 함수만 쓰면 됩니다.
  embed(text)      → 문장을 숫자 벡터(list[float])로 바꿈  (STEP 4 Dense 검색)
  chat(messages)   → HCX에게 대화를 보내고 답변 문자열을 받음 (STEP 5 답변 생성)

.env (프로젝트 루트, 실행하는 위치 기준)
  HCX_API_KEY=nv-...
  HCX_BASE_URL=https://clovastudio.stream.ntruss.com
  HCX_MODEL=HCX-007
"""
import os
import re
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env")


def _host(url):
    """'https://host/v1/...' 처럼 경로까지 넣어도 호스트만 사용"""
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


HOST = _host(os.getenv("HCX_BASE_URL"))
MODEL = os.getenv("HCX_MODEL", "HCX-007")
EMBED_PATH = os.getenv("HCX_EMBED_PATH", "/v1/api-tools/embedding/v2")


def _post(path, body, tries=5):
    key = os.getenv("HCX_API_KEY")
    if not key:
        raise RuntimeError(".env 에 HCX_API_KEY 를 넣어 주세요.")
    for i in range(tries):
        r = requests.post(HOST + path, json=body, timeout=60, headers={
            "Authorization": f"Bearer {key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
            "Content-Type": "application/json; charset=utf-8"})
        if r.status_code == 429 or r.status_code >= 500:     # 너무 많이 호출 / 서버 오류 → 잠깐 쉬고 재시도
            time.sleep(2 ** i)
            continue
        data = r.json()
        status = data.get("status") or {}
        if r.status_code != 200 or str(status.get("code", "20000")) != "20000":
            raise RuntimeError(f"HCX 오류 {r.status_code}: {status.get('message') or str(data)[:200]}")
        return data.get("result") or {}
    raise RuntimeError("HCX 재시도 횟수 초과 (잠시 후 다시 실행하세요)")


def embed(text):
    """문장 1개 → 벡터 (임베딩 v2, 1024차원)"""
    return _post(EMBED_PATH, {"text": str(text)[:6000]})["embedding"]


def chat(messages, max_tokens=800, temperature=0.3):
    """messages 예: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]"""
    body = {"messages": messages, "temperature": temperature, "topP": 0.8,
            "maxCompletionTokens": max_tokens, "repetitionPenalty": 1.1}
    if MODEL.upper().startswith("HCX-007"):
        body["thinking"] = {"effort": "none"}                 # 추론 모드 끄기 (빠른 응답)
    result = _post(f"/v3/chat-completions/{MODEL}", body)
    return (result.get("message") or {}).get("content", "")
