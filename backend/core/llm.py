"""
HCX(HyperCLOVA X) 클라이언트 — 대화와 CLOVA 임베딩 v2(bge-m3)

  chat(messages, schema=None, ...)   대화. schema 를 주면 구조화 출력(JSON)
  chat(..., thinking="low")          HCX-007 추론(low·medium·high). 추론은 구조화 출력과 함께 못 써서(HCX 문서) schema 를
                                     요청에 넣지 않고 응답 글에서 JSON 을 뽑음. maxCompletionTokens 는 추론 토큰을 포함 →
                                     effort 별 기본값(5120·10240·20480). 오래 걸려 시간 제한 180초·시간 초과 재시도 1회
  embed_one / embed_many             임베딩 (캐시: config.EMBED_CACHE sqlite, VECTOR_STORE=pgvector 면 db-server.
                                     같은 문장은 한 번만 호출)

429·5xx·네트워크 끊김은 점점 길게 기다리며 재시도하고, 400 등 요청 오류는 바로 올린다.
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

from backend.core.config import EMBED_CACHE


def _host(url):
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


HCX_HOST = _host(os.getenv("HCX_BASE_URL"))
CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")
EMBED_PATH = os.getenv("HCX_EMBED_PATH", "/v1/api-tools/embedding/v2")
EMBED_MODEL = "clova-embedding-v2(bge-m3)"
EMBED_MAX_CHARS = 6000

_tls = threading.local()


class HcxError(Exception):
    def __init__(self, http, code, msg):
        super().__init__(f"HTTP {http} / {code}: {msg}")
        self.http, self.code = http, str(code)


class HcxKeyMissing(RuntimeError):
    pass


def _session():
    if not hasattr(_tls, "s"):
        import requests
        _tls.s = requests.Session()
    return _tls.s


def _post(path, body, timeout=60):
    key = os.getenv("HCX_API_KEY", "").strip()
    if not key:
        raise HcxKeyMissing(".env 에 HCX_API_KEY 를 넣어 주세요.")
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


def with_retry(fn, tries=8, timeout_tries=None):
    """timeout_tries: 시간 초과·끊김만 따로 이 횟수까지 (추론 호출 — 같은 긴 요청을 8번 되풀이하지 않게)"""
    t_left = timeout_tries
    for i in range(tries):
        try:
            return fn()
        except HcxError as e:
            if e.http not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(min(60, (5 if e.http == 429 else 2) * 2 ** i) + random.random())
        except HcxKeyMissing:
            raise
        except Exception:  # noqa: BLE001  (RemoteDisconnected, Timeout 등)
            if i == tries - 1 or (t_left is not None and t_left <= 1):
                raise
            if t_left is not None:
                t_left -= 1
            time.sleep(min(60, 2 * 2 ** i) + random.random())


def _chat_path(model):
    app_type = os.getenv("HCX_APP_TYPE", "testapp").strip()
    return f"/{app_type}/v3/chat-completions/{model}"


THINK_TOKENS = {"low": 5120, "medium": 10240, "high": 20480}  # HCX 문서의 effort 별 기본 maxCompletionTokens


def chat(messages, schema=None, temperature=0.0, max_tokens=1500, model=None, thinking=None, timeout=None,
         with_thinking=False):
    """HCX v3 대화. 기본은 추론 없이(effort none) — 구조화 출력(schema)은 추론과 함께 쓸 수 없음 (HCX 문서)
    thinking: 'low'|'medium'|'high' 이면 HCX-007 추론을 켬. schema 는 요청에 넣지 않고 응답 글의 JSON 을 파싱
      (스키마를 따르게 하려면 프롬프트에 형식을 적을 것). max_tokens 는 추론 토큰 포함 → 작으면 effort 기본값으로 올림
    with_thinking: schema 와 함께 쓰면 결과 dict 에 '_thinking' (추론 글) · '_finish' 를 붙임 (진단용 — 사용자에게 보이지 말 것)"""
    model = model or CHAT_MODEL
    think = str(thinking or "").lower() if thinking and str(thinking).lower() != "none" else None
    if think and think not in THINK_TOKENS:
        raise ValueError(f"thinking 은 low·medium·high 중 하나: {thinking}")
    if think and not model.upper().startswith("HCX-007"):
        think = None                                   # 추론 모델이 아님 → 일반 호출
    if think:
        max_tokens = max(int(max_tokens or 0), THINK_TOKENS[think])
    body = {"messages": messages, "temperature": temperature, "topP": 0.8,
            "maxCompletionTokens": max_tokens, "repetitionPenalty": 1.1}
    if model.upper().startswith("HCX-007"):
        body["thinking"] = {"effort": think or "none"}
    if schema and not think:
        body["responseFormat"] = {"type": "json", "schema": schema}
    path = _chat_path(model)
    to = timeout or (180 if think else 60)
    try:
        res = with_retry(lambda: _post(path, body, timeout=to), timeout_tries=2 if think else None)
    except HcxError as e:
        if not schema or e.http != 400:
            raise
        body.pop("responseFormat")                     # 구조화 출력 미지원 모델 → 일반 응답 + JSON 파싱
        res = with_retry(lambda: _post(path, body, timeout=to))
    msg = res.get("message") or {}
    txt = msg.get("content") or ""
    if not schema:
        return txt
    out = parse_json(txt)
    if with_thinking and isinstance(out, dict):
        out["_thinking"] = msg.get("thinkingContent") or ""
        out["_finish"] = res.get("finishReason") or ""
    return out


def parse_json(txt):
    """응답 글 → dict. 코드 울타리(```json)·앞뒤 설명을 견딤. 못 읽으면 {'_raw': 글}"""
    t = re.sub(r"```(?:json)?", "", txt or "")
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0) if m else t)
    except json.JSONDecodeError:
        return {"_raw": txt}


class _EmbedCache:
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

    def get_many(self, texts):
        return [self.get(t) for t in texts]

    def put(self, text, vec):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)",
                            (self.key(text), np.asarray(vec, dtype=np.float32).tobytes()))
            self.db.commit()


_cache = None


def embed_cache():
    """VECTOR_STORE=pgvector 면 db-server 의 vec.embedding_cache (backend/db/vectors.py), 아니면 sqlite (EMBED_CACHE)"""
    global _cache
    if _cache is None:
        from backend.db.conn import vector_store
        if vector_store() == "pgvector":
            from backend.db.vectors import PgEmbedCache
            _cache = PgEmbedCache(EMBED_MODEL)
        else:
            _cache = _EmbedCache(EMBED_CACHE)
    return _cache


def embed_one(text):
    text = (text or "")[:EMBED_MAX_CHARS]
    v = embed_cache().get(text)
    if v is not None:
        return v
    res = with_retry(lambda: _post(EMBED_PATH, {"text": text}))
    v = np.asarray(res["embedding"], dtype=np.float32)
    embed_cache().put(text, v)
    return v


def embed_many(texts, workers=4, progress=print):
    """1건마다 캐시에 저장 → 중단·실패해도 다시 실행하면 남은 것만 호출"""
    out = embed_cache().get_many([(t or "")[:EMBED_MAX_CHARS] for t in texts])
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
            el = max(time.time() - t0, 1e-6)
            progress(f"  {n}/{len(todo)}  {n / el:.2f}건/초  남은 시간 약 {el / n * (len(todo) - n) / 60:.0f}분"
                     + (f"  실패 {len(failed)}" if failed else ""))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, todo))
    if failed:
        raise RuntimeError(f"임베딩 {len(failed)}건 실패 (나머지는 캐시에 저장됨, 다시 실행하면 실패한 것만 호출). "
                           f"예: {failed[:3]}")
    return np.vstack(out) if out else np.zeros((0, 1024), np.float32)
