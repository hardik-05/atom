"""The buy pass: rank by deviation, walk the ranking, gate, size, price.

Pure. Everything the pass needs arrives as arguments and everything it decides
leaves as a ``BuyPlan``; nothing here reads a database or calls a broker. That
is what makes a run explicable from its own record (D-035, D-052) — and what
lets this module be tested against hand-built markets.

Per category, in the configured priority order (D-042):

1. every member gets a reference price — the MEAN or MEDIAN of the last
   ``lookback_days`` closes — and a deviation of LTP from it, in PERCENT (D-149)
2. members are ranked most-negative first
3. the ranking is walked down to ``depth_levels``; the first candidate that is
   below its reference, not already held, and passes every gate is bought
4. one buy per category per run

Every member writes a candidate row whether or not it is bought.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from atom.domain.deviation import deviation_pct
from atom.domain.money import ZERO, apply_pct, money, quantity_for_budget, round_tick_up
from atom.strategy import gates
from atom.strategy.config import RunConfig


@dataclass(frozen=True, slots=True)
class Member:
    instrument_id: int
    symbol: str
    category: str | None
    member_frozen: bool
    instrument_status: str
    broker_mapped: bool
    broker_tradable: bool
    tick_size: Decimal | None


@dataclass(frozen=True, slots=True)
class Market:
    """What the pass knows about one instrument's market."""

    ltp: Decimal | None
    closes: Sequence[Decimal]
    """Newest first, strictly before today."""
    volumes: Sequence[int | None]
    """Newest first, aligned with ``closes``."""
    nav: Decimal | None = None
    nav_date: date | None = None


@dataclass(frozen=True, slots=True)
class Position:
    """What ATOM already holds of an instrument in this universe, and on the account."""

    held_in_universe: bool = False
    holds_harvest_proxy: bool = False
    withheld_quantity: int = 0
    bought_today: bool = False


@dataclass(frozen=True, slots=True)
class PlannedBuy:
    instrument_id: int
    symbol: str
    category: str
    quantity: int
    limit_price: Decimal
    ltp: Decimal

    @property
    def value(self) -> Decimal:
        return money(self.limit_price * self.quantity)


@dataclass(slots=True)
class BuyPlan:
    candidates: list[dict[str, object]] = field(default_factory=list)
    """Rows for ``run_candidate``, one per member."""
    orders: list[PlannedBuy] = field(default_factory=list)
    spent: Decimal = ZERO


def reference_price(closes: Sequence[Decimal], method: str) -> tuple[Decimal, Decimal]:
    """``(reference, median)``. The reference is the mean or the median per config;
    the median is recorded either way, because the gap between the two is the
    first thing to look at when a candidate surprises."""
    median = money(statistics.median(closes))
    mean = money(sum(closes, ZERO) / len(closes))
    return (mean if method == "MEAN" else median), median


def plan_buys(
    *,
    config: RunConfig,
    members: Sequence[Member],
    market: Mapping[int, Market],
    positions: Mapping[int, Position],
    today: date,
    orders_already_planned: int = 0,
) -> BuyPlan:
    plan = BuyPlan()
    ranked: dict[str, list[tuple[Member, Decimal, Decimal, Decimal, Decimal]]] = {}

    def record(member: Member, rank: int, **fields: object) -> None:
        row: dict[str, object] = {
            "instrument_id": member.instrument_id,
            "category": member.category or "UNCATEGORISED",
            "rank": rank,
            "mean_price": ZERO,
            "median_price": None,
            "ltp": ZERO,
            "deviation_pct": ZERO,
            "nav": None,
            "nav_premium_pct": None,
            "holdings_status": None,
            "gate_failed": None,
        }
        row.update(fields)
        plan.candidates.append(row)

    # ---- 1. reference price and deviation for every member
    for member in members:
        mkt = market.get(member.instrument_id)
        cat_cfg = config.categories.get(member.category) if member.category else None
        if member.category is None or cat_cfg is None:
            record(
                member,
                0,
                decision="NOT_CONSIDERED",
                decision_reason="instrument fits none of this universe's categories",
            )
            continue
        closes = list(mkt.closes[: cat_cfg.lookback_days]) if mkt else []
        if mkt is None or mkt.ltp is None:
            record(member, 0, decision="NOT_CONSIDERED", decision_reason="no live price")
            continue
        if len(closes) < cat_cfg.lookback_days:
            record(
                member,
                0,
                ltp=mkt.ltp,
                decision="NOT_CONSIDERED",
                decision_reason=(
                    f"only {len(closes)} of {cat_cfg.lookback_days} days of history — "
                    "sync market data before this instrument can be ranked"
                ),
            )
            continue
        reference, median = reference_price(closes, cat_cfg.average_method)
        deviation = deviation_pct(mkt.ltp, reference)
        ranked.setdefault(member.category, []).append(
            (member, reference, median, mkt.ltp, deviation)
        )

    # ---- 2-4. per category, in priority order
    for category in config.category_priority:
        cat_cfg = config.categories[category]
        rows = sorted(ranked.get(category, []), key=lambda r: (r[4], r[0].symbol))
        bought = False
        for rank, (member, reference, median, ltp, deviation) in enumerate(rows, start=1):
            mkt = market[member.instrument_id]
            pos = positions.get(member.instrument_id, Position())
            base: dict[str, object] = {
                "mean_price": reference,
                "median_price": median,
                "ltp": ltp,
                "deviation_pct": deviation,
                "nav": mkt.nav,
                "holdings_status": "HELD" if pos.held_in_universe else "NOT_HELD",
            }
            _, premium = gates.nav_premium(
                ltp,
                mkt.nav,
                mkt.nav_date,
                enabled=False,
                tolerance_pct=None,
                today=today,
            )
            base["nav_premium_pct"] = premium

            if not cat_cfg.buying_enabled:
                record(
                    member,
                    rank,
                    **base,
                    decision="NOT_CONSIDERED",
                    decision_reason=f"buying off for {category}: {cat_cfg.disabled_reason}",
                )
                continue
            if bought:
                record(
                    member,
                    rank,
                    **base,
                    decision="NOT_CONSIDERED",
                    decision_reason=f"{category} already has its buy for this run",
                )
                continue
            if rank > cat_cfg.depth_levels:
                record(
                    member,
                    rank,
                    **base,
                    decision="NOT_CONSIDERED",
                    decision_reason=f"below depth_levels {cat_cfg.depth_levels}",
                )
                continue
            if deviation >= 0:
                record(
                    member,
                    rank,
                    **base,
                    decision="SKIPPED",
                    decision_reason=f"at or above its reference price ({deviation}%)",
                )
                continue
            if pos.held_in_universe:
                record(
                    member,
                    rank,
                    **base,
                    decision="SKIPPED",
                    decision_reason="already held in this universe — averaging is its own run type",
                )
                continue

            limit = (
                round_tick_up(apply_pct(ltp, config.buy_limit_premium_pct), member.tick_size)
                if member.tick_size
                else None
            )
            quantity = (
                quantity_for_budget(cat_cfg.trade_amount_inr, config.budget_buffer_pct, limit)
                if limit is not None
                else 0
            )
            order_value = money(limit * quantity) if limit is not None else ZERO

            failure = (
                gates.liquidity(
                    list(mkt.volumes),
                    window=cat_cfg.volume_window_days,
                    threshold_units=cat_cfg.volume_threshold_units,
                )
                or gates.nav_premium(
                    ltp,
                    mkt.nav,
                    mkt.nav_date,
                    enabled=cat_cfg.nav_check_enabled,
                    tolerance_pct=cat_cfg.nav_premium_tolerance_pct,
                    today=today,
                )[0]
                or gates.freeze_or_exclusion(
                    member_frozen=member.member_frozen, withheld_quantity=pos.withheld_quantity
                )
                or gates.one_lot_per_day(bought_today=pos.bought_today)
                or gates.proxy_block(holds_harvest_proxy=pos.holds_harvest_proxy)
                or gates.tradability(
                    instrument_status=member.instrument_status,
                    broker_mapped=member.broker_mapped,
                    broker_tradable=member.broker_tradable,
                    tick_size=member.tick_size,
                )
                or (
                    gates.GateFailure("funds", f"trade amount buys zero units at {limit}")
                    if quantity == 0
                    else None
                )
                or gates.funds(
                    order_value=order_value,
                    spent_so_far=plan.spent,
                    cap=config.daily_spend_cap_inr,
                    orders_so_far=orders_already_planned + len(plan.orders),
                    max_orders=config.max_orders_per_run,
                )
            )
            if failure is not None:
                record(
                    member,
                    rank,
                    **base,
                    gate_failed=failure.gate,
                    decision="SKIPPED",
                    decision_reason=failure.reason,
                )
                continue

            assert limit is not None
            plan.orders.append(
                PlannedBuy(
                    instrument_id=member.instrument_id,
                    symbol=member.symbol,
                    category=category,
                    quantity=quantity,
                    limit_price=limit,
                    ltp=ltp,
                )
            )
            plan.spent += order_value
            bought = True
            record(
                member,
                rank,
                **base,
                decision="BOUGHT",
                decision_reason=(
                    f"rank {rank} in {category}, {deviation}% from its "
                    f"{cat_cfg.average_method.lower()}; {quantity} @ {limit} "
                    f"= {order_value}"
                ),
            )
    return plan
