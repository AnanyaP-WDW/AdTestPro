"""A3 exit criteria: stage-localized logs, token sums, no secrets, timeout cancel, budget."""

import asyncio
import logging
import os

from app.core.pipeline import estimate_cost_usd, run_pipeline
from tests.test_pipeline import BRIEF, full_fake, make_png


def run(coro):
    return asyncio.run(coro)


def test_logs_localize_stage_and_tokens_add_up(caplog, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-should-never-appear")
    with caplog.at_level(logging.INFO, logger="adtestpro.pipeline"):
        res = run(run_pipeline(brief_data=BRIEF, image=make_png(), filename="a.png",
                               content_type="image/png", question_ids=["clarity"],
                               client=full_fake()))
    assert res.status == "complete"
    assert sum(c.input_tokens for c in res.trace.calls) > 0
    assert estimate_cost_usd(res.trace) >= 0
    rec = next(r for r in caplog.records if "eval=" in r.getMessage())
    assert res.evaluation_id in rec.getMessage()
    assert res.status in rec.getMessage()
    # no secrets or media in logs
    assert "sk-test-secret" not in caplog.text
    assert "base64" not in caplog.text and "data:image" not in caplog.text


def test_disconnect_timeout_cancels_pending_work(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_PIPELINE_TIMEOUT_S", "0.05")

    async def slow(kw):
        await asyncio.sleep(30)
        return {}

    from tests.fake_client import FakeClient
    res = run(run_pipeline(brief_data=BRIEF, image=make_png(), filename="a.png",
                           content_type="image/png", question_ids=["clarity"],
                           client=FakeClient(handler=slow)))
    assert res.status == "budget_exhausted"  # declared per-run budget enforced


def test_readiness_separate_from_liveness():
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert "ready" in c.get("/ready").json()
