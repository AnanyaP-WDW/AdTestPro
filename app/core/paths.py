"""Writable data directory for settings, preferences, and the run database.

`ADTESTPRO_DATA_DIR` overrides the location; the default is the repo root for
local dev. Docker sets it to `/data`, which is a named volume, so settings and
history survive image rebuilds.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def custom_data_dir() -> bool:
    """True when ADTESTPRO_DATA_DIR points somewhere other than the repo root.

    Legacy fallbacks (repo-root settings/DB) only make sense for that default;
    a container with its own volume must never read the host's bind-mounted files.
    """
    return bool(os.getenv("ADTESTPRO_DATA_DIR", "").strip())


def data_dir() -> Path:
    raw = os.getenv("ADTESTPRO_DATA_DIR", "").strip()
    path = Path(raw).expanduser() if raw else REPO_ROOT
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return REPO_ROOT
    return path
