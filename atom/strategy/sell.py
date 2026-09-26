"""The sell pass plan: tranches per instrument, capped at what can actually sell.

Pure. The cancel-and-verify half of the pass (D-063) talks to the broker and so
lives in orchestration; this module only answers "what should rest after it".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from atom.domain.models import OpenLot, SellTranche
from atom.strategy.basis import sell_tranches


@dataclass(frozen=True, slots=True)
class SellInput:
    category: str | None
    profit_target_pct: Decimal | None
    tick_size: Decimal | None
    sellable_quantity: int | None
    """Broker free quantity minus what is excluded or frozen. ``None`` when the
    broker publishes no free quantity — then ATOM's own lots cap the sell, and
    the caller logs that the cap is assumed (D-182)."""


@dataclass(frozen=True, slots=True)
class SkippedSell:
    instrument_id: int
    reason: str


def plan_sells(
    lots: Sequence[OpenLot], inputs: Mapping[int, SellInput]
) -> tuple[list[SellTranche], list[SkippedSell]]:
    by_instrument: dict[int, list[OpenLot]] = defaultdict(list)
    for lot in lots:
        by_instrument[lot.instrument_id].append(lot)

    tranches: list[SellTranche] = []
    skipped: list[SkippedSell] = []
    for instrument_id, group in sorted(by_instrument.items()):
        spec = inputs.get(instrument_id)
        if spec is None or spec.profit_target_pct is None:
            skipped.append(
                SkippedSell(instrument_id, "no profit target configured for its category")
            )
            continue
        if spec.tick_size is None or spec.tick_size <= 0:
            skipped.append(
                SkippedSell(instrument_id, "no tick size — a sell price cannot be formed")
            )
            continue
        if spec.sellable_quantity is not None and spec.sellable_quantity <= 0:
            skipped.append(
                SkippedSell(
                    instrument_id,
                    "nothing sellable: held quantity is excluded, frozen or unsettled",
                )
            )
            continue
        tranches.extend(
            sell_tranches(
                group,
                profit_target_pct=spec.profit_target_pct,
                tick_size=spec.tick_size,
                sellable_quantity=spec.sellable_quantity,
            )
        )
    return tranches, skipped
