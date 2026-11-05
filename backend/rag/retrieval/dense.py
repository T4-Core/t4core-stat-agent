"""
(구 view_model/services/embedding.py) 임베딩 클라이언트 — CLOVA Studio 임베딩 v2 (bge-m3 기반, 1024차원) 를 HCX API 로 호출

  POST {HCX 호스트}/v1/api-tools/embedding/v2   body {"text": ...}   (한 번에 문장 1개)
  인증: .env 의 HCX_API_KEY (Bearer)

- 같은 (모델, 문장) 은 한 번만 호출: view_model/output/embed_cache.sqlite 에 저장 → 중단 후 다시 실행하면 이어서
- 429·5xx·네트워크 끊김은 점점 길게 기다리며 재시도, 400 등 요청 오류는 바로 중단
- 공용 kosis_rag_qa.py 와 같은 방식이지만 import 하지 않음 (import 하면 캐시가 공용 폴더 kosis_data/index 에 써짐)
- dense 벡터만 돌려준다 (bge-m3 의 sparse 는 API 에 없음) → 키워드 검색은 resolve 의 BM25 가 맡음
"""
import hashlib
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from backend.core.config import VIEW_EMBED_CACHE   # .env 는 config 가 import 될 때 읽음
# [CHANGED] 이전: from dotenv import load_dotenv
#                from config import OUT, ROOT
#                load_dotenv(ROOT / ".env")

EMBED_PATH = "/v1/api-tools/embedding/v2"
EMBED_MODEL = "clova-embedding-v2(bge-m3)"     # 캐시 키 구분용 이름
MAX_CHARS = 6000                               # 입력 한도(약 8k 토큰) 여유


def _host():
    # 'https://host/v1/openai' 처럼 경로까지 넣어도 호스트만 사용
    m = re.match(r"(https?://[^/\s]+)", (os.getenv("HCX_BASE_URL") or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


class HcxError(Exception):
    def __init__(self, http, code, msg):
        super().__init__(f"HTTP {http} / {code}: {msg}")
        self.http = http


_tls = threading.local()


def _post(text, timeout=60):
    key = os.getenv("HCX_API_KEY")
    if not key:
        raise RuntimeError(".env 에 HCX_API_KEY 가 없습니다")
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
    r = _tls.s.post(_host() + EMBED_PATH, json={"text": text}, timeout=timeout, headers={
        "Authorization": f"Bearer {key}", "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
        "Content-Type": "application/json; charset=utf-8"})
    try:
        data = r.json()
    except ValueError:
        raise HcxError(r.status_code, "-", r.text[:200])
    st = data.get("status") or {}
    if r.status_code != 200 or str(st.get("code", "20000")) != "20000":
        raise HcxError(r.status_code, st.get("code", "-"), st.get("message") or str(data)[:200])
    return (data.get("result") or {})["embedding"]


def _with_retry(fn, tries=8):
    for i in range(tries):
        try:
            return fn()
        except HcxError as e:
            if e.http not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(min(60, (5 if e.http == 429 else 2) * 2 ** i) + random.random())
        except requests.RequestException:
            _tls.__dict__.pop("s", None)
            if i == tries - 1:
                raise
            time.sleep(min(60, 2 * 2 ** i) + random.random())


class _Cache:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB)")
        self.lock = threading.Lock()

    @staticmethod
    def key(text):
        return hashlib.sha1(f"{EMBED_MODEL}\n{text}".encode()).hexdigest()

    def get(self, text):
        with self.lock:
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
        _cache = _Cache(VIEW_EMBED_CACHE)   # [CHANGED] 이전: _Cache(OUT / "embed_cache.sqlite")
    return _cache


def embed_one(text):
    text = (text or "")[:MAX_CHARS]
    v = cache().get(text)
    if v is not None:
        return v
    v = np.asarray(_with_retry(lambda: _post(text)), dtype=np.float32)
    cache().put(text, v)
    return v


def embed_many(texts, workers=4, progress=print):
    # 일괄 임베딩. 1건마다 캐시에 저장 → 실패·중단돼도 다시 실행하면 남은 것만 호출
    out = [cache().get((t or "")[:MAX_CHARS]) for t in texts]
    todo = [i for i, v in enumerate(out) if v is None]
    progress(f"임베딩: 전체 {len(texts)}, 캐시 {len(texts) - len(todo)}, 새로 호출 {len(todo)}")
    done, failed, lock, t0 = [0], [], threading.Lock(), time.time()

    def job(i):
        try:
            out[i] = embed_one(texts[i])
        except Exception as e:  # noqa: BLE001  (1건 실패로 전체를 멈추지 않음)
            with lock:
                failed.append((i, f"{e.__class__.__name__}: {str(e)[:120]}"))
        with lock:
            done[0] += 1
            n = done[0]
        if n % 100 == 0 or n == len(todo):
            el = max(time.time() - t0, 1e-6)    # [CHANGED 11-03] 너무 빨리 끝나면(테스트용 가짜 임베딩) 0초 → 0 으로 나누기 오류
            progress(f"  {n}/{len(todo)}  {n / el:.2f}건/초  남은 시간 약 {el / n * (len(todo) - n) / 60:.0f}분"
                     + (f"  실패 {len(failed)}" if failed else ""))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, todo))
    if failed:
        raise RuntimeError(f"임베딩 {len(failed)}건 실패 (나머지는 캐시에 저장됨, 다시 실행하면 실패한 것만 호출). "
                           f"예: {failed[:3]}")
    return np.vstack(out)


def normalize(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-12)
