"""Money arithmetic. The cheapest tests, and the ones that catch the most
damaging class of bug: a wrong number gets executed, a crash does not."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from atom.domain.money import (
    MoneyError,
    apply_pct,
    display,
    fraction_of_pct,
    money,
    pct,
    quantity_for_budget,
    round_tick_down,
    round_tick_up,
    weighted_average,
)


class TestMoney:
    def test_accepts_decimal_int_and_str(self) -> None:
        assert money(D("12.5")) == D("12.5000")
        assert money(7) == D("7.0000")
        assert money("3985.00") == D("3985.0000")  # Groww returns decimal strings

    def test_rejects_float(self) -> None:
        # Accepting float is how binary rounding error leaks into a ledger.
        with pytest.raises(MoneyError, match="float"):
            money(12.5)

    def test_rejects_bool(self) -> None:
        with pytest.raises(MoneyError):
            money(True)

    def test_rejects_nonsense(self) -> None:
        for bad in ["", "   ", "abc", None, [], {}]:
            with pytest.raises(MoneyError):
                money(bad)

    def test_rejects_non_finite(self) -> None:
        for bad in ["NaN", "Infinity", "-Infinity"]:
            with pytest.raises(MoneyError):
                money(bad)

    def test_quantises_to_four_places(self) -> None:
        assert money("1.23456").as_tuple().exponent == -4
        assert money("1.00005") == D("1.0001")  # half-up

    def test_display_is_two_places(self) -> None:
        assert display(money("98.3250")) == D("98.33")
        assert display(money("98.3240")) == D("98.32")


class TestPercentages:
    def test_apply_pct_is_a_scale_up(self) -> None:
        assert apply_pct(D("100"), D("3.5")) == D("103.5000")
        assert apply_pct(D("95"), D("3.5")) == D("98.3250")  # the case-3 harvest target

    def test_fraction_of_pct_is_a_portion(self) -> None:
        assert fraction_of_pct(D("20000"), D("99")) == D("19800.0000")

    def test_pct_keeps_four_places(self) -> None:
        assert pct("2.5") == D("2.5000")


class TestTickRounding:
    def test_sell_targets_round_up(self) -> None:
        # Rounding a sell target down would place it below the configured threshold.
        assert round_tick_up(D("98.3250"), D("0.01")) == D("98.3300")
        assert round_tick_up(D("98.3300"), D("0.01")) == D("98.3300")  # already on tick

    def test_buy_limits_round_down(self) -> None:
        assert round_tick_down(D("284.5678"), D("0.01")) == D("284.5600")

    def test_rejects_bad_tick(self) -> None:
        for bad in [D("0"), D("-0.01")]:
            with pytest.raises(MoneyError):
                round_tick_up(D("100"), bad)


class TestQuantityForBudget:
    def test_the_documented_example(self) -> None:
        # Rs.20,000 x 99% / Rs.2,440 = 8.11 -> 8 units (D-059b)
        assert quantity_for_budget(D("20000"), D("99"), D("2440")) == 8

    def test_floors_never_rounds(self) -> None:
        # 8.99 must not become 9: that would breach the budget.
        assert quantity_for_budget(D("899"), D("100"), D("100")) == 8

    def test_zero_when_unaffordable(self) -> None:
        # The caller skips rather than placing a zero-quantity order.
        assert quantity_for_budget(D("100"), D("99"), D("2440")) == 0

    def test_buffer_keeps_the_order_inside_budget(self) -> None:
        # Without the buffer, 10 units at Rs.100 costs Rs.1,010-1,020 with brokerage
        # against a Rs.1,000 budget, and is rejected.
        assert quantity_for_budget(D("1000"), D("100"), D("100")) == 10
        assert quantity_for_budget(D("1000"), D("99"), D("100")) == 9

    def test_rejects_non_positive_price(self) -> None:
        with pytest.raises(MoneyError):
            quantity_for_budget(D("1000"), D("99"), D("0"))

    @given(
        amount=st.integers(min_value=1, max_value=10_000_000),
        price=st.integers(min_value=1, max_value=100_000),
    )
    def test_never_exceeds_budget(self, amount: int, price: int) -> None:
        qty = quantity_for_budget(D(amount), D("99"), D(price))
        assert qty * D(price) <= D(amount) * D("0.99")


class TestWeightedAverage:
    def test_the_averaged_source_case(self) -> None:
        # 10 @ Rs.100 + 10 @ Rs.90 -> Rs.95 (D-205)
        assert weighted_average([(10, D("100")), (10, D("90"))]) == D("95.0000")

    def test_weights_by_quantity_not_count(self) -> None:
        assert weighted_average([(90, D("100")), (10, D("50"))]) == D("95.0000")

    def test_rejects_zero_total(self) -> None:
        # An average of nothing is not zero; returning zero would feed a nonsense
        # basis into a sell target.
        with pytest.raises(MoneyError):
            weighted_average([])
