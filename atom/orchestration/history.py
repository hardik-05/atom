"""Daily-bar history sync: plan the gaps, fetch them in parallel, write in bulk.

Three costs made the old sync slow, and each has its own answer here:

* **Refetching what is held.** :func:`plan_ranges` asks the broker only for dates
  the data pool does not already cover — two days when 388 of 390 are present.
* **One request at a time.** The broker call is network-bound, so
  :func:`fetch_all` runs a bounded thread pool over one shared, rate-limited
  client. The limiter, not the pool, decides the pace; the pool only keeps it full.
* **One database round trip per bar.** The caller writes everything fetched in a
  few ``unnest`` statements (``market.upsert_candles_bulk``).

Today's bar is never requested: it is incomplete until the close, and the run
fetches its own price when it executes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from atom.domain.errors import AuthError
from atom.domain.models import CanonicalCandle

DEFAULT_WORKERS = 8
Range = tuple[date, date]


def plan_ranges(
    *,
    wanted_from: date,
    end: date,
    first_bar: date | None,
    last_bar: date | None,
    requested_from: date | None,
    synced_through: date | None,
) -> list[Range]:
    """The (from, to) spans, inclusive, that still need fetching.

    ``first_bar``/``last_bar`` are what the price table holds; ``requested_from``/
    ``synced_through`` are what earlier syncs already asked the broker for, which
    is what keeps an ETF listed after ``wanted_from`` (or a weekend with no bars)
    from being asked about again on every run.
    """
    ends = [d for d in (last_bar, synced_through) if d is not None]
    starts = [d for d in (first_bar, requested_from) if d is not None]
    if not ends and not starts:
        return [(wanted_from, end)] if wanted_from <= end else []

    out: list[Range] = []
    known_from = min(starts) if starts else None
    if known_from is not None and wanted_from < known_from:
        out.append((wanted_from, known_from - timedelta(days=1)))
    known_to = max(ends) if ends else None
    if known_to is None:
        known_to = known_from - timedelta(days=1) if known_from else wanted_from
    if known_to < end:
        out.append((known_to + timedelta(days=1), end))
    return [r for r in out if r[0] <= r[1]]


@dataclass(slots=True)
class Task:
    instrument_id: int
    symbol: str
    broker_token: str
    ranges: list[Range]


@dataclass(slots=True)
class Outcome:
    task: Task
    bars: list[CanonicalCandle] = field(default_factory=list)
    calls: int = 0
    error: str | None = None
    auth_failed: bool = False
    skipped: bool = False


def fetch_all(
    fetch: Callable[[str, date, date], list[CanonicalCandle]],
    tasks: list[Task],
    *,
    workers: int = DEFAULT_WORKERS,
    on_done: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    """Run every task's ranges through ``fetch``, ``workers`` at a time.

    A failure on one instrument is recorded against it and the rest carry on. An
    authentication failure is different: every later call would fail the same way,
    so it stops the pool from starting anything further.
    """
    stop = threading.Event()

    def run(task: Task) -> Outcome:
        out = Outcome(task)
        if stop.is_set():
            out.skipped = True
            return out
        try:
            for start, end in task.ranges:
                out.calls += 1
                out.bars.extend(fetch(task.broker_token, start, end))
        except AuthError as exc:
            stop.set()
            out.error, out.auth_failed = str(exc)[:200], True
        except Exception as exc:
            out.error = str(exc)[:200]
        return out

    outcomes: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="atom-hist") as pool:
        for future in as_completed([pool.submit(run, t) for t in tasks]):
            outcome = future.result()
            outcomes.append(outcome)
            if on_done is not None:
                on_done(outcome)
    return outcomes


def summary(outcomes: list[Outcome]) -> dict[str, Any]:
    return {
        "calls": sum(o.calls for o in outcomes),
        "bars": sum(len(o.bars) for o in outcomes if o.error is None),
    }
