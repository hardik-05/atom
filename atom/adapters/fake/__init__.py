"""An in-memory adapter for testing every layer above the adapter boundary.

This is not a mock: it is a small, honest implementation of the whole contract
with deterministic behaviour. Strategy, orchestration and reporting are tested
against it, so those tests need neither a network nor a broker account.

It is deliberately *strict* — it enforces the same invariants a real broker would
(no market orders, positive quantities, unique client refs) so that a bug caught
here is a real bug and not an artefact of a permissive stub.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from atom.adapters.base import UnsupportedOperationError
from atom.domain.enums import (
    CashEventType,
    ChargeSource,
    GttStatus,
    OrderStatus,
    SellAuthScope,
    Side,
    StaticIpScope,
    TokenProbe,
)
from atom.domain.errors import (
    DuplicateRefError,
    InsufficientFundsError,
    ValidationError,
)
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
from atom.domain.money import ZERO, money

FAKE_CAPABILITIES = BrokerCapabilities(
    broker_code="FAKE",
    supports_gtt=True,
    gtt_carries_client_ref=True,
    gtt_max_validity_days=365,
    client_ref_field="client_ref",
    client_ref_max_len=20,
    client_ref_is_idempotent=True,
    lookup_by_client_ref=True,
    provides_trade_charges=True,
    provides_charge_preview=True,
    provides_ledger=True,
    provides_free_quantity=True,
    requires_static_ip=True,
    static_ip_scope=StaticIpScope.ALL_CALLS,
    token_probe_endpoint=TokenProbe.PROFILE,
    token_revocable=True,
    sell_authorisation_scope=SellAuthScope.NONE,
    orders_per_second=10,
    quote_batch_size=500,
)


@dataclass(slots=True)
class FakeBrokerState:
    """Everything the fake broker knows. Set it up, then assert against it."""

    holdings: dict[int, CanonicalHolding] = field(default_factory=dict)
    quotes: dict[int, Decimal] = field(default_factory=dict)
    instruments: list[CanonicalInstrument] = field(default_factory=list)
    ledger: list[CanonicalCashEvent] = field(default_factory=list)
    available_cash: Decimal = field(default_factory=lambda: money("1000000"))

    orders: dict[str, OrderState] = field(default_factory=dict)
    order_intents: dict[str, OrderIntent] = field(default_factory=dict)
    gtts: dict[str, GttState] = field(default_factory=dict)
    fills: list[CanonicalFill] = field(default_factory=list)

    candles: dict[int, list[CanonicalCandle]] = field(default_factory=dict)
    """Daily bars per instrument id, oldest first."""
    profile_client_id: str | None = None
    """The client id the fake profile reports. ``None`` echoes the account's own."""

    seen_refs: set[str] = field(default_factory=set)
    token_valid: bool = True
    fill_immediately: bool = True
    """When False, placed orders rest as PLACED so partial-fill paths can be driven."""


class FakeAdapter:
    """A complete, deterministic :class:`~atom.adapters.base.BrokerAdapter`."""

    capabilities = FAKE_CAPABILITIES

    def __init__(self, state: FakeBrokerState | None = None) -> None:
        self.state = state or FakeBrokerState()
        self._order_seq = itertools.count(1)
        self._gtt_seq = itertools.count(1)
        self._trade_seq = itertools.count(1)
        self.calls: list[str] = []
        """Call log, so tests can assert on ordering — e.g. that cancel precedes place."""

    # ------------------------------------------------------------ session
    def build_auth_url(self, account: AccountRef) -> str | None:
        self.calls.append("build_auth_url")
        return f"https://fake.broker/authorize?client_id={account.broker_client_id}"

    def exchange_code(self, account: AccountRef, code: str) -> Token:
        self.calls.append("exchange_code")
        if not code:
            raise ValidationError("empty authorisation code", broker="FAKE")
        return Token(
            secret_ref=f"/atom/sessions/{account.trading_account_id}/fake",
            obtained_at=datetime.now(UTC),
            broker_client_id=account.broker_client_id,
        )

    def probe_token(self, account: AccountRef) -> TokenProbeResult:
        self.calls.append("probe_token")
        return TokenProbeResult(
            ok=self.state.token_valid,
            probe_used=TokenProbe.PROFILE,
            detail="fake profile" if self.state.token_valid else "token rejected",
        )

    def revoke_token(self, account: AccountRef) -> None:
        self.calls.append("revoke_token")
        self.state.token_valid = False

    def fetch_profile(self, account: AccountRef) -> BrokerProfile:
        self.calls.append("fetch_profile")
        return BrokerProfile(
            broker_client_id=self.state.profile_client_id or account.broker_client_id,
            display_name="Fake Investor",
            is_active=self.state.token_valid,
        )

    # ------------------------------------------------------- reference data
    def fetch_instruments(self) -> Iterable[CanonicalInstrument]:
        self.calls.append("fetch_instruments")
        return list(self.state.instruments)

    # --------------------------------------------------------------- reads
    def fetch_holdings(self, account: AccountRef) -> list[CanonicalHolding]:
        self.calls.append("fetch_holdings")
        return list(self.state.holdings.values())

    def fetch_positions(self, account: AccountRef) -> list[CanonicalHolding]:
        self.calls.append("fetch_positions")
        return []

    def fetch_funds(self, account: AccountRef) -> CanonicalFunds:
        self.calls.append("fetch_funds")
        return CanonicalFunds(
            available_cash=self.state.available_cash,
            used_margin=ZERO,
            as_of=datetime.now(UTC),
        )

    def fetch_daily_candles(
        self, account: AccountRef, broker_token: str, from_date: date, to_date: date
    ) -> list[CanonicalCandle]:
        self.calls.append("fetch_daily_candles")
        bars = self.state.candles.get(int(broker_token), [])
        return [bar for bar in bars if from_date <= bar.trade_date <= to_date]

    def fetch_quotes(
        self, account: AccountRef, broker_tokens: Sequence[str]
    ) -> list[CanonicalQuote]:
        self.calls.append("fetch_quotes")
        now = datetime.now(UTC)
        out = []
        for token in broker_tokens:
            instrument_id = int(token)
            if instrument_id in self.state.quotes:
                out.append(
                    CanonicalQuote(
                        instrument_id=instrument_id,
                        last_price=self.state.quotes[instrument_id],
                        as_of=now,
                    )
                )
        return out

    def fetch_orders(self, account: AccountRef) -> list[OrderState]:
        self.calls.append("fetch_orders")
        return list(self.state.orders.values())

    def fetch_fills(self, account: AccountRef, since: date) -> list[CanonicalFill]:
        self.calls.append("fetch_fills")
        return list(self.state.fills)

    def fetch_charges(
        self, account: AccountRef, broker_order_ids: Sequence[str]
    ) -> dict[str, CanonicalCharges]:
        self.calls.append("fetch_charges")
        return {
            oid: CanonicalCharges(source=ChargeSource.BROKER, brokerage=ZERO, stt=money("1.00"))
            for oid in broker_order_ids
            if oid in self.state.orders
        }

    def fetch_ledger(
        self, account: AccountRef, from_date: date, to_date: date
    ) -> list[CanonicalCashEvent]:
        self.calls.append("fetch_ledger")
        return [e for e in self.state.ledger if from_date <= e.event_date <= to_date]

    # -------------------------------------------------------------- writes
    def place_order(self, account: AccountRef, intent: OrderIntent) -> OrderState:
        self.calls.append("place_order")
        self._guard_ref(intent.client_ref)

        cost = money(intent.limit_price) * intent.quantity
        if intent.side is Side.BUY and cost > self.state.available_cash:
            # Recorded and returned, not raised past the adapter as fatal: the run
            # continues to the next order (D-052).
            raise InsufficientFundsError(
                f"need {cost} but only {self.state.available_cash} available", broker="FAKE"
            )

        order_id = f"FO{next(self._order_seq):06d}"
        self.state.order_intents[order_id] = intent

        if self.state.fill_immediately:
            state = OrderState(
                broker_order_id=order_id,
                status=OrderStatus.FILLED,
                raw_status="COMPLETE",
                filled_quantity=intent.quantity,
                pending_quantity=0,
                average_price=intent.limit_price,
                client_ref=intent.client_ref,
            )
            self.state.fills.append(
                CanonicalFill(
                    broker_order_id=order_id,
                    broker_trade_id=f"FT{next(self._trade_seq):06d}",
                    quantity=intent.quantity,
                    fill_price=intent.limit_price,
                    filled_at=datetime.now(UTC),
                )
            )
            if intent.side is Side.BUY:
                self.state.available_cash = money(self.state.available_cash - cost)
        else:
            state = OrderState(
                broker_order_id=order_id,
                status=OrderStatus.PLACED,
                raw_status="OPEN",
                filled_quantity=0,
                pending_quantity=intent.quantity,
                client_ref=intent.client_ref,
            )

        self.state.orders[order_id] = state
        return state

    def cancel_order(self, account: AccountRef, broker_order_id: str) -> OrderState:
        self.calls.append("cancel_order")
        existing = self.state.orders.get(broker_order_id)
        if existing is None:
            raise ValidationError(f"unknown order {broker_order_id}", broker="FAKE")
        cancelled = OrderState(
            broker_order_id=broker_order_id,
            status=OrderStatus.CANCELLED,
            raw_status="CANCELLED",
            filled_quantity=existing.filled_quantity,
            pending_quantity=0,
            client_ref=existing.client_ref,
        )
        self.state.orders[broker_order_id] = cancelled
        return cancelled

    def place_gtt(self, account: AccountRef, intent: GttIntent) -> GttState:
        self.calls.append("place_gtt")
        self._guard_ref(intent.client_ref)
        gtt_id = f"FG{next(self._gtt_seq):06d}"
        state = GttState(
            broker_gtt_id=gtt_id,
            status=GttStatus.ACTIVE,
            raw_status="active",
            client_ref=intent.client_ref,
            instrument_id=intent.instrument_id,
            trigger_price=intent.trigger_price,
            quantity=intent.quantity,
            is_ours=True,
        )
        self.state.gtts[gtt_id] = state
        return state

    def cancel_gtt(self, account: AccountRef, broker_gtt_id: str) -> GttState:
        self.calls.append("cancel_gtt")
        existing = self.state.gtts.get(broker_gtt_id)
        if existing is None:
            raise ValidationError(f"unknown GTT {broker_gtt_id}", broker="FAKE")
        cancelled = GttState(
            broker_gtt_id=broker_gtt_id,
            status=GttStatus.CANCELLED,
            raw_status="cancelled",
            client_ref=existing.client_ref,
            instrument_id=existing.instrument_id,
            is_ours=existing.is_ours,
        )
        self.state.gtts[broker_gtt_id] = cancelled
        return cancelled

    def fetch_gtts(self, account: AccountRef) -> list[GttState]:
        self.calls.append("fetch_gtts")
        return list(self.state.gtts.values())

    # ------------------------------------------- optional, per capabilities
    def preview_charges(
        self, account: AccountRef, intents: Sequence[OrderIntent]
    ) -> dict[str, CanonicalCharges]:
        self.calls.append("preview_charges")
        return {
            i.client_ref: CanonicalCharges(source=ChargeSource.COMPUTED, stt=money("1.00"))
            for i in intents
        }

    def initiate_sell_authorisation(
        self, account: AccountRef, isins: Sequence[str]
    ) -> AuthorisationRequest:
        raise UnsupportedOperationError("FAKE", "initiate_sell_authorisation")

    # ------------------------------------------------------------- helpers
    def _guard_ref(self, client_ref: str) -> None:
        """Reject a reused reference, as Groww does with ``GA007``.

        The engine treats this as *success, already placed* — so the fake must
        raise it rather than quietly accepting a duplicate, or the recovery path
        would never be exercised.
        """
        if client_ref in self.state.seen_refs:
            raise DuplicateRefError(f"client_ref {client_ref} already used", broker="FAKE")
        self.state.seen_refs.add(client_ref)


def cash_event(
    day: date, amount: str, event_type: CashEventType = CashEventType.DEPOSIT
) -> CanonicalCashEvent:
    """Convenience constructor for test ledgers."""
    return CanonicalCashEvent(
        event_date=day,
        amount=money(amount),
        event_type=event_type,
        narration=event_type.value,
    )
