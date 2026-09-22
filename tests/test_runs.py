"""R1 exit criteria: sqlite round-trip, revalidation, no key leaks, corrupt rows."""

import json
import os
import sqlite3

import pytest

from app.core.models import EvaluationResult, EvaluationTrace, ScoreSummary
from app.core.runs import RunRecordError, get_run, list_runs, save_run, summarize_result


def _result(eid="eval-1", status="complete", mean=4.25):
    from app.core.models import QuestionScore
    return EvaluationResult(
        evaluation_id=eid, status=status,
        scores=ScoreSummary(
            per_question=[QuestionScore(question_id="clarity", count=12, mean=mean,
                                        median=4.0, stdev=0.5,
                                        distribution={1: 0, 2: 0, 3: 1, 4: 7, 5: 4})],
            overall_mean=mean, valid_responses=12, missing_responses=0),
        trace=EvaluationTrace(evaluation_id=eid, model="m1"),
    )


def test_save_get_list_round_trip(tmp_path):
    db = tmp_path / "t.db"
    save_run(_result("e1"), thumb_uri="data:image/jpeg;base64,AAA", path=db)
    save_run(_result("e2", status="persona_invalid", mean=None), path=db)
    got = get_run("e1", path=db)
    assert got["status"] == "complete" and got["panel_size"] == 0
    assert got["overall_mean"] == 4.25 and got["thumb_uri"].startswith("data:image")
    assert got["result"]["evaluation_id"] == "e1"
    # stored payload revalidates against the live schema
    assert EvaluationResult.model_validate(got["result"]).evaluation_id == "e1"
    rows = list_runs(path=db)
    assert [r["evaluation_id"] for r in rows] == ["e2", "e1"]  # newest first
    assert "result_json" not in rows[0] and "thumb_uri" not in rows[0]
    assert rows[0]["question_ids"] == ["clarity"]


def test_get_unknown_and_corrupt_rows_raise_typed(tmp_path):
    db = tmp_path / "t.db"
    save_run(_result("e1"), path=db)
    with pytest.raises(RunRecordError):
        get_run("nope", path=db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE runs SET result_json='{' WHERE evaluation_id='e1'")
    conn.commit()
    conn.close()
    with pytest.raises(RunRecordError):
        get_run("e1", path=db)


def test_stored_payload_never_carries_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-v1-CANARYKEY999")
    db = tmp_path / "t.db"
    save_run(_result("e1"), path=db)
    raw = sqlite3.connect(db).execute(
        "SELECT result_json FROM runs").fetchone()[0]
    assert "CANARYKEY999" not in raw
    assert os.getenv("OPENAI_API_KEY") not in raw


def test_connect_reads_legacy_db_location(tmp_path, monkeypatch):
    from app.core import runs as r

    legacy = tmp_path / "data" / r.DB_FILENAME
    legacy.parent.mkdir()
    r.save_run(_result("e1"), path=legacy)
    monkeypatch.setattr(r, "default_path", lambda: tmp_path / "new.db")
    monkeypatch.setattr(r, "_legacy_path", lambda: legacy)
    assert r.get_run("e1")["status"] == "complete"


def test_save_is_idempotent_per_evaluation_id(tmp_path):
    db = tmp_path / "t.db"
    save_run(_result("e1", mean=4.0), path=db)
    save_run(_result("e1", mean=3.0), path=db)
    assert get_run("e1", path=db)["overall_mean"] == 3.0
    assert len(list_runs(path=db)) == 1


def test_summary_covers_complete_and_failed_runs():
    s = summarize_result(_result("e1"))
    assert "4.25" in s and "clarity" in s and "themes" in s
    assert len(s) <= 200
    failed = _result("e2", status="persona_invalid", mean=None)
    failed.trace.warnings.append("persona_invalid: bad brief")
    assert summarize_result(failed).startswith("persona_invalid:")


def test_summary_stored_and_listed(tmp_path):
    db = tmp_path / "t.db"
    save_run(_result("e1"), path=db)
    rows = list_runs(path=db)
    assert rows[0]["summary"] and "4.25" in rows[0]["summary"]


def test_migration_adds_summary_to_legacy_db(tmp_path):
    from app.core import runs as runs_mod

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE runs (evaluation_id TEXT PRIMARY KEY,"
                 " created_at TEXT NOT NULL, status TEXT NOT NULL,"
                 " panel_size INTEGER NOT NULL, question_ids TEXT NOT NULL,"
                 " overall_mean REAL, valid_responses INTEGER NOT NULL,"
                 " missing_responses INTEGER NOT NULL, model TEXT NOT NULL,"
                 " thumb_uri TEXT, result_json TEXT NOT NULL)")
    conn.execute("INSERT INTO runs VALUES ('old', '2026-01-01', 'complete', 12,"
                 " '[]', 4.0, 12, 0, 'm', NULL, '{}')")
    conn.commit()
    conn.close()
    rows = runs_mod.list_runs(path=db)  # must not raise; legacy rows show no summary
    assert len(rows) == 1 and rows[0]["summary"] is None


def test_responses_carry_model_labels(monkeypatch):
    import asyncio
    from app.core.pipeline import run_pipeline
    from tests.test_pipeline import BRIEF, make_png, full_fake

    monkeypatch.delenv("ADTESTPRO_MODEL", raising=False)  # isolate from ambient .env
    monkeypatch.delenv("ADTESTPRO_MODELS", raising=False)  # isolate from ambient .env

    async def main():
        return await run_pipeline(
            brief_data=BRIEF, image=make_png(), filename="a.png",
            content_type="image/png", question_ids=["clarity"],
            client=full_fake())

    res = asyncio.run(main())
    assert res.status == "complete"
    assert res.responses and all(r.model == "injected-fake" for r in res.responses)
