"""The adapter contract.

An adapter is a **pure translator plus an HTTP client**. It holds no strategy
logic, makes no trading decision, and writes nothing to the database — it returns
canonical objects and the engine persists them. That separation is what lets an
adapter be tested against recorded vendor fixtures with neither network nor
database.

Twenty required methods. ``modify_order`` and ``modify_gtt`` are deliberately
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
    BrokerProfile,
    CanonicalCandle,
    CanonicalCashEvent,
    CanonicalCharges,
    CanonicalFill,
    CanonicalFunds,
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
class InstrumentResolver(Protocol):
    """Maps a broker's instrument identifier to ATOM's ``instrument_id`` and back.

    This is stage 4 of the inbound pipeline — *enrich* — and it is injected rather
    than done by the adapter, because resolving means reading (and, for an
    instrument seen for the first time, writing) ``instrument`` and
    ``broker_instrument``. An adapter never touches the database, so the engine
    hands it this object and owns what it does.
    """

    def instrument_id_for(self, broker_token: str) -> int | None:
        """``None`` when ATOM has never seen this instrument."""
        ...

    def broker_token_for(self, instrument_id: int) -> str:
        """The broker's key for an ATOM instrument. Raises if unmapped."""
        ...

    def register(self, instrument: CanonicalInstrument) -> int:
        """Record an instrument met for the first time — in a holding, say — and
        return its id. Resolution is by ISIN (D-187); a row without one is never
        matched on symbol alone."""
        ...


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

    def fetch_profile(self, account: AccountRef) -> BrokerProfile:
        """Whose token this is. Compared to the account before the token is kept."""
        ...

    # ------------------------------------------------------- reference data
    def fetch_instruments(self) -> Iterable[CanonicalInstrument]:
        """The broker's instrument master. Public and token-free on three of five."""
        ...

    # --------------------------------------------------------------- reads
    def fetch_holdings(self, account: AccountRef) -> list[CanonicalHolding]: ...

    def fetch_positions(self, account: AccountRef) -> list[CanonicalHolding]: ...

    def fetch_funds(self, account: AccountRef) -> CanonicalFunds:
        """Cash available for a delivery buy, as the broker reports it."""
        ...

    def fetch_daily_candles(
        self, account: AccountRef, broker_token: str, from_date: date, to_date: date
    ) -> list[CanonicalCandle]:
        """Daily bars, oldest first, inclusive of both ends.

        The deviation metric is computed from these closes, so a gap here is a gap
        in the strategy's view of the market — the caller records which days came
        back, and never interpolates a missing close.
        """
        ...

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
