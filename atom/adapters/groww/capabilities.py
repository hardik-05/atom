"""Groww's capability profile.

Researched in [`docs/03-brokers/adapters/GROWW-ADAPTER.md`]. Groww is the only
broker whose client reference is genuinely idempotent, and the only one that
reports free quantity as a field rather than a derivation.
"""

from __future__ import annotations

from atom.domain.enums import SellAuthScope, StaticIpScope, TokenProbe
from atom.domain.models import BrokerCapabilities

GROWW = BrokerCapabilities(
    broker_code="GROWW",
    # GTT
    supports_gtt=True,
    gtt_carries_client_ref=True,  # reference_id
    gtt_max_validity_days=365,  # forced by Groww, not a choice ATOM makes
    # Orders
    client_ref_field="order_reference_id",
    client_ref_max_len=20,  # 8-20 alphanumeric, at most two hyphens — the tightest of the five
    client_ref_is_idempotent=True,  # a duplicate returns GA007 rather than a second order
    lookup_by_client_ref=True,  # GET /v1/order/status/reference/{id}
    # Data
    provides_trade_charges=False,  # an aggregate only, with no per-component breakdown
    provides_charge_preview=True,  # also aggregate only
    provides_ledger=False,
    provides_free_quantity=True,  # demat_free_quantity, direct
    # Infrastructure
    requires_static_ip=True,  # procedure undocumented (Q-274)
    static_ip_scope=StaticIpScope.ALL_CALLS,  # assumed strictest until confirmed
    static_ip_lock_days=0,
    token_probe_endpoint=TokenProbe.HOLDINGS,  # there is no profile endpoint
    token_revocable=True,  # through the web console, not the API
    sell_authorisation_scope=SellAuthScope.NONE,  # not documented either way (Q-291)
    # Limits
    orders_per_second=10,
    quote_batch_size=None,  # not documented
)
"""Groww fixed the shape of `client_ref` for all five brokers.

Its 8-20 alphanumeric, at-most-two-hyphens rule is the floor; Zerodha's 20
characters is the ceiling. Together they leave exactly one format that satisfies
everyone, which is why `atom.adapters.client_ref` generates that one format
rather than one per broker (D-175). A reference that works everywhere means the
same string identifies an order in the database and at whichever broker it went
to.

``client_ref_is_idempotent = True`` makes Groww the one broker where a blind
retry after a timeout is safe: the duplicate is refused with GA007, which
``DuplicateRefError`` deliberately treats as *success, already placed* rather
than as a failure. Everywhere else a timeout has to be resolved by looking.

``provides_trade_charges = False`` alongside ``provides_charge_preview = True``
is the mirror image of Upstox: Groww gives attribution without components, Upstox
components without attribution. Neither alone supports a per-fill contrast, so
for both the charges view shows a dash rather than a zero.
"""
