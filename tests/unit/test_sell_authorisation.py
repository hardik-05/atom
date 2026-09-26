"""Whether the sell pass may run: the operator's record first, broker flags second."""

from __future__ import annotations

from atom.adapters.dhan.capabilities import DHAN
from atom.adapters.upstox.capabilities import UPSTOX
from atom.orchestration.runner import sell_authorisation_blocked


def test_recorded_ddpi_allows_sells_even_when_the_profile_says_nothing() -> None:
    """2026-09-26: every account has DDPI. The profile field was never observed."""
    assert sell_authorisation_blocked(UPSTOX, {}, "LIVE", "DDPI") is None
    assert sell_authorisation_blocked(UPSTOX, {}, "LIVE", "POA") is None


def test_recorded_edis_blocks_whatever_the_flags_say() -> None:
    reason = sell_authorisation_blocked(UPSTOX, {"ddpi": True}, "LIVE", "EDIS")
    assert reason is not None and "EDIS" in reason


def test_unknown_falls_back_to_the_broker_flags() -> None:
    assert sell_authorisation_blocked(UPSTOX, {"ddpi": True}, "LIVE", "UNKNOWN") is None
    assert sell_authorisation_blocked(UPSTOX, {}, "LIVE", "UNKNOWN") is not None


def test_dry_runs_and_brokers_without_the_requirement_are_never_blocked() -> None:
    assert sell_authorisation_blocked(UPSTOX, {}, "DRY", "UNKNOWN") is None
    assert sell_authorisation_blocked(DHAN, {}, "LIVE", "UNKNOWN") is None
