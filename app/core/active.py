"""The one evaluation this process is allowed to run at a time (R2).

Process-local by design: the container runs a single uvicorn worker. A second
visitor is redirected to the live view instead of starting another run, and a
finished/abandoned run leaves nothing behind (TTL guard included).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Stage -> honest user-facing label. Keys are the pipeline's trace states.
STAGE_LABELS = {
    "RECEIVED": "Validating the brief",
    "VALIDATED": "Building the panel",
    "PERSONAS_READY": "Reading the creative",
    "EXTRACTION_READY": "Asking the panel",
    "RESPONSES_READY": "Scoring responses",
    "AGGREGATED": "Writing the report",  # synthesis runs after aggregation
    "REVIEWED": "Finishing up",
    "COMPLETE": "Finishing up",
}

# Coarse weights. The answered-persona band is the long one (the respond fan-out).
BASE_PERCENT = {
    "RECEIVED": 3, "VALIDATED": 10, "PERSONAS_READY": 25,
    "EXTRACTION_READY": 35, "RESPONSES_READY": 82,
    "AGGREGATED": 85, "REVIEWED": 95, "COMPLETE": 99,
}
PERSONAS_BAND = (35, 82)


def new_run_id() -> str:
    return f"eval-{uuid.uuid4().hex[:12]}"


def ttl_s() -> float:
    """A run older than its own budget plus slack is treated as gone."""
    try:
        return max(60.0, float(os.getenv("ADTESTPRO_PIPELINE_TIMEOUT_S", "300")) + 120)
    except ValueError:
        return 420.0


@dataclass
class ActiveRun:
    evaluation_id: str
    kind: str = "image"
    panel_size: int = 0
    questions: int = 0
    started_at: float = field(default_factory=time.monotonic)
    stage: str = "RECEIVED"
    personas_done: int = 0
    personas_total: int = 0
    _percent: int = 0

    def elapsed_s(self) -> int:
        return max(0, int(time.monotonic() - self.started_at))

    def percent(self) -> int:
        """Monotonic: a retried stage must never move the bar backwards."""
        if self.stage == "EXTRACTION_READY" and self.personas_total:
            lo, hi = PERSONAS_BAND
            frac = min(self.personas_done / self.personas_total, 1.0)
            target = lo + (hi - lo) * frac
        else:
            target = BASE_PERCENT.get(self.stage, 3)
        self._percent = max(self._percent, int(target))
        return min(self._percent, 99)

    def status(self) -> dict:
        return {
            "state": "running",
            "evaluation_id": self.evaluation_id,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, "Working"),
            "percent": self.percent(),
            "personas_done": self.personas_done,
            "personas_total": self.personas_total,
            "panel_size": self.panel_size,
            "elapsed_s": self.elapsed_s(),
            "redirect_url": f"/runs/{self.evaluation_id}",
        }


class ActiveRegistry:
    def __init__(self) -> None:
        self._run: Optional[ActiveRun] = None

    def claim(self, evaluation_id: str, *, kind: str = "image",
              panel_size: int = 0, questions: int = 0) -> bool:
        """Synchronous check-and-set: no awaits, so one event loop cannot race."""
        if self.current() is not None:  # expires a stale entry first
            return False
        self._run = ActiveRun(evaluation_id=evaluation_id, kind=kind,
                              panel_size=panel_size, questions=questions)
        return True

    def current(self) -> Optional[ActiveRun]:
        run = self._run
        if run is not None and run.elapsed_s() > ttl_s():
            self._run = None
            return None
        return run

    def update(self, stage: str, personas_done: int = 0, personas_total: int = 0) -> None:
        run = self._run
        if run is None:
            return
        if stage:
            run.stage = stage
        if personas_total:
            run.personas_done = personas_done
            run.personas_total = personas_total

    def finish(self, evaluation_id: Optional[str] = None) -> None:
        if evaluation_id is None or (self._run and self._run.evaluation_id == evaluation_id):
            self._run = None

    def reset(self) -> None:
        self._run = None


ACTIVE = ActiveRegistry()


def consume_task_error(task: "asyncio.Task") -> None:
    """Mark a detached task's exception as retrieved (the route already handled it)."""
    if not task.cancelled():
        task.exception()
