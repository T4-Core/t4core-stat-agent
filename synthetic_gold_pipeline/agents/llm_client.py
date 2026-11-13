"""독립 LLM Client 인터페이스.

  MockLLMClient     : API 키 없이 Demo Mode — 에이전트별 결정론적 응답 함수(responder)로 구조화 응답을 흉내낸다.
                      Mock 통과는 실제 LLM 생성 품질의 검증이 아니다.
  HCXClient         : CLOVA Studio v3 chat-completions (기존 backend/core/llm.py 와 같은 환경변수·요청 형식을
                      신규 Adapter 로 독립 구현 — 토큰 사용량 기록, 비동기, SystemExit 없는 오류 처리)
  RepoHCXClient     : 기존 backend.core.llm.chat 을 읽기 전용으로 import 해 호출 (호환성 확인 후. 토큰 사용량은 반환되지 않음)
  OpenAICompatClient: OpenAI 호환 /chat/completions (선택)

공통: Pydantic 검증 · JSON 파싱 · 제한된 구조화 재시도 · 일시 오류(429/5xx/네트워크) 지수 백오프 ·
     동시 실행 제한 · 호출 간 최소 간격 · 최대 API 호출 수 · 호출 수/지연/토큰 기록. API 키는 저장·로그하지 않는다.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


class LLMBudgetExceeded(Exception):
    pass


class LLMResponseError(Exception):
    pass


class LLMTransientError(Exception):
    """일시 오류. rate_limited=True 면 호출 한도 초과(429) — 기다리면 되므로 예산에서 빼고 따로 셈"""

    def __init__(self, msg="", rate_limited: bool = False, retry_after: float | None = None):
        super().__init__(msg)
        self.rate_limited, self.retry_after = rate_limited, retry_after


class LLMRateLimitExhausted(Exception):
    """호출 한도 초과(429)가 기다려도 계속됨 → 실행을 멈추고 --resume 으로 이어서"""


def parse_reset(v) -> float | None:
    """'23s' · '1m3s' · '850ms' · '12' → 초 (x-ratelimit-reset-*, Retry-After)"""
    if v is None:
        return None
    t = str(v).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return float(t)
    total, ok = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", t):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
        ok = True
    return total if ok else None


class RateLimiter:
    """분당 요청 수(QPM)·토큰 수(TPM) 슬라이딩 창. CLOVA Studio 는 TPM 에 '입력 토큰 + 최대 출력 토큰' 을 셈
    → 요청 전 추정 토큰으로 자리를 잡고, 응답의 실제 입력 토큰으로 글자/토큰 비율을 보정한다."""

    def __init__(self, rpm: float = 0, tpm: float = 0, safety: float = 0.85, chars_per_token: float = 2.0):
        self.rpm, self.tpm, self.safety = float(rpm or 0), float(tpm or 0), float(safety)
        self.cpt = float(chars_per_token)
        self.events: list[tuple[float, float]] = []      # (시각, 토큰)
        self.cooldown_until = 0.0
        self._lock = asyncio.Lock()
        self.waited_seconds = 0.0

    @property
    def enabled(self):
        return bool(self.rpm or self.tpm)

    def estimate(self, n_chars: int, max_tokens: int) -> float:
        return n_chars / max(self.cpt, 0.5) + max_tokens

    def calibrate(self, n_chars: int, prompt_tokens: int):
        if prompt_tokens > 0 and n_chars > 0:
            self.cpt = 0.7 * self.cpt + 0.3 * (n_chars / prompt_tokens)

    def cooldown(self, seconds: float):
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + seconds)

    async def acquire(self, tokens: float):
        while True:
            async with self._lock:
                now = time.monotonic()
                wait = self.cooldown_until - now
                if wait <= 0:
                    self.events = [(t, k) for t, k in self.events if now - t < 60]
                    n_ok = not self.rpm or len(self.events) < self.rpm * self.safety
                    cap = self.tpm * self.safety
                    used = sum(k for _, k in self.events)
                    t_ok = not self.tpm or used + tokens <= cap or not self.events   # 하나가 한도보다 커도 혼자는 보냄
                    if n_ok and t_ok:
                        self.events.append((now, tokens))
                        return
                    wait = max(0.05, 60 - (now - self.events[0][0])) if self.events else 1.0
            self.waited_seconds += wait
            await asyncio.sleep(min(wait, 30))


class LLMConfigError(Exception):
    pass


@dataclass
class LLMUsage:
    calls: int = 0
    failed_calls: int = 0
    transient_retries: int = 0
    structured_retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_reported: bool = False
    rate_limited: int = 0                 # 429 로 거절된 요청 (예산 calls 에 넣지 않음)
    rate_limit_wait_seconds: float = 0.0
    latency_ms_total: float = 0.0
    by_task: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: {"calls": 0, "latency_ms": 0.0,
                                                                                               "tokens": 0, "failures": 0}))

    def to_json(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "by_task"}
        d["by_task"] = {k: dict(v) for k, v in self.by_task.items()}
        d["avg_latency_ms"] = round(self.latency_ms_total / self.calls, 2) if self.calls else None
        return d

    def load(self, d: dict):
        for k, v in (d or {}).items():
            if k == "by_task":
                for t, x in v.items():
                    self.by_task[t].update(x)
            elif hasattr(self, k) and k != "avg_latency_ms":
                setattr(self, k, v)


def inline_refs(schema: dict) -> dict:
    """$defs/$ref 를 펼친 JSON Schema (일부 Structured Output API 가 $ref 를 지원하지 않음)."""
    defs = schema.get("$defs", {})

    def walk(x, depth=0):
        if depth > 30:
            return {}
        if isinstance(x, dict):
            if "$ref" in x:
                name = x["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs.get(name, {})), depth + 1)
            return {k: walk(v, depth + 1) for k, v in x.items() if k != "$defs"}
        if isinstance(x, list):
            return [walk(v, depth + 1) for v in x]
        return x
    return walk(schema)


def extract_json(text: str) -> Any:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    raise LLMResponseError(f"JSON 을 찾지 못함: {t[:200]}")


class BaseLLMClient:
    provider = "base"

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.model = cfg.get("model") or ""
        self.temperature = float(cfg.get("temperature", 0.2))
        self.max_tokens = int(cfg.get("max_tokens", 2500))
        self.max_api_calls = int(cfg.get("max_api_calls", 5000))
        self.transient_retries = int(cfg.get("transient_retries", 4))
        self.structured_retries = int(cfg.get("structured_retries", 2))
        self.timeout = float(cfg.get("timeout_seconds", 90))
        self.min_interval = float(cfg.get("min_interval_seconds", 0.0))
        self.max_tokens_by_task = {k: int(v) for k, v in (cfg.get("max_tokens_by_task") or {}).items()}
        rl = cfg.get("rate_limit") or {}
        self.limiter = RateLimiter(rl.get("requests_per_minute", 0), rl.get("tokens_per_minute", 0),
                                   rl.get("safety", 0.85), rl.get("chars_per_token", 2.0))
        self.rate_limit_retries = int(rl.get("max_retries", 8))
        self.rate_limit_backoff = float(rl.get("backoff_seconds", 15))
        self.rate_limit_max_backoff = float(rl.get("max_backoff_seconds", 120))
        self._sem = asyncio.Semaphore(int(cfg.get("max_concurrency", 4)))
        self._lock = asyncio.Lock()
        self._last = 0.0
        self.usage = LLMUsage()

    async def _throttle(self):
        async with self._lock:
            if self.usage.calls >= self.max_api_calls:
                raise LLMBudgetExceeded(f"최대 API 호출 수 {self.max_api_calls} 도달")
            self.usage.calls += 1
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def _raw(self, task: str, system: str, user: str, schema: dict | None, context: Any) -> tuple[str, dict]:
        raise NotImplementedError

    def tokens_for(self, task: str) -> int:
        return self.max_tokens_by_task.get(task, self.max_tokens)

    async def _call(self, task, system, user, schema, context) -> str:
        n_chars = len(system) + len(user) + (len(json.dumps(schema, ensure_ascii=False)) if schema else 0)
        est = self.limiter.estimate(n_chars, self.tokens_for(task))
        if self.limiter.tpm and est > self.limiter.tpm * 0.95:
            # 요청 하나가 분당 토큰 한도보다 큼 → 기다려도 영원히 429. 이 샘플만 실패시키고 실행은 계속
            raise LLMResponseError(f"{task}: 프롬프트가 너무 큼 (추정 {est:,.0f} 토큰 > 분당 한도 {self.limiter.tpm:,.0f})")
        n_transient = n_rate = 0
        while True:
            if self.limiter.enabled:
                await self.limiter.acquire(self.limiter.estimate(n_chars, self.tokens_for(task)))
            await self._throttle()
            t0 = time.perf_counter()
            try:
                async with self._sem:
                    text, usage = await self._raw(task, system, user, schema, context)
                dt = (time.perf_counter() - t0) * 1000
                self._account(task, dt, usage)
                if usage.get("prompt_tokens"):
                    self.limiter.calibrate(n_chars, int(usage["prompt_tokens"]))
                return text
            except LLMTransientError as e:
                dt = (time.perf_counter() - t0) * 1000
                if e.rate_limited:
                    async with self._lock:
                        self.usage.calls -= 1                     # 거절된 요청은 처리되지 않았으므로 예산에서 뺌
                    self.usage.rate_limited += 1
                    self.usage.by_task[task]["rate_limited"] = self.usage.by_task[task].get("rate_limited", 0) + 1
                    n_rate += 1
                    if n_rate > self.rate_limit_retries:
                        raise LLMRateLimitExhausted(f"{task}: 호출 한도 초과(429)가 {n_rate}번 연속 — 한도 설정 확인 후 --resume")
                    wait = e.retry_after if e.retry_after else min(self.rate_limit_max_backoff,
                                                                    self.rate_limit_backoff * 2 ** (n_rate - 1))
                    wait += random.random() * 2
                    self.limiter.cooldown(wait)                    # 모든 작업이 함께 쉼 (각자 재시도하면 계속 429)
                    self.usage.rate_limit_wait_seconds += wait
                    log.warning("HCX 호출 한도 초과(429) — %.0f초 쉼 (%s, %d번째)", wait, task, n_rate)
                    if not self.limiter.enabled:
                        await asyncio.sleep(wait)
                    continue
                self._account(task, dt, {}, failed=True)
                n_transient += 1
                if n_transient > self.transient_retries:
                    raise LLMResponseError(f"일시 오류 재시도 초과: {e}")
                self.usage.transient_retries += 1
                await asyncio.sleep(min(60.0, (2 ** n_transient) + random.random()))

    def _account(self, task, dt, usage, failed=False):
        u = self.usage
        u.latency_ms_total += dt
        bt = u.by_task[task]
        bt["calls"] += 1
        bt["latency_ms"] += dt
        if failed:
            u.failed_calls += 1
            bt["failures"] += 1
        if usage:
            u.tokens_reported = True
            u.prompt_tokens += int(usage.get("prompt_tokens", 0))
            u.completion_tokens += int(usage.get("completion_tokens", 0))
            u.total_tokens += int(usage.get("total_tokens", 0))
            bt["tokens"] += int(usage.get("total_tokens", 0))

    async def generate_structured(self, task: str, system: str, user: str, model_cls: type[BaseModel],
                                  context: Any = None, validator: Callable[[BaseModel], list[str]] | None = None
                                  ) -> tuple[BaseModel, dict]:
        """JSON 파싱 + Pydantic 검증 + (선택) 결정론적 검증. 실패하면 오류를 붙여 제한된 횟수만 다시 요청."""
        schema = inline_refs(model_cls.model_json_schema())
        feedback: list[str] = []
        attempts = []
        for attempt in range(self.structured_retries + 1):
            u = user if not feedback else (user + "\n\n<previous_output_errors>\n" + "\n".join(feedback[-5:]) +
                                           "\n</previous_output_errors>\n위 오류를 고쳐 스키마에 맞는 JSON 만 다시 출력하세요.")
            ctx = dict(context or {}, _attempt=attempt, _feedback=list(feedback)) if isinstance(context, dict) else context
            text = await self._call(task, system, u, schema, ctx)
            try:
                obj = model_cls.model_validate(extract_json(text))
                errs = validator(obj) if validator else []
                if errs:
                    raise LLMResponseError("; ".join(errs))
                return obj, {"attempts": attempt + 1, "errors": attempts}
            except (ValidationError, LLMResponseError) as e:
                msg = str(e)[:800]
                attempts.append(msg)
                feedback.append(msg)
                self.usage.structured_retries += 1
        err = LLMResponseError(f"{task}: 구조화 응답 {self.structured_retries + 1}회 실패: {attempts[-1][:300]}")
        err.last_text = (text or "")[:3000]                     # 진단용: 마지막 LLM 응답 원문
        raise err


# ── Mock ────────────────────────────────────────────────────────────
class MockLLMClient(BaseLLMClient):
    provider = "mock"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.model = self.model or "mock-deterministic"
        self.min_interval = 0.0
        self.limiter = RateLimiter()                     # Mock 은 호출 한도 없음 (데모가 느려지지 않게)
        self.responders: dict[str, Callable[[Any], dict]] = {}

    def register(self, task: str, fn: Callable[[Any], dict]):
        self.responders[task] = fn

    async def _raw(self, task, system, user, schema, context):
        if task not in self.responders:
            raise LLMResponseError(f"Mock 응답 함수 없음: {task}")
        await asyncio.sleep(0)
        out = self.responders[task](context)
        return json.dumps(out, ensure_ascii=False), {}


# ── HCX (신규 Adapter) ─────────────────────────────────────────────
def _host(url: str | None) -> str:
    m = re.match(r"(https?://[^/\s]+)", (url or "").strip())
    return m.group(1) if m else "https://clovastudio.stream.ntruss.com"


class HCXClient(BaseLLMClient):
    provider = "hcx"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        cfg = cfg or {}
        self.api_key = os.getenv(cfg.get("api_key_env", "HCX_API_KEY"), "").strip()
        if not self.api_key:
            raise LLMConfigError("HCX_API_KEY 환경변수(.env)가 없습니다. Demo Mode 를 쓰거나 키를 설정하세요.")
        self.host = _host(os.getenv("HCX_BASE_URL"))
        self.model = self.model or os.getenv("HCX_MODEL", "HCX-007")
        self.app_type = os.getenv("HCX_APP_TYPE", "testapp").strip()
        self.path_template = cfg.get("path_template", "/{app_type}/v3/chat-completions/{model}")
        self.use_schema = bool(cfg.get("native_structured_output", True))

    def _post(self, body: dict) -> dict:
        import requests
        path = self.path_template.format(app_type=self.app_type, model=self.model)
        try:
            r = requests.post(self.host + path, json=body, timeout=self.timeout, headers={
                "Authorization": f"Bearer {self.api_key}", "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
                "Content-Type": "application/json; charset=utf-8"})
        except (requests.ConnectionError, requests.Timeout) as e:
            raise LLMTransientError(f"network: {type(e).__name__}")
        if r.status_code == 429:
            h = r.headers
            reset = max([x for x in (parse_reset(h.get("x-ratelimit-reset-requests")), parse_reset(h.get("x-ratelimit-reset-tokens")),
                                     parse_reset(h.get("Retry-After"))) if x is not None], default=None)
            raise LLMTransientError("HTTP 429", rate_limited=True, retry_after=reset)
        if r.status_code in (500, 502, 503, 504):
            raise LLMTransientError(f"HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise LLMResponseError(f"HTTP {r.status_code}: JSON 아님")
        st = data.get("status") or {}
        if str(st.get("code", "")).startswith("429"):
            raise LLMTransientError(f"status {st.get('code')}", rate_limited=True)
        if r.status_code != 200 or str(st.get("code", "20000")) != "20000":
            raise LLMResponseError(f"HTTP {r.status_code} / {st.get('code')}: {st.get('message')}"[:300])
        return data.get("result") or {}

    async def _raw(self, task, system, user, schema, context):
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": self.temperature, "topP": 0.8, "maxCompletionTokens": self.tokens_for(task),
                "repetitionPenalty": 1.1}
        if self.model.upper().startswith("HCX-007"):
            body["thinking"] = {"effort": "none"}       # 구조화 출력은 추론 모드와 함께 쓸 수 없음 (기존 llm.py 와 같은 처리)
        if schema and self.use_schema:
            body["responseFormat"] = {"type": "json", "schema": schema}
        try:
            res = await asyncio.to_thread(self._post, body)
        except LLMResponseError as e:
            if "responseFormat" in body and "HTTP 400" in str(e):
                body.pop("responseFormat")              # 구조화 출력 미지원 → 일반 응답 + JSON 파싱
                res = await asyncio.to_thread(self._post, body)
            else:
                raise
        u = res.get("usage") or {}
        usage = {"prompt_tokens": u.get("promptTokens", 0), "completion_tokens": u.get("completionTokens", 0),
                 "total_tokens": u.get("totalTokens", 0)} if u else {}
        return ((res.get("message") or {}).get("content") or ""), usage


class RepoHCXClient(BaseLLMClient):
    """기존 backend.core.llm.chat 을 수정 없이 호출. 시그니처가 맞지 않으면 사용하지 않는다."""
    provider = "hcx_repo"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        import inspect
        if not os.getenv("HCX_API_KEY", "").strip():
            raise LLMConfigError("HCX_API_KEY 환경변수(.env)가 없습니다.")
        try:
            from backend.core import llm as repo_llm      # 읽기·호출 목적의 재사용
        except Exception as e:  # noqa: BLE001
            raise LLMConfigError(f"backend.core.llm import 실패: {e}")
        params = inspect.signature(repo_llm.chat).parameters
        if not {"messages", "schema"} <= set(params):
            raise LLMConfigError("backend.core.llm.chat 시그니처가 예상과 다름 (messages, schema)")
        self._chat = repo_llm.chat
        self.model = self.model or getattr(repo_llm, "CHAT_MODEL", "")

    async def _raw(self, task, system, user, schema, context):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            out = await asyncio.to_thread(self._chat, msgs, schema, self.temperature, self.tokens_for(task))
        except SystemExit as e:                          # 기존 코드가 키 없음 시 SystemExit
            raise LLMResponseError(str(e))
        except Exception as e:  # noqa: BLE001
            raise LLMTransientError(f"{type(e).__name__}: {str(e)[:120]}", rate_limited="429" in str(e))
        return (json.dumps(out, ensure_ascii=False) if isinstance(out, dict) and "_raw" not in out
                else (out.get("_raw", "") if isinstance(out, dict) else str(out))), {}


class OpenAICompatClient(BaseLLMClient):
    provider = "openai_compat"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        cfg = cfg or {}
        self.api_key = os.getenv(cfg.get("api_key_env", "OPENAI_API_KEY"), "").strip()
        if not self.api_key:
            raise LLMConfigError("OPENAI_API_KEY 환경변수가 없습니다.")
        self.base_url = (os.getenv("OPENAI_BASE_URL") or cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = self.model or os.getenv("OPENAI_MODEL", "")

    def _post(self, body):
        import requests
        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                              headers={"Authorization": f"Bearer {self.api_key}"})
        except (requests.ConnectionError, requests.Timeout) as e:
            raise LLMTransientError(type(e).__name__)
        if r.status_code == 429:
            raise LLMTransientError("HTTP 429", rate_limited=True, retry_after=parse_reset(r.headers.get("Retry-After")))
        if r.status_code in (500, 502, 503, 504):
            raise LLMTransientError(f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise LLMResponseError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def _raw(self, task, system, user, schema, context):
        body = {"model": self.model, "temperature": self.temperature, "max_tokens": self.tokens_for(task),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": task, "schema": schema, "strict": False}}
        data = await asyncio.to_thread(self._post, body)
        u = data.get("usage") or {}
        return data["choices"][0]["message"]["content"], {"prompt_tokens": u.get("prompt_tokens", 0),
                                                          "completion_tokens": u.get("completion_tokens", 0),
                                                          "total_tokens": u.get("total_tokens", 0)}


def make_llm_client(mode: str, cfg: dict) -> BaseLLMClient:
    lcfg = dict(cfg.get("llm", {}))
    provider = lcfg.get("provider_demo", "mock") if mode == "demo" else lcfg.get("provider", "hcx")
    if provider == "mock":
        return MockLLMClient(lcfg)
    if provider == "hcx":
        return HCXClient(lcfg)
    if provider == "hcx_repo":
        return RepoHCXClient(lcfg)
    if provider == "openai_compat":
        return OpenAICompatClient(lcfg)
    raise LLMConfigError(f"알 수 없는 LLM provider: {provider}")
