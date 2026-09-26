"""The buy signal."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from atom.domain.deviation import deviation_pct, premium_pct
from atom.domain.money import MoneyError


class TestDeviation:
    def test_below_mean_is_negative(self) -> None:
        assert deviation_pct(D("90"), D("100")) == D("-10.0000")

    def test_above_mean_is_positive(self) -> None:
        assert deviation_pct(D("110"), D("100")) == D("10.0000")

    def test_at_mean_is_zero(self) -> None:
        assert deviation_pct(D("100"), D("100")) == D("0.0000")

    def test_holds_four_places(self) -> None:
        assert deviation_pct(D("99.9999"), D("100")) == D("-0.0001")

    def test_rejects_non_positive_mean(self) -> None:
        # A fabricated deviation would drive a real order.
        for bad in [D("0"), D("-1")]:
            with pytest.raises(MoneyError):
                deviation_pct(D("90"), bad)

    def test_percentage_not_rupees(self) -> None:
        # Two instruments 10% below their means give the same signal despite an
        # 80x price difference. A rupee threshold could not do this (D-149).
        assert deviation_pct(D("22.5"), D("25")) == deviation_pct(D("1800"), D("2000"))


class TestPremium:
    def test_global_etf_premium_fails_a_two_percent_gate(self) -> None:
        # Observed global ETF premiums run +18.9% and higher, which disables the
        # category at a 2% threshold.
        assert premium_pct(D("118.9"), D("100")) == D("18.9000")

    def test_rejects_non_positive_nav(self) -> None:
        with pytest.raises(MoneyError):
            premium_pct(D("100"), D("0"))
