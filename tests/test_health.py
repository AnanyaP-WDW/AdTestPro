"""Offline smoke test: import + /health (F1 exit criteria, no network, no key)."""

from fastapi.testclient import TestClient


def test_import_and_health():
    from app.main import app

    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_ready_reports_missing_config_without_secrets():
    import os

    os.environ.pop("OPENAI_API_KEY", None)
    from app.main import app

    c = TestClient(app)
    r = c.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "OPENAI_API_KEY" in body["missing"]
    # names only, never values
    assert "sk-" not in r.text
