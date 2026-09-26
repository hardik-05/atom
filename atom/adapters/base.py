"""The adapter contract.

An adapter is a **pure translator plus an HTTP client**. It holds no strategy
logic, makes no trading decision, and writes nothing to the database — it returns
canonical objects and the engine persists them. That separation is what lets an
adapter be tested against recorded vendor fixtures with neither network nor
database.

Seventeen required methods. ``modify_order`` and ``modify_gtt`` are deliberately
absent: ATOM cancels and re-places (D-063), and an unused method is a liability
that invites someone to use it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from atom.domain.models import (
    AccountRef,
    AuthorisationRequest,
    BrokerCapabilities,
    CanonicalCashEvent,
    CanonicalCharges,
    CanonicalFill,
    CanonicalHolding,
    CanonicalInstrument,
    CanonicalQuote,
    GttIntent,
    GttState,
    OrderIntent,
    OrderState,
    Token,
    TokenProbeResult,
)


@runtime_checkable
class BrokerAdapter(Protocol):
    """What every broker adapter must provide."""

    capabilities: BrokerCapabilities

    # ------------------------------------------------------------ session
    def build_auth_url(self, account: AccountRef) -> str | None:
        """The URL the operator visits to authenticate, or ``None`` if paste-only."""
        ...

    def exchange_code(self, account: AccountRef, code: str) -> Token:
        """Exchange an authorisation code for a token, and store it in SSM."""
        ...

    def probe_token(self, account: AccountRef) -> TokenProbeResult:
        """Test whether the token works. Never computed from a documented lifetime."""
        ...

    def revoke_token(self, account: AccountRef) -> None:
        """Actively invalidate the session. A no-op where the broker offers none."""
        ...

    # ------------------------------------------------------- reference data
    def fetch_instruments(self) -> Iterable[CanonicalInstrument]:
        """The broker's instrument master. Public and token-free on three of five."""
        ...

    # --------------------------------------------------------------- reads
    def fetch_holdings(self, account: AccountRef) -> list[CanonicalHolding]: ...

    def fetch_positions(self, account: AccountRef) -> list[CanonicalHolding]: ...

    def fetch_quotes(
        self, account: AccountRef, broker_tokens: Sequence[str]
    ) -> list[CanonicalQuote]:
        """Batched. Never one call per instrument — three brokers cap quotes at ~1/sec."""
        ...

    def fetch_orders(self, account: AccountRef) -> list[OrderState]: ...

    def fetch_fills(self, account: AccountRef, since: date) -> list[CanonicalFill]: ...

    def fetch_charges(
        self, account: AccountRef, broker_order_ids: Sequence[str]
    ) -> dict[str, CanonicalCharges]:
        """Reported charges keyed by broker order id. Empty where unsupported."""
        ...

    def fetch_ledger(
        self, account: AccountRef, from_date: date, to_date: date
    ) -> list[CanonicalCashEvent]:
        """Cash movements. Only Dhan provides a real ledger."""
        ...

    # -------------------------------------------------------------- writes
    def place_order(self, account: AccountRef, intent: OrderIntent) -> OrderState: ...

    def cancel_order(self, account: AccountRef, broker_order_id: str) -> OrderState: ...

    def place_gtt(self, account: AccountRef, intent: GttIntent) -> GttState: ...

    def cancel_gtt(self, account: AccountRef, broker_gtt_id: str) -> GttState: ...

    def fetch_gtts(self, account: AccountRef) -> list[GttState]: ...

    # ------------------------------------------- optional, per capabilities
    def preview_charges(
        self, account: AccountRef, intents: Sequence[OrderIntent]
    ) -> dict[str, CanonicalCharges]:
        """Pre-trade charge estimate from the broker's own calculator.

        Only where ``capabilities.provides_charge_preview`` — Zerodha prices
        imaginary orders, which also gives dry-run real charge figures (D-186).
        """
        ...

    def initiate_sell_authorisation(
        self, account: AccountRef, isins: Sequence[str]
    ) -> AuthorisationRequest:
        """Begin a depository authorisation, where the broker exposes an API for it."""
        ...


class UnsupportedOperationError(NotImplementedError):
    """Raised when a method is called that the broker's capabilities exclude.

    Preferred over silently returning nothing: a caller that ignored the
    capability profile has a bug, and it should surface at the call site.
    """

    def __init__(self, broker_code: str, operation: str) -> None:
        super().__init__(f"{broker_code} does not support {operation}")
        self.broker_code = broker_code
        self.operation = operation
