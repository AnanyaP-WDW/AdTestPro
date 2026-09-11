"""Global test hygiene: no test may touch the developer's real data/ directory.

The save hooks in both routers write to `runs.default_path()` (`data/`),
so without this every TestClient POST pollutes the real history DB.
"""

import pytest

from app.core import runs as runs_mod


@pytest.fixture(autouse=True)
def _isolate_runs_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_mod, "default_path", lambda: tmp_path / "test.db")
