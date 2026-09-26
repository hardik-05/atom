"""The buy signal.

Deviation is a *percentage*, not a rupee amount (D-149): price dispersion inside
a single bucket spans 83x, which makes a rupee threshold meaningless across a
universe.
"""

from __future__ import annotations

from decimal import Decimal

from atom.domain.money import HUNDRED, MoneyError, money, pct


def deviation_pct(ltp: Decimal, mean: Decimal) -> Decimal:
    """``(ltp - mean) / mean`` as percentage points, 4dp.

    Negative means the price is *below* the mean, which is the buy direction.
    ``deviation_pct(90, 100)`` is ``-10.0000``.

    A non-positive mean raises: it would otherwise divide by zero or invert the
    sign, and a fabricated deviation would drive a real order.
    """
    m = money(mean)
    if m <= 0:
        raise MoneyError(f"mean must be positive to compute deviation, got {mean!r}")
    return pct((money(ltp) - m) / m * HUNDRED)


def premium_pct(price: Decimal, nav: Decimal) -> Decimal:
    """ETF market price premium over NAV, as percentage points.

    Same arithmetic as :func:`deviation_pct` against a different reference; kept
    separate because the two are gates with different thresholds and conflating
    them in code has repeatedly been a source of confusion.
    """
    n = money(nav)
    if n <= 0:
        raise MoneyError(f"nav must be positive to compute premium, got {nav!r}")
    return pct((money(price) - n) / n * HUNDRED)
