"""
KOSIS 통계 RAG 질의응답: BM25(Kiwi) + Dense(HCX 임베딩) 하이브리드 검색 → HCX 답변

데이터셋 두 가지(variant)를 각각 인덱싱해 비교할 수 있습니다.
  base     : kosis_views.py views 결과 (LLM 보강 없음)      kosis_data/rag_views/records.jsonl
  enriched : LLM(GPT 등)으로 보강한 결과                   kosis_data/rag_views_enriched/records.jsonl  (경로는 --records 로 변경)

단계
  python kosis_rag_qa.py index   --variant base                 # BM25 + Dense 인덱스 생성 (임베딩은 캐시되어 이어서 진행)
  python kosis_rag_qa.py index   --variant enriched --records <보강된 records.jsonl>
  python kosis_rag_qa.py search  "서울 인구 추이" --variant base   # 검색 결과만 확인 (LLM 호출 없음, 임베딩 1회)
  python kosis_rag_qa.py ask     "최근 10년 서울 인구 어떻게 변했어?" --variant base
  python kosis_rag_qa.py compare "1인 가구 많은 지역은?"           # base vs enriched 검색·답변 나란히 비교
  python kosis_rag_qa.py eval    --variant base --n 200          # 검색 성능(Recall@k, MRR) 자동 측정

.env
  HCX_API_KEY=nv-...                                   # CLOVA Studio API 키 (Bearer 인증, HMAC 서명 불필요)
  HCX_BASE_URL=https://clovastudio.stream.ntruss.com   # 호스트까지만 (경로는 코드가 붙임)
  HCX_MODEL=HCX-007                                    # 답변·질의 재작성 모델 (v3 Chat Completions)
  # 선택: HCX_EMBED_PATH=/v1/api-tools/embedding/v2     # 임베딩 v2 (1024차원, 입력 약 8k 토큰)

호출 API (CLOVA Studio 기본 REST, openai SDK 사용 안 함)
  대화   POST {HCX_BASE_URL}/v3/chat-completions/{HCX_MODEL}
         HCX-007 은 구조화 출력(JSON 스키마) 사용 시 thinking.effort=none 이어야 함
  임베딩 POST {HCX_BASE_URL}/v1/api-tools/embedding/v2   body {"text": ...}

필요 패키지: pip install requests rank-bm25 kiwipiepy numpy pandas duckdb pyarrow python-dotenv  (차트: plotly)
같은 폴더의 kosis_views.py 에서 load_view(좌표 → 데이터)와 render(차트)를 가져다 씁니다.
"""
import argparse
import hashlib
import json
import math
import os
import pickle
import random
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env")

DATA = Path(os.getenv("KOSIS_DATA", "kosis_data"))
VIEWS_DIR = DATA / "rag_views"                       # processed/ 가 있는 곳 (좌표의 기준 폴더)
INDEX_DIR = DATA / "index"
DEFAULT_RECORDS = {"base": VIEWS_DIR / "records.jsonl",
                   "enriched": DATA / "rag_views_enriched" / "records.jsonl"}

def _host(url):
    """'https://host/v1/openai' 처럼 경로까지 넣어도 호스트만 사용"""
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


HCX_HOST = _host(os.getenv("HCX_BASE_URL"))
CHAT_MODEL = os.getenv("HCX_MODEL", "HCX-007")
EMBED_PATH = os.getenv("HCX_EMBED_PATH", "/v1/api-tools/embedding/v2")
EMBED_MODEL = "clova-embedding-v2"                    # 캐시 키 구분용 이름
RRF_K = 60
TOKEN_TAGS = ("NN", "SL", "SN", "XR", "VV", "VA")     # kosis_views.py --kiwi 와 같은 기준


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
    key = os.getenv("HCX_API_KEY")
    if not key:
        raise SystemExit(".env 에 HCX_API_KEY 를 넣어 주세요.")
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


def chat(messages, schema=None, temperature=0.0, max_tokens=1500):
    """HCX v3 대화. schema 를 주면 구조화 출력(responseFormat json + schema).
    HCX-007 의 구조화 출력은 추론(thinking)과 함께 쓸 수 없어 effort=none 으로 호출"""
    body = {"messages": messages, "temperature": temperature, "topP": 0.8,
            "maxCompletionTokens": max_tokens, "repetitionPenalty": 1.1}
    if CHAT_MODEL.upper().startswith("HCX-007"):
        body["thinking"] = {"effort": "none"}
    if schema:
        body["responseFormat"] = {"type": "json", "schema": schema}
    path = f"/v3/chat-completions/{CHAT_MODEL}"
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

# 토큰 -bm25 용
_kiwi = None


REGION_SUFFIX = re.compile(r"(특별자치시|특별자치도|특별자치|특별시|광역시|자치시|자치도|도)$")


def tokenize(text):
    """BM25 토큰: 기본 형태소 + 복합어 분해 + 지역명·비율 용어 축약형
    예) 서울특별시 → 서울특별시, 서울 / 경기도 → 경기도, 경기 / 합계출산율 → 합계출산율, 출산율
    문서와 질의에 똑같이 적용해야 하므로 인덱싱 때도 bm25_tokens 대신 이 함수로 다시 토큰화합니다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    text = str(text)
    toks = [t.form for t in _kiwi.tokenize(text) if t.tag.startswith(TOKEN_TAGS)]
    extra = [t.form for t in _kiwi.tokenize(text, split_complex=True) if t.tag.startswith(TOKEN_TAGS)]
    for t in toks:
        if len(t) >= 3 and REGION_SUFFIX.search(t):
            stem = REGION_SUFFIX.sub("", t)
            if len(stem) >= 2:
                extra.append(stem)
        if len(t) >= 4 and t[-1] in "율률":
            extra.append(t[-3:])
    return toks + [e for e in extra if e not in toks]


# 인덱스
def load_records(path):
    return [json.loads(l) for l in Path(path).open(encoding="utf-8") if l.strip()]


def embed_texts_of(rec, mode):
    """Dense 에 넣을 텍스트. single: embed_text 1개 / multi: + 질문마다 별도 벡터(같은 레코드를 가리킴)"""
    texts = [rec["embed_text"]]
    if mode == "multi":
        texts += [q for q in (rec.get("questions") or [])[:12]] + [p for p in (rec.get("paraphrases") or [])[:5]]
    return texts


def stage_index(args):
    recs = load_records(args.records)
    if args.doc_type:
        recs = [r for r in recs if r.get("doc_type") == args.doc_type]
    if args.limit:
        recs = recs[: args.limit]
    out = INDEX_DIR / args.variant
    out.mkdir(parents=True, exist_ok=True)
    print(f"[{args.variant}] 레코드 {len(recs)}개 ← {args.records}")

    # BM25: Kiwi 형태소 + 축약형 토큰
    from rank_bm25 import BM25Okapi
    toks = [tokenize(r["bm25_text"]) for r in recs]   # 질의와 같은 규칙으로 토큰화
    bm25 = BM25Okapi(toks)
    print("  BM25 인덱스 완료")

    # Dense: HCX 임베딩
    owners, texts = [], []
    for i, r in enumerate(recs):
        for t in embed_texts_of(r, args.dense_mode):
            owners.append(i)
            texts.append(t)
    mat = normalize(embed_many(texts, workers=args.workers))
    np.save(out / "dense.npy", mat.astype(np.float32))
    np.save(out / "dense_owner.npy", np.asarray(owners, dtype=np.int32))
    with (out / "bm25.pkl").open("wb") as f:
        pickle.dump(bm25, f)
    meta = [{"id": r["id"], "doc_type": r.get("doc_type"), "parent_id": r.get("parent_id")} for r in recs]
    (out / "meta.json").write_text(json.dumps({
        "variant": args.variant, "records": str(args.records), "n": len(recs), "dense_mode": args.dense_mode,
        "embed_model": EMBED_MODEL, "dim": int(mat.shape[1]), "n_vectors": int(mat.shape[0]),
        "built": datetime.now().isoformat(timespec="seconds"), "docs": meta}, ensure_ascii=False), encoding="utf-8")
    print(f"  Dense 벡터 {mat.shape} 저장 → {out}")


class Index:
    """하이브리드 검색기: BM25 + Dense → RRF, 연도·최신 보정, 표(parent) 맥락 연결"""

    def __init__(self, variant):
        d = INDEX_DIR / variant
        if not (d / "meta.json").exists():
            raise SystemExit(f"인덱스 없음: {d}  →  python kosis_rag_qa.py index --variant {variant}")
        self.meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.variant = variant
        recs = load_records(self.meta["records"])
        keep = {m["id"] for m in self.meta["docs"]}
        self.by_id = {r["id"]: r for r in recs if r["id"] in keep}
        self.ids = [m["id"] for m in self.meta["docs"]]
        with (d / "bm25.pkl").open("rb") as f:
            self.bm25 = pickle.load(f)
        self.dense = np.load(d / "dense.npy")
        self.owner = np.load(d / "dense_owner.npy")

    def search_bm25(self, query, k=10):
        """BM25 단독 검색 → [{id, score, title}] (점수 > 0 인 것만)"""
        bs = self.bm25.get_scores(tokenize(query))
        return [{"id": self.ids[i], "score": float(bs[i]), "title": self.by_id[self.ids[i]]["title"]}
                for i in np.argsort(-bs)[:k] if bs[i] > 0 and self.ids[i] in self.by_id]

    def search_dense(self, query, k=10, query_vec=None):
        """Dense 단독 검색 → [{id, score(코사인 유사도), title}] (multi-vector 면 레코드별 최고값)"""
        qv = query_vec if query_vec is not None else normalize(embed_one(query))
        sims = self.dense @ qv
        best = {}
        for vi in np.argsort(-sims)[: k * 20]:
            o = int(self.owner[vi])
            if o not in best:
                best[o] = float(sims[vi])
            if len(best) >= k:
                break
        return [{"id": self.ids[o], "score": s, "title": self.by_id[self.ids[o]]["title"]}
                for o, s in sorted(best.items(), key=lambda x: -x[1]) if self.ids[o] in self.by_id]

    def search(self, query, k=10, pool=50, doc_type=None, query_vec=None):
        # 1) BM25
        bs = self.bm25.get_scores(tokenize(query))
        bm_rank = {int(i): r for r, i in enumerate(np.argsort(-bs)[:pool]) if bs[i] > 0}
        # 2) Dense (multi-vector 면 레코드별 최고 점수)
        qv = query_vec if query_vec is not None else normalize(embed_one(query))
        sims = self.dense @ qv
        best = {}
        for vi in np.argsort(-sims)[: pool * 4]:
            o = int(self.owner[vi])
            if o not in best:
                best[o] = float(sims[vi])
            if len(best) >= pool:
                break
        de_rank = {o: r for r, o in enumerate(sorted(best, key=lambda x: -best[x]))}
        # 3) RRF 결합
        cand = set(bm_rank) | set(de_rank)
        years = [int(y) for y in re.findall(r"(19\d{2}|20\d{2})", query)]
        wants_latest = bool(re.search(r"최근|최신|요즘|현재|올해|작년", query))
        scored = []
        for i in cand:
            rec = self.by_id.get(self.ids[i])
            if rec is None or (doc_type and rec.get("doc_type") != doc_type):
                continue
            s = sum(1 / (RRF_K + r + 1) for r in (bm_rank.get(i), de_rank.get(i)) if r is not None)
            f = rec.get("filters", {})
            try:                                       # 질문의 연도가 수록 범위 안이면 가산
                lo, hi = int(str(f.get("prd_from"))[:4]), int(str(f.get("prd_to"))[:4])
                if years and any(lo <= y <= hi for y in years):
                    s += 0.004
            except (TypeError, ValueError):
                pass
            if wants_latest and f.get("is_latest"):
                s += 0.002
            scored.append((s, i))
        scored.sort(reverse=True)
        hits = []
        for s, i in scored[:k]:
            rec = self.by_id[self.ids[i]]
            hits.append({"id": rec["id"], "score": round(s, 5), "title": rec["title"],
                         "doc_type": rec.get("doc_type"), "bm25_rank": bm_rank.get(i), "dense_rank": de_rank.get(i),
                         "dense_sim": round(best.get(i, float("nan")), 4)})
        return hits


# 질의 재정의
REWRITE_SCHEMA = {"type": "object", "properties": {
    "rewritten": {"type": "string"}, "sub_questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["rewritten", "sub_questions"]}
REWRITE_SYS = ("너는 한국 국가통계(KOSIS) 검색 도우미다. 사용자의 구어체 질문을 통계표 검색에 맞는 용어로 바꾼다. "
               "지역·연도·성별·연령 같은 조건은 유지하고, 없는 조건을 추가하지 않는다. "
               "여러 통계가 필요한 복합 질문이면 sub_questions 에 하위 질문(최대 3개)을 나누고, 단순 질문이면 빈 배열. JSON만 출력.")


def rewrite(question):
    out = chat([{"role": "system", "content": REWRITE_SYS},
                {"role": "user", "content": f"질문: {question}\n예) '애 낳는 사람 줄었어?' → '출생아수 추이'"}],
               schema=REWRITE_SCHEMA, max_tokens=300)
    rw = (out.get("rewritten") or question).strip()
    subs = [s for s in (out.get("sub_questions") or []) if isinstance(s, str) and s.strip()][:3]
    return rw, subs


# 답변
ANSWER_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"},
    "summary": {"type": "string"},
    "key_points": {"type": "array", "items": {"type": "string"}},
    "used_ids": {"type": "array", "items": {"type": "string"}},
    "chart_id": {"type": "string"},
    "insufficient": {"type": "boolean"}},
    "required": ["answer", "summary", "key_points", "used_ids", "chart_id", "insufficient"]}
ANSWER_SYS = """너는 한국 공식통계(KOSIS)를 근거로 답하는 통계 안내원이다.
규칙:
1. 반드시 [자료]에 있는 숫자만 쓴다. 계산(차이·증감률)이 필요하면 [자료]의 숫자로 계산하고 '약'을 붙인다. 없는 숫자를 만들지 않는다.
2. 질문에 맞는 자료가 없거나 조건(연도·지역)이 다르면 insufficient=true 로 하고, 가장 가까운 자료로 무엇을 알 수 있는지 설명한다.
   자료의 지역·시점이 질문과 다르면 그 값을 질문 대상의 값처럼 쓰지 않는다 (예: 전국 값을 서울 값으로 쓰지 않는다).
   '질문 조건 적용' 데이터가 있으면 그 값을 우선 사용한다. 지표 이름이 질문과 다르면(예: 주민등록인구 ↔ 주민등록연앙인구) 차이를 밝힌다.
3. 기준 시점과 단위를 항상 밝힌다. 주의사항이 있으면 한 문장으로 덧붙인다.
4. 문체는 '~입니다'체. answer 는 3~6문장, summary 는 1문장, key_points 는 핵심 수치 2~4개.
5. used_ids 에 실제로 근거로 쓴 자료 id, chart_id 에 그래프로 보여줄 자료 id 1개를 넣는다.
JSON만 출력한다."""


def fmt_v(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "자료없음"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def context_block(rec, max_rows, cond=None):
    """cond = (적용된 조건, 적용 못 한 조건, 조회 행) — 있으면 미리보기 대신 질문 조건에 맞춘 데이터를 넣음"""
    pv = rec.get("preview") or {}
    rows = pv.get("rows") or []
    cols = pv.get("columns") or []
    lines = [f"[자료 id={rec['id']}]",
             f"제목: {rec['title']}",
             f"출처: {rec.get('source_text') or rec.get('survey_nm', '')}",
             f"설명: {rec['description']}"]
    if cond:
        applied, missing, crow = cond
        if missing:
            lines.append("⚠ 질문 조건 중 이 자료에 없는 것: " + "; ".join(missing)
                         + " → 이 자료의 값을 질문 대상의 값으로 답하지 말 것")
        if applied and crow:
            lines.append("질문 조건 적용: " + ", ".join(f"{k}={v}" for k, v in applied.items()))
            lines += [r[0] for r in crow]
            if rec.get("caveats"):
                lines.append("주의: " + " / ".join(c[:150] for c in rec["caveats"][:3]))
            return "\n".join(lines)
    if rec.get("facts"):
        lines.append("핵심 수치(기본 단면): " + "; ".join(f["text"] for f in rec["facts"]))
    if rows:
        unit = (rec.get("filters") or {}).get("unit") or ""
        lines.append(f"데이터({' | '.join(cols)}, 단위 {unit}):")
        for r in rows[:max_rows]:
            lines.append("  " + " | ".join(fmt_v(x) if isinstance(x, (int, float)) else str(x) for x in r))
        if len(rows) > max_rows:
            lines.append(f"  … 외 {len(rows) - max_rows}행")
    if rec.get("caveats"):
        lines.append("주의: " + " / ".join(c[:150] for c in rec["caveats"][:3]))
    return "\n".join(lines)


NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def nums(text):
    out = set()
    for n in NUM_RE.findall(str(text)):
        n = n.replace(",", "")
        try:
            v = float(n)
        except ValueError:
            continue
        out.add(f"{v:.2f}")
        out.add(f"{round(v):.2f}")
    return out


def verify_numbers(answer_text, context_text):
    ctx = nums(context_text)
    bad = []
    for n in NUM_RE.findall(answer_text):
        v = n.replace(",", "")
        if len(v.replace(".", "")) <= 2:              # 1~2자리(순위·개수)는 제외
            continue
        if not (nums(n) & ctx):
            bad.append(n)
    return sorted(set(bad))



# 질문 조건 적용 (지역·연도·성별) 
SIDO = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
        "경기도", "강원특별자치도", "강원도", "충청북도", "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도",
        "경상남도", "제주특별자치도"]
_SHORT = re.compile(r"(특별자치시|특별자치도|특별시|광역시|도)$")
_PROFILES = {}


def short_name(nm):
    s = _SHORT.sub("", nm)
    return {"충청북": "충북", "충청남": "충남", "전라북": "전북", "전라남": "전남", "경상북": "경북", "경상남": "경남"}.get(s, s)


def mentioned_regions(q):
    """질문에 나온 시도 (정식명 기준). '서울', '경북' 같은 줄임말도 인식"""
    out = []
    for nm in SIDO:
        if nm in q or (len(short_name(nm)) >= 2 and short_name(nm) in q):
            out.append(nm)
    return list(dict.fromkeys(out))


def _profile(table_key):
    if table_key not in _PROFILES:
        p = VIEWS_DIR / "profiles" / f"{table_key}.json"
        _PROFILES[table_key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _PROFILES[table_key]


def apply_conditions(rec, question):
    """검색된 뷰의 좌표(source)에 질문의 지역·연도·성별을 적용
    → (새 좌표, 적용된 조건, 적용 못 한 조건)  예) 전국 추이 뷰 + '2023년 서울' → 서울·2023 좌표"""
    import copy
    src = copy.deepcopy(rec["source"])
    prof = _profile(src.get("table_key", ""))
    applied, missing = {}, []
    if not prof:
        return src, applied, ["표 구조 정보(profiles) 없음"]
    q = question
    # 지역
    want = mentioned_regions(q)
    geo = [lv for lv in prof["levels"] if lv["kind"] == "geo"]
    if geo:                                            # 이 표의 하위 지역(시군구 등) 이름도 인식
        local = sorted({c["name"] for c in geo[0]["codes"] if len(c["name"]) >= 2 and not c.get("is_total")
                        and c["name"] in q and c["name"] not in want}, key=len, reverse=True)
        want += [n for n in local if not any(n in w for w in want)]
    if want:
        if not geo:
            missing.append(f"지역({', '.join(want)}): 이 표에는 지역 분류가 없음")
        else:
            lv = geo[0]
            codes = [c["code"] for c in lv["codes"]
                     if c["name"] in want or any(short_name(w) == short_name(c["name"]) for w in want)]
            if codes:
                src["dims"][f"c{lv['level']}"] = {"codes": codes}
                applied["지역"] = want
            else:
                missing.append(f"지역({', '.join(want)}): 이 표의 지역 목록에 없음")
    # 성별
    sex = [w for w in ("남자", "여자") if w in q or w[0] + "성" in q]
    sexlv = [lv for lv in prof["levels"] if lv["kind"] == "sex"]
    if sex and sexlv:
        codes = [c["code"] for c in sexlv[0]["codes"] if c["name"] in sex]
        if codes:
            src["dims"][f"c{sexlv[0]['level']}"] = {"codes": codes}
            applied["성별"] = sex
    # 연도 (월·분기 표면 그해 전체)
    years = re.findall(r"(19\d{2}|20\d{2})\s*년?", q)
    plist = [p["prd_de"] for p in prof["periods"].get(src["prd_se"], [])]
    if years and plist:
        hit = [p for p in plist if p[:4] in years]
        if hit:
            src["period"] = {"in": hit}
            applied["시점"] = years
        else:
            missing.append(f"시점({', '.join(years)}): 수록기간 {plist[0]}~{plist[-1]} 밖")
    return src, applied, missing


def condition_rows(src, max_rows):
    """조건을 적용한 좌표로 실제 값을 다시 조회 → 문맥용 행"""
    from kosis_views import load_view
    df = load_view(src, VIEWS_DIR)
    name_cols = [c for c in df.columns if re.fullmatch(r"c\d_name", c)]
    cols = ["period_label"] + name_cols + ["itm_nm", "value", "unit"]
    df = df[[c for c in cols if c in df.columns]]
    return df, [["조건 적용 데이터: " + " | ".join(df.columns)]] + [
        [" | ".join(fmt_v(v) if isinstance(v, (int, float)) else str(v) for v in r)] for r in df.head(max_rows).values]


def load_chart_data(rec, src=None):
    """좌표(source)로 실제 데이터를 다시 조회 → 차트·근거표용. kosis_views.py 가 없으면 preview 사용"""
    try:
        from kosis_views import load_view
        df = load_view(src or rec["source"], VIEWS_DIR)
        cols = [c for c in ["period_label", rec["chart"]["x"], rec["chart"].get("series"), "itm_nm", "unit", "value"]
                if c and c in df.columns and c != "period_date"]
        return df[list(dict.fromkeys(cols))], "source"
    except Exception as e:  # noqa: BLE001
        import pandas as pd
        pv = rec.get("preview") or {}
        return pd.DataFrame(pv.get("rows") or [], columns=pv.get("columns") or None), f"preview ({e.__class__.__name__})"


def answer(question, variant="base", k=5, use_rewrite=True, max_rows=40, save=True, idx=None):
    idx = idx or Index(variant)
    t0 = time.time()
    rw, subs = rewrite(question) if use_rewrite else (question, [])
    queries = [rw] + subs
    # 원 질문 + 재작성 + 하위 질문 각각 검색 후 RRF 로 합침 (Decomposition)
    agg = {}
    weights = {q: 1.0 for q in queries}               # 재작성·하위 질문 = 1.0
    if question not in weights:
        weights[question] = 0.5                         # 원 질문(구어체)은 보조 신호로 절반만 반영
    for q, w in weights.items():
        for r, h in enumerate(idx.search(q, k=k * 2)):
            agg.setdefault(h["id"], {"h": h, "s": 0.0})["s"] += w / (RRF_K + r + 1)
    hits = [v["h"] | {"fused": round(v["s"], 5)} for v in sorted(agg.values(), key=lambda x: -x["s"])][:k]

    # 맥락: 뷰 우선, 표 레코드는 같은 표의 뷰가 없을 때만
    ctx_recs = []
    for h in hits:
        rec = idx.by_id[h["id"]]
        if rec.get("doc_type") == "table":
            vids = [v for v in rec.get("view_ids", []) if v in idx.by_id][:1]
            if vids and vids[0] not in [c["id"] for c in ctx_recs]:
                rec = idx.by_id[vids[0]]
        if rec["id"] not in [c["id"] for c in ctx_recs] and rec.get("doc_type") == "view":
            ctx_recs.append(rec)
    # 질문의 지역·연도·성별을 각 뷰의 좌표에 적용해 실제 값을 다시 조회
    conds, srcs = {}, {}
    for r in ctx_recs:
        try:
            src, applied, missing = apply_conditions(r, question)
            crow = condition_rows(src, max_rows)[1] if applied else None
        except Exception as e:  # noqa: BLE001  (kosis_views 없음 등 → 기존 미리보기 사용)
            src, applied, missing, crow = r["source"], {}, [f"조건 적용 실패: {e.__class__.__name__}"], None
        conds[r["id"]], srcs[r["id"]] = (applied, missing, crow), src
    # 조건을 모두 적용한 자료 → 일부 적용 → 미적용 순서로 정렬 (같은 순위면 검색 순서 유지)
    ctx_recs.sort(key=lambda r: (len(conds[r["id"]][1]) > 0, -len(conds[r["id"]][0])))
    ctx_recs = ctx_recs[:4]
    context = "\n\n".join(context_block(r, max_rows, conds[r["id"]]) for r in ctx_recs)
    asked = mentioned_regions(question) + re.findall(r"(19\d{2}|20\d{2})\s*년?", question)
    cond_ok = (not asked) or any(not conds[r["id"]][1] and conds[r["id"]][0] for r in ctx_recs)

    out = chat([{"role": "system", "content": ANSWER_SYS},
                {"role": "user", "content": f"[질문]\n{question}\n\n[검색어]\n{' / '.join(queries)}\n\n[자료]\n{context}"}],
               schema=ANSWER_SCHEMA, max_tokens=1200)
    ans = out.get("answer") or out.get("_raw", "")
    used = [u for u in (out.get("used_ids") or []) if u in idx.by_id] or [r["id"] for r in ctx_recs[:1]]
    chart_id = out.get("chart_id") if out.get("chart_id") in idx.by_id else (used[0] if used else None)
    unverified = verify_numbers(" ".join([ans, out.get("summary", "")] + list(out.get("key_points") or [])), context)

    result = {
        "question": question, "variant": variant, "rewritten": rw, "sub_questions": subs,
        "answer": ans, "summary": out.get("summary", ""), "key_points": out.get("key_points") or [],
        "insufficient": bool(out.get("insufficient")) or not cond_ok, "unverified_numbers": unverified,
        "conditions": {r["id"]: {"applied": conds[r["id"]][0], "missing": conds[r["id"]][1]} for r in ctx_recs},
        "condition_matched": cond_ok,
        "used_ids": used, "chart_id": chart_id,
        "sources": list(dict.fromkeys(
            f"{idx.by_id[u].get('source_text', '')} {idx.by_id[u]['source'].get('kosis_url', '')}".strip()
            for u in used)),
        "caveats": [c[:200] + ("…" if len(c) > 200 else "") for c in
                    dict.fromkeys(c for u in used for c in (idx.by_id[u].get("caveats") or []))][:4],
        "retrieved": hits, "elapsed_s": round(time.time() - t0, 2),
    }
    if chart_id:
        rec = idx.by_id[chart_id]
        df, how = load_chart_data(rec, srcs.get(chart_id))
        result["chart"] = {"view_id": chart_id, "spec": rec["chart"], "data_from": how,
                           "columns": list(df.columns), "rows": df.head(500).astype(object)
                           .where(df.head(500).notna(), None).values.tolist()}
    if save:
        save_result(result, idx)
    return result


def save_result(result, idx):
    d = DATA / "answers"
    d.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{result['variant']}"
    (d / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if result.get("chart_id"):
        try:
            from kosis_views import render
            render(idx.by_id[result["chart_id"]], VIEWS_DIR, d / f"{stem}.html")
            result["chart_html"] = str(d / f"{stem}.html")
        except Exception:  # noqa: BLE001  (plotly 미설치 등)
            pass
    result["saved"] = str(d / f"{stem}.json")


def print_result(r):
    print(f"\n질문: {r['question']}   [{r['variant']}]  ({r['elapsed_s']}s)")
    print(f"검색어: {r['rewritten']}" + (f"  | 하위 질문: {r['sub_questions']}" if r["sub_questions"] else ""))
    print("\n■ 답변\n" + r["answer"])
    if r["key_points"]:
        print("\n■ 핵심 수치\n" + "\n".join(f"- {p}" for p in r["key_points"]))
    for rid, c in (r.get("conditions") or {}).items():
        if c["applied"] or c["missing"]:
            print(f"  · 조건 {rid.split('::')[1]}: 적용 {c['applied']}" + (f" / 없음 {c['missing']}" if c["missing"] else ""))
    if r["insufficient"]:
        print("\n⚠ 질문 조건과 정확히 맞는 자료가 없어 가장 가까운 자료로 답했습니다.")
    if r["unverified_numbers"]:
        print(f"\n⚠ 자료에서 확인되지 않은 숫자(계산값일 수 있음): {r['unverified_numbers']}")
    if r["caveats"]:
        print("\n■ 주의\n" + "\n".join(f"- {c}" for c in r["caveats"]))
    print("\n■ 출처\n" + "\n".join(f"- {s}" for s in r["sources"]))
    if r.get("chart"):
        print(f"\n■ 그래프: {r['chart']['spec']['type']} ({len(r['chart']['rows'])}행, {r['chart']['data_from']})"
              + (f" → {r['chart_html']}" if r.get("chart_html") else ""))
    print("\n■ 검색 결과")
    for h in r["retrieved"]:
        print(f"  {h['fused']:.4f}  bm25#{h['bm25_rank']}  dense#{h['dense_rank']}  {h['title']}")
    if r.get("saved"):
        print(f"\n저장: {r['saved']}")

# test 단계
def stage_search(args):
    idx = Index(args.variant)
    for h in idx.search(args.query, k=args.k):
        print(f"{h['score']:.4f}  bm25#{h['bm25_rank']}  dense#{h['dense_rank']}({h['dense_sim']})  "
              f"[{h['doc_type']}] {h['title']}  {h['id']}")


def stage_ask(args):
    print_result(answer(args.query, args.variant, k=args.k, use_rewrite=not args.no_rewrite))


def stage_compare(args):
    """같은 질문을 base / enriched 인덱스로 각각 처리해 비교"""
    res = {}
    for v in ("base", "enriched"):
        if not (INDEX_DIR / v / "meta.json").exists():
            print(f"({v} 인덱스 없음 → 건너뜀)")
            continue
        res[v] = answer(args.query, v, k=args.k, use_rewrite=not args.no_rewrite)
        print_result(res[v])
        print("=" * 80)
    if len(res) == 2:
        a, b = ([h["id"] for h in res[v]["retrieved"]] for v in ("base", "enriched"))
        print(f"검색 결과 겹침: {len(set(a) & set(b))}/{len(a)}  |  "
              f"사용 자료 동일: {set(res['base']['used_ids']) == set(res['enriched']['used_ids'])}")


def stage_eval(args):
    """검색 성능 측정. --qa 파일(jsonl: {"question": ..., "gold": [view_id, ...]})이 없으면
    뷰의 템플릿 질문을 무작위로 뽑아 사용 (자체 질문이라 실제보다 높게 나옴 → 직접 만든 질문 추가 권장)"""
    idx = Index(args.variant)
    if args.qa:
        qa = [json.loads(l) for l in Path(args.qa).open(encoding="utf-8") if l.strip()]
    else:
        random.seed(0)
        views = [r for r in idx.by_id.values() if r.get("doc_type") == "view" and r.get("questions")]
        qa = [{"question": random.choice(r["questions"]), "gold": [r["id"], r.get("parent_id")]}
              for r in random.sample(views, min(args.n, len(views)))]
    ks = (1, 3, 5, 10)
    hit = {k: 0 for k in ks}
    mrr = 0.0
    for q in qa:
        ids = [h["id"] for h in idx.search(q["question"], k=max(ks))]
        rank = next((i for i, x in enumerate(ids) if x in set(q["gold"])), None)
        for k in ks:
            hit[k] += rank is not None and rank < k
        mrr += 1 / (rank + 1) if rank is not None else 0
    n = max(1, len(qa))
    print(f"[{args.variant}] 질문 {len(qa)}개  " + "  ".join(f"Recall@{k}={hit[k] / n:.3f}" for k in ks)
          + f"  MRR={mrr / n:.3f}")


def main():
    global VIEWS_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["index", "search", "ask", "compare", "eval"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--variant", default="base", help="base | enriched (임의 이름도 가능)")
    ap.add_argument("--records", default=None, help="index: 인덱싱할 records.jsonl (기본: variant 별 경로)")
    ap.add_argument("--views-dir", default=None, help="processed/ 가 있는 폴더 (기본 kosis_data/rag_views)")
    ap.add_argument("--dense-mode", choices=["single", "multi"], default="single",
                    help="multi: embed_text + 질문마다 벡터 (재현율↑, 임베딩 호출 수↑)")
    ap.add_argument("--doc-type", choices=["table", "view"], default=None, help="index: 특정 문서 종류만")
    ap.add_argument("--limit", type=int, default=None, help="index: 테스트용 레코드 수 제한")
    ap.add_argument("--workers", type=int, default=4, help="임베딩 동시 호출 수")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--no-rewrite", action="store_true", help="질의 재작성(HCX) 생략")
    ap.add_argument("--qa", default=None, help="eval: 평가 질문 jsonl")
    ap.add_argument("--n", type=int, default=200, help="eval: 자동 생성 질문 수")
    args = ap.parse_args()
    if args.views_dir:
        VIEWS_DIR = Path(args.views_dir)
    if args.stage == "index":
        args.records = Path(args.records or DEFAULT_RECORDS.get(args.variant, ""))
        if not args.records.exists():
            raise SystemExit(f"records 파일 없음: {args.records}  (--records 로 지정)")
        stage_index(args)
    elif args.stage == "search":
        stage_search(args)
    elif args.stage == "ask":
        stage_ask(args)
    elif args.stage == "compare":
        stage_compare(args)
    elif args.stage == "eval":
        stage_eval(args)


if __name__ == "__main__":
    main()
