"""Run records (R1). Stdlib sqlite3 only — no new dependencies.

One row per terminal evaluation: queryable metadata columns plus the full
`EvaluationResult` JSON (the same `model_dump(mode="json")` the API already
emits) and the bounded report thumbnail. API keys never appear: result JSON
carries model names only, and this module has no access to secrets.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.models import EvaluationResult
from app.core.paths import REPO_ROOT, data_dir

logger = logging.getLogger("adtestpro.runs")

DB_FILENAME = "adtestpro.db"


class RunRecordError(ValueError):
    """Stored row is missing or unreadable."""


def default_path() -> Path:
    return data_dir() / DB_FILENAME


def _legacy_path() -> Path:
    """Pre-data-dir location (repo/data); read once so history isn't lost."""
    return REPO_ROOT / "data" / DB_FILENAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  evaluation_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  panel_size INTEGER NOT NULL,
  question_ids TEXT NOT NULL,
  overall_mean REAL,
  valid_responses INTEGER NOT NULL,
  missing_responses INTEGER NOT NULL,
  model TEXT NOT NULL,
  thumb_uri TEXT,
  summary TEXT,
  result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
"""

_LIST_COLS = ("evaluation_id, created_at, status, panel_size, question_ids,"
              " overall_mean, valid_responses, missing_responses, model, summary")


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from DBs created by older versions (no data loss)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "summary" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN summary TEXT")


def summarize_result(result: EvaluationResult) -> str:
    """One-line experiment summary for the runs list (≤200 chars)."""
    if result.status != "complete" and not result.status.startswith("complete"):
        first_warn = (result.trace.warnings or ["no details"])[0]
        return f"{result.status}: {first_warn}"[:200]
    rated = [q for q in result.scores.per_question if q.mean is not None]
    if not rated:
        return "complete: no rated dimensions"
    top = max(rated, key=lambda q: q.mean)
    low = min(rated, key=lambda q: q.mean)
    mean = result.scores.overall_mean
    mean_txt = f"{mean:.2f}" if mean is not None else "n/a"
    return (f"mean {mean_txt} ({top.question_id} {top.mean:.1f} → "
            f"{low.question_id} {low.mean:.1f}) · {len(result.themes)} themes · "
            f"{len(result.recommendations)} recommendations")[:200]


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Short-lived connection per operation (thread-safe under TestClient + uvicorn)."""
    if path:
        path = Path(path)
    else:
        path = default_path()
        if not path.exists():
            legacy = _legacy_path()
            if legacy.exists():
                path = legacy  # migrate on next write
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def save_run(result: EvaluationResult, thumb_uri: Optional[str] = None,
             path: Optional[Path] = None) -> str:
    """INSERT OR REPLACE one terminal run. Returns the evaluation id."""
    scores = result.scores
    qids = [q.question_id for q in scores.per_question]
    started = result.trace.started_at
    if isinstance(started, datetime):
        created = started.isoformat()
    else:
        created = datetime.now(timezone.utc).isoformat()
    row = {
        "evaluation_id": result.evaluation_id,
        "created_at": created,
        "status": result.status,
        "panel_size": len(result.personas.personas) if result.personas else 0,
        "question_ids": json.dumps(qids),
        "overall_mean": scores.overall_mean,
        "valid_responses": scores.valid_responses,
        "missing_responses": scores.missing_responses,
        "model": result.trace.model,
        "thumb_uri": thumb_uri,
        "summary": summarize_result(result),
        "result_json": json.dumps(result.model_dump(mode="json")),
    }
    conn = connect(path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runs (evaluation_id, created_at, status, panel_size,"
            " question_ids, overall_mean, valid_responses, missing_responses, model,"
            " thumb_uri, summary, result_json) VALUES (:evaluation_id, :created_at, :status,"
            " :panel_size, :question_ids, :overall_mean, :valid_responses,"
            " :missing_responses, :model, :thumb_uri, :summary, :result_json)", row)
        conn.commit()
    finally:
        conn.close()
    return result.evaluation_id


def record(result: EvaluationResult, thumb_uri: Optional[str] = None) -> Optional[str]:
    """Best-effort save. Storage failures warn and return None — never break a run."""
    try:
        return save_run(result, thumb_uri=thumb_uri)
    except Exception as e:
        logger.warning("run record failed: %s", type(e).__name__)
        return None


def get_run(evaluation_id: str, path: Optional[Path] = None) -> dict[str, Any]:
    """Full row with parsed `result` dict. Raises RunRecordError when missing/corrupt."""
    conn = connect(path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE evaluation_id = ?",
                           (evaluation_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RunRecordError(f"unknown evaluation id: {evaluation_id}")
    out = dict(row)
    try:
        out["result"] = json.loads(out["result_json"])
        out["question_ids"] = json.loads(out["question_ids"])
    except (ValueError, TypeError) as e:
        raise RunRecordError(f"corrupt stored run {evaluation_id}: {e}") from e
    return out


def list_runs(limit: int = 50, offset: int = 0,
              path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Newest-first metadata rows (no result JSON / thumbnails)."""
    conn = connect(path)
    try:
        rows = conn.execute(
            f"SELECT {_LIST_COLS} FROM runs ORDER BY created_at DESC, rowid DESC"
            " LIMIT ? OFFSET ?",
            (max(1, limit), max(0, offset))).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["question_ids"] = json.loads(d["question_ids"])
        except (ValueError, TypeError):
            d["question_ids"] = []
        out.append(d)
    return out
