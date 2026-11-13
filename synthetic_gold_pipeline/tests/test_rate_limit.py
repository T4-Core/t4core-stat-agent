"""HCX 호출 한도(429): 함께 쉬기 · 예산에서 빼기 · 한도 창 · 계속되면 탈락이 아니라 실행 중단"""
from __future__ import annotations

import asyncio

import pytest

from synthetic_gold_pipeline.agents import llm_client as L
from synthetic_gold_pipeline.agents.llm_client import (BaseLLMClient, LLMRateLimitExhausted, LLMTransientError,
                                                       RateLimiter, parse_reset)


@pytest.fixture
def fast(monkeypatch):
    """asyncio.sleep 을 가짜 시계로 (실제로 기다리지 않음)"""
    clock = {"t": 1000.0, "slept": 0.0}
    monkeypatch.setattr(L.time, "monotonic", lambda: clock["t"])

    async def fake_sleep(s):
        clock["t"] += s
        clock["slept"] += s
    monkeypatch.setattr(L.asyncio, "sleep", fake_sleep)
    return clock


def test_parse_reset():
    assert parse_reset("23s") == 23 and parse_reset("1m3s") == 63 and parse_reset("850ms") == pytest.approx(0.85)
    assert parse_reset("12") == 12 and parse_reset(None) is None and parse_reset("soon") is None


def test_limiter_waits_for_token_window(fast):
    lim = RateLimiter(rpm=100, tpm=1000, safety=1.0)

    async def go():
        await lim.acquire(600)
        await lim.acquire(600)                   # 1200 > 1000 → 첫 요청이 창(60초)에서 빠질 때까지 대기
    asyncio.run(go())
    assert fast["slept"] >= 59.9


def test_429_is_waited_out_and_not_charged(fast):
    class C(BaseLLMClient):
        n = 0

        async def _raw(self, task, system, user, schema, context):
            C.n += 1
            if C.n <= 2:
                raise LLMTransientError("HTTP 429", rate_limited=True, retry_after=20 if C.n == 1 else None)
            return '{"ok": 1}', {"prompt_tokens": 50}

    c = C({"max_api_calls": 2, "rate_limit": {"requests_per_minute": 60, "tokens_per_minute": 60000,
                                              "backoff_seconds": 15}})
    out = asyncio.run(c._call("planner", "s", "u" * 100, None, None))
    assert out == '{"ok": 1}'
    assert c.usage.calls == 1 and c.usage.rate_limited == 2           # 거절 2번은 예산에서 빠짐 (예산 2로도 성공)
    assert fast["slept"] >= 20 + 30 - 0.1 - 2                          # 헤더 20초 + 두 번째 15·2^1=30초


def test_429_forever_raises_exhausted(fast):
    class C(BaseLLMClient):
        async def _raw(self, task, system, user, schema, context):
            raise LLMTransientError("HTTP 429", rate_limited=True)

    c = C({"rate_limit": {"requests_per_minute": 60, "max_retries": 3}})
    with pytest.raises(LLMRateLimitExhausted):
        asyncio.run(c._call("planner", "s", "u", None, None))
    assert c.usage.calls == 0 and c.usage.rate_limited == 4


def test_pipeline_stops_on_rate_limit_without_rejecting(tmp_path, monkeypatch):
    from synthetic_gold_pipeline.tests.test_pipeline import run_pipeline
    import synthetic_gold_pipeline.agents.planner_agent as P

    async def boom(self, cluster, errors=None, attempt=0):
        raise LLMRateLimitExhausted("planner: 429")
    monkeypatch.setattr(P.PlannerAgent, "plan", boom)
    pipe, rep = run_pipeline(tmp_path / "o", 4)
    assert rep["final_dataset_count"] == 0 and rep["processed_samples"] == 0
    assert any("429" in s for s in rep["shortfall_reasons"])
    assert not any(k.startswith("llm:") for k in rep["failure_reasons"])
