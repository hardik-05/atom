"""The buy-side gates, in the order RUN-LIFECYCLE.md 7 fixes:

    liquidity → NAV premium → freeze/exclusion → one-lot-per-day
             → proxy-block → tradability → funds

Each gate is a pure function of what the run already knows, and returns either
``None`` (pass) or a ``GateFailure`` carrying the gate's name and the reason in
words. The reason is written into ``run_candidate`` verbatim, so "why did ATOM
not buy X on 12 March" is answered by SQL, not by reading code.

Ranking and selection happen BEFORE the gates and are never influenced by
them (D-042): a candidate that fails is skipped, and the next one in the
existing rank order is tried. A failing candidate is never replaced by a
better-priced one from further down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from atom.domain.deviation import premium_pct
from atom.domain.money import HUNDRED, money

NAV_MAX_AGE_DAYS = 7
"""How old the latest NAV may be before the premium check treats it as unknown.

Not a strategy parameter: AMFI publishes daily, so a NAV more than a week old
means the feed has stopped, and a premium computed against it is fiction.
"""


@dataclass(frozen=True, slots=True)
class GateFailure:
    gate: str
    reason: str


def liquidity(
    volumes: list[int | None], *, window: int, threshold_units: Decimal
) -> GateFailure | None:
    """Average daily volume over the window, in UNITS (D-027), at or above the floor."""
    usable = [v for v in volumes[:window] if v is not None]
    if len(usable) < window:
        return GateFailure(
            "liquidity", f"only {len(usable)} of {window} days of volume available to average"
        )
    average = Decimal(sum(usable)) / Decimal(window)
    if average < threshold_units:
        return GateFailure(
            "liquidity",
            f"average volume {average:.0f} units over {window} days is below the "
            f"{threshold_units:.0f} floor",
        )
    return None


def nav_premium(
    ltp: Decimal,
    nav: Decimal | None,
    nav_date: date | None,
    *,
    enabled: bool,
    tolerance_pct: Decimal | None,
    today: date,
) -> tuple[GateFailure | None, Decimal | None]:
    """Premium over NAV at or below the tolerance. Returns the premium too, for the
    decision record, whether or not the check is enabled."""
    premium = premium_pct(ltp, nav) if nav is not None and nav > 0 else None
    if not enabled:
        return None, premium
    if nav is None or nav_date is None:
        return GateFailure("nav_premium", "no NAV available to compare against"), None
    if (today - nav_date).days > NAV_MAX_AGE_DAYS:
        return (
            GateFailure(
                "nav_premium", f"latest NAV is from {nav_date}, over {NAV_MAX_AGE_DAYS} days old"
            ),
            premium,
        )
    assert premium is not None and tolerance_pct is not None
    if premium > tolerance_pct:
        return (
            GateFailure(
                "nav_premium",
                f"trading {premium}% over NAV {nav}, above the {tolerance_pct}% tolerance",
            ),
            premium,
        )
    return None, premium


def freeze_or_exclusion(*, member_frozen: bool, withheld_quantity: int) -> GateFailure | None:
    if member_frozen:
        return GateFailure("freeze", "frozen in this universe: stays a member, takes no new buys")
    if withheld_quantity > 0:
        return GateFailure(
            "freeze",
            f"{withheld_quantity} units excluded or frozen on this account; not adding to it",
        )
    return None


def one_lot_per_day(*, bought_today: bool) -> GateFailure | None:
    if bought_today:
        return GateFailure("one_lot_per_day", "already bought today in this universe")
    return None


def proxy_block(*, holds_harvest_proxy: bool) -> GateFailure | None:
    """D-196. A harvest proxy shows a negative deviation against its synthetic
    basis and so surfaces as a buy — averaging it concentrates exactly the
    position the harvest diversified away from. Blocked without an override."""
    if holds_harvest_proxy:
        return GateFailure("proxy_block", "PROXY APPLIED — averaging blocked (override required)")
    return None


def tradability(
    *, instrument_status: str, broker_mapped: bool, broker_tradable: bool, tick_size: Decimal | None
) -> GateFailure | None:
    """Knowable in advance, so refused BEFORE placing rather than left to the broker."""
    if instrument_status != "ACTIVE":
        return GateFailure("tradability", f"instrument status is {instrument_status}")
    if not broker_mapped:
        return GateFailure("tradability", "no broker instrument mapping — run the instrument sync")
    if not broker_tradable:
        return GateFailure("tradability", "the broker lists this instrument as suspended")
    if tick_size is None or tick_size <= 0:
        return GateFailure(
            "tradability", "no tick size in ATOM's reference data — a limit price cannot be formed"
        )
    return None


def funds(
    *,
    order_value: Decimal,
    spent_so_far: Decimal,
    cap: Decimal,
    orders_so_far: int,
    max_orders: int,
) -> GateFailure | None:
    """The run's own budget, not the broker's cash. Broker funds cannot be known
    reliably ahead of the exchange, so a buy the broker refuses for funds is
    recorded and the run continues (D-052); this gate is the hard stop ATOM
    CAN know — the operator's daily cap and the order-count guard."""
    if orders_so_far >= max_orders:
        return GateFailure("funds", f"max_orders_per_run {max_orders} reached")
    if spent_so_far + order_value > cap:
        return GateFailure(
            "funds",
            f"would take today's spend to {money(spent_so_far + order_value)}, over the "
            f"{cap} daily cap",
        )
    return None


def pct_of(value: Decimal, percent: Decimal) -> Decimal:
    return value * percent / HUNDRED
