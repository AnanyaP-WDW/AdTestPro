"""Global test hygiene: no test may touch the developer's real data/ directory.

The save hooks in both routers write to `runs.default_path()` (`data/`),
so without this every TestClient POST pollutes the real history DB.
"""

import os

# Never let the real OS keychain block or prompt during tests (conftest loads
# before any test module imports app.main, which reads settings.local.json).
os.environ.setdefault("ADTESTPRO_DISABLE_KEYRING", "1")

import pytest

from app.core import prefs as prefs_mod
from app.core import runs as runs_mod
from app.core import settings as settings_mod


@pytest.fixture(autouse=True)
def _isolate_local_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_mod, "default_path", lambda: tmp_path / "test.db")
    monkeypatch.setattr(runs_mod, "_legacy_path", lambda: tmp_path / "no-legacy.db")
    monkeypatch.setattr(prefs_mod, "default_path", lambda: tmp_path / "preferences.json")
    monkeypatch.setattr(settings_mod, "default_path", lambda: tmp_path / "settings.local.json")
    monkeypatch.setattr(settings_mod, "_legacy_path", lambda: tmp_path / "no-legacy.json")
    yield
