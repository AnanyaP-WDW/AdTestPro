"""R1 UI exit criteria: save hooks, history list/detail, failure isolation."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import runs as runs_mod
from app.routers import pages as pages_mod
from tests.test_api import FORM, _files
from tests.test_pipeline import full_fake


def test_browser_run_is_saved_and_listed():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        assert r.status_code == 200
        rows = runs_mod.list_runs()
        assert len(rows) == 1
        assert rows[0]["panel_size"] == 12
        assert rows[0]["question_ids"] == ["clarity"]
        lr = c.get("/runs")
        assert lr.status_code == 200
        assert rows[0]["evaluation_id"] in lr.text
        assert "Coverage panel" not in lr.text  # list page, not the report
    finally:
        app.state.llm_client = None


def test_runs_list_shows_summary_column():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        lr = c.get("/runs")
        assert lr.status_code == 200
        assert "<th scope=\"col\">Summary</th>" in lr.text
        assert "themes" in lr.text  # stored summary text renders
    finally:
        app.state.llm_client = None


def test_run_detail_shows_per_persona_model(monkeypatch):
    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)  # isolate from ambient .env
    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)  # isolate from ambient .env
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        r = c.get(f"/runs/{eid}")
        assert r.status_code == 200
        assert "<th scope=\"col\">Model</th>" in r.text
        assert "injected-fake" in r.text  # fake pool label recorded per persona
    finally:
        app.state.llm_client = None


def test_run_detail_renders_scores_from_storage():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        r = c.get(f"/runs/{eid}")
        assert r.status_code == 200
        assert "Evaluation report" in r.text
        assert "At a glance" in r.text
    finally:
        app.state.llm_client = None


def test_run_detail_unknown_id_is_404():
    c = TestClient(app)
    r = c.get("/runs/eval-doesnotexist")
    assert r.status_code == 404
    assert "not found" in r.text.lower()


def test_api_run_saved_but_replay_is_not():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        form = dict(FORM, idempotency_key="hist1")
        r1 = c.post("/api/evaluations", data=form, files=_files())
        assert r1.status_code == 200
        r2 = c.post("/api/evaluations", data=form, files=_files())
        assert r2.headers.get("X-Idempotent-Replay") == "true"
        assert len(runs_mod.list_runs()) == 1
        # API runs have no thumbnail; detail still renders with the fallback
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        d = c.get(f"/runs/{eid}")
        assert d.status_code == 200 and "No image retained" in d.text
    finally:
        app.state.llm_client = None


def test_storage_failure_never_breaks_a_run(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(runs_mod, "save_run", _boom)
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        assert r.status_code == 200
        assert "Evaluation report" in r.text
        r2 = c.post("/api/evaluations", data=FORM, files=_files())
        assert r2.status_code == 200
    finally:
        app.state.llm_client = None


def test_report_renders_visual_summary_charts():
    qids = "attention,clarity,relevance"
    app.state.llm_client = full_fake(question_ids=("attention", "clarity", "relevance"))
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids=qids), files=_files())
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        html = c.get(f"/runs/{eid}").text
    finally:
        app.state.llm_client = None
    assert "Visual summary" in html
    for view in ("means", "distribution", "heatmap", "radar"):
        assert f'data-view="{view}"' in html
    assert 'class="cbar"' in html  # means / composition bars
    assert "stack__seg" in html  # distribution
    assert "heatcell" in html  # persona heatmap
    assert "data:image/svg+xml;base64," in html  # radar profile image
    assert "Dimension scores" in html and "Coverage panel" in html


def test_download_button_tracks_pdf_engine(monkeypatch):
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        eid = runs_mod.list_runs()[0]["evaluation_id"]

        monkeypatch.setattr(pages_mod, "engine_available", lambda: True)
        html = c.get(f"/runs/{eid}").text
        assert f'href="/runs/{eid}/report.pdf"' in html
        assert "Download PDF report" in html

        monkeypatch.setattr(pages_mod, "engine_available", lambda: False)
        assert "/report.pdf" not in c.get(f"/runs/{eid}").text
    finally:
        app.state.llm_client = None


def test_runs_list_links_pdf_when_engine_available(monkeypatch):
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        monkeypatch.setattr(pages_mod, "engine_available", lambda: True)
        assert f"/runs/{eid}/report.pdf" in c.get("/runs").text
    finally:
        app.state.llm_client = None
