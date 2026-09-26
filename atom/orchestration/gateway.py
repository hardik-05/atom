"""The OrderGateway — the one seam where DRY and LIVE differ (D-045).

Everything upstream of this — planning, gating, pricing, intents written before
the send — is the same code in both modes. A paper result that ran different
logic from the live one would measure nothing.

The DRY gateway never opens a socket. Its broker ids are prefixed ``DRY-`` so a
paper order can never be mistaken for, or reconciled against, a real one.
"""

from __future__ import annotations

from typing import Protocol

from atom.adapters.base import BrokerAdapter
from atom.domain.enums import GttStatus, OrderStatus
from atom.domain.models import AccountRef, GttIntent, GttState, OrderIntent, OrderState


class OrderGateway(Protocol):
    mode: str

    def place_order(self, intent: OrderIntent, *, order_request_id: int) -> OrderState: ...

    def place_gtt(self, intent: GttIntent, *, order_request_id: int) -> GttState: ...

    def cancel_gtt(self, broker_gtt_id: str) -> GttState: ...

    def resting_gtt_ids(self) -> set[str] | None:
        """Ids the broker still shows as ACTIVE, for the post-cancel verify.
        ``None`` means there is no broker to ask (DRY)."""
        ...


class LiveGateway:
    mode = "LIVE"

    def __init__(self, adapter: BrokerAdapter, account: AccountRef) -> None:
        self._adapter = adapter
        self._account = account

    def place_order(self, intent: OrderIntent, *, order_request_id: int) -> OrderState:
        return self._adapter.place_order(self._account, intent)

    def place_gtt(self, intent: GttIntent, *, order_request_id: int) -> GttState:
        return self._adapter.place_gtt(self._account, intent)

    def cancel_gtt(self, broker_gtt_id: str) -> GttState:
        return self._adapter.cancel_gtt(self._account, broker_gtt_id)

    def resting_gtt_ids(self) -> set[str] | None:
        return {
            g.broker_gtt_id
            for g in self._adapter.fetch_gtts(self._account)
            if g.status is GttStatus.ACTIVE
        }


class DryGateway:
    mode = "DRY"

    def place_order(self, intent: OrderIntent, *, order_request_id: int) -> OrderState:
        return OrderState(
            broker_order_id=f"DRY-{order_request_id}",
            status=OrderStatus.PLACED,
            raw_status="paper",
            pending_quantity=intent.quantity,
            client_ref=intent.client_ref,
        )

    def place_gtt(self, intent: GttIntent, *, order_request_id: int) -> GttState:
        return GttState(
            broker_gtt_id=f"DRY-GTT-{order_request_id}",
            status=GttStatus.ACTIVE,
            raw_status="paper",
            client_ref=intent.client_ref,
            instrument_id=intent.instrument_id,
            trigger_price=intent.trigger_price,
            quantity=intent.quantity,
            is_ours=True,
        )

    def cancel_gtt(self, broker_gtt_id: str) -> GttState:
        return GttState(broker_gtt_id=broker_gtt_id, status=GttStatus.CANCELLED, raw_status="paper")

    def resting_gtt_ids(self) -> set[str] | None:
        return None
