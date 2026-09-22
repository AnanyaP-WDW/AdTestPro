"""Remembered evaluation-form inputs (non-secret UI preferences).

Stored as JSON in the data dir (mode 0644) so the brief, panel size, and selected
questions are prefilled next time. The uploaded image is NEVER persisted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.core.paths import data_dir

PREFERENCES_FILENAME = "preferences.json"

# Form fields remembered verbatim (strings, so they re-render in inputs).
BRIEF_FIELDS = (
    "product_description", "campaign_objective", "age_min", "age_max", "location",
    "interests", "pain_points", "category_familiarity",
    "gender_constraint", "price_sensitivity", "brand_familiarity",
)
DEFAULT_QUESTIONS = ["attention", "clarity", "relevance"]


def default_path() -> Path:
    return data_dir() / PREFERENCES_FILENAME


def load_prefs(path: Optional[Path] = None) -> dict:
    path = path or default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(prefs: dict, path: Optional[Path] = None) -> Path:
    path = path or default_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o644)  # no secrets live here
    except OSError:
        pass
    return path


def clear_prefs(path: Optional[Path] = None) -> None:
    path = path or default_path()
    try:
        path.unlink()
    except OSError:
        pass


def snapshot(form: dict, persona_count: int, question_ids: list[str]) -> dict:
    """Build the storable subset from a submitted form."""
    data = {k: str(form.get(k, "") or "") for k in BRIEF_FIELDS}
    data["persona_count"] = int(persona_count)
    data["question_ids"] = [q for q in question_ids if q]
    return data


def form_values(prefs: dict) -> dict:
    """Only non-empty remembered fields, safe to render into inputs."""
    return {k: prefs[k] for k in BRIEF_FIELDS if isinstance(prefs.get(k), str) and prefs[k]}


def persona_count(prefs: dict, default: int) -> int:
    try:
        n = int(prefs.get("persona_count", default))
        return n if 1 <= n <= 100 else default
    except (TypeError, ValueError):
        return default


def question_ids(prefs: dict) -> list[str]:
    ids = prefs.get("question_ids")
    return [str(q) for q in ids] if isinstance(ids, list) and ids else list(DEFAULT_QUESTIONS)
