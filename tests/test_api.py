"""A1 exit criteria: full fake-client pipeline via HTTP, safe errors, idempotency."""

import io

from fastapi.testclient import TestClient

from app.main import app
from tests.test_pipeline import BRIEF, full_fake, make_png

FORM = {
    "product_description": BRIEF["product_description"],
    "campaign_objective": BRIEF["campaign_objective"],
    "age_min": str(BRIEF["age_min"]),
    "age_max": str(BRIEF["age_max"]),
    "location": BRIEF["location"],
    "interests": "running, coffee",
    "pain_points": "lack of time, plastic waste",
    "category_familiarity": "casual",
    "price_sensitivity": "medium",
    "question_ids": "clarity,relevance",
}


def _files(png: bytes = None, name="ad.png", ctype="image/png"):
    return {"image": (name, io.BytesIO(png or make_png()), ctype)}


def test_end_to_end_fake_pipeline():
    app.state.llm_client = full_fake()
    c = TestClient(app)
    r = c.post("/api/evaluations", data=FORM, files=_files())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete"
    assert body["scores"]["valid_responses"] > 0
    assert "evaluation_id" in body and "trace" in body
    app.state.llm_client = None


def test_invalid_input_causes_no_llm_calls():
    fake = full_fake()
    app.state.llm_client = fake
    c = TestClient(app)
    bad = dict(FORM, age_min="90", age_max="20")
    r = c.post("/api/evaluations", data=bad, files=_files())
    assert r.status_code == 422
    assert fake.n_calls == 0
    r2 = c.post("/api/evaluations", data=FORM,
                files=_files(png=b"junk-bytes", name="evil.png"))
    assert r2.status_code == 200  # reaches pipeline -> typed extraction_invalid
    assert r2.json()["status"] == "extraction_invalid"
    app.state.llm_client = None


def test_provider_errors_are_safe_and_idempotent():
    from tests.fake_client import FakeClient

    app.state.llm_client = FakeClient(handler=lambda kw: RuntimeError("secret-key sk-xyz boom"))
    c = TestClient(app)
    r = c.post("/api/evaluations", data=FORM, files=_files())
    assert r.status_code in (200, 502)
    assert "sk-xyz" not in r.text and "traceback" not in r.text.lower()
    app.state.llm_client = full_fake()

    r1 = c.post("/api/evaluations", data={**FORM, "idempotency_key": "k123"}, files=_files())
    n_after_first = app.state.llm_client.n_calls
    r2 = c.post("/api/evaluations", data={**FORM, "idempotency_key": "k123"}, files=_files())
    assert r1.status_code == r2.status_code == 200
    assert r2.headers.get("X-Idempotent-Replay") == "true"
    assert app.state.llm_client.n_calls == n_after_first  # no duplicate run
    assert r1.json()["evaluation_id"] == r2.json()["evaluation_id"]
    app.state.llm_client = None


def test_openapi_exposes_contracts():
    c = TestClient(app)
    spec = c.get("/openapi.json").json()
    assert "/api/evaluations" in spec["paths"]
    assert "EvaluationResult" in str(spec)
