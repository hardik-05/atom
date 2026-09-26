"""Config resolution, the buy pass and the sell plan — all pure, no I/O."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from atom.domain.enums import BasisKind
from atom.domain.errors import ConfigError
from atom.domain.models import OpenLot
from atom.strategy.buy import Market, Member, Position, plan_buys
from atom.strategy.config import RunConfig, resolve
from atom.strategy.sell import SellInput, plan_sells

D = Decimal
TODAY = date(2026, 9, 28)
CATS = ["EQUITY", "COMMODITY"]


def category_values(
    cat: str, **overrides: str | None
) -> dict[tuple[str, str | None], tuple[bool, str | None]]:
    base = {
        "profit_target_pct": "3.5",
        "depth_levels": "3",
        "trade_amount_inr": "10000",
        "lookback_days": "5",
        "average_method": "MEAN",
        "category_enabled": "true",
        "nav_check_enabled": "false",
        "nav_premium_tolerance_pct": "2",
        "volume_threshold_units": "1000",
        "volume_window_days": "3",
    }
    base.update(overrides)
    return {(k, cat): (True, v) for k, v in base.items()}


def full_values(
    **account_overrides: str | None,
) -> dict[tuple[str, str | None], tuple[bool, str | None]]:
    values: dict[tuple[str, str | None], tuple[bool, str | None]] = {}
    for cat in CATS:
        values.update(category_values(cat))
    account = {
        "category_priority": "EQUITY,COMMODITY",
        "daily_spend_cap_inr": "50000",
        "max_orders_per_run": "10",
        "dry_run": "true",
        "budget_buffer_pct": "99",
        "buy_limit_premium_pct": "0",
    }
    account.update(account_overrides)
    values.update({(k, None): (True, v) for k, v in account.items()})
    return values


GLOBALS = {"kill_switch": (True, "false"), "market_open_gate_time": (True, "09:30")}


def config(**overrides: str | None) -> RunConfig:
    return resolve(
        universe_categories=CATS, account_values=full_values(**overrides), global_values=GLOBALS
    )


# ------------------------------------------------------------------- config


def test_every_missing_key_is_reported_at_once() -> None:
    values = full_values()
    del values[("daily_spend_cap_inr", None)]
    del values[("depth_levels", "COMMODITY")]
    with pytest.raises(ConfigError) as caught:
        resolve(universe_categories=CATS, account_values=values, global_values={})
    message = str(caught.value)
    assert "daily_spend_cap_inr" in message
    assert "depth_levels [COMMODITY]" in message
    assert "kill_switch (global)" in message


def test_explicit_null_switches_buying_off_for_that_category_only() -> None:
    """D-039/D-068: NULL is 'do not buy this category', not 'unset'."""
    values = full_values()
    values.update({("trade_amount_inr", "COMMODITY"): (True, None)})
    cfg = resolve(universe_categories=CATS, account_values=values, global_values=GLOBALS)
    assert cfg.categories["EQUITY"].buying_enabled
    assert not cfg.categories["COMMODITY"].buying_enabled
    assert "trade_amount_inr" in (cfg.categories["COMMODITY"].disabled_reason or "")


def test_validation_rules_are_enforced_at_resolve_time() -> None:
    values = full_values(category_priority="EQUITY", budget_buffer_pct="120")
    values.update(category_values("EQUITY", depth_levels="0", average_method="MODE"))
    with pytest.raises(ConfigError) as caught:
        resolve(universe_categories=CATS, account_values=values, global_values=GLOBALS)
    message = str(caught.value)
    assert "permutation" in message
    assert "budget_buffer_pct" in message
    assert "depth_levels [EQUITY]" in message
    assert "MEAN or MEDIAN" in message


def test_snapshot_keeps_decimals_exact() -> None:
    snap = config().snapshot()
    assert snap["daily_spend_cap_inr"] == "50000"
    assert snap["categories"]["EQUITY"]["profit_target_pct"] == "3.5"


# --------------------------------------------------------------------- buys


def member(iid: int, symbol: str, category: str = "EQUITY", **kw: object) -> Member:
    fields = {
        "instrument_id": iid,
        "symbol": symbol,
        "category": category,
        "member_frozen": False,
        "instrument_status": "ACTIVE",
        "broker_mapped": True,
        "broker_tradable": True,
        "tick_size": D("0.01"),
    }
    fields.update(kw)
    return Member(**fields)  # type: ignore[arg-type]


def market(ltp: str, mean: str = "100", volume: int = 50_000) -> Market:
    return Market(ltp=D(ltp), closes=[D(mean)] * 5, volumes=[volume] * 5)


def decisions(plan) -> dict[int, tuple[str, str]]:  # type: ignore[no-untyped-def]
    return {
        row["instrument_id"]: (row["decision"], row["decision_reason"]) for row in plan.candidates
    }


def test_most_negative_deviation_is_bought_one_per_category() -> None:
    members = [member(1, "AAA"), member(2, "BBB"), member(3, "CCC")]
    mkt = {1: market("95"), 2: market("90"), 3: market("99")}
    plan = plan_buys(config=config(), members=members, market=mkt, positions={}, today=TODAY)

    assert [o.instrument_id for o in plan.orders] == [2]
    d = decisions(plan)
    assert d[2][0] == "BOUGHT"
    assert d[1][0] == "NOT_CONSIDERED" and "already has its buy" in d[1][1]
    # 10000 x 99% / 90 = 110.0 → 110 units, limit at LTP with a zero premium
    assert plan.orders[0].quantity == 110
    assert plan.orders[0].limit_price == D("90.0000")


def test_held_candidates_are_walked_past_within_depth() -> None:
    members = [member(1, "AAA"), member(2, "BBB")]
    mkt = {1: market("90"), 2: market("95")}
    plan = plan_buys(
        config=config(),
        members=members,
        market=mkt,
        positions={1: Position(held_in_universe=True)},
        today=TODAY,
    )
    assert [o.instrument_id for o in plan.orders] == [2]
    assert "averaging" in decisions(plan)[1][1]


def test_nothing_below_depth_is_bought() -> None:
    members = [member(i, f"S{i}") for i in range(1, 5)]
    mkt = {i: market(str(90 + i)) for i in range(1, 5)}
    positions = {i: Position(held_in_universe=True) for i in (1, 2, 3)}
    plan = plan_buys(config=config(), members=members, market=mkt, positions=positions, today=TODAY)
    assert plan.orders == []
    assert "below depth_levels 3" in decisions(plan)[4][1]


def test_a_gate_failure_skips_to_the_next_rank_never_substitutes() -> None:
    members = [member(1, "THIN"), member(2, "OK")]
    mkt = {1: market("90", volume=10), 2: market("95")}
    plan = plan_buys(config=config(), members=members, market=mkt, positions={}, today=TODAY)
    rows = {r["instrument_id"]: r for r in plan.candidates}
    assert rows[1]["gate_failed"] == "liquidity"
    assert [o.instrument_id for o in plan.orders] == [2]


def test_above_reference_is_never_bought() -> None:
    plan = plan_buys(
        config=config(),
        members=[member(1, "UP")],
        market={1: market("101")},
        positions={},
        today=TODAY,
    )
    assert plan.orders == []
    assert "at or above" in decisions(plan)[1][1]


def test_short_history_is_not_ranked() -> None:
    mkt = {1: Market(ltp=D("90"), closes=[D("100")] * 3, volumes=[5000] * 3)}
    plan = plan_buys(
        config=config(), members=[member(1, "NEW")], market=mkt, positions={}, today=TODAY
    )
    assert decisions(plan)[1][0] == "NOT_CONSIDERED"
    assert "3 of 5 days" in decisions(plan)[1][1]


def test_daily_cap_stops_the_second_category() -> None:
    cfg = config(daily_spend_cap_inr="15000")
    members = [member(1, "EQ"), member(2, "GOLD", category="COMMODITY")]
    mkt = {1: market("90"), 2: market("90")}
    plan = plan_buys(config=cfg, members=members, market=mkt, positions={}, today=TODAY)
    assert [o.instrument_id for o in plan.orders] == [1]
    rows = {r["instrument_id"]: r for r in plan.candidates}
    assert rows[2]["gate_failed"] == "funds"


def test_quantity_uses_the_limit_price_so_the_budget_holds() -> None:
    """A premium above LTP must shrink quantity, or the order overshoots its budget."""
    cfg = config(buy_limit_premium_pct="1")
    plan = plan_buys(
        config=cfg, members=[member(1, "X")], market={1: market("99.99")}, positions={}, today=TODAY
    )
    order = plan.orders[0]
    assert order.limit_price == D("100.9900")  # 99.99 x 1.01 = 100.9899 → rounded UP
    assert order.value <= D("10000") * D("0.99")


def test_proxy_block_and_freeze_are_gates() -> None:
    members = [member(1, "PROXY"), member(2, "FROZEN", member_frozen=True), member(3, "FINE")]
    mkt = {1: market("85"), 2: market("88"), 3: market("95")}
    plan = plan_buys(
        config=config(),
        members=members,
        market=mkt,
        positions={1: Position(holds_harvest_proxy=True)},
        today=TODAY,
    )
    rows = {r["instrument_id"]: r for r in plan.candidates}
    assert rows[1]["gate_failed"] == "proxy_block"
    assert rows[2]["gate_failed"] == "freeze"
    assert [o.instrument_id for o in plan.orders] == [3]


def test_every_member_gets_a_candidate_row() -> None:
    members = [member(i, f"S{i}") for i in range(1, 8)] + [member(99, "ODD", category=None)]
    mkt = {i: market(str(90 + i)) for i in range(1, 8)}
    plan = plan_buys(config=config(), members=members, market=mkt, positions={}, today=TODAY)
    assert len(plan.candidates) == len(members)
    assert all(r["decision_reason"] for r in plan.candidates)


# -------------------------------------------------------------------- sells


def lot(lot_id: int, qty: int, cost: str, synthetic: str | None = None) -> OpenLot:
    return OpenLot(
        lot_id=lot_id,
        instrument_id=1,
        universe_id=1,
        quantity_open=qty,
        unit_cost=D(cost),
        acquired_on=TODAY - timedelta(days=lot_id),
        synthetic_cost_basis=D(synthetic) if synthetic else None,
    )


def test_sells_split_into_tranches_and_round_up() -> None:
    tranches, skipped = plan_sells(
        [lot(1, 10, "100"), lot(2, 5, "85", synthetic="200")],
        {1: SellInput("EQUITY", D("3.5"), D("0.05"), sellable_quantity=None)},
    )
    assert skipped == []
    by_kind = {t.basis_kind: t for t in tranches}
    assert by_kind[BasisKind.ACTUAL].target_price == D("103.5000")
    assert by_kind[BasisKind.SYNTHETIC].target_price == D("207.0000")


def test_nothing_sellable_is_skipped_with_a_reason() -> None:
    tranches, skipped = plan_sells(
        [lot(1, 10, "100")], {1: SellInput("EQUITY", D("3.5"), D("0.05"), sellable_quantity=0)}
    )
    assert tranches == []
    assert "nothing sellable" in skipped[0].reason
