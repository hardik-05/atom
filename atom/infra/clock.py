"""Time, in the two zones ATOM cares about.

Storage is UTC everywhere (D-073c). The *trading day* is Indian: a token, a run
and a one-lot-per-day cap all belong to an IST calendar date, and near midnight
UTC those are different days — 00:30 IST on the 27th is still the 26th in UTC.

IST is a fixed +05:30 offset rather than a zoneinfo lookup: India observes no
daylight saving, and ``zoneinfo`` on Windows needs the separate ``tzdata``
package, which would make a developer laptop and the server disagree about what
day it is for no gain at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    """The Indian trading date. Use this, never ``date.today()``."""
    return now_ist().date()


def ist_time(value: str) -> time:
    """Parse ``HH:MM`` as an IST wall-clock time."""
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes), tzinfo=IST)
