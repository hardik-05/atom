"""Cost bases and sell tranches.

The two-basis model in one place. Everything about *why* is in
``docs/04-strategy/HARVEST-COST-BASIS.md``; this module is the arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from atom.domain.enums import BasisKind
from atom.domain.errors import HarvestError
from atom.domain.models import OpenLot, SellTranche
from atom.domain.money import (
    ZERO,
    apply_pct,
    money,
    round_tick_up,
    weighted_average,
)

MAX_TRANCHES_PER_INSTRUMENT = 2
"""Synthetic lots blend with each other; only the synthetic/actual boundary splits."""


def actual_average(lots: Iterable[OpenLot]) -> Decimal:
    """Quantity-weighted ``unit_cost``. Drives tax, cash P&L and cost of capital."""
    pairs = [(lot.quantity_open, lot.unit_cost) for lot in lots]
    return weighted_average(pairs)


def strategy_average(lots: Iterable[OpenLot]) -> Decimal:
    """Quantity-weighted ``COALESCE(synthetic_cost_basis, unit_cost)``.

    Drives the deviation, the sell trigger and the averaging decision. Identical
    to :func:`actual_average` for any position with no harvest history — and that
    sameness is what the averaging screen surfaces (D-197).
    """
    pairs = [(lot.quantity_open, lot.strategy_cost) for lot in lots]
    return weighted_average(pairs)


def sell_tranches(
    lots: Sequence[OpenLot],
    *,
    profit_target_pct: Decimal,
    tick_size: Decimal,
    sellable_quantity: int | None = None,
) -> list[SellTranche]:
    """Split a position into at most two sell tranches (D-195, D-198).

    Lots carrying a synthetic basis form one tranche at their own weighted
    synthetic average; everything else forms a second at its weighted
    ``unit_cost``. Blending across the boundary would exit a proxy unit below the
    capital it is recovering and book the shortfall as a gain.

    ``sellable_quantity`` caps the total (D-182). When it binds, the **synthetic**
    tranche is filled first: it carries the older capital, so it is the one that
    has been waiting.

    Returns ``[]`` for an empty position. A position with no synthetic lots yields
    a single ``ACTUAL`` tranche — today's behaviour unchanged.
    """
    if not lots:
        return []

    instrument_ids = {lot.instrument_id for lot in lots}
    if len(instrument_ids) != 1:
        raise HarvestError(f"sell_tranches expects one instrument, got {sorted(instrument_ids)}")
    instrument_id = instrument_ids.pop()

    synthetic = [lot for lot in lots if lot.is_harvest_proxy]
    actual = [lot for lot in lots if not lot.is_harvest_proxy]

    cap = sum(lot.quantity_open for lot in lots) if sellable_quantity is None else sellable_quantity
    if cap <= 0:
        return []

    tranches: list[SellTranche] = []
    remaining = cap

    # Synthetic first: older capital, and the tranche most likely to matter.
    for group, kind in ((synthetic, BasisKind.SYNTHETIC), (actual, BasisKind.ACTUAL)):
        if not group or remaining <= 0:
            continue
        available = sum(lot.quantity_open for lot in group)
        quantity = min(available, remaining)
        basis = (
            weighted_average([(lot.quantity_open, lot.strategy_cost) for lot in group])
            if kind is BasisKind.SYNTHETIC
            else weighted_average([(lot.quantity_open, lot.unit_cost) for lot in group])
        )
        tranches.append(
            SellTranche(
                instrument_id=instrument_id,
                basis_kind=kind,
                quantity=quantity,
                basis_price=basis,
                target_price=round_tick_up(apply_pct(basis, profit_target_pct), tick_size),
                lot_ids=tuple(lot.lot_id for lot in group),
            )
        )
        remaining -= quantity

    return tranches


def carried_basis_amount(
    harvested_lots: Sequence[OpenLot], sell_charges: Decimal = ZERO
) -> Decimal:
    """The rupee amount a harvest carries forward to its proxy (D-188, D-205).

    The **amount**, not a per-unit price: the proxy usually trades at a different
    price, so quantity differs, and what survives the substitution is the capital
    committed. A source position with several lots collapses into one carried
    amount — 10 @ Rs.100 plus 10 @ Rs.90 carries Rs.1,900, which is why the proxy
    ends up on a Rs.95 basis and one tranche rather than two (D-205).

    ``sell_charges`` are included so the cost of harvesting must also be earned
    back (Q-284) — excluding them would let a harvest quietly cost the investor
    with the strategy none the wiser.
    """
    if not harvested_lots:
        raise HarvestError("a harvest must carry at least one lot")
    for lot in harvested_lots:
        if lot.is_harvest_proxy:
            raise HarvestError(
                f"lot {lot.lot_id} already carries a synthetic basis; "
                "chained harvests are not allowed (D-193)"
            )
    total = sum((money(lot.unit_cost) * lot.quantity_open for lot in harvested_lots), start=ZERO)
    return money(total + money(sell_charges))


def synthetic_unit_basis(
    carried_amount: Decimal,
    proxy_quantity: int,
    *,
    deployed_amount: Decimal | None = None,
    proceeds: Decimal | None = None,
) -> Decimal:
    """Per-unit synthetic basis for a proxy lot.

    ``carried_amount / proxy_quantity`` — the step where "sell at the original
    buy price" stops being literally true once the proxy trades at a different
    price. A Rs.1,000 carry over 20 units is Rs.50/unit, not Rs.100 (D-206).

    When ``deployed_amount`` and ``proceeds`` are both given, the carry is scaled
    to the portion actually invested (Q-283): leftover cash returns to idle, where
    its share of the loss is already booked, so it should not inflate the target.
    """
    if proxy_quantity <= 0:
        raise HarvestError(f"proxy quantity must be positive, got {proxy_quantity}")
    amount = money(carried_amount)
    if deployed_amount is not None and proceeds is not None:
        gross = money(proceeds)
        if gross <= 0:
            raise HarvestError("proceeds must be positive to scale a carried basis")
        amount = money(amount * money(deployed_amount) / gross)
    return money(amount / proxy_quantity)


def assert_harvestable(lot: OpenLot) -> None:
    """Raise if a lot may not be harvested.

    Chaining is not allowed (D-193): a proxy can never itself be harvested. The
    database enforces it with ``CHECK (chain_depth = 1)``; this is the same rule
    at the point where the candidate list is built, so the operator sees a reason
    rather than a missing row.
    """
    if lot.is_harvest_proxy:
        raise HarvestError(
            f"lot {lot.lot_id} is already a harvest proxy; it cannot be re-harvested (D-193)"
        )
