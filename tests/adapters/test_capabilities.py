"""The five capability profiles.

These tests do not re-assert every field — the profiles are research findings and
restating them here would just be a second copy to keep in sync. They assert the
things that would be *wrong* rather than merely different: internal contradictions,
and the handful of findings the engine's behaviour actually hangs on.
"""

from __future__ import annotations

from datetime import date

import pytest

from atom.adapters.client_ref import make_client_ref, validate_client_ref
from atom.adapters.dhan.capabilities import DHAN
from atom.adapters.groww.capabilities import GROWW
from atom.adapters.shoonya.capabilities import SHOONYA
from atom.adapters.upstox.capabilities import UPSTOX
from atom.adapters.zerodha.capabilities import ZERODHA
from atom.domain.enums import SellAuthScope, StaticIpScope
from atom.domain.models import BrokerCapabilities

ALL = [DHAN, ZERODHA, GROWW, UPSTOX, SHOONYA]


def test_every_broker_has_a_profile() -> None:
    assert {c.broker_code for c in ALL} == {"DHAN", "ZERODHA", "GROWW", "UPSTOX", "SHOONYA"}


@pytest.mark.parametrize("caps", ALL, ids=lambda c: c.broker_code)
def test_profile_is_internally_consistent(caps: BrokerCapabilities) -> None:
    # A broker with no GTT cannot put a reference on one.
    if not caps.supports_gtt:
        assert not caps.gtt_carries_client_ref
        assert caps.gtt_max_validity_days is None

    # Looking an order up by our own reference needs a field to put it in.
    if caps.lookup_by_client_ref or caps.client_ref_is_idempotent:
        assert caps.client_ref_field is not None

    # Every one of the five requires a static IP from 1 April 2026 (D-136).
    assert caps.requires_static_ip
    assert caps.static_ip_lock_days >= 0

    # ATOM places one order per second; a profile claiming less would break the run.
    assert caps.orders_per_second >= 1


@pytest.mark.parametrize("caps", ALL, ids=lambda c: c.broker_code)
def test_canonical_client_ref_fits_every_broker(caps: BrokerCapabilities) -> None:
    """D-175: one reference format, accepted everywhere.

    Groww sets the floor at 8 characters and Zerodha the ceiling at 20. If a
    generated reference did not fit one broker, the same order would need two
    identities and the database would stop being the link between them.
    """
    ref = make_client_ref(trade_date=date(2026, 9, 26), run_id=6, sequence=3)
    validate_client_ref(ref)
    assert len(ref) <= caps.client_ref_max_len


def test_only_dhan_needs_a_separate_egress_check() -> None:
    """D-173/Q-305: a token probe proves the IP everywhere except Dhan.

    Dhan whitelists writes only, so its token goes green from the wrong address
    and the first order fails with no IP-specific error. Every other broker gates
    all calls, so a successful probe already proves the egress path.
    """
    assert DHAN.egress_needs_separate_check
    assert DHAN.static_ip_scope is StaticIpScope.ORDERS_ONLY
    for caps in ALL:
        if caps is not DHAN:
            assert not caps.egress_needs_separate_check


def test_sell_authorisation_is_derived_not_duplicated() -> None:
    assert UPSTOX.requires_sell_authorisation  # eDIS, per instruction
    assert ZERODHA.requires_sell_authorisation  # per session
    assert UPSTOX.sell_authorisation_scope is SellAuthScope.ONE_TIME
    assert ZERODHA.sell_authorisation_scope is SellAuthScope.PER_SESSION
    for caps in (DHAN, GROWW, SHOONYA):
        assert not caps.requires_sell_authorisation


def test_groww_is_the_only_idempotent_broker() -> None:
    """Which decides where a blind retry is safe and where a lookup is required."""
    assert GROWW.client_ref_is_idempotent
    assert [c.broker_code for c in ALL if c.client_ref_is_idempotent] == ["GROWW"]


def test_only_dhan_and_zerodha_can_price_a_trade() -> None:
    """D-024's contrast is unavailable for three of the five, and shows a dash."""
    assert [c.broker_code for c in ALL if c.provides_trade_charges] == ["DHAN", "ZERODHA"]
    assert DHAN.provides_ledger
    assert [c.broker_code for c in ALL if c.provides_ledger] == ["DHAN"]


def test_shoonya_has_no_gtt_and_therefore_no_resting_protection() -> None:
    """Q-271: undocumented is treated as absent, and the cost is accepted openly."""
    assert not SHOONYA.supports_gtt
    assert [c.broker_code for c in ALL if not c.supports_gtt] == ["SHOONYA"]


def test_every_broker_reports_free_quantity_somehow() -> None:
    """Directly for Dhan and Groww, derived for the rest — the sell pass caps at it."""
    assert all(c.provides_free_quantity for c in ALL)


@pytest.mark.parametrize("caps", ALL, ids=lambda c: c.broker_code)
def test_profiles_are_frozen(caps: BrokerCapabilities) -> None:
    """A profile is a research finding, not run-time state."""
    with pytest.raises((AttributeError, TypeError)):
        caps.supports_gtt = True  # type: ignore[misc]
