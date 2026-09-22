"""Runtime provider settings (S1). Env stays the default for model config; the
Settings UI owns provider keys and overrides model values.

Integration point: `apply()` writes effective values into process env and resets
the cached LLM client, because every consumer (`model_pool`, `_timeout_s`,
`shared_client`, trace model) already resolves env at call time. Single-user
assumption: one global settings object; concurrent users would share it.

API keys are owned exclusively by the UI store (form -> settings.local.json).
The environment `OPENAI_API_KEY` is never read back; `apply()` only pushes the
active stored key into it so the shared client keeps a single lookup path.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field

from app.core.paths import REPO_ROOT, data_dir
from pathlib import Path
from typing import Optional

SETTINGS_FILENAME = "settings.local.json"  # gitignored; never commit

# OpenRouter is the default provider: a blank Base URL resolves here, and the
# default text model uses OpenRouter's vendor/model form.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def default_path() -> Path:
    return data_dir() / SETTINGS_FILENAME


def _legacy_path() -> Path:
    """Pre-data-dir location (repo root); read once so settings aren't lost."""
    return REPO_ROOT / SETTINGS_FILENAME


def resolve_base_url(raw: Optional[str]) -> str:
    """One endpoint resolver used by the probe and the LLM client, so they agree.

    Blank means the default provider (OpenRouter); trailing slashes are trimmed.
    """
    return (raw or "").strip().rstrip("/") or DEFAULT_BASE_URL


def new_key_id() -> str:
    return secrets.token_hex(4)


def mask_key(key: str) -> str:
    """Show only the head and tail; short keys degrade to a presence marker."""
    k = (key or "").strip()
    if not k:
        return ""
    return f"{k[:9]}…{k[-3:]}" if len(k) > 12 else "…set…"


# ---------------------------------------------------------------- keychain
# Optional OS keychain storage (Keychain / Credential Manager / Secret Service).
# The `keyring` package is imported lazily; when absent or without a working
# backend every helper is a no-op and secrets stay in the 0600 settings file.

KEYRING_SERVICE = "adtestpro"
KEYRING_TIMEOUT_S = 1.5  # never let a locked/headless keychain block startup


def _keyring_disabled() -> bool:
    """Kill-switch for headless/CI/locked-keychain environments."""
    return bool(os.getenv("ADTESTPRO_DISABLE_KEYRING", "").strip())


def _with_timeout(fn, default=None, timeout_s: Optional[float] = None):
    """Run a possibly-blocking keychain call in a daemon thread with a timeout.

    macOS Keychain can block indefinitely on a locked keychain or an unsigned
    interpreter (permission prompt). We must never hang import/startup on it.
    """
    import threading
    if timeout_s is None:
        timeout_s = KEYRING_TIMEOUT_S

    box: dict = {}

    def run() -> None:
        try:
            box["v"] = fn()
        except Exception:
            box["v"] = default

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    return box.get("v", default)


def keyring_available() -> bool:
    """True when a working OS keychain backend is importable and usable."""
    if _keyring_disabled():
        return False
    try:
        import keyring
        from keyring.backends import fail
        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False


def keyring_get(key_id: str) -> Optional[str]:
    if _keyring_disabled():
        return None
    import keyring
    return _with_timeout(lambda: keyring.get_password(KEYRING_SERVICE, key_id))


def keyring_set(key_id: str, secret: str) -> None:
    if _keyring_disabled():
        return
    import keyring
    _with_timeout(lambda: keyring.set_password(KEYRING_SERVICE, key_id, secret),
                  timeout_s=3.0)


def keyring_delete(key_id: str) -> None:
    if _keyring_disabled():
        return
    import keyring
    _with_timeout(lambda: keyring.delete_password(KEYRING_SERVICE, key_id),
                  timeout_s=3.0)  # already gone / backend unavailable: nothing to clean up


# Curated scoring-pool candidates, verified 2026-09-09 via the OpenRouter
# /models API: all support response_format (required by the scoring stage),
# all cheap enough for ~25 calls/run. Family = vendor prefix before "/".
# Kept static (not live-fetched) so tests and offline runs stay deterministic.
SUPPORTED_POOL_MODELS = [
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "vendor": "openai",
     "blurb": "Proven default · cheapest OpenAI"},
    {"id": "openai/gpt-5-mini", "label": "GPT-5 mini", "vendor": "openai",
     "blurb": "Current-gen efficient OpenAI"},
    {"id": "anthropic/claude-sonnet-5", "label": "Claude Sonnet 5", "vendor": "anthropic",
     "blurb": "Anthropic workhorse"},
    {"id": "z-ai/glm-5.3-flash", "label": "GLM 5.3 Flash", "vendor": "z-ai",
     "blurb": "Zhipu · cheapest of all · 1M ctx"},
    {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash", "vendor": "deepseek",
     "blurb": "DeepSeek · cheap · 1M ctx"},
]

VENDOR_NAMES = {
    "openai": "OpenAI", "anthropic": "Anthropic",
    "z-ai": "Zhipu (GLM)", "deepseek": "DeepSeek",
}


def pool_vendors(pool: list[str]) -> list[str]:
    """Vendor prefixes in first-seen order, e.g. ['openai', 'anthropic']."""
    vendors: list[str] = []
    for m in pool:
        v = m.split("/")[0].strip().lower() if "/" in m else "unknown"
        if v not in vendors:
            vendors.append(v)
    return vendors


@dataclass
class ApiKey:
    """One named provider credential. Secret lives inline (file) or in the OS keychain."""

    id: str
    label: str = ""
    key: str = ""
    base_url: str = ""
    secret_source: str = field(default="file", compare=False)  # "file" | "keyring"

    def masked(self) -> str:
        return mask_key(self.key)

    @classmethod
    def from_dict(cls, data: dict) -> "ApiKey":
        return cls(
            id=str(data.get("id") or new_key_id()),
            label=str(data.get("label", "")),
            key=str(data.get("key", "")),
            base_url=str(data.get("base_url", "")),
            secret_source=str(data.get("secret_source", "file") or "file"),
        )


@dataclass
class ProviderSettings:
    keys: list[ApiKey] = field(default_factory=list)
    active_key_id: str = ""
    keyring_enabled: bool = False  # opt-in OS keychain storage (default: 0600 file)
    model: str = ""          # ADTESTPRO_MODEL (primary text model)
    models: str = ""         # ADTESTPRO_MODELS (comma-separated pool)
    image_model: str = ""    # ADTESTPRO_IMAGE_MODEL
    timeout_s: Optional[float] = None

    # -- active key --

    def active_key(self) -> Optional[ApiKey]:
        """Matching active id, else the first stored key (never env)."""
        for k in self.keys:
            if k.id == self.active_key_id:
                return k
        return self.keys[0] if self.keys else None

    # -- effective values (explicit wins, else env for non-key fields) --

    def effective_api_key(self) -> str:
        k = self.active_key()
        return k.key.strip() if k else ""

    def effective_base_url(self) -> str:
        k = self.active_key()
        return k.base_url.strip() if k else ""

    def effective_model(self) -> str:
        return (self.model.strip() or os.getenv("ADTESTPRO_MODEL", "").strip()
                or DEFAULT_MODEL)

    def effective_pool(self) -> list[str]:
        raw = self.models.strip() or os.getenv("ADTESTPRO_MODELS", "")
        return [m.strip() for m in raw.split(",") if m.strip()]

    def effective_image_model(self) -> str:
        return self.image_model.strip() or os.getenv("ADTESTPRO_IMAGE_MODEL", "").strip()

    def effective_timeout_s(self) -> float:
        if self.timeout_s is not None:
            return self.timeout_s
        try:
            return max(1.0, float(os.getenv("ADTESTPRO_TIMEOUT_S", "60")))
        except ValueError:
            return 60.0

    @property
    def is_configured(self) -> bool:
        return bool(self.effective_api_key())

    @property
    def masked_key(self) -> str:
        k = self.active_key()
        return k.masked() if k else ""

    def validate(self) -> dict[str, str]:
        """Semantics of the *explicit* values; env fallbacks are assumed valid."""
        errs: dict[str, str] = {}
        if self.models.strip() and not self.effective_pool():
            errs["models"] = "Pool must contain at least one model id."
        if self.timeout_s is not None and self.timeout_s < 1:
            errs["timeout_s"] = "Timeout must be at least 1 second."
        ids = [k.id for k in self.keys]
        if len(ids) != len(set(ids)):
            errs["keys"] = "Duplicate key ids."
        labels = [k.label.strip() for k in self.keys if k.label.strip()]
        if len(labels) != len(set(labels)):
            errs["keys"] = "Key labels must be unique."
        if any(not k.key.strip() for k in self.keys):
            errs["keys"] = "Key value cannot be empty."
        return errs

    # -- file persistence (gitignored) --

    def to_file_dict(self) -> dict:
        """Serialize; secrets go to the OS keychain only when opted in + available."""
        use_keyring = self.keyring_enabled and keyring_available()
        keys_out: list[dict] = []
        for k in self.keys:
            entry = {"id": k.id, "label": k.label, "base_url": k.base_url}
            secret = k.key.strip()
            source = "file"
            if use_keyring and secret:
                try:
                    keyring_set(k.id, secret)
                    source = "keyring"
                    entry["key"] = ""
                except Exception:
                    entry["key"] = k.key
            else:
                entry["key"] = k.key
            entry["secret_source"] = source
            keys_out.append(entry)
        return {
            "keys": keys_out,
            "active_key_id": self.active_key_id,
            "keyring_enabled": self.keyring_enabled,
            "model": self.model,
            "models": self.models,
            "image_model": self.image_model,
            "timeout_s": self.timeout_s,
        }

    @classmethod
    def from_file_dict(cls, data: dict) -> "ProviderSettings":
        data = data or {}
        keys: list[ApiKey] = []
        raw_keys = data.get("keys")
        if isinstance(raw_keys, list):
            for item in raw_keys:
                if not isinstance(item, dict):
                    continue
                k = ApiKey.from_dict(item)
                if k.secret_source == "keyring" and not k.key:
                    try:
                        k.key = keyring_get(k.id) or ""
                    except Exception:
                        k.key = ""  # keychain locked/missing: stays unconfigured
                keys.append(k)
        # Legacy shape: a single top-level api_key/base_url becomes one stored key.
        if not keys and str(data.get("api_key", "")).strip():
            keys = [ApiKey(
                id=new_key_id(), label="Imported key",
                key=str(data.get("api_key", "")),
                base_url=str(data.get("base_url", "")),
            )]
        active = str(data.get("active_key_id", "") or "")
        if keys and not any(k.id == active for k in keys):
            active = keys[0].id
        clean: dict = {
            "keys": keys,
            "active_key_id": active,
            "keyring_enabled": bool(data.get("keyring_enabled", False)),
            "model": str(data.get("model", "") or ""),
            "models": str(data.get("models", "") or ""),
            "image_model": str(data.get("image_model", "") or ""),
        }
        try:
            if data.get("timeout_s") is not None:
                clean["timeout_s"] = float(data["timeout_s"])
        except (TypeError, ValueError):
            pass
        return cls(**clean)


def load_settings(path: Optional[Path] = None) -> ProviderSettings:
    """Missing or corrupt file -> empty settings (env still applies to models)."""
    if path is None:
        path = default_path()
        if not path.exists():
            legacy = _legacy_path()
            if legacy.exists():
                path = legacy  # migrate on next save
    try:
        return ProviderSettings.from_file_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ProviderSettings()


def save_settings(settings: ProviderSettings, path: Optional[Path] = None) -> Path:
    path = path or default_path()
    _prune_keyring_secrets(settings, path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings.to_file_dict(), f, indent=2)
    return path


def _prune_keyring_secrets(settings: ProviderSettings, path: Path) -> None:
    """Drop keychain entries for keys deleted since the previous save."""
    if not keyring_available():
        return
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    current = {k.id for k in settings.keys}
    for item in prev.get("keys", []) or []:
        if not isinstance(item, dict):
            continue
        kid = str(item.get("id", "") or "")
        if kid and kid not in current and item.get("secret_source") == "keyring":
            keyring_delete(kid)


def apply_settings(settings: ProviderSettings) -> None:
    """Push effective values into process env; reset cached client/semaphore.

    Must run before serving requests (startup) or on Settings save. In-flight
    calls keep the old semaphore; acceptable for a rare user-initiated event.
    The key/base URL are cleared when no key is active, so switching or deleting
    a key never leaves a stale credential in the environment.
    """
    from app.core import llm  # local import: llm never imports settings

    key = settings.effective_api_key()
    if key:
        os.environ["OPENAI_API_KEY"] = key
    else:
        os.environ.pop("OPENAI_API_KEY", None)
    base_url = resolve_base_url(settings.effective_base_url())
    os.environ["ADTESTPRO_BASE_URL"] = base_url
    if settings.model.strip():
        os.environ["ADTESTPRO_MODEL"] = settings.model.strip()
    if settings.models.strip():
        os.environ["ADTESTPRO_MODELS"] = settings.models.strip()
    if settings.image_model.strip():
        os.environ["ADTESTPRO_IMAGE_MODEL"] = settings.image_model.strip()
    if settings.timeout_s is not None:
        os.environ["ADTESTPRO_TIMEOUT_S"] = str(settings.timeout_s)
    llm.reset_client()


def probe_connection(api_key: str, base_url: str, timeout_s: float = 10.0) -> tuple[bool, str]:
    """Provider reachability check against the *resolved* endpoint (never logs the key).

    Uses `GET {base}/models`, which OpenAI-compatible providers (OpenAI, OpenRouter)
    expose, so the probe tests exactly where the pipeline will send calls.
    """
    import httpx  # local import: keeps settings importable without http deps

    base = resolve_base_url(base_url)
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {api_key.strip()}"},
                      timeout=max(1.0, timeout_s))
    except Exception as e:
        return False, f"unreachable: {type(e).__name__} · {base}"
    if r.status_code == 200:
        return True, f"connected · {base}"
    if r.status_code in (401, 403):
        return False, f"key rejected (401/403) · {base}"
    return False, f"unexpected status {r.status_code} · {base}"


def mismatch_warnings(settings: "ProviderSettings") -> list[str]:
    """Warn-only checks: a key/model that doesn't match the resolved endpoint."""
    key = settings.effective_api_key()
    base = resolve_base_url(settings.effective_base_url())
    model = settings.effective_model()
    openrouter = "openrouter.ai" in base
    warns: list[str] = []
    if key.startswith("sk-or-") and not openrouter:
        warns.append(f"This looks like an OpenRouter key, but calls go to {base}. "
                     f"Set Base URL to {DEFAULT_BASE_URL}.")
    if openrouter and "/" not in model:
        warns.append(f"OpenRouter model ids look like 'vendor/model' (e.g. {DEFAULT_MODEL}); "
                     f"'{model}' may be rejected.")
    if not openrouter and "/" in model:
        warns.append(f"Endpoint {base} expects a plain OpenAI model id, but '{model}' "
                     "has a vendor prefix.")
    return warns
