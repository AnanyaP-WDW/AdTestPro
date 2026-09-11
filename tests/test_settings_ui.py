"""S1 UI exit criteria: key add/activate/delete/reveal, model pool save/validate, test."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import pages as pages_mod
from app.core.settings import ApiKey, ProviderSettings


def _mk(label="Work", key="sk-or-v1-testkey123456", base="https://openrouter.ai/api/v1",
        kid="k1"):
    return ApiKey(id=kid, label=label, key=key, base_url=base)


@pytest.fixture(autouse=True)
def _isolate_provider_settings(monkeypatch):
    monkeypatch.setattr(app.state, "provider_settings", ProviderSettings(), raising=False)
    for var in ("ADTESTPRO_MODEL", "ADTESTPRO_MODELS", "OPENAI_API_KEY", "ADTESTPRO_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    yield
    app.state.provider_settings = ProviderSettings()


def _saved(monkeypatch):
    captured: dict = {}

    def _fake_save(settings):
        captured["settings"] = settings

    monkeypatch.setattr(pages_mod, "save_settings", _fake_save)
    return captured


# ---------------- provider key store ----------------

def test_settings_page_renders_masked_key_and_add_form():
    app.state.provider_settings = ProviderSettings(
        keys=[_mk(key="sk-or-v1-SECRETKEY123456789")], active_key_id="k1", model="m1")
    c = TestClient(app)
    r = c.get("/settings")
    assert r.status_code == 200
    assert 'type="password"' in r.text and 'name="key_value"' in r.text
    assert 'aria-current="page">Settings' in r.text
    assert 'value="m1"' in r.text  # non-secret values are echoed back
    assert "Work" in r.text and "active" in r.text
    assert "sk-or-v1-SECRETKEY123456789" not in r.text  # full key never renders
    assert "sk-or-v1-…789" in r.text  # masked indicator does


def test_add_key_activates_first_and_masks(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={"action": "add_key", "key_label": "Work",
                                  "key_value": "sk-or-v1-testkey123456",
                                  "key_base_url": "https://openrouter.ai/api/v1"})
    assert r.status_code == 200
    assert "Settings saved and applied" in r.text
    saved = captured["settings"]
    assert len(saved.keys) == 1
    assert saved.active_key_id == saved.keys[0].id
    assert saved.keys[0].key == "sk-or-v1-testkey123456"
    assert saved.keys[0].base_url == "https://openrouter.ai/api/v1"
    assert app.state.provider_settings.is_configured
    assert os.getenv("OPENAI_API_KEY") == "sk-or-v1-testkey123456"
    assert "sk-or-v1-testkey123456" not in r.text  # masked only
    assert "sk-or-v1-…456" in r.text


def test_add_key_requires_label_and_value(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={"action": "add_key", "key_label": "", "key_value": ""})
    assert r.status_code == 422
    assert "Label is required." in r.text and "API key is required." in r.text
    assert captured == {}


def test_add_key_rejects_duplicate_label(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk(label="Work")], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "add_key", "key_label": "Work",
                                  "key_value": "another-key", "key_base_url": ""})
    assert r.status_code == 422
    assert "already used" in r.text
    assert captured == {}


def test_activate_and_delete_key(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk("A", "key-a", "", "k1"), _mk("B", "key-b", "", "k2")], active_key_id="k1")
    c = TestClient(app)

    r = c.post("/settings", data={"action": "activate_key", "key_id": "k2"})
    assert r.status_code == 200
    assert captured["settings"].active_key_id == "k2"
    assert app.state.provider_settings.active_key_id == "k2"
    assert os.getenv("OPENAI_API_KEY") == "key-b"

    r = c.post("/settings", data={"action": "delete_key", "key_id": "k2"})
    assert r.status_code == 200
    assert [k.id for k in captured["settings"].keys] == ["k1"]
    assert captured["settings"].active_key_id == "k1"  # promoted after active delete
    assert os.getenv("OPENAI_API_KEY") == "key-a"


def test_delete_last_key_becomes_unconfigured(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk()], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "delete_key", "key_id": "k1"})
    assert r.status_code == 200
    assert captured["settings"].keys == [] and captured["settings"].active_key_id == ""
    assert not app.state.provider_settings.is_configured
    assert "Provider not configured" in c.get("/").text


def test_reveal_key_shows_full_key_without_persisting(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk(key="sk-or-v1-REVEALME999")], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "reveal_key", "key_id": "k1"})
    assert r.status_code == 200
    assert "sk-or-v1-REVEALME999" in r.text  # explicit reveal only
    assert captured == {}


def test_unknown_key_action_is_safe(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={"action": "delete_key", "key_id": "nope"})
    assert r.status_code == 422
    assert "no longer exists" in r.text
    assert captured == {}


def test_edit_key_renders_inline_form_without_persisting(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk()], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "edit_key", "key_id": "k1"})
    assert r.status_code == 200
    assert 'name="edit_label"' in r.text
    assert 'name="edit_value"' in r.text and 'name="edit_base_url"' in r.text
    assert captured == {}


def test_update_key_changes_label_and_base_keeps_secret(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk(key="sk-or-v1-original999", base="https://old")], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "update_key", "key_id": "k1",
                                  "edit_label": "Renamed", "edit_value": "",
                                  "edit_base_url": "https://new"})
    assert r.status_code == 200
    saved = captured["settings"]
    assert saved.keys[0].label == "Renamed"
    assert saved.keys[0].key == "sk-or-v1-original999"  # blank keeps the secret
    assert saved.keys[0].base_url == "https://new"
    assert saved.active_key_id == "k1"  # activation untouched


def test_update_key_replaces_secret_when_provided(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk(key="old-secret")], active_key_id="k1")
    c = TestClient(app)
    c.post("/settings", data={"action": "update_key", "key_id": "k1",
                              "edit_label": "Work", "edit_value": "new-secret",
                              "edit_base_url": ""})
    assert captured["settings"].keys[0].key == "new-secret"


def test_update_key_rejects_duplicate_label(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk("A", "ka", "", "k1"), _mk("B", "kb", "", "k2")], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "update_key", "key_id": "k2",
                                  "edit_label": "A", "edit_value": "", "edit_base_url": ""})
    assert r.status_code == 422
    assert "already used" in r.text
    assert captured == {}


def test_update_key_requires_label(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk()], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "update_key", "key_id": "k1",
                                  "edit_label": "", "edit_value": "", "edit_base_url": ""})
    assert r.status_code == 422
    assert "Label is required." in r.text
    assert captured == {}


def test_set_storage_toggles_keyring(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk()], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "set_storage", "keyring_enabled": "on"})
    assert r.status_code == 200
    assert captured["settings"].keyring_enabled is True
    c.post("/settings", data={"action": "set_storage"})
    assert captured["settings"].keyring_enabled is False


# ---------------- test connection ----------------

def test_settings_test_connection_uses_active_key(monkeypatch):
    _saved(monkeypatch)
    seen: dict = {}

    def _probe(key, base_url, timeout_s=10.0):
        seen.update(key=key, base_url=base_url)
        return True, "connected"

    monkeypatch.setattr(pages_mod, "probe_connection", _probe)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk(key="active-key", base="https://openrouter.ai/api/v1")], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "test", "model": "", "image_model": "", "timeout_s": ""})
    assert r.status_code == 200
    assert "Connection OK" in r.text
    assert seen == {"key": "active-key", "base_url": "https://openrouter.ai/api/v1"}


def test_settings_test_connection_without_key(monkeypatch):
    _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={"action": "test", "model": "", "image_model": "", "timeout_s": ""})
    assert r.status_code == 422
    assert "No key to test." in r.text


# ---------------- model pool / save ----------------

def test_settings_save_applies_model_pool_and_masks(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(keys=[_mk()], active_key_id="k1")
    c = TestClient(app)
    r = c.post("/settings", data={
        "action": "save", "model": "ui-model",
        "pool_models": ["openai/gpt-4o-mini", "deepseek/deepseek-v4-flash"],
        "image_model": "", "timeout_s": "45",
    })
    assert r.status_code == 200
    assert "Settings saved and applied" in r.text
    saved = captured["settings"]
    assert saved.model == "ui-model"
    assert saved.models == "openai/gpt-4o-mini, deepseek/deepseek-v4-flash"
    assert saved.keys and saved.active_key_id == "k1"  # key store preserved
    assert os.getenv("ADTESTPRO_MODEL") == "ui-model"
    assert os.getenv("ADTESTPRO_MODELS") == "openai/gpt-4o-mini, deepseek/deepseek-v4-flash"
    assert "sk-or-v1-testkey123456" not in r.text  # still masked
    assert "sk-or-v1-…456" in r.text


def test_settings_invalid_timeout_rejected_no_save(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={"action": "save", "timeout_s": "abc"})
    assert r.status_code == 422
    assert "number of seconds" in r.text
    assert captured == {}


def test_blank_pool_clears_models(monkeypatch):
    captured = _saved(monkeypatch)
    app.state.provider_settings = ProviderSettings(
        keys=[_mk()], active_key_id="k1", models="openai/gpt-4o-mini")
    c = TestClient(app)
    r = c.post("/settings", data={"action": "save", "model": "", "image_model": "",
                                  "timeout_s": ""})
    assert r.status_code == 200
    assert captured["settings"].models == ""


def test_pool_checkboxes_render_with_tooltip(monkeypatch):
    _saved(monkeypatch)
    c = TestClient(app)
    html = c.get("/settings").text
    assert 'name="pool_models"' in html
    assert html.count('name="pool_models"') >= 5
    assert "tested and validated on" in html
    assert 'name="models_custom"' not in html  # custom ids removed


def test_pool_checkboxes_dedup(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={
        "action": "save", "model": "",
        "pool_models": ["openai/gpt-4o-mini", "openai/gpt-4o-mini",
                        "deepseek/deepseek-v4-flash"],
        "image_model": "", "timeout_s": "",
    })
    assert r.status_code == 200
    assert captured["settings"].models == "openai/gpt-4o-mini, deepseek/deepseek-v4-flash"
    assert "Single-vendor pool" not in r.text and "Single-model pool" not in r.text


def test_single_vendor_pool_warns_without_blocking(monkeypatch):
    captured = _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={
        "action": "save", "model": "",
        "pool_models": ["openai/gpt-4o-mini", "openai/gpt-5-mini"],
        "image_model": "", "timeout_s": "",
    })
    assert r.status_code == 200  # warning, not an error
    assert "Single-vendor pool" in r.text
    assert "family bias" in r.text
    assert captured["settings"].models == "openai/gpt-4o-mini, openai/gpt-5-mini"


def test_single_model_pool_warns(monkeypatch):
    _saved(monkeypatch)
    c = TestClient(app)
    r = c.post("/settings", data={
        "action": "save", "model": "", "pool_models": ["openai/gpt-4o-mini"],
        "image_model": "", "timeout_s": "",
    })
    assert r.status_code == 200
    assert "Single-model pool" in r.text


def test_pool_catalog_covers_four_vendors_with_json_mode_ids():
    from app.core.settings import SUPPORTED_POOL_MODELS, pool_vendors

    ids = [m["id"] for m in SUPPORTED_POOL_MODELS]
    assert len(ids) >= 5 and len(set(ids)) == len(ids)
    assert all("/" in i and ":batch" not in i for i in ids)
    vendors = pool_vendors(ids)
    assert {"openai", "anthropic", "deepseek"} <= set(vendors)
    assert any("glm" in i for i in ids)
    assert pool_vendors(["openai/a", "openai/b", "x"]) == ["openai", "unknown"]


def test_nav_links_settings_and_runs():
    c = TestClient(app)
    home = c.get("/").text
    assert 'href="/settings"' in home and 'href="/runs"' in home


def test_report_shows_model_mix_note():
    from tests.test_api import FORM, _files
    from tests.test_pipeline import full_fake

    app.state.llm_client = full_fake()
    try:
        c = TestClient(app)
        r = c.post("/evaluate", data=dict(FORM, question_ids="clarity"), files=_files())
        assert r.status_code == 200
        assert "Scored by 1 model(s) across 1 vendor(s)" in r.text
        assert "single-family pool" in r.text
    finally:
        app.state.llm_client = None
