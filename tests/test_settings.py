"""S1 exit criteria: store-owned keys, env fallback for models, validation, apply."""

import json
import os

import pytest

from app.core.settings import (
    ApiKey,
    ProviderSettings,
    apply_settings,
    load_settings,
    save_settings,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "ADTESTPRO_BASE_URL", "ADTESTPRO_MODEL",
                "ADTESTPRO_MODELS", "ADTESTPRO_IMAGE_MODEL", "ADTESTPRO_TIMEOUT_S"):
        monkeypatch.delenv(var, raising=False)


def _key(**kw):
    return ApiKey(**{**{"id": "k1", "label": "Primary", "key": "ui-key"}, **kw})


def test_explicit_values_win_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("ADTESTPRO_MODEL", "env-model")
    s = ProviderSettings(
        keys=[_key(key="  ui-key ", base_url="https://api.example/v1")],
        active_key_id="k1", model="ui-model", models="a, b ,")
    assert s.effective_api_key() == "ui-key"
    assert s.effective_base_url() == "https://api.example/v1"
    assert s.effective_model() == "ui-model"
    assert s.effective_pool() == ["a", "b"]
    assert s.effective_image_model() == ""  # unset everywhere
    assert s.is_configured


def test_env_key_is_never_read():
    os.environ["OPENAI_API_KEY"] = "env-key-should-be-ignored"
    s = ProviderSettings()
    assert s.effective_api_key() == ""
    assert not s.is_configured
    assert s.masked_key == ""


def test_empty_settings_fall_back_to_env_for_models(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODELS", "m1,m2")
    s = ProviderSettings()
    assert s.effective_pool() == ["m1", "m2"]
    assert not s.is_configured


def test_masked_key_never_contains_full_key():
    s = ProviderSettings(keys=[_key(key="sk-or-v1-abcdefghijklmnop123")], active_key_id="k1")
    assert s.effective_api_key() not in s.masked_key
    assert s.masked_key.startswith("sk-or-v1-") and s.masked_key.endswith("123")


def test_active_key_falls_back_to_first_stored():
    s = ProviderSettings(keys=[_key(id="a", label="A"), _key(id="b", label="B")],
                         active_key_id="missing")
    assert s.active_key().id == "a"


def test_validate_flags_bad_pool_timeout_and_keys():
    assert ProviderSettings(models="  ,, ").validate()["models"]
    assert ProviderSettings(timeout_s=0).validate()["timeout_s"]
    assert ProviderSettings(timeout_s=120).validate() == {}
    assert ProviderSettings().validate() == {}
    assert "keys" in ProviderSettings(
        keys=[_key(id="x", label="A"), _key(id="x", label="B")]).validate()
    assert "keys" in ProviderSettings(
        keys=[_key(id="1", label="A"), _key(id="2", label="A")]).validate()
    assert "keys" in ProviderSettings(keys=[_key(key="")]).validate()


def test_file_round_trip_and_missing_file(tmp_path):
    path = tmp_path / "settings.local.json"
    assert load_settings(path) == ProviderSettings()  # missing -> defaults
    s = ProviderSettings(
        keys=[_key(key="secret", base_url="https://x")], active_key_id="k1",
        model="m", timeout_s=120.0)
    save_settings(s, path)
    assert load_settings(path) == s
    assert (path.stat().st_mode & 0o777) == 0o600


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == ProviderSettings()


def test_legacy_single_key_migrates_to_key_store(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"api_key": "legacy-key", "base_url": "https://legacy",
                                "model": "m", "timeout_s": 30}), encoding="utf-8")
    s = load_settings(path)
    assert len(s.keys) == 1
    assert s.keys[0].key == "legacy-key" and s.keys[0].base_url == "https://legacy"
    assert s.active_key_id == s.keys[0].id
    assert s.effective_api_key() == "legacy-key"
    assert s.model == "m" and s.timeout_s == 30.0


def test_apply_pushes_env_and_resets_client(monkeypatch):
    from app.core import llm

    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)
    llm._client = object()  # prove reset
    apply_settings(ProviderSettings(
        keys=[_key(key="active-key", base_url="https://b")], active_key_id="k1",
        model="ui-model", timeout_s=90.0))
    assert os.getenv("OPENAI_API_KEY") == "active-key"
    assert os.getenv("ADTESTPRO_BASE_URL") == "https://b"
    assert os.getenv("ADTESTPRO_MODEL") == "ui-model"
    assert os.getenv("ADTESTPRO_TIMEOUT_S") == "90.0"
    assert llm._client is None and llm._sem is None
    llm._sem = None


def test_apply_clears_stale_key_and_resets_base_url(monkeypatch):
    from app.core.settings import DEFAULT_BASE_URL

    monkeypatch.setenv("OPENAI_API_KEY", "stale-key")
    monkeypatch.setenv("ADTESTPRO_BASE_URL", "https://stale")
    apply_settings(ProviderSettings())
    assert os.getenv("OPENAI_API_KEY") is None  # no key -> cleared
    assert os.getenv("ADTESTPRO_BASE_URL") == DEFAULT_BASE_URL  # blank -> OpenRouter


def test_apply_leaves_unset_fields_on_env(monkeypatch):
    monkeypatch.setenv("ADTESTPRO_MODEL", "env-model")
    apply_settings(ProviderSettings())
    assert os.getenv("ADTESTPRO_MODEL") == "env-model"


def test_apply_flows_into_real_consumers(monkeypatch):
    from app.core import llm

    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)
    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)
    apply_settings(ProviderSettings(
        keys=[_key(key="k")], active_key_id="k1",
        model="ui-primary", models="a, b", timeout_s=45.0))
    assert llm.model_pool() == ["a", "b"]
    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)
    assert llm.model_pool() == ["ui-primary"]
    assert llm._timeout_s() == 45.0


def test_probe_hits_resolved_endpoint_and_reports_it(monkeypatch):
    import httpx
    from app.core.settings import DEFAULT_BASE_URL, probe_connection

    seen: dict = {}

    class _R:
        def __init__(self, code):
            self.status_code = code

    def _get(url, **k):
        seen["url"] = url
        return _R(200)

    monkeypatch.setattr(httpx, "get", _get)
    ok, msg = probe_connection("k", "")  # blank -> OpenRouter default
    assert ok and DEFAULT_BASE_URL in msg
    assert seen["url"] == f"{DEFAULT_BASE_URL}/models"

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R(401))
    ok, msg = probe_connection("bad", "https://api.openai.com/v1")
    assert not ok and "401" in msg and "api.openai.com" in msg

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R(404))
    ok, msg = probe_connection("k", "https://example.test/v1")
    assert not ok and "404" in msg

    def _boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", _boom)
    ok, msg = probe_connection("k", "")
    assert not ok and "unreachable" in msg


def test_resolve_base_url_defaults_to_openrouter():
    from app.core.settings import DEFAULT_BASE_URL, resolve_base_url

    assert resolve_base_url("") == DEFAULT_BASE_URL
    assert resolve_base_url(None) == DEFAULT_BASE_URL
    assert resolve_base_url("  ") == DEFAULT_BASE_URL
    assert resolve_base_url("https://openrouter.ai/api/v1/") == DEFAULT_BASE_URL
    assert resolve_base_url(" https://api.openai.com/v1 ") == "https://api.openai.com/v1"


def test_apply_sets_openrouter_base_url_when_key_blank(monkeypatch):
    from app.core.settings import DEFAULT_BASE_URL, resolve_base_url

    monkeypatch.delenv("ADTESTPRO_BASE_URL", raising=False)
    apply_settings(ProviderSettings(keys=[_key(key="sk-or-v1-abc")], active_key_id="k1"))
    assert os.getenv("ADTESTPRO_BASE_URL") == DEFAULT_BASE_URL
    assert resolve_base_url(os.getenv("ADTESTPRO_BASE_URL", "")) == DEFAULT_BASE_URL


def test_effective_model_defaults_to_openrouter_model(monkeypatch):
    from app.core.settings import DEFAULT_MODEL

    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)
    assert ProviderSettings().effective_model() == DEFAULT_MODEL


def test_load_settings_reads_legacy_location(tmp_path, monkeypatch):
    from app.core import settings as s

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(
        {"keys": [{"id": "k1", "label": "L", "key": "secret"}]}), encoding="utf-8")
    monkeypatch.setattr(s, "default_path", lambda: tmp_path / "new.json")
    monkeypatch.setattr(s, "_legacy_path", lambda: legacy)
    assert s.load_settings().effective_api_key() == "secret"


def test_keyring_kill_switch_and_timeout(monkeypatch):
    from app.core import settings as s

    # kill-switch: no keychain access at all
    monkeypatch.setenv("ADTESTPRO_DISABLE_KEYRING", "1")
    assert s.keyring_available() is False
    assert s.keyring_get("anything") is None

    # a slow/hanging keychain call must return instead of blocking startup
    monkeypatch.delenv("ADTESTPRO_DISABLE_KEYRING", raising=False)
    import time
    import keyring
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: time.sleep(5) or "late")
    monkeypatch.setattr(s, "KEYRING_TIMEOUT_S", 0.2)
    started = time.perf_counter()
    assert s.keyring_get("k") is None
    assert time.perf_counter() - started < 2.0


def test_mismatch_warnings(monkeypatch):
    from app.core.settings import mismatch_warnings

    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)
    # OpenRouter key pointed at OpenAI
    w = mismatch_warnings(ProviderSettings(
        keys=[_key(key="sk-or-v1-abc", base_url="https://api.openai.com/v1")], active_key_id="k1"))
    assert any("OpenRouter key" in m for m in w)
    # OpenRouter endpoint but a bare OpenAI model id
    w = mismatch_warnings(ProviderSettings(
        keys=[_key(key="k", base_url="")], active_key_id="k1", model="gpt-4o-mini-2024-07-18"))
    assert any("vendor/model" in m for m in w)
    # OpenAI endpoint but a vendor-prefixed model id
    w = mismatch_warnings(ProviderSettings(
        keys=[_key(key="sk-openai", base_url="https://api.openai.com/v1")],
        active_key_id="k1", model="openai/gpt-4o-mini"))
    assert any("vendor prefix" in m for m in w)
    # Matching OpenRouter config: no warnings
    assert mismatch_warnings(ProviderSettings(
        keys=[_key(key="sk-or-v1-abc", base_url="")], active_key_id="k1",
        model="openai/gpt-4o-mini")) == []


# ---------------- OS keychain storage (keyring) ----------------

@pytest.fixture
def fake_keyring(monkeypatch):
    """Patch the settings keyring seam with an in-memory backend."""
    from app.core import settings as s

    store: dict[str, str] = {}
    monkeypatch.setattr(s, "keyring_available", lambda: True)
    monkeypatch.setattr(s, "keyring_get", lambda kid: store.get(kid))
    monkeypatch.setattr(s, "keyring_set", lambda kid, secret: store.__setitem__(kid, secret))
    monkeypatch.setattr(s, "keyring_delete", lambda kid: store.pop(kid, None))
    return store


def test_keyring_round_trip_keeps_secret_out_of_file(tmp_path, fake_keyring):
    path = tmp_path / "settings.local.json"
    s = ProviderSettings(
        keys=[_key(key="secret-key-123", base_url="https://x")], active_key_id="k1",
        keyring_enabled=True, model="m")
    save_settings(s, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["keyring_enabled"] is True
    assert raw["keys"][0]["key"] == ""  # secret never in the file
    assert raw["keys"][0]["secret_source"] == "keyring"
    assert fake_keyring["k1"] == "secret-key-123"

    loaded = load_settings(path)
    assert loaded.keyring_enabled is True
    assert loaded.effective_api_key() == "secret-key-123"
    assert loaded.keys[0].secret_source == "keyring"


def test_keyring_unavailable_falls_back_to_file(tmp_path, monkeypatch):
    from app.core import settings as s

    monkeypatch.setattr(s, "keyring_available", lambda: False)
    path = tmp_path / "settings.local.json"
    s_obj = ProviderSettings(keys=[_key(key="inline-key")], active_key_id="k1",
                             keyring_enabled=True)
    save_settings(s_obj, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["keys"][0]["key"] == "inline-key"
    assert raw["keys"][0]["secret_source"] == "file"
    assert load_settings(path).effective_api_key() == "inline-key"


def test_keyring_locked_on_load_leaves_key_unconfigured(tmp_path, fake_keyring, monkeypatch):
    from app.core import settings as s

    path = tmp_path / "settings.local.json"
    save_settings(ProviderSettings(keys=[_key(key="secret")], active_key_id="k1",
                                   keyring_enabled=True), path)
    monkeypatch.setattr(s, "keyring_get", lambda kid: None)  # keychain now unreachable
    loaded = load_settings(path)
    assert loaded.keys[0].key == ""
    assert loaded.keys[0].secret_source == "keyring"
    assert not loaded.is_configured


def test_deleting_key_prunes_keyring_secret(tmp_path, fake_keyring):
    path = tmp_path / "settings.local.json"
    save_settings(ProviderSettings(
        keys=[_key(id="k1", label="A", key="s1"), _key(id="k2", label="B", key="s2")],
        active_key_id="k1", keyring_enabled=True), path)
    assert set(fake_keyring) == {"k1", "k2"}
    save_settings(ProviderSettings(
        keys=[_key(id="k1", label="A", key="s1")],
        active_key_id="k1", keyring_enabled=True), path)
    assert set(fake_keyring) == {"k1"}


def test_secret_source_never_breaks_equality():
    assert ApiKey(id="a", label="A", key="x") == ApiKey(
        id="a", label="A", key="x", secret_source="keyring")

