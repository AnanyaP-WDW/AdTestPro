"""Offline smoke test: import + /health (F1 exit criteria, no network, no key)."""

from fastapi.testclient import TestClient

from app.core.settings import ApiKey, ProviderSettings


def test_import_and_health():
    from app.main import app

    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_ready_reports_missing_config_without_secrets(monkeypatch):
    from app.main import app

    monkeypatch.setattr(app.state, "provider_settings", ProviderSettings(), raising=False)
    c = TestClient(app)
    r = c.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "api_key" in body["missing"]
    # names only, never values
    assert "sk-" not in r.text


def test_ready_true_with_stored_key(monkeypatch):
    from app.main import app

    monkeypatch.setattr(app.state, "provider_settings", ProviderSettings(
        keys=[ApiKey(id="k1", label="A", key="sk-or-v1-stored123456")],
        active_key_id="k1"), raising=False)
    c = TestClient(app)
    body = c.get("/ready").json()
    assert body["ready"] is True
    assert "sk-" not in c.get("/ready").text
