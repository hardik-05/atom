"""Dhan's capability profile.

Researched in [`docs/03-brokers/adapters/DHAN-ADAPTER.md`]. Dhan is the strongest
of the five for reconciliation — itemised per-trade charges, a real ledger with a
running balance, and lookup by ATOM's own reference — and the weakest for
infrastructure, because it locks the whitelisted IP for seven days.

Built first for exactly that reason (MODULE-MAP build order): the adapter with
the most complete data surface proves the canonical models before a broker that
supplies less forces guesses about what "missing" means.
"""

from __future__ import annotations

from atom.domain.enums import SellAuthScope, StaticIpScope, TokenProbe
from atom.domain.models import BrokerCapabilities

DHAN = BrokerCapabilities(
    broker_code="DHAN",
    # GTT — Dhan calls it a "Forever Order".
    supports_gtt=True,
    gtt_carries_client_ref=True,  # correlationId survives onto the GTT
    gtt_max_validity_days=None,  # not stated anywhere in the docs (Q-301)
    # Orders
    client_ref_field="correlationId",
    client_ref_max_len=30,  # Dhan allows 30; the canonical generator caps at 20
    client_ref_is_idempotent=False,  # a duplicate is accepted, not rejected (Q-302)
    lookup_by_client_ref=True,  # GET /v2/orders/external/{correlation-id}
    # Data
    provides_trade_charges=True,  # per trade, itemised — the only broker that does
    provides_charge_preview=False,
    provides_ledger=True,  # with runbal, so a balance can be reconstructed
    provides_free_quantity=True,  # availableQty, direct
    # Infrastructure
    requires_static_ip=True,
    static_ip_scope=StaticIpScope.ORDERS_ONLY,
    static_ip_lock_days=7,
    token_probe_endpoint=TokenProbe.PROFILE,  # GET /v2/profile returns tokenValidity
    token_revocable=False,  # no documented revoke
    sell_authorisation_scope=SellAuthScope.NONE,  # DDPI reported, not enforced (Q-303)
    # Limits
    orders_per_second=10,
    quote_batch_size=None,  # the quote API is capped at one request per second
)
"""Two findings here change how the engine behaves, not just what it logs.

``static_ip_scope = ORDERS_ONLY`` means a token probes green from the wrong
address and the first *order* still fails, with no IP-specific error code to
recognise it by. That is why egress verification is a pre-flight gate of its own
rather than a side effect of the token check — see
``BrokerCapabilities.egress_needs_separate_check``.

``static_ip_lock_days = 7`` means changing the whitelisted IP costs a week. The
Elastic IP in the Terraform is not a convenience; with Dhan it is the only way the
account stays usable after an instance replacement.

``client_ref_is_idempotent = False`` with ``lookup_by_client_ref = True`` is an
unusual pair, and a useful one: a blind retry is unsafe, but after a timeout ATOM
can *ask* whether the order exists rather than guess. That is the difference
between an ambiguous send and a recoverable one (D-180).
"""
