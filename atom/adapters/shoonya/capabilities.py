"""Shoonya's capability profile.

Researched in [`docs/03-brokers/adapters/SHOONYA-ADAPTER.md`]. Shoonya is the
weakest of the five and the profile says so plainly: no documented GTT, no
idempotency field of any kind, HTTP 200 on a rejected order, and documentation
that contradicts itself about how the token is transported (Q-310).
"""

from __future__ import annotations

from atom.domain.enums import SellAuthScope, StaticIpScope, TokenProbe
from atom.domain.models import BrokerCapabilities

SHOONYA = BrokerCapabilities(
    broker_code="SHOONYA",
    # GTT — undocumented, so treated as absent (Q-271)
    supports_gtt=False,
    gtt_carries_client_ref=False,
    gtt_max_validity_days=None,
    # Orders
    client_ref_field="remarks",  # free text; there is no client-order-id field
    client_ref_max_len=20,  # the canonical cap; Shoonya documents no limit
    client_ref_is_idempotent=False,
    lookup_by_client_ref=False,  # the order book must be scanned
    # Data
    provides_trade_charges=False,
    provides_charge_preview=False,
    provides_ledger=False,
    provides_free_quantity=True,  # derived from seven separate quantity fields
    # Infrastructure
    requires_static_ip=True,
    static_ip_scope=StaticIpScope.ALL_CALLS,  # gates login itself, so it fails early
    static_ip_lock_days=0,
    token_probe_endpoint=TokenProbe.HOLDINGS,  # there is no profile endpoint
    token_revocable=True,  # POST /Logout
    sell_authorisation_scope=SellAuthScope.NONE,  # POA-dependent; see npoadqty
    # Limits
    orders_per_second=10,
    quote_batch_size=None,  # roughly one request per second per instrument
)
"""``supports_gtt = False`` is a decision about unverified documentation, not a
statement that the feature is absent.

Shoonya may well support resting orders; nothing in its published API describes
one (Q-271). Treating an undocumented capability as present would mean building a
sell path on a guess, so the flag reads False and the engine falls back to
same-day limit sells (D-129/D-164). The cost is real and named: positions are
unprotected on days the engine does not run. That is the honest trade, and it
flips the moment the capability is confirmed rather than assumed.

Two quirks the adapter must absorb so nothing above it has to know:

**HTTP 200 on rejection.** The status code carries no information, so the
adapter reads the body's own status field and maps a rejection to
``RejectedError`` rather than trusting the transport. A layer that trusted the
200 would record a rejected order as placed and then wait for a fill that is
never coming.

**Token transport is self-contradictory** — the docs say a header in one place
and ``jKey`` in the request body in another, and disagree on the content type
(Q-310). Until that is resolved by observation, the client is written to one
documented form and the other is a one-line change, which is the only sane
posture toward documentation that disagrees with itself.

``static_ip_scope = ALL_CALLS`` is, unusually, a point in Shoonya's favour: the
IP gates login, so a wrong egress address fails immediately and unmistakably
instead of passing every read and failing the first order the way Dhan does.
"""
