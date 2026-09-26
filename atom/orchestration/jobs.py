"""A small in-process job runner for work that outlives an HTTP request.

Syncing a year of daily bars for 300 instruments is a few hundred broker calls;
the console starts it, gets a job id back immediately, and polls. One worker
thread, deliberately: two syncs in parallel would share the broker's rate limit
and the database pool for no gain, and a queue is easier to reason about than
contention.

State is in memory. A restart loses the job LIST, not the work — every job
writes its results to the database as it goes, and re-running one is safe.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atom.infra.clock import now_utc


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "QUEUED"  # QUEUED | RUNNING | DONE | FAILED
    progress: int = 0
    total: int = 0
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime = field(default_factory=now_utc)
    finished_at: datetime | None = None

    def update(
        self, *, progress: int | None = None, total: int | None = None, message: str | None = None
    ) -> None:
        if progress is not None:
            self.progress = progress
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message


class JobRunner:
    def __init__(self, max_kept: int = 50) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atom-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_kept = max_kept

    def submit(self, kind: str, fn: Callable[[Job], dict[str, Any]]) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.job_id] = job
            self._trim()

        def run() -> None:
            job.status = "RUNNING"
            try:
                job.result = fn(job) or {}
                job.status = "DONE"
            except Exception as exc:
                job.status = "FAILED"
                job.error = f"{type(exc).__name__}: {exc}"
                job.result = {"trace": traceback.format_exc(limit=5)}
            finally:
                job.finished_at = now_utc()

        self._executor.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def _trim(self) -> None:
        if len(self._jobs) <= self._max_kept:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("DONE", "FAILED")),
            key=lambda j: j.created_at,
        )
        for job in finished[: len(self._jobs) - self._max_kept]:
            self._jobs.pop(job.job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
