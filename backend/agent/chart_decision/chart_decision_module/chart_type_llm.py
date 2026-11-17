"""HCX 호출 (노트북 0번)

CLOVA Studio v3 Chat Completions. schema를 주면 JSON 구조화 출력.
(노트북 chart_type_decision.ipynb에서 옮김 — 로직은 노트북과 같다)
"""
import json
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

# .env는 저장소 최상위에 있음 → 실행 위치에서 위로 찾고, 못 찾으면 이 파일 위치에서 위로 찾는다
load_dotenv(find_dotenv(usecwd=True))
if not os.getenv("HCX_API_KEY"):
    for _p in Path(__file__).resolve().parents:
        if (_p / ".env").exists():
            load_dotenv(_p / ".env")
            break

def _host(url):
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"

HCX_HOST = _host(os.getenv("HCX_BASE_URL"))

CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")

APP_TYPE = os.getenv("HCX_APP_TYPE", "testapp").strip()

_tls = threading.local()

class HcxError(Exception):
    def __init__(self, http, code, msg):
        super().__init__(f"HTTP {http} / {code}: {msg}")
        self.http, self.code = http, str(code)

def _session():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
    return _tls.s

def _post(path, body, timeout=60):
    key = os.getenv("HCX_API_KEY", "").strip()
    if not key:
        raise RuntimeError(".env 에 HCX_API_KEY 를 넣어 주세요.")
    path = f"/{APP_TYPE}/" + path.lstrip("/")          # 예: /testapp/v3/chat-completions/HCX-007
    try:
        r = _session().post(HCX_HOST + path, json=body, timeout=timeout, headers={
            "Authorization": f"Bearer {key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
            "Content-Type": "application/json; charset=utf-8"})
    except (requests.ConnectionError, requests.Timeout):
        _tls.__dict__.pop("s", None)                   # 끊긴 세션 버리기
        raise
    try:
        data = r.json()
    except ValueError:
        raise HcxError(r.status_code, "-", r.text[:200])
    st = data.get("status") or {}
    if r.status_code != 200 or str(st.get("code", "20000")) != "20000":
        raise HcxError(r.status_code, st.get("code", "-"), st.get("message") or str(data)[:200])
    return data.get("result") or {}

def with_retry(fn, tries=5):
    """429·5xx·네트워크 끊김은 점점 길게 기다리며 재시도, 400 등 요청 오류는 즉시 중단"""
    for i in range(tries):
        try:
            return fn()
        except HcxError as e:
            if e.http not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(min(60, (5 if e.http == 429 else 2) * 2 ** i) + random.random())
        except (requests.ConnectionError, requests.Timeout):
            if i == tries - 1:
                raise
            time.sleep(min(60, 2 * 2 ** i) + random.random())

def hcx_chat(messages, schema=None, temperature=0.0, max_tokens=1500, model=None):
    """HCX v3 대화. schema를 주면 구조화 출력(JSON). HCX-007은 thinking.effort=none으로 호출"""
    model = model or CHAT_MODEL
    body = {"messages": messages, "temperature": temperature, "topP": 0.8,
            "maxCompletionTokens": max_tokens, "repetitionPenalty": 1.1}
    if model.upper().startswith("HCX-007"):
        body["thinking"] = {"effort": "none"}
    if schema:
        body["responseFormat"] = {"type": "json", "schema": schema}
    res = with_retry(lambda: _post(f"/v3/chat-completions/{model}", body))
    txt = (res.get("message") or {}).get("content") or ""
    if not schema:
        return txt
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0) if m else txt)
    except json.JSONDecodeError:
        return {"_raw": txt}
