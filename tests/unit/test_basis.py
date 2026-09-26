"""Cost bases and sell tranches.

The operator's three walkthrough cases are tests here, and all three must resolve
through the same code path with no branching — that is the test of whether the
rule sits at the right level.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from atom.domain.enums import BasisKind
from atom.domain.errors import HarvestError
from atom.domain.models import OpenLot
from atom.strategy.basis import (
    MAX_TRANCHES_PER_INSTRUMENT,
    actual_average,
    assert_harvestable,
    carried_basis_amount,
    sell_tranches,
    strategy_average,
    synthetic_unit_basis,
)

TICK = D("0.01")
TARGET = D("3.5")
DAY = date(2026, 9, 26)


def lot(
    lot_id: int,
    qty: int,
    unit_cost: str,
    synthetic: str | None = None,
    instrument_id: int = 1,
) -> OpenLot:
    return OpenLot(
        lot_id=lot_id,
        instrument_id=instrument_id,
        universe_id=1,
        quantity_open=qty,
        unit_cost=D(unit_cost),
        acquired_on=DAY,
        synthetic_cost_basis=None if synthetic is None else D(synthetic),
    )


class TestAverages:
    def test_agree_when_no_harvest_history(self) -> None:
        lots = [lot(1, 10, "100"), lot(2, 10, "90")]
        assert actual_average(lots) == strategy_average(lots) == D("95.0000")

    def test_diverge_after_a_harvest(self) -> None:
        # Pre-existing 10 @ Rs.48, harvest proxy 20 @ Rs.45 actual / Rs.50 synthetic
        lots = [lot(1, 10, "48"), lot(2, 20, "45", synthetic="50")]
        assert actual_average(lots) == D("46.0000")
        assert strategy_average(lots) == D("49.3333")

    def test_fresh_capital_dilutes_the_carry_over(self) -> None:
        # Correct: the new money genuinely entered at market and has no committed
        # capital to recover.
        before = strategy_average([lot(1, 10, "90", synthetic="100")])
        after = strategy_average([lot(1, 10, "90", synthetic="100"), lot(2, 10, "85")])
        assert before == D("100.0000")
        assert after == D("92.5000")


class TestSellTranches:
    def test_no_harvest_history_yields_one_actual_tranche(self) -> None:
        """Today's behaviour, unchanged."""
        tranches = sell_tranches(
            [lot(1, 10, "100"), lot(2, 10, "90")], profit_target_pct=TARGET, tick_size=TICK
        )
        assert len(tranches) == 1
        assert tranches[0].basis_kind is BasisKind.ACTUAL
        assert tranches[0].quantity == 20
        assert tranches[0].basis_price == D("95.0000")
        assert tranches[0].target_price == D("98.3300")

    def test_averaged_proxy_splits_into_two(self) -> None:
        """The operator's case 2 — and the bug blending would reintroduce.

        Blended, the average is Rs.92.50 and one order at Rs.95.74 would exit the
        proxy unit against Rs.100 of committed capital: a Rs.4.26 loss booked as a
        3.5% gain.
        """
        lots = [lot(1, 1, "90", synthetic="100"), lot(2, 1, "85")]
        tranches = sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK)

        assert len(tranches) == 2
        synthetic, actual = tranches
        assert synthetic.basis_kind is BasisKind.SYNTHETIC
        assert synthetic.basis_price == D("100.0000")
        assert synthetic.target_price == D("103.5000")
        assert actual.basis_kind is BasisKind.ACTUAL
        assert actual.basis_price == D("85.0000")
        assert actual.target_price == D("87.9800")

        # The blended target that must NOT appear anywhere.
        assert all(t.target_price != D("95.7400") for t in tranches)

    def test_synthetic_lots_blend_with_each_other(self) -> None:
        """Two securities harvested into the same proxy stay one tranche.

        Chaining is banned, but A -> B in March and C -> B in July is legitimate,
        and one order per harvest would grow without bound.
        """
        lots = [
            lot(1, 10, "90", synthetic="100"),
            lot(2, 10, "80", synthetic="120"),
            lot(3, 10, "85"),
        ]
        tranches = sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK)
        assert len(tranches) == 2
        assert tranches[0].basis_price == D("110.0000")  # (100 + 120) / 2

    def test_ceiling_is_two(self) -> None:
        lots = [lot(i, 1, "90", synthetic=str(90 + i)) for i in range(1, 6)]
        lots += [lot(i, 1, str(80 + i)) for i in range(6, 11)]
        assert len(sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK)) == 2

    def test_sellable_cap_fills_synthetic_first(self) -> None:
        """Synthetic carries the older capital, so it is the one that has waited."""
        lots = [lot(1, 10, "90", synthetic="100"), lot(2, 10, "85")]
        tranches = sell_tranches(
            lots, profit_target_pct=TARGET, tick_size=TICK, sellable_quantity=12
        )
        assert [(t.basis_kind, t.quantity) for t in tranches] == [
            (BasisKind.SYNTHETIC, 10),
            (BasisKind.ACTUAL, 2),
        ]

    def test_zero_sellable_yields_nothing(self) -> None:
        lots = [lot(1, 10, "100")]
        assert (
            sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK, sellable_quantity=0) == []
        )

    def test_empty_position(self) -> None:
        assert sell_tranches([], profit_target_pct=TARGET, tick_size=TICK) == []

    def test_rejects_mixed_instruments(self) -> None:
        lots = [lot(1, 10, "100", instrument_id=1), lot(2, 10, "90", instrument_id=2)]
        with pytest.raises(HarvestError, match="one instrument"):
            sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK)

    @given(
        synthetic_qty=st.integers(min_value=0, max_value=50),
        actual_qty=st.integers(min_value=0, max_value=50),
    )
    def test_invariants(self, synthetic_qty: int, actual_qty: int) -> None:
        lots: list[OpenLot] = []
        if synthetic_qty:
            lots.append(lot(1, synthetic_qty, "90", synthetic="100"))
        if actual_qty:
            lots.append(lot(2, actual_qty, "85"))

        tranches = sell_tranches(lots, profit_target_pct=TARGET, tick_size=TICK)

        # Nothing lost, nothing duplicated.
        assert sum(t.quantity for t in tranches) == synthetic_qty + actual_qty
        # The D-195 ceiling.
        assert len(tranches) <= MAX_TRANCHES_PER_INSTRUMENT
        # Every target clears its own basis.
        assert all(t.target_price > t.basis_price for t in tranches)


class TestCarriedBasis:
    def test_case_one_single_lot(self) -> None:
        """A 10 @ Rs.100, sold at Rs.90, proxy 10 @ Rs.90 -> synthetic Rs.100."""
        carried = carried_basis_amount([lot(1, 10, "100")])
        assert carried == D("1000.0000")
        assert synthetic_unit_basis(carried, 10) == D("100.0000")

    def test_case_three_averaged_source_collapses_to_one_basis(self) -> None:
        """X 10 @ Rs.100 + 10 @ Rs.90, harvested into 20 proxy units -> Rs.95.

        A source position with several lots produces ONE synthetic tranche (D-205).
        """
        carried = carried_basis_amount([lot(1, 10, "100"), lot(2, 10, "90")])
        assert carried == D("1900.0000")
        assert synthetic_unit_basis(carried, 20) == D("95.0000")

    def test_proxy_at_a_different_price_is_not_the_source_price(self) -> None:
        """The case where a literal reading of the rule breaks (D-206).

        Rs.1,000 across 20 units of a Rs.45 proxy is Rs.50/unit. Read literally as
        Rs.100/unit the target would be Rs.2,000 — double the capital committed.
        """
        carried = carried_basis_amount([lot(1, 10, "100")])
        assert synthetic_unit_basis(carried, 20) == D("50.0000")
        assert synthetic_unit_basis(carried, 20) * 20 == D("1000.0000")

    def test_harvest_charges_must_also_be_earned_back(self) -> None:
        carried = carried_basis_amount([lot(1, 10, "100")], sell_charges=D("12.40"))
        assert carried == D("1012.4000")

    def test_leftover_cash_scales_the_carry(self) -> None:
        """Rs.900 proceeds, Rs.860.70 deployed: the idle Rs.39.30 must not inflate
        the target (Q-283)."""
        basis = synthetic_unit_basis(D("1000"), 19, deployed_amount=D("860.70"), proceeds=D("900"))
        assert basis == D("50.3333")

    def test_chained_harvest_is_refused(self) -> None:
        with pytest.raises(HarvestError, match="chained"):
            carried_basis_amount([lot(1, 10, "90", synthetic="100")])

    def test_assert_harvestable_names_the_reason(self) -> None:
        assert_harvestable(lot(1, 10, "100"))  # fine
        with pytest.raises(HarvestError, match="already a harvest proxy"):
            assert_harvestable(lot(2, 10, "90", synthetic="100"))

    def test_rejects_empty_and_zero_quantity(self) -> None:
        with pytest.raises(HarvestError):
            carried_basis_amount([])
        with pytest.raises(HarvestError):
            synthetic_unit_basis(D("1000"), 0)

    @given(
        qty=st.integers(min_value=1, max_value=1000),
        cost=st.integers(min_value=1, max_value=100_000),
        proxy_qty=st.integers(min_value=1, max_value=1000),
    )
    def test_carry_preserves_capital(self, qty: int, cost: int, proxy_qty: int) -> None:
        """Whatever the proxy's price, the carried capital is conserved to the paisa."""
        carried = carried_basis_amount([lot(1, qty, str(cost))])
        basis = synthetic_unit_basis(carried, proxy_qty)
        assert abs(basis * proxy_qty - carried) <= D("0.0001") * proxy_qty
