"""Static creative kinds (image / banner / design comp): boundary + dispatch."""

import asyncio
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import prefs as prefs_mod
from app.core import runs as runs_mod
from app.core.media import (
    ImageInvalid,
    banner_size_warning,
    normalize_kind,
    verify_creative,
)
from app.core.models import EvaluationResult, MediaInfo
from app.core.pipeline import run_pipeline
from app.main import app
from app.report.view import build_report_view
from tests.fake_client import FakeClient
from tests.test_api import FORM, _files
from tests.test_pipeline import BRIEF, full_fake, make_png


def test_verify_creative_stamps_media_facts():
    content = make_png(size=(300, 250))
    body, mime, checksum, media = verify_creative(content, "b.png", "image/png", "banner")
    assert body == content and mime == "image/png" and checksum.startswith("sha256:")
    assert media.kind == "banner"
    assert (media.width, media.height, media.bytes) == (300, 250, len(content))
    assert banner_size_warning(media) is None  # standard IAB size
    offsize = MediaInfo(kind="banner", width=640, height=100)
    assert "not a standard IAB size" in banner_size_warning(offsize)


def test_kind_is_whitelisted():
    assert normalize_kind("Design") == "design"
    assert normalize_kind(None) == "image"
    with pytest.raises(ImageInvalid):
        normalize_kind("video")
    with pytest.raises(ImageInvalid):
        verify_creative(make_png(), "a.png", "image/png", "poster")


def test_api_dispatches_banner_prompt_and_uncertainty():
    app.state.llm_client = full_fake()
    try:
        r = TestClient(app).post("/api/evaluations",
                                 data={**FORM, "creative_kind": "banner", "persona_count": "2"},
                                 files=_files())
    finally:
        app.state.llm_client = None
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media"]["kind"] == "banner" and body["media"]["width"] == 64
    assert "extract_banner" in body["trace"]["prompt_hashes"]
    assert "banner" in body["uncertainty"][0]


def test_api_dispatches_design_prompt():
    app.state.llm_client = full_fake()
    try:
        r = TestClient(app).post("/api/evaluations",
                                 data={**FORM, "creative_kind": "design", "persona_count": "2"},
                                 files=_files())
    finally:
        app.state.llm_client = None
    assert r.status_code == 200, r.text
    assert "extract_design" in r.json()["trace"]["prompt_hashes"]


def test_api_rejects_unknown_kind():
    r = TestClient(app).post("/api/evaluations",
                             data={**FORM, "creative_kind": "video"}, files=_files())
    assert r.status_code == 422 and "creative type" in r.json()["detail"]


def test_idempotency_separates_kinds():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        r1 = c.post("/api/evaluations", data={**FORM, "persona_count": "2",
                                              "idempotency_key": "kinds", "creative_kind": "image"},
                    files=_files())
        r2 = c.post("/api/evaluations", data={**FORM, "persona_count": "2",
                                              "idempotency_key": "kinds", "creative_kind": "banner"},
                    files=_files())
    finally:
        app.state.llm_client = None
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["evaluation_id"] != r2.json()["evaluation_id"]
    assert r2.headers.get("X-Idempotent-Replay") is None


def test_report_labels_kind_and_dimensions():
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        ok = c.post("/api/evaluations", data={**FORM, "creative_kind": "banner",
                                              "persona_count": "2"}, files=_files())
        eid = ok.json()["evaluation_id"]
        page = c.get(f"/runs/{eid}")
    finally:
        app.state.llm_client = None
    assert page.status_code == 200
    assert "Banner" in page.text and "64×64 px" in page.text
    assert "ctx-grid--wide" in page.text


def test_kind_casing_is_normalized_before_prompt_choice():
    app.state.llm_client = full_fake()
    try:
        r = TestClient(app).post("/api/evaluations",
                                 data={**FORM, "creative_kind": "Banner", "persona_count": "2"},
                                 files=_files())
    finally:
        app.state.llm_client = None
    assert r.status_code == 200, r.text
    assert r.json()["media"]["kind"] == "banner"
    assert "extract_banner" in r.json()["trace"]["prompt_hashes"]


def test_image_prompts_stay_on_v3_without_viewing_context():
    image_client = full_fake()
    app.state.llm_client = image_client
    try:
        r = TestClient(app).post("/api/evaluations",
                                 data={**FORM, "creative_kind": "image", "persona_count": "2"},
                                 files=_files())
    finally:
        app.state.llm_client = None
    assert r.status_code == 200
    assert r.json()["trace"]["prompt_versions"]["respond"] == "respond-v3"
    respond_user = next(c["messages"][1]["content"] for c in image_client.calls
                        if "AS the given persona" in c["messages"][0]["content"])
    assert "Viewing context" not in respond_user

    banner_client = full_fake()
    app.state.llm_client = banner_client
    try:
        TestClient(app).post("/api/evaluations",
                             data={**FORM, "creative_kind": "banner", "persona_count": "2"},
                             files=_files())
    finally:
        app.state.llm_client = None
    banner_user = next(c["messages"][1]["content"] for c in banner_client.calls
                       if "AS the given persona" in c["messages"][0]["content"])
    assert "Viewing context" in banner_user


def test_thumbnail_scales_by_kind():
    def stored_size(kind, size):
        thumb = runs_mod.get_run(runs_mod.list_runs()[0]["evaluation_id"])["thumb_uri"]
        raw = base64.b64decode(thumb.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as img:
            return kind, img.size

    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        for kind, size in (("banner", (728, 90)), ("design", (1440, 900)),
                           ("image", (1000, 1000))):
            r = c.post("/evaluate", data={**FORM, "creative_kind": kind, "persona_count": "2",
                                          "question_ids": "clarity"},
                       files=_files(make_png(size=size)))
            assert r.status_code == 200
            # Banners keep native width; design comps cap at 1000; images at 320.
            assert stored_size(kind, size)[1] == {
                "banner": (728, 90), "design": (1000, 625), "image": (320, 320)}[kind]
    finally:
        app.state.llm_client = None


def test_legacy_run_without_media_still_renders():
    legacy = EvaluationResult.model_validate({
        "evaluation_id": "eval-legacy", "status": "complete",
        "brief": None, "personas": None, "extraction": None, "responses": [],
        "scores": {"per_question": [], "valid_responses": 0, "missing_responses": 0},
        "themes": [], "recommendations": [], "uncertainty": [],
        "trace": {"evaluation_id": "eval-legacy", "model": "m"},
    })
    assert legacy.media is None
    assert build_report_view(legacy)["media_label"] == "Image ad"
    runs_mod.save_run(legacy)
    page = TestClient(app).get("/runs/eval-legacy")
    assert page.status_code == 200 and "Image ad" in page.text


def test_noncomplete_run_keeps_media_and_uncertainty():
    broken = FakeClient(handler=lambda kw: {"coverage_label": "coverage_panel", "personas": []})
    result = asyncio.run(run_pipeline(
        brief_data=BRIEF, image=make_png(), filename="b.png", content_type="image/png",
        question_ids=["clarity"], client=broken, kind="banner", persona_count=2,
    ))
    assert result.status == "pipeline_error"
    assert result.media is not None and result.media.kind == "banner"
    assert any("banner" in line for line in result.uncertainty)


def test_banner_pdf_renders():
    pytest.importorskip("weasyprint")
    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        r = c.post("/evaluate", data={**FORM, "creative_kind": "banner", "persona_count": "2",
                                      "question_ids": "clarity"},
                   files=_files(make_png(size=(728, 90))))
        eid = runs_mod.list_runs()[0]["evaluation_id"]
        pdf = c.get(f"/runs/{eid}/report.pdf")
    finally:
        app.state.llm_client = None
    assert r.status_code == 200
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_preferences_remember_kind_and_form_offers_it():
    data = prefs_mod.snapshot({"product_description": "x", "creative_kind": "design"},
                              8, ["clarity"])
    assert data["creative_kind"] == "design"
    assert prefs_mod.creative_kind(data) == "design"
    assert prefs_mod.creative_kind({"creative_kind": "bogus"}) == "image"
    html = TestClient(app).get("/").text
    assert 'name="creative_kind"' in html and "Design comp" in html
