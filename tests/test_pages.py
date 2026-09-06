"""A2 exit criteria: form wiring, validation parity, results states.

Task 8 (frontend revamp): tests assert behavior and semantics, not utility classes.
"""

import io
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import FORM, _files
from tests.test_pipeline import full_fake


def _css():
    c = TestClient(app)
    r = c.get("/static/app.css")
    assert r.status_code == 200
    return r.text


# ---------------- shell + assets ----------------

def test_static_assets_served_no_cdp_or_inline_handlers():
    c = TestClient(app)
    assert c.get("/static/app.css").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    home = c.get("/").text
    assert "cdn.tailwindcss.com" not in home
    assert "onclick=" not in home
    assert 'href="/static/app.css"' in home
    assert 'src="/static/app.js"' in home


def test_design_tokens_and_themes_in_css():
    css = _css()
    assert ":root" in css and "--canvas" in css and "--accent" in css
    assert "html.dark" in css and "prefers-reduced-motion" in css
    assert "https://" not in css  # no remote fonts or imports


def test_single_h1_and_skip_link_on_pages():
    c = TestClient(app)
    for path in ("/",):
        html = c.get(path).text
        assert len(re.findall(r"<h1[ >]", html)) == 1, path
        assert 'class="skip-link"' in html
        assert 'href="#main"' in html


def test_navigation_is_real_and_active_state_works():
    c = TestClient(app)
    home = c.get("/").text
    assert 'aria-label="Primary"' in home
    assert ">Evaluate</a>" in home and "/docs" in home
    assert 'aria-current="page"' in home
    # no invented product surfaces
    for absent in ("Dashboard", "Projects", "Billing", "Team"):
        assert f">{absent}</a>" not in home


def test_readiness_state_disables_submission(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(app)
    html = c.get("/").text
    assert "Provider not configured" in html
    assert "Not configured" in html
    assert 'id="submit-btn" class="btn btn--primary" disabled' in html
    assert "OPENAI_API_KEY" in html  # says what is missing


# ---------------- form ----------------

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
                 'value="action_intent"', 'name="persona_count"', "required"):
        assert attr in html, attr
    assert "fieldset" in html and "<legend" in html
    assert 'id="image-preview"' in html  # local preview target
    assert "image-preview-img" in html


def test_form_labels_match_controls():
    c = TestClient(app)
    html = c.get("/").text
    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', html))
    fors = set(re.findall(r'<label[^>]*for="([^"]+)"', html))
    assert ids and ids <= fors, ids - fors


def test_browser_evaluate_accepts_persona_count():
    fake = full_fake(n_personas=25)
    app.state.llm_client = fake
    c = TestClient(app)
    form = dict(FORM, question_ids="clarity", persona_count="25")
    r = c.post("/evaluate", data=form, files=_files())
    assert r.status_code == 200
    assert "Coverage panel" in r.text
    app.state.llm_client = None


def test_browser_persona_count_out_of_range_rejected():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity", persona_count="99"),
               files=_files())
    assert r.status_code == 422
    assert "Panel size must be between 1 and 25" in r.text
    app.state.llm_client = None


def test_field_errors_preserve_values_and_skip_llm():
    fake = full_fake()
    app.state.llm_client = fake
    c = TestClient(app)
    bad = dict(FORM, interests="", age_min="90", age_max="20")
    r = c.post("/evaluate", data=bad, files=_files())
    assert r.status_code == 422
    assert "Fix the highlighted fields" in r.text
    assert "This field is required." in r.text
    assert "Max age must be" in r.text
    # preserved values come back into the form
    assert f'value="{FORM["campaign_objective"]}"' in r.text
    assert FORM["product_description"] in r.text  # textarea content preserved
    assert 'aria-invalid="true"' in r.text
    assert fake.n_calls == 0
    app.state.llm_client = None


def test_no_questions_selected_is_rejected_with_guidance():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data={k: v for k, v in FORM.items() if k != "question_ids"},
               files=_files())
    assert r.status_code == 422
    assert "at least one question" in r.text.lower()
    app.state.llm_client = None


def test_bad_image_rejected_before_llm_with_recovery_copy():
    fake = full_fake()
    app.state.llm_client = fake
    c = TestClient(app)
    r = c.post("/evaluate", data=FORM, files=_files(png=b"junk-bytes", name="evil.png"))
    assert r.status_code == 422
    assert "image could not be used" in r.text.lower()
    assert fake.n_calls == 0
    app.state.llm_client = None


# ---------------- results ----------------

def test_browser_evaluate_renders_report_sections():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    form = dict(FORM)
    form["question_ids"] = "clarity"
    r = c.post("/evaluate", data=form, files=_files())
    assert r.status_code == 200
    html = r.text
    for needle in ("Evaluation report", "Run context", "At a glance",
                   "Recommended next actions", "Dimension scores", "Audience themes",
                   "Structured extraction", "Coverage panel", "Methodology",
                   "Experimental creative-screening", "not a replacement for human research",
                   'role="img"', "<table", "data:image/jpeg;base64"):
        assert needle in html, needle
    # order: recommendations before extraction/panel sections
    assert html.find("Recommended next actions") < html.find('id="evidence"')
    assert html.find("Recommended next actions") < html.find('id="panel"')
    app.state.llm_client = None


def test_sample_semantics_show_panel_and_per_dimension_n():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    html = r.text
    assert "<strong>12</strong> personas" in html  # panel, not rating cells
    assert "n=12 ratings" in html  # per-dimension n
    assert "Rating cells <strong>12</strong> valid" in html  # cells labeled as cells
    app.state.llm_client = None


def test_score_distribution_renders_and_sums_to_count():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    html = r.text
    assert 'class="dist"' in html
    ns = [int(x) for x in re.findall(r'class="dist__n tnum">(\d+)<', html)]
    assert len(ns) == 5 and sum(ns) == 12  # 1..5 cells summing to n
    app.state.llm_client = None


def test_question_and_status_labels_are_human_readable():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity,action_intent"), files=_files())
    html = r.text
    assert "Action intent" in html  # label, not raw id
    assert "data-status=" in html  # raw status kept for machine reads
    assert ">Complete</span>" in html
    app.state.llm_client = None


def test_theme_evidence_links_resolve_to_rendered_anchors():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    html = r.text
    anchors = set(re.findall(r'id="obs-([^"]+)"', html))
    assert anchors, "extraction anchors missing"
    hrefs = re.findall(r'class="ref" href="#obs-([^"]+)"', html)
    assert hrefs, "theme evidence refs missing"
    unresolved = set(re.findall(r'>([a-z0-9]+) unresolved<', html))
    assert set(hrefs) <= anchors
    assert not (unresolved & anchors)


def test_focus_visible_and_sticky_action_bar_in_css():
    css = _css()
    assert ":focus-visible" in css
    assert "position: sticky" in css
    c = TestClient(app)
    assert "action-bar" in c.get("/").text


def test_no_old_palette_and_dark_mode_tokens():
    c = TestClient(app)
    home = c.get("/").text
    assert "text-gray-" not in home and "bg-gray-800" not in home
    assert 'id="theme-toggle"' in home and "aria-pressed" in home
    assert "adtestpro-theme" in home  # persistence key


def test_u6_labels_rings_tables():
    c = TestClient(app)
    app.state.llm_client = full_fake()
    try:
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    finally:
        app.state.llm_client = None
    assert 'role="img" aria-label="Clarity mean' in r.text
    assert r.text.count('scope="col"') >= 9 and 'scope="row"' in r.text


def test_error_recovery_states_image_not_kept():
    from tests.fake_client import FakeClient

    # pipeline_error renders as a report with the raw status + no inline retry handlers
    app.state.llm_client = FakeClient(handler=lambda kw: RuntimeError("down"))
    c = TestClient(app)
    r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    assert r.status_code == 200
    assert 'data-status="pipeline_error"' in r.text
    assert 'onclick="history.back()"' not in r.text
    app.state.llm_client = None

    # a crashed pipeline renders the 502 recovery page; image is never preserved
    from app.routers import pages as pages_mod

    c2 = TestClient(app)
    orig = pages_mod.run_pipeline

    def boom(**kw):
        raise RuntimeError("crashed")

    pages_mod.run_pipeline = boom
    try:
        r2 = c2.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
    finally:
        pages_mod.run_pipeline = orig
    assert r2.status_code == 502
    assert "not kept between attempts" in r2.text
    assert "start a new run" in r2.text


def test_every_terminal_status_renders_safely():
    import asyncio
    import os

    from tests.fake_client import FakeClient
    from tests.test_pipeline import BRIEF, extraction_payload, full_fake, make_png, persona_payload

    c = TestClient(app)

    def post(client, **kw):
        app.state.llm_client = client
        try:
            return c.post("/evaluate", data=dict(FORM, question_ids="clarity"),
                          files=_files(**kw) if kw else _files())
        finally:
            app.state.llm_client = None

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
    ]
    for status, client, fkw in cases:
        r = post(client, **fkw)
        assert r.status_code == 200, status
        assert f'data-status="{status}"' in r.text, status
        assert "Traceback" not in r.text and "sk-" not in r.text

    # extraction_invalid never reaches the pipeline in the browser flow:
    # junk images are rejected at the boundary with a recovery page (see 422 test above).

    os.environ["ADTESTPRO_PIPELINE_TIMEOUT_S"] = "0.05"
    try:
        async def slow(kw):
            await asyncio.sleep(30)
            return {}
        r = post(FakeClient(handler=slow))
        assert 'data-status="budget_exhausted"' in r.text
    finally:
        del os.environ["ADTESTPRO_PIPELINE_TIMEOUT_S"]
