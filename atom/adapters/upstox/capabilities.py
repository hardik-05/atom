"""Upstox's capability profile.

Researched in [`docs/03-brokers/adapters/UPSTOX-ADAPTER.md`]. Upstox is the only
broker whose instrument key *is* the ISIN, and the only one that needs a fresh
demat authorisation for every sell instruction.
"""

from __future__ import annotations

from atom.domain.enums import SellAuthScope, StaticIpScope, TokenProbe
from atom.domain.models import BrokerCapabilities

UPSTOX = BrokerCapabilities(
    broker_code="UPSTOX",
    # GTT
    supports_gtt=True,
    gtt_carries_client_ref=False,  # no tag field on the GTT payload (Q-297)
    gtt_max_validity_days=365,
    # Orders
    client_ref_field="tag",  # regular orders only
    client_ref_max_len=20,  # the canonical ceiling; Upstox states no limit of its own
    client_ref_is_idempotent=False,
    lookup_by_client_ref=False,
    # Data
    provides_trade_charges=False,  # period totals, never per order
    provides_charge_preview=False,
    provides_ledger=False,
    provides_free_quantity=True,  # derived from the holdings payload
    # Infrastructure
    requires_static_ip=True,
    static_ip_scope=StaticIpScope.ALL_CALLS,
    static_ip_lock_days=0,
    token_probe_endpoint=TokenProbe.PROFILE,  # GET /v2/user/profile
    token_revocable=True,  # POST /v2/logout
    sell_authorisation_scope=SellAuthScope.ONE_TIME,  # eDIS, per instruction
    # Limits
    orders_per_second=10,
    quote_batch_size=500,
)
"""``sell_authorisation_scope = ONE_TIME`` is the expensive one.

eDIS authorisation is per instruction, so every sell needs the operator to
complete a redirect-and-paste round trip: ATOM produces an authorisation URL, the
operator logs in at Upstox with 2FA, and brings back the code. That is a person in
the sell path, which is why the console has a token screen and why Upstox sells
cannot be part of an unattended run.

``instrument_key`` being literally ``NSE_EQ|<ISIN>`` is worth knowing for a
different reason: it is the one broker identifier ATOM could reconstruct rather
than look up. It still looks it up, through ``broker_instrument`` like every
other broker, because a format that happens to be derivable today is not a
contract — and a single adapter that special-cases its own identifier resolution
is how the layer starts leaking broker knowledge upward (D-185).

Two documented pitfalls the adapter has to respect: a redirect URI ending in
`.php` may be blocked, and the tick size arrives in paise over JSON where the CSV
gives rupees. ATOM prices against its own `instrument.tick_size` and never a
broker's, so the second one cannot reach an order — but it is checked and warned
about, because a mismatch means the reference data is stale (Q-300).
"""
