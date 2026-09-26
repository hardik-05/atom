"""The fake adapter must satisfy the real contract, or every test above it is
testing against a fiction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from atom.adapters.base import BrokerAdapter, UnsupportedOperationError
from atom.adapters.client_ref import make_client_ref
from atom.adapters.fake import FakeAdapter, FakeBrokerState
from atom.domain.enums import GttStatus, OrderStatus, Side
from atom.domain.errors import DuplicateRefError, InsufficientFundsError
from atom.domain.models import AccountRef, CanonicalHolding, GttIntent, OrderIntent
from atom.domain.money import money

ACCOUNT = AccountRef(
    trading_account_id=1,
    broker_code="FAKE",
    broker_client_id="FAKE001",
    proxy_url="http://127.0.0.1:3128",
    egress_ip="13.234.1.1",
    secret_ref="/atom/sessions/1/2026-09-26",
)


def ref(seq: int = 1) -> str:
    return make_client_ref(trade_date=date(2026, 9, 26), run_id=1, sequence=seq)


def buy(qty: int = 10, price: str = "100", seq: int = 1) -> OrderIntent:
    return OrderIntent(
        trading_account_id=1,
        universe_id=1,
        instrument_id=101,
        side=Side.BUY,
        quantity=qty,
        limit_price=money(price),
        client_ref=ref(seq),
    )


def test_satisfies_the_protocol() -> None:
    assert isinstance(FakeAdapter(), BrokerAdapter)


class TestOrders:
    def test_fills_and_debits_cash(self) -> None:
        adapter = FakeAdapter()
        before = adapter.state.available_cash
        state = adapter.place_order(ACCOUNT, buy())
        assert state.status is OrderStatus.FILLED
        assert state.filled_quantity == 10
        assert adapter.state.available_cash == money(before - D("1000"))
        assert len(adapter.state.fills) == 1

    def test_can_be_made_to_rest(self) -> None:
        adapter = FakeAdapter(FakeBrokerState(fill_immediately=False))
        state = adapter.place_order(ACCOUNT, buy())
        assert state.status is OrderStatus.PLACED
        assert state.pending_quantity == 10
        assert adapter.state.fills == []

    def test_duplicate_ref_is_refused(self) -> None:
        """Groww's GA007 behaviour. The engine reads this as success-already-placed,
        so the fake must produce it or that path is never exercised."""
        adapter = FakeAdapter()
        adapter.place_order(ACCOUNT, buy(seq=1))
        with pytest.raises(DuplicateRefError):
            adapter.place_order(ACCOUNT, buy(seq=1))

    def test_insufficient_funds_raises_rather_than_silently_shrinking(self) -> None:
        adapter = FakeAdapter(FakeBrokerState(available_cash=money("500")))
        with pytest.raises(InsufficientFundsError):
            adapter.place_order(ACCOUNT, buy(qty=10, price="100"))

    def test_rejects_zero_quantity_at_construction(self) -> None:
        # A zero-quantity order is a caller bug; the domain model refuses it.
        with pytest.raises(ValueError, match="quantity"):
            buy(qty=0)

    def test_cancel_is_recorded(self) -> None:
        adapter = FakeAdapter(FakeBrokerState(fill_immediately=False))
        placed = adapter.place_order(ACCOUNT, buy())
        cancelled = adapter.cancel_order(ACCOUNT, placed.broker_order_id)
        assert cancelled.status is OrderStatus.CANCELLED
        assert adapter.state.orders[placed.broker_order_id].status is OrderStatus.CANCELLED


class TestGtt:
    def test_place_and_cancel(self) -> None:
        adapter = FakeAdapter()
        intent = GttIntent(
            instrument_id=101,
            quantity=10,
            trigger_price=money("103.50"),
            limit_price=money("103.45"),
            client_ref=ref(),
        )
        gtt = adapter.place_gtt(ACCOUNT, intent)
        assert gtt.status is GttStatus.ACTIVE
        assert gtt.is_ours is True
        assert gtt.client_ref == ref()

        cancelled = adapter.cancel_gtt(ACCOUNT, gtt.broker_gtt_id)
        assert cancelled.status is GttStatus.CANCELLED
        assert not cancelled.status.is_live

    def test_only_sell_gtts_are_permitted(self) -> None:
        with pytest.raises(ValueError, match="sell GTT"):
            GttIntent(
                instrument_id=101,
                quantity=10,
                trigger_price=money("103.50"),
                limit_price=money("103.45"),
                client_ref=ref(),
                side=Side.BUY,
            )


class TestHoldings:
    def test_free_quantity_caps_the_sellable_figure(self) -> None:
        holding = CanonicalHolding(
            instrument_id=101,
            total_quantity=100,
            average_price=money("95"),
            free_quantity=60,
            unsettled_quantity=20,
            pledged_quantity=20,
        )
        assert holding.sellable == 60
        assert holding.free_quantity_is_assumed is False

    def test_missing_free_quantity_falls_back_and_says_so(self) -> None:
        holding = CanonicalHolding(instrument_id=101, total_quantity=100, average_price=money("95"))
        assert holding.sellable == 100
        assert holding.free_quantity_is_assumed is True


class TestCallOrdering:
    def test_calls_are_logged_so_sequence_can_be_asserted(self) -> None:
        """Lets orchestration tests prove cancel-all-first actually runs first."""
        adapter = FakeAdapter()
        adapter.fetch_gtts(ACCOUNT)
        adapter.place_order(ACCOUNT, buy())
        assert adapter.calls == ["fetch_gtts", "place_order"]


def test_unsupported_operation_is_explicit() -> None:
    # Preferred over returning nothing: a caller that ignored the capability
    # profile has a bug, and it should surface at the call site.
    with pytest.raises(UnsupportedOperationError):
        FakeAdapter().initiate_sell_authorisation(ACCOUNT, ["INE002A01018"])
