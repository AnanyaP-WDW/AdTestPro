"""One active evaluation at a time, live progress, and the resume path."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core import active as active_mod
from app.core import runs as runs_mod
from app.main import app
from app.routers import pages as pages_mod
from tests.fake_client import FakeClient
from tests.test_api import FORM, _files
from tests.test_pipeline import full_fake, make_png
from tests.test_runs import _result

ACTIVE = active_mod.ACTIVE


def _claim(eid="eval-active", **kwargs):
    assert ACTIVE.claim(eid, **kwargs)
    return eid


def _wait_for_active(timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        run = ACTIVE.current()
        if run is not None:
            return run
        time.sleep(0.02)
    return None


# ---------------------------------------------------------------- registry

def test_registry_allows_one_run_and_keeps_percent_monotonic():
    assert ACTIVE.claim("eval-a", panel_size=4)
    assert not ACTIVE.claim("eval-b")
    run = ACTIVE.current()
    assert run is not None and run.evaluation_id == "eval-a"

    ACTIVE.update("PERSONAS_READY", 0, 4)
    starts = run.percent()
    ACTIVE.update("EXTRACTION_READY", 2, 4)
    middle = run.percent()
    ACTIVE.update("EXTRACTION_READY", 4, 4)
    answered = run.percent()
    ACTIVE.update("REVIEWED", 4, 4)
    final = run.percent()
    assert starts <= middle <= answered <= final <= 99

    ACTIVE.finish("someone-else")  # only the owning id releases the slot
    assert ACTIVE.current() is not None
    ACTIVE.finish("eval-a")
    assert ACTIVE.current() is None


def test_stale_run_is_forgotten(monkeypatch):
    _claim("eval-stale")
    ACTIVE.current().started_at = time.monotonic() - 10_000
    assert ACTIVE.current() is None


# ---------------------------------------------------------------- live view

def test_root_redirects_to_the_live_run_and_status_tracks_progress():
    eid = _claim("eval-live", kind="banner", panel_size=12)
    run = ACTIVE.current()
    run.stage = "EXTRACTION_READY"
    run.personas_done, run.personas_total = 3, 12

    c = TestClient(app)
    root = c.get("/", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == f"/runs/{eid}/live"

    page = c.get(f"/runs/{eid}/live")
    assert page.status_code == 200
    assert "Asking the panel" in page.text
    assert "3 of 12 personas answered" in page.text
    assert 'value="' in page.text and "<progress" in page.text

    status = c.get(f"/runs/{eid}/status").json()
    assert status["state"] == "running"
    assert status["panel_size"] == 12
    assert 35 <= status["percent"] <= 82
    assert status["redirect_url"] == f"/runs/{eid}"


def test_finished_run_sends_the_live_page_to_the_report():
    eid = _claim("eval-done")
    runs_mod.save_run(_result(eid))
    ACTIVE.finish(eid)

    c = TestClient(app)
    live = c.get(f"/runs/{eid}/live", follow_redirects=False)
    assert live.status_code == 303 and live.headers["location"] == f"/runs/{eid}"
    assert c.get(f"/runs/{eid}/status").json()["state"] == "done"
    assert c.get(f"/runs/{eid}").status_code == 200


def test_unknown_run_is_reported_not_invented():
    c = TestClient(app)
    assert c.get("/runs/eval-nope/status").json()["state"] == "unknown"
    assert c.get("/runs/eval-nope/live").status_code == 404


def test_runs_page_points_at_the_active_run():
    eid = _claim("eval-banner")
    page = TestClient(app).get("/runs")
    assert page.status_code == 200
    assert "Evaluation in progress" in page.text
    assert f"/runs/{eid}/live" in page.text


# ---------------------------------------------------------------- busy

def test_second_browser_run_redirects_to_the_live_one():
    eid = _claim("eval-busy")
    r = TestClient(app).post(
        "/evaluate", data={**FORM, "question_ids": "clarity"}, files=_files(),
        follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/runs/{eid}/live?busy=1"
    assert ACTIVE.current().evaluation_id == eid


def test_api_rejects_a_second_run_with_the_active_id():
    eid = _claim("eval-busy")
    r = TestClient(app).post("/api/evaluations", data=FORM, files=_files())
    assert r.status_code == 409
    body = r.json()
    assert body["evaluation_id"] == eid
    assert body["status_url"] == f"/runs/{eid}/status"


# ---------------------------------------------------------------- real run

def test_live_view_sees_a_real_run_then_the_report():
    base = full_fake(question_ids=("clarity",))

    async def slow(kw):
        if "respondent profiles" in kw["messages"][0]["content"]:
            await asyncio.sleep(0.3)  # keep the run in flight while we poll
        return base.handler(kw)

    app.state.llm_client = FakeClient(handler=slow)
    worker = TestClient(app)
    viewer = TestClient(app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.post, "/evaluate", data={
                **FORM, "question_ids": "clarity", "persona_count": "2"},
                files=_files(make_png()))
            run = _wait_for_active()
            assert run is not None
            eid = run.evaluation_id

            assert viewer.get("/", follow_redirects=False).status_code == 303
            assert viewer.get(f"/runs/{eid}/status").json()["state"] == "running"
            assert viewer.get(f"/runs/{eid}/live").status_code == 200

            response = future.result(timeout=30)
        assert response.status_code == 200
        assert viewer.get(f"/runs/{eid}/status").json()["state"] == "done"
        assert viewer.get(f"/runs/{eid}").status_code == 200
        assert ACTIVE.current() is None
    finally:
        app.state.llm_client = None


def test_failed_run_releases_the_slot(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(pages_mod, "run_pipeline", boom)
    r = TestClient(app).post("/evaluate", data={**FORM, "question_ids": "clarity"},
                             files=_files())
    assert r.status_code == 502
    assert ACTIVE.current() is None
