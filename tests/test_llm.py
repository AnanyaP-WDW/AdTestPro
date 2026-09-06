"""F3 exit criteria: typed failures, single repair, call recording, semaphore."""

import asyncio
import os

import pytest
from pydantic import BaseModel

from app.core import llm
from app.core.llm import LLMConfigError, LLMError, LLMOutputError, LLMTimeout, complete_structured, model_pool
from app.core.models import EvaluationTrace
from tests.fake_client import FakeClient


class _M(BaseModel):
    name: str


def _env(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODEL", "fake-model-1")
    monkeypatch.setenv("ADTESTPRO_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("ADTESTPRO_TIMEOUT_S", "5")


def test_model_pool_parses_multi_with_whitespace(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODEL", "primary")
    monkeypatch.setenv("ADTESTPRO_MODELS", " a , b ,c, ")
    assert model_pool() == ["a", "b", "c"]


def test_model_pool_falls_back_to_single_model(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODEL", "primary")
    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)
    assert model_pool() == ["primary"]


def test_model_pool_blank_pool_falls_back(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODEL", "primary")
    monkeypatch.setenv("ADTESTPRO_MODELS", "  ,, ")
    assert model_pool() == ["primary"]


def test_model_pool_unset_model_raises(monkeypatch):
    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)
    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)
    with pytest.raises(LLMConfigError):
        model_pool()


def test_success_records_call_metadata(monkeypatch):
    _env(monkeypatch)
    trace = EvaluationTrace(evaluation_id="e", model="fake-model-1")
    fake = FakeClient(handler=lambda kw: {"name": "ok"})
    out = asyncio.run(complete_structured(
        model_cls=_M, system="s", user="u", prompt_version="p-v1",
        stage="test", trace=trace, client=fake,
    ))
    assert out.name == "ok"
    assert len(trace.calls) == 1
    rec = trace.calls[0]
    assert (rec.model, rec.prompt_version, rec.retries) == ("fake-model-1", "p-v1", 0)
    assert rec.input_tokens == 10 and rec.output_tokens == 20
    assert rec.latency_ms >= 0


def test_malformed_output_one_repair_then_typed_failure(monkeypatch):
    _env(monkeypatch)
    trace = EvaluationTrace(evaluation_id="e", model="fake-model-1")
    fake = FakeClient(handler=lambda kw: "not-json{{{")
    with pytest.raises(LLMOutputError):
        asyncio.run(complete_structured(
            model_cls=_M, system="s", user="u", prompt_version="p-v1",
            stage="test", trace=trace, client=fake,
        ))
    assert fake.n_calls == 2  # initial + one repair, never more


def test_schema_error_repaired_once(monkeypatch):
    _env(monkeypatch)
    seen = {"n": 0}

    def handler(kw):
        seen["n"] += 1
        return {"wrong": "shape"} if seen["n"] == 1 else {"name": "fixed"}

    fake = FakeClient(handler=handler)
    out = asyncio.run(complete_structured(
        model_cls=_M, system="s", user="u", prompt_version="p-v1",
        stage="test", trace=None, client=fake,
    ))
    assert out.name == "fixed" and fake.n_calls == 2


def test_timeout_becomes_typed_failure(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("ADTESTPRO_TIMEOUT_S", "0.05") if False else None
    import asyncio as _a

    async def slow(kw):
        await _a.sleep(5)
        return {"name": "late"}

    monkeypatch.setenv("ADTESTPRO_TIMEOUT_S", "1")
    # force tiny timeout by monkeypatching _timeout_s via env is >=1; instead patch function
    monkeypatch.setattr(llm, "_timeout_s", lambda: 0.05)
    fake = FakeClient(handler=slow)
    with pytest.raises(LLMTimeout):
        asyncio.run(complete_structured(
            model_cls=_M, system="s", user="u", prompt_version="p-v1",
            stage="test", trace=None, client=fake,
        ))


def test_provider_error_typed_no_retry(monkeypatch):
    _env(monkeypatch)
    fake = FakeClient(handler=lambda kw: RuntimeError("boom"))
    with pytest.raises(LLMError):
        asyncio.run(complete_structured(
            model_cls=_M, system="s", user="u", prompt_version="p-v1",
            stage="test", trace=None, client=fake,
        ))
    assert fake.n_calls == 1


def test_concurrency_respects_semaphore(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("ADTESTPRO_MAX_CONCURRENCY", "2")
    llm._sem = None  # reset global semaphore for this test
    active = {"n": 0, "peak": 0}

    async def handler(kw):
        active["n"] += 1
        active["peak"] = max(active["peak"], active["n"])
        await asyncio.sleep(0.02)
        active["n"] -= 1
        return {"name": "ok"}

    fake = FakeClient(handler=handler)
    llm._sem = None

    async def main():
        await asyncio.gather(*[
            complete_structured(model_cls=_M, system="s", user="u", prompt_version="p",
                                stage="t", trace=None, client=fake)
            for _ in range(6)
        ])

    asyncio.run(main())
    assert active["peak"] <= 2, active
    llm._sem = None
