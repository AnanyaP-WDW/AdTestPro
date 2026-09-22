"""PDF export: route, magic bytes, parity with the web report, safe failures."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import runs as runs_mod
from app.routers import pages as pages_mod
from tests.test_api import FORM, _files
from tests.test_pipeline import full_fake


def _run_and_get_id(c, monkeypatch, fake=None, qids="attention,clarity,relevance"):
    app.state.llm_client = fake or full_fake(question_ids=("attention", "clarity", "relevance"))
    try:
        r = c.post("/evaluate", data=dict(FORM, question_ids=qids), files=_files())
        assert r.status_code == 200
        return runs_mod.list_runs()[0]["evaluation_id"]
    finally:
        app.state.llm_client = None


def test_report_pdf_returns_valid_pdf(monkeypatch):
    pytest.importorskip("weasyprint")
    c = TestClient(app)
    eid = _run_and_get_id(c, monkeypatch)
    r = c.get(f"/runs/{eid}/report.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert len(r.content) > 5000  # a real document, not an error stub
    assert f'adtestpro-{eid}.pdf' in r.headers.get("content-disposition", "")


def test_report_pdf_unknown_id_is_404(monkeypatch):
    pytest.importorskip("weasyprint")
    c = TestClient(app)
    r = c.get("/runs/eval-doesnotexist/report.pdf")
    assert r.status_code == 404


def test_report_pdf_degrades_when_engine_missing(monkeypatch):
    monkeypatch.setattr(pages_mod, "engine_available", lambda: False)
    c = TestClient(app)
    r = c.get("/runs/whatever/report.pdf")
    assert r.status_code == 503
    assert "unavailable" in r.text.lower()


def test_web_and_pdf_render_the_same_sections(monkeypatch):
    """Both surfaces include the shared partial, so their content must match."""
    c = TestClient(app)
    eid = _run_and_get_id(c, monkeypatch)
    row = runs_mod.get_run(eid)
    from app.core.models import EvaluationResult
    result = EvaluationResult.model_validate(row["result"])
    ctx = pages_mod._results_ctx(result, row["question_ids"], row["thumb_uri"], pdf_available=True)
    env = app.state.templates.env

    web = env.get_template("_report_sections.html").render(**ctx, for_pdf=False)
    pdf = env.get_template("_report_sections.html").render(**ctx, for_pdf=True)

    for heading in ("Run context", "At a glance", "Visual summary", "Recommended next actions",
                    "Dimension scores", "Audience themes", "Structured extraction",
                    "Coverage panel"):
        assert heading in web, heading
        assert heading in pdf, heading
    # identical core numbers on both surfaces
    assert result.evaluation_id in web and result.evaluation_id in pdf
    if result.scores.overall_mean is not None:
        mean = f"{result.scores.overall_mean:.2f}"
        assert mean in web and mean in pdf
    # the download control is web-only
    assert "report.pdf" in web and "report.pdf" not in pdf
