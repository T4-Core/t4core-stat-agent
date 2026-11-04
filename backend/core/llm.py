"""
HCX(HyperCLOVA X) 대화 + CLOVA 임베딩 v2(bge-m3) 클라이언트  (구 kosis_rag_qa.py 의 HCX 호출부를 그대로 옮김)

  chat(messages, schema=None, ...)   대화 (구조화 출력 지원)          ← 질의 재작성(query_analyzer)·답변(agent) 공용
  embed_one / embed_many / normalize 임베딩 (캐시: RAG_INDEX_DIR/embed_cache.sqlite)

[CHANGED] 이전에는 kosis_rag_qa.py 안에 있었고, rewriter 는 kosis_rag_qa.py '복사본'을 파일 경로로 import 해 chat() 을 썼음
          → 복사본(Rewritten_fastapi/kosis_rag_qa.py) 삭제, 모두 이 모듈을 import
[CHANGED] .env 는 backend.core.config 가 import 될 때 한 번 읽음 (이전: load_dotenv(Path.cwd() / ".env"))
[CHANGED] 캐시 위치: INDEX_DIR(= kosis_data/index) → config.RAG_INDEX_DIR (예전 위치에 캐시가 있으면 그대로 사용)

※ View 모듈의 임베딩 클라이언트(backend/rag/retrieval/dense.py)는 캐시 키·위치가 달라 아직 별도로 둠 (추후 통합 대상)
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from backend.core.config import RAG_INDEX_DIR

INDEX_DIR = RAG_INDEX_DIR   # [CHANGED] 이전: INDEX_DIR = DATA / "index"   (DATA = Path(os.getenv("KOSIS_DATA", "kosis_data")))

# ─── 아래는 구 kosis_rag_qa.py 57~65행 를 그대로 옮긴 코드 ───
def _host(url):
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


HCX_HOST = _host(os.getenv("HCX_BASE_URL"))
CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")
EMBED_PATH = os.getenv("HCX_EMBED_PATH", "/v1/api-tools/embedding/v2")
EMBED_MODEL = "clova-embedding-v2"                    # 캐시 키 구분용 이름


_tls = threading.local()

class HcxError(Exception):
    def __init__(self, http, code, msg):
        super().__init__(f"HTTP {http} / {code}: {msg}")
        self.http, self.code = http, str(code)


def _session():
    if not hasattr(_tls, "s"):
        import requests
        _tls.s = requests.Session()
    return _tls.s


def _post(path, body, timeout=60):
    key = os.getenv("HCX_API_KEY", "").strip()
    if not key:
        raise SystemExit(".env 에 HCX_API_KEY 를 넣어 주세요.")

    app_type = os.getenv("HCX_APP_TYPE", "testapp").strip()
    if path.startswith(("/serviceapp/", "/testapp/")):
        path = re.sub(r"^/(serviceapp|testapp)/", f"/{app_type}/", path)
    elif not path.startswith(f"/{app_type}/"):
        path = f"/{app_type}/" + path.lstrip("/")

    import requests
    try:
        r = _session().post(HCX_HOST + path, json=body, timeout=timeout, headers={
            "Authorization": f"Bearer {key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
            "Content-Type": "application/json; charset=utf-8"})
    except (requests.ConnectionError, requests.Timeout):
        _tls.__dict__.pop("s", None)                  
        raise
    try:
        data = r.json()
    except ValueError:
        raise HcxError(r.status_code, "-", r.text[:200])
    st = data.get("status") or {}
    if r.status_code != 200 or str(st.get("code", "20000")) != "20000":
        raise HcxError(r.status_code, st.get("code", "-"), st.get("message") or str(data)[:200])
    return data.get("result") or {}


def with_retry(fn, tries=8):
    """429·5xx·네트워크 끊김은 점점 길게 기다리며 재시도 (최대 약 5분), 400 등 요청 오류는 즉시 중단"""
    for i in range(tries):
        try:
            return fn()
        except HcxError as e:
            if e.http not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(min(60, (5 if e.http == 429 else 2) * 2 ** i) + random.random())
        except Exception:  # noqa: BLE001  (RemoteDisconnected, Timeout 등)
            if i == tries - 1:
                raise
            time.sleep(min(60, 2 * 2 ** i) + random.random())


def chat(messages, schema=None, temperature=0.0, max_tokens=1500, model=None):
    """HCX v3 대화. schema 를 주면 구조화 출력(responseFormat json + schema).
    HCX-007 의 구조화 출력은 추론(thinking)과 함께 쓸 수 없어 effort=none 으로 호출
    [CHANGED] model 인자 추가 (단계별로 다른 모델을 쓸 때). 비우면 예전과 같이 .env 의 HCX_MODEL"""
    model = model or CHAT_MODEL
    body = {"messages": messages, "temperature": temperature, "topP": 0.8,
            "maxCompletionTokens": max_tokens, "repetitionPenalty": 1.1}
    if model.upper().startswith("HCX-007"):          # [CHANGED] 이전: CHAT_MODEL.upper()…
        body["thinking"] = {"effort": "none"}
    if schema:
        body["responseFormat"] = {"type": "json", "schema": schema}
    path = f"/v3/chat-completions/{model}"            # [CHANGED] 이전: …/{CHAT_MODEL}
    try:
        res = with_retry(lambda: _post(path, body))
    except HcxError as e:
        if not schema or e.http != 400:
            raise
        body.pop("responseFormat")                     # 구조화 출력 미지원 모델 → 일반 응답 + JSON 파싱
        res = with_retry(lambda: _post(path, body))
    txt = ((res.get("message") or {}).get("content")) or ""
    if not schema:
        return txt
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0) if m else txt)
    except json.JSONDecodeError:
        return {"_raw": txt}


class EmbedCache:
    """같은 (모델, 텍스트)는 한 번만 임베딩. 중단 후 재실행 시 이어서 진행"""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.lock = threading.Lock()

    @staticmethod
    def key(text):
        return hashlib.sha1(f"{EMBED_MODEL}\n{text}".encode()).hexdigest()

    def get(self, text):
        with self.lock:                                # 연결 하나를 여러 스레드가 쓰므로 읽기도 잠금
            row = self.db.execute("SELECT v FROM emb WHERE k=?", (self.key(text),)).fetchone()
        return np.frombuffer(row[0], dtype=np.float32) if row else None

    def put(self, text, vec):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)",
                            (self.key(text), np.asarray(vec, dtype=np.float32).tobytes()))
            self.db.commit()


_cache = None


def cache():
    global _cache
    if _cache is None:
        _cache = EmbedCache(INDEX_DIR / "embed_cache.sqlite")
    return _cache


def embed_one(text):
    text = text[:6000]                                 # 임베딩 v2 입력 한도(약 8k 토큰) 여유
    v = cache().get(text)
    if v is not None:
        return v
    res = with_retry(lambda: _post(EMBED_PATH, {"text": text}))
    v = np.asarray(res["embedding"], dtype=np.float32)
    cache().put(text, v)
    return v


def embed_many(texts, workers=4):
    """임베딩 일괄 처리. 결과는 1건마다 캐시에 저장 → 중단·실패해도 다시 실행하면 이어서 진행"""
    out = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        v = cache().get(t[:6000])
        if v is None:
            todo.append(i)
        else:
            out[i] = v
    print(f"  임베딩: 전체 {len(texts)}, 캐시 {len(texts) - len(todo)}, 새로 호출 {len(todo)}", flush=True)
    done, failed = [0], []
    lock = threading.Lock()
    t0 = time.time()

    def job(i):
        try:
            out[i] = embed_one(texts[i])
        except Exception as e:  # noqa: BLE001  (1건 실패로 전체를 멈추지 않음)
            with lock:
                failed.append((i, f"{e.__class__.__name__}: {str(e)[:120]}"))
        with lock:
            done[0] += 1
            n = done[0]
        if n % 200 == 0 or n == len(todo):
            el = time.time() - t0
            eta = el / n * (len(todo) - n)
            print(f"    임베딩 {n}/{len(todo)}  {n / el:.2f}건/초  경과 {el / 60:.0f}분  남은 시간 약 {eta / 60:.0f}분"
                  + (f"  실패 {len(failed)}" if failed else ""), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, todo))
    if failed:
        for i, msg in failed[:5]:
            print(f"    ✗ #{i}: {msg}")
        raise SystemExit(f"임베딩 {len(failed)}건 실패 (나머지 {len(todo) - len(failed)}건은 캐시에 저장됨). "
                         f"같은 명령을 다시 실행하면 실패한 건만 다시 호출합니다.")
    return np.vstack(out)


def normalize(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-12)
