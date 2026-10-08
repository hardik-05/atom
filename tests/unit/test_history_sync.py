"""Planning, parallel fetching and job de-duplication for the history sync."""

from __future__ import annotations

import threading
from datetime import date, timedelta

from atom.domain.errors import AuthError, TransientError
from atom.orchestration import history
from atom.orchestration.jobs import JobRunner

END = date(2026, 10, 8)
WANTED = END - timedelta(days=389)  # 390 days inclusive


def plan(**kw: date | None) -> list[history.Range]:
    base: dict[str, date | None] = {
        "first_bar": None,
        "last_bar": None,
        "requested_from": None,
        "synced_through": None,
    }
    base.update(kw)
    return history.plan_ranges(wanted_from=WANTED, end=END, **base)  # type: ignore[arg-type]


def test_an_unseen_instrument_fetches_the_whole_window() -> None:
    assert plan() == [(WANTED, END)]


def test_388_days_held_fetches_only_the_last_two() -> None:
    last = END - timedelta(days=2)
    assert plan(first_bar=WANTED, last_bar=last) == [(END - timedelta(days=1), END)]


def test_a_fully_current_instrument_fetches_nothing() -> None:
    assert plan(first_bar=WANTED, last_bar=END) == []


def test_a_longer_window_fetches_only_the_missing_head() -> None:
    first = WANTED + timedelta(days=100)
    assert plan(first_bar=first, last_bar=END) == [(WANTED, first - timedelta(days=1))]


def test_a_head_and_a_tail_are_two_ranges() -> None:
    first, last = WANTED + timedelta(days=50), END - timedelta(days=3)
    assert plan(first_bar=first, last_bar=last) == [
        (WANTED, first - timedelta(days=1)),
        (last + timedelta(days=1), END),
    ]


def test_a_recent_listing_is_not_asked_about_again() -> None:
    """Listed last month: the broker has nothing before, and a recorded request
    says it was already asked."""
    listed = END - timedelta(days=30)
    assert plan(first_bar=listed, last_bar=END, requested_from=WANTED, synced_through=END) == []


def test_a_weekend_is_not_refetched_once_synced_through() -> None:
    friday = END - timedelta(days=2)
    assert plan(first_bar=WANTED, last_bar=friday, requested_from=WANTED, synced_through=END) == []


def test_state_without_bars_still_skips_what_was_asked() -> None:
    assert plan(requested_from=WANTED, synced_through=END) == []


def task(n: int, ranges: list[history.Range] | None = None) -> history.Task:
    return history.Task(n, f"S{n}", str(n), ranges or [(WANTED, END)])


def test_fetch_runs_in_parallel_and_collects_every_result() -> None:
    barrier = threading.Barrier(4, timeout=5)

    def fetch(token: str, start: date, stop: date) -> list:
        barrier.wait()  # four calls must be in flight at once, or this times out
        return []

    out = history.fetch_all(fetch, [task(n) for n in range(4)], workers=4)
    assert len(out) == 4 and all(o.error is None for o in out)


def test_one_failure_does_not_stop_the_others() -> None:
    def fetch(token: str, start: date, stop: date) -> list:
        if token == "1":
            raise TransientError("boom", broker="UPSTOX")
        return []

    out = {o.task.instrument_id: o for o in history.fetch_all(fetch, [task(n) for n in range(3)])}
    assert out[1].error and out[0].error is None and out[2].error is None


def test_an_auth_failure_stops_new_work() -> None:
    def fetch(token: str, start: date, stop: date) -> list:
        raise AuthError("expired", broker="UPSTOX")

    out = history.fetch_all(fetch, [task(n) for n in range(20)], workers=1)
    assert any(o.auth_failed for o in out)
    assert sum(o.skipped for o in out) == 19


def test_a_keyed_job_is_not_queued_twice_while_unfinished() -> None:
    runner = JobRunner()
    release = threading.Event()
    try:
        first = runner.submit("history_sync", lambda j: release.wait(5) and {}, key="history:1")
        second = runner.submit("history_sync", lambda j: {}, key="history:1")
        other = runner.submit("history_sync", lambda j: {}, key="history:2")
        assert second is first and other is not first
    finally:
        release.set()
        runner.shutdown()
