"""Global test hygiene: no test may touch the developer's real data/ directory.

The save hooks in both routers write to `runs.default_path()` (`data/`),
so without this every TestClient POST pollutes the real history DB.
"""

import os

# Never let the real OS keychain block or prompt during tests (conftest loads
# before any test module imports app.main, which reads settings.local.json).
os.environ.setdefault("ADTESTPRO_DISABLE_KEYRING", "1")

import pytest

from app.core import runs as runs_mod


@pytest.fixture(autouse=True)
def _isolate_runs_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_mod, "default_path", lambda: tmp_path / "test.db")
