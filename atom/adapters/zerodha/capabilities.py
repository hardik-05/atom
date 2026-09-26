"""Zerodha's capability profile.

Researched in [`docs/03-brokers/adapters/ZERODHA-ADAPTER.md`]. Zerodha is the only
broker that will price an imaginary order, and the only one whose sell
authorisation is per session rather than per instruction.
"""

from __future__ import annotations

from atom.domain.enums import SellAuthScope, StaticIpScope, TokenProbe
from atom.domain.models import BrokerCapabilities

ZERODHA = BrokerCapabilities(
    broker_code="ZERODHA",
    # GTT
    supports_gtt=True,
    gtt_carries_client_ref=False,  # no tag field on a GTT — identification is DB-only
    gtt_max_validity_days=None,  # the broker returns expires_at; about a year observed
    # Orders
    client_ref_field="tag",
    client_ref_max_len=20,  # alphanumeric; this is the ceiling the canonical ref respects
    client_ref_is_idempotent=False,  # `guid` exists but is undocumented for this use
    lookup_by_client_ref=False,  # the order book must be scanned
    # Data
    provides_trade_charges=True,  # POST /charges/orders
    provides_charge_preview=True,  # the same endpoint prices an imaginary order
    provides_ledger=False,  # console reports only, no API
    provides_free_quantity=True,  # derived, not a field
    # Infrastructure
    requires_static_ip=True,
    static_ip_scope=StaticIpScope.ALL_CALLS,  # procedure undocumented (Q-274); assume strictest
    static_ip_lock_days=0,  # unknown; assume none
    token_probe_endpoint=TokenProbe.PROFILE,  # GET /user/profile
    token_revocable=True,  # DELETE /session/token
    sell_authorisation_scope=SellAuthScope.PER_SESSION,
    # Limits
    orders_per_second=10,
    quote_batch_size=500,
)
"""``gtt_carries_client_ref = False`` is the finding with teeth.

An active Zerodha GTT carries no ATOM identifier at all, so the run cannot tell
its own resting sells from ones the operator placed by hand. D-063 requires
cancelling every ATOM GTT at the head of a run and halting on a survivor — which
is only possible because ATOM records each GTT's broker order ID when it places
it. The database is the only link, so losing that row loses the ability to
distinguish, and an unrecognised resting sell is reported and never cancelled.

``provides_charge_preview = True`` is the opposite kind of finding: a capability
no other broker offers. `POST /charges/orders` accepts any order_id — "it can be
any random string" — so it prices orders that do not exist. The execution list
can therefore show Zerodha's own numbers before the operator releases anything,
and the same endpoint called with the achieved price gives the actual. Estimated
against actual, from one source, without waiting for a statement (D-024).

``sell_authorisation_scope = PER_SESSION`` costs one authorisation per day rather
than one per sell instruction, which is Upstox's ``ONE_TIME``. Cheaper, and it
means the authorisation belongs in the morning token flow rather than in the sell
path.
"""
