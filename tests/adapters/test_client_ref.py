"""``client_ref`` must satisfy five brokers at once."""

from __future__ import annotations

from datetime import date

import pytest

from atom.adapters.client_ref import (
    MAX_LEN,
    MIN_LEN,
    ClientRefError,
    make_client_ref,
    truncate_for,
    validate_client_ref,
)


def test_fits_every_broker() -> None:
    ref = make_client_ref(trade_date=date(2026, 9, 26), run_id=8871, sequence=3)
    assert MIN_LEN <= len(ref) <= MAX_LEN  # Groww's floor, Zerodha's ceiling
    assert ref.isalnum()
    assert ref.count("-") <= 2


def test_is_deterministic() -> None:
    """A retry after a timeout must produce the SAME reference — that is what
    turns Groww's duplicate rejection into a recovery mechanism."""
    args = {"trade_date": date(2026, 9, 26), "run_id": 8871, "sequence": 3}
    assert make_client_ref(**args) == make_client_ref(**args)


def test_distinguishes_orders_within_a_run() -> None:
    a = make_client_ref(trade_date=date(2026, 9, 26), run_id=1, sequence=1)
    b = make_client_ref(trade_date=date(2026, 9, 26), run_id=1, sequence=2)
    assert a != b


def test_distinguishes_runs_and_days() -> None:
    day = date(2026, 9, 26)
    assert make_client_ref(trade_date=day, run_id=1, sequence=1) != make_client_ref(
        trade_date=day, run_id=2, sequence=1
    )
    assert make_client_ref(trade_date=day, run_id=1, sequence=1) != make_client_ref(
        trade_date=date(2026, 9, 27), run_id=1, sequence=1
    )


def test_survives_large_run_and_sequence_numbers() -> None:
    ref = make_client_ref(trade_date=date(2026, 9, 26), run_id=999_999, sequence=1000)
    validate_client_ref(ref)


@pytest.mark.parametrize(
    "bad",
    ["short", "a" * 21, "has space", "under_score", "a-b-c-d", "with/slash"],
)
def test_rejects_invalid(bad: str) -> None:
    with pytest.raises(ClientRefError):
        validate_client_ref(bad)


def test_truncation_keeps_the_tail() -> None:
    """The sequence number is the distinguishing part, so it must survive."""
    ref = make_client_ref(trade_date=date(2026, 9, 26), run_id=8871, sequence=3)
    assert truncate_for(ref, 10) == ref[-10:]
    assert truncate_for(ref, 30) == ref
