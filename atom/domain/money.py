"""Money and quantity arithmetic.

Every monetary value in ATOM is a :class:`~decimal.Decimal`. ``float`` is never
used in a monetary path — binary floating point cannot represent 0.01, and the
errors compound across a lot ledger.

Storage is 4 decimal places, display is 2 (D-026).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

MONEY_DP: Final = 4
"""Decimal places stored for currency."""

DISPLAY_DP: Final = 2
"""Decimal places displayed for currency."""

PCT_DP: Final = 4
"""Decimal places for percentages, held as percentage points (2.5 == 2.5%)."""

ZERO: Final = Decimal("0")
HUNDRED: Final = Decimal("100")

_MONEY_Q: Final = Decimal(1).scaleb(-MONEY_DP)
_PCT_Q: Final = Decimal(1).scaleb(-PCT_DP)
_DISPLAY_Q: Final = Decimal(1).scaleb(-DISPLAY_DP)


class MoneyError(ValueError):
    """A value could not be interpreted as money."""


def money(value: object) -> Decimal:
    """Coerce to a 4dp Decimal.

    Accepts ``Decimal``, ``int`` and ``str`` — including the decimal strings
    Groww and Shoonya return. ``float`` is rejected outright rather than
    silently converted, because accepting it is how floats leak into a ledger.
    """
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, bool):  # bool is an int subclass; almost never intended
        raise MoneyError(f"refusing to treat {value!r} as money")
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise MoneyError("empty string is not money")
        try:
            d = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"not a decimal: {value!r}") from exc
    elif isinstance(value, float):
        raise MoneyError(
            f"float {value!r} rejected — use Decimal or str to avoid binary rounding error"
        )
    else:
        raise MoneyError(f"cannot interpret {type(value).__name__} as money")

    if not d.is_finite():
        raise MoneyError(f"{value!r} is not finite")
    return d.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)


def pct(value: object) -> Decimal:
    """Coerce to a 4dp percentage, in percentage points."""
    return money(value).quantize(_PCT_Q, rounding=ROUND_HALF_UP)


def display(value: Decimal) -> Decimal:
    """Round to 2dp for presentation only. Never write this back to storage."""
    return value.quantize(_DISPLAY_Q, rounding=ROUND_HALF_UP)


def apply_pct(base: Decimal, percent: Decimal) -> Decimal:
    """``base`` scaled by ``percent`` percentage points.

    ``apply_pct(100, 3.5)`` is ``103.5`` — used for sell targets.
    """
    return money(base * (HUNDRED + pct(percent)) / HUNDRED)


def fraction_of_pct(base: Decimal, percent: Decimal) -> Decimal:
    """``percent`` percent *of* ``base``.

    ``fraction_of_pct(20000, 99)`` is ``19800`` — used for the budget buffer.
    """
    return money(base * pct(percent) / HUNDRED)


def round_tick_up(price: Decimal, tick: Decimal) -> Decimal:
    """Round *up* to the next whole tick. Used for sell targets.

    Rounding a sell target down would place it below the configured threshold,
    so the direction is not arbitrary.
    """
    _check_tick(tick)
    return money((money(price) / tick).quantize(Decimal(1), rounding=ROUND_CEILING) * tick)


def round_tick_down(price: Decimal, tick: Decimal) -> Decimal:
    """Round *down* to the previous whole tick. Used for buy limits."""
    _check_tick(tick)
    return money((money(price) / tick).quantize(Decimal(1), rounding=ROUND_FLOOR) * tick)


def _check_tick(tick: Decimal) -> None:
    if not isinstance(tick, Decimal) or not tick.is_finite() or tick <= 0:
        raise MoneyError(f"tick size must be a positive Decimal, got {tick!r}")


def quantity_for_budget(trade_amount: Decimal, buffer_pct: Decimal, ltp: Decimal) -> int:
    """Whole shares affordable within ``trade_amount``, after the budget buffer.

    ``floor((trade_amount * buffer_pct%) / ltp)`` — D-059b.

    The buffer exists because a naive ``amount / price`` goes over budget once
    brokerage is added. Indian equity markets have no fractional shares, so the
    result is floored and the remainder stays as cash.

    Returns ``0`` when nothing is affordable; the caller skips rather than
    placing a zero-quantity order.
    """
    price = money(ltp)
    if price <= 0:
        raise MoneyError(f"ltp must be positive, got {ltp!r}")
    budget = fraction_of_pct(money(trade_amount), buffer_pct)
    if budget <= 0:
        return 0
    return int((budget / price).to_integral_value(rounding=ROUND_FLOOR))


def weighted_average(pairs: list[tuple[int, Decimal]]) -> Decimal:
    """Quantity-weighted average price.

    Raises when the total quantity is zero — an average of nothing is not zero,
    and returning zero would feed a nonsense basis into a sell target.
    """
    total_qty = sum(q for q, _ in pairs)
    if total_qty <= 0:
        raise MoneyError("weighted_average needs a positive total quantity")
    total = sum((money(price) * q for q, price in pairs), start=ZERO)
    return money(total / total_qty)
