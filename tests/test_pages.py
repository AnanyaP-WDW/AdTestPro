"""A2 exit criteria: form wiring, validation parity, results states."""

import io

from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import FORM, _files
from tests.test_pipeline import full_fake


def test_form_renders_with_wired_fields():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    html = r.text
    for attr in ('method="post"', 'action="/evaluate"', 'enctype="multipart/form-data"',
                 'name="product_description"', 'name="campaign_objective"',
                 'name="age_min"', 'name="age_max"', 'name="location"',
                 'name="interests"', 'name="pain_points"', 'name="category_familiarity"',
                 'name="image"', 'name="question_ids"', 'value="attention"',
                 'value="action_intent"', "required"):
        assert attr in html, attr


def test_browser_evaluate_renders_scores_and_disclaimer():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    form = dict(FORM)
    form["question_ids"] = "clarity"
    # pages router reads repeated question_ids fields; emulate with list
    r = c.post("/evaluate", data=form, files=_files())
    assert r.status_code == 200
    html = r.text
    for needle in ("Dimension scores", "Coverage personas", "Structured extraction",
                   "Evidence-linked recommendations", "Experimental creative-screening",
                   "Scale: <strong>1–5</strong>", "not a replacement for human research",
                   'role="img"', "<table", "Run provenance"):
        assert needle in html, needle
    app.state.llm_client = None


def test_browser_error_and_partial_states():
    from tests.fake_client import FakeClient

    app.state.llm_client = FakeClient(handler=lambda kw: RuntimeError("down"))
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    assert r.status_code == 200  # pipeline_error result renders with warning state
    assert "pipeline_error" in r.text or "Something went wrong" in r.text
    app.state.llm_client = None


def test_u6_labels_rings_tables_and_no_old_palette():
    import re

    from app.main import app as _app  # noqa: F401
    c = TestClient(app)
    html = c.get("/").text
    # every input/select/textarea has a matching label
    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', html))
    fors = set(re.findall(r'<label[^>]*for="([^"]+)"', html))
    assert ids and ids <= fors, ids - fors
    # focus ring + old dark palette gone
    assert ":focus-visible" in html
    assert "text-gray-" not in html and "bg-gray-800" not in html and "bg-gray-900" not in html
    # progressive disclosure + sticky action bar
    assert "<details" in html and "sticky bottom-0" in html
    # results: bars labelled, tables scoped
    app.state.llm_client = full_fake()
    try:
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    finally:
        app.state.llm_client = None
    assert 'role="img" aria-label="clarity mean' in r.text
    assert r.text.count('scope="col"') >= 9 and 'scope="row"' in r.text


def test_dark_mode_toggle_present_and_classes_wired():
    c = TestClient(app)
    html = c.get("/").text
    assert "darkMode" in html and 'id="theme-toggle"' in html
    assert "adtestpro-theme" in html and 'aria-pressed' in html
    for needle in ("dark:bg-slate-900", "dark:bg-slate-800", "dark:border-slate-700",
                   "dark:text-slate-300", "dark:text-slate-400"):
        assert needle in html, needle
    app.state.llm_client = full_fake()
    try:
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    finally:
        app.state.llm_client = None
    assert "dark:bg-slate-800" in r.text and "dark:bg-slate-700" in r.text


def test_every_terminal_status_renders_safely():
    import asyncio

    import pytest

    from tests.fake_client import FakeClient
    from tests.test_pipeline import BRIEF, full_fake, make_png, persona_payload, extraction_payload

    c = TestClient(app)

    def post(client, **kw):
        app.state.llm_client = client
        try:
            return c.post("/evaluate", data=dict(FORM, question_ids="clarity"),
                          files=_files(**kw) if kw else _files())
        finally:
            app.state.llm_client = None

    # insufficient_evidence: answers cite unknown evidence -> dropped
    def unknown_evidence(kw):
        s = kw["messages"][0]["content"]
        if "respondent profiles" in s:
            return {"coverage_label": "coverage_panel",
                    "personas": [persona_payload(i) for i in range(12)]}
        if "observable facts" in s:
            return extraction_payload()
        if "AS the given persona" in s:
            return {"answers": [{"question_id": "clarity", "rating": 5,
                                 "not_enough_information": False, "explanation": "x",
                                 "evidence_ids": ["o999"], "confidence": 50}]}
        if "contradictions" in s:
            return {"valid": True, "issues": []}
        raise AssertionError("unexpected " + s[:40])

    cases = [
        ("complete", full_fake(), {}),
        ("complete_high_disagreement", full_fake(split_panel=True), {}),
        ("insufficient_evidence", FakeClient(handler=unknown_evidence), {}),
        ("extraction_invalid", full_fake(), {"png": b"junk-bytes"}),
    ]
    for status, client, fkw in cases:
        r = post(client, **fkw)
        assert r.status_code == 200, status
        assert status in r.text, status
        assert "Traceback" not in r.text and "sk-" not in r.text

    # budget_exhausted via tiny wall-clock budget
    import os
    os.environ["ADTESTPRO_PIPELINE_TIMEOUT_S"] = "0.05"
    try:
        async def slow(kw):
            await asyncio.sleep(30)
            return {}
        r = post(FakeClient(handler=slow))
        assert "budget_exhausted" in r.text
    finally:
        del os.environ["ADTESTPRO_PIPELINE_TIMEOUT_S"]
