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
                   "Scale:</strong> 1–5", "not a replacement for human research"):
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
