"""The engine end to end, against the real schema, with the fake broker.

Token → onboarding → config → market data → plan → release → settle, and then a
second trading day on which the position bought on the first is sold. Every
repository, the strategy and the runner run for real; only the broker is fake.

Skipped unless ATOM_TEST_DATABASE_URL is set. Each test gets a freshly migrated
schema, because the services commit — which is the point of testing them.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest

from atom.adapters.fake import FakeAdapter, FakeBrokerState
from atom.domain.errors import PreflightError
from atom.domain.models import CanonicalCandle, CanonicalHolding
from atom.infra.secrets import MemorySecretStore
from atom.infra.settings import Settings
from atom.orchestration import runner as runner_module
from atom.orchestration import services as services_module
from atom.orchestration.engine import Engine
from atom.orchestration.runner import RunService
from atom.orchestration.services import ConfigService, TokenService
from atom.persistence.db import DbSettings, fetch_all, make_pool, transaction
from atom.persistence.migrate import apply_all
from atom.persistence.repositories import accounts, instruments, market, universes

D = Decimal
DAY1 = date(2026, 9, 28)  # a Monday
DAY2 = DAY1 + timedelta(days=1)

ALL_KEYS = {
    "category_priority": "EQUITY",
    "daily_spend_cap_inr": "50000",
    "max_orders_per_run": "10",
    "dry_run": "false",
    "budget_buffer_pct": "99",
    "buy_limit_premium_pct": "0",
}
CATEGORY_KEYS = {
    "profit_target_pct": "3.5",
    "depth_levels": "3",
    "trade_amount_inr": "10000",
    "lookback_days": "5",
    "average_method": "MEAN",
    "category_enabled": "true",
    "nav_check_enabled": "false",
    "nav_premium_tolerance_pct": "2",
    "volume_threshold_units": "1000",
    "volume_window_days": "5",
}


@pytest.fixture
def fresh_dsn(migrated_dsn: str) -> str:
    apply_all(migrated_dsn, drop_schema_first=True)
    return migrated_dsn


@pytest.fixture
def world(fresh_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    pool = make_pool(
        DbSettings(
            dsn=fresh_dsn,
            min_size=1,
            max_size=4,
            connect_timeout_sec=10,
            statement_timeout_ms=30_000,
        )
    )
    pool.open()
    state = FakeBrokerState()
    fake = FakeAdapter(state)
    settings = Settings(
        env="dev",
        region="ap-south-1",
        public_base_url="http://localhost",
        secret_backend="memory",
        static_dir=None,
        activity_marker=None,
        cookie_secure=False,
    )
    engine = Engine(
        pool=pool,
        secrets=MemorySecretStore(),
        settings=settings,
        adapter_factory=lambda code, conn, eng: fake,
    )

    clock = {"today": DAY1}
    for module in (runner_module, services_module):
        monkeypatch.setattr(module, "today_ist", lambda: clock["today"])

    with transaction(pool) as conn:
        investor = accounts.create_investor(
            conn,
            external_key="INV-NIDHI",
            display_name="Nidhi",
            relationship="SELF",
            onboarded_on=DAY1,
        )
        account = accounts.create_account(
            conn,
            investor_id=investor,
            broker_code="UPSTOX",
            broker_client_code="NID001",
            execution_mode="DRY",
            egress_ip=None,
            proxy_url=None,
        )
        broker_id = instruments.broker_id_for(conn, "UPSTOX")
        universe = universes.create_universe(
            conn, name="Test ETFs", source="MANUAL", created_by="test", categories=["EQUITY"]
        )
        ids = {}
        for symbol, isin in (
            ("AAA", "INF000000AA1"),
            ("BBB", "INF000000BB2"),
            ("CCC", "INF000000CC3"),
        ):
            iid = instruments.upsert_instrument(
                conn,
                isin=isin,
                symbol=symbol,
                name=symbol,
                instrument_type="ETF",
                asset_class="EQUITY",
                tick_size=D("0.01"),
            )
            # The fake broker's token for an instrument is its id as a string.
            instruments.upsert_broker_instrument(
                conn,
                broker_id=broker_id,
                instrument_id=iid,
                broker_token=str(iid),
                broker_symbol=symbol,
                tradable=True,
            )
            universes.set_member(
                conn,
                universe_id=universe,
                instrument_id=iid,
                member_status="ACTIVE",
                changed_by="test",
            )
            ids[symbol] = iid
            # five days of history at 100, before DAY1
            market.upsert_candles(
                conn,
                instrument_id=iid,
                source="TEST",
                candles=[
                    CanonicalCandle(
                        trade_date=DAY1 - timedelta(days=n),
                        open=D("100"),
                        high=D("101"),
                        low=D("99"),
                        close=D("100"),
                        volume=50_000,
                    )
                    for n in range(1, 6)
                ],
            )

    config = ConfigService(engine)
    changes = [{"key_name": k, "value_text": v} for k, v in ALL_KEYS.items()]
    changes += [
        {"key_name": k, "category_code": "EQUITY", "value_text": v}
        for k, v in CATEGORY_KEYS.items()
    ]
    changes += [
        {"key_name": "kill_switch", "value_text": "false"},
        {"key_name": "market_open_gate_time", "value_text": "09:30"},
    ]
    config.set_values(account, universe, changes, actor="test")

    yield {
        "engine": engine,
        "pool": pool,
        "state": state,
        "fake": fake,
        "account": account,
        "universe": universe,
        "ids": ids,
        "clock": clock,
    }
    pool.close()


def rows(pool, sql: str, params: tuple = ()) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    with transaction(pool) as conn:
        return fetch_all(conn, sql, params)


def test_a_run_cannot_plan_before_onboarding(world: dict) -> None:
    with pytest.raises(PreflightError) as caught:
        RunService(world["engine"]).plan(
            account_id=world["account"], universe_id=world["universe"], actor="test"
        )
    assert caught.value.gate == "onboarding"


def test_a_token_for_a_different_client_is_discarded(world: dict) -> None:
    world["state"].profile_client_id = None
    fake: FakeAdapter = world["fake"]
    original = fake.exchange_code

    def wrong_client(account, code):  # type: ignore[no-untyped-def]
        token = original(account, code)
        return token.__class__(
            secret_ref=token.secret_ref,
            obtained_at=token.obtained_at,
            broker_client_id="SOMEONE-ELSE",
        )

    fake.exchange_code = wrong_client  # type: ignore[method-assign]
    with pytest.raises(Exception, match="belongs to broker client SOMEONE-ELSE"):
        TokenService(world["engine"]).exchange(world["account"], "code", actor="test")
    assert rows(world["pool"], "SELECT * FROM atom.broker_session") == []


def test_two_trading_days_buy_then_sell(world: dict) -> None:
    engine, pool, state, ids = world["engine"], world["pool"], world["state"], world["ids"]
    account, universe = world["account"], world["universe"]

    # ---- token + onboarding (DRY: the paper book starts empty)
    result = TokenService(engine).exchange(account, "the-code", actor="test")
    assert result["ok"] and result["onboarding"]["mode"] == "DRY"
    [session] = rows(pool, "SELECT status FROM atom.broker_session")
    assert session["status"] == "VALID"

    # ---- DAY1 plan: BBB is furthest below its mean and gets the buy
    state.quotes = {ids["AAA"]: D("97"), ids["BBB"]: D("90"), ids["CCC"]: D("103")}
    runs = RunService(engine)
    plan = runs.plan(account_id=account, universe_id=universe, actor="test")
    assert (plan.execution_mode, plan.buys, plan.sells, plan.candidates) == ("DRY", 1, 0, 3)

    candidates = {
        r["instrument_id"]: r
        for r in rows(pool, "SELECT * FROM atom.run_candidate WHERE run_id = %s", (plan.run_id,))
    }
    assert candidates[ids["BBB"]]["decision"] == "BOUGHT"
    # CCC is never reached: the category already has its buy (one per category per run)
    assert candidates[ids["CCC"]]["decision"] == "NOT_CONSIDERED"
    assert "already has its buy" in candidates[ids["CCC"]]["decision_reason"]
    [intent] = rows(pool, "SELECT * FROM atom.order_request WHERE run_id = %s", (plan.run_id,))
    assert intent["status"] == "INTENT"  # written before anything is sent (D-094)
    assert intent["quantity"] == 110 and intent["limit_price"] == D("90.0000")

    # a second plan the same day is refused, the first is still live
    with pytest.raises(PreflightError, match="already exists"):
        runs.plan(account_id=account, universe_id=universe, actor="test")

    # ---- release through the DRY gateway: nothing reaches the fake broker
    released = runs.release(plan.run_id, actor="test")
    assert released == {"placed": 1, "rejected": 0, "halted": None}
    assert "place_order" not in world["fake"].calls
    [sent] = rows(pool, "SELECT * FROM atom.order_request WHERE run_id = %s", (plan.run_id,))
    assert sent["broker_order_id"] == f"DRY-{sent['order_request_id']}"

    # ---- settle: the day's low reached the limit → filled at the limit, one lot
    state.candles = {
        ids["BBB"]: [
            CanonicalCandle(
                trade_date=DAY1,
                open=D("92"),
                high=D("93"),
                low=D("89.5"),
                close=D("91"),
                volume=60_000,
            )
        ]
    }
    settled = runs.settle(plan.run_id)
    assert settled["new_fills"] == 1 and settled.get("run_completed")
    assert runs.settle(plan.run_id)["new_fills"] == 0  # idempotent
    [lot] = rows(pool, "SELECT * FROM atom.position_lot")
    assert (lot["quantity_open"], lot["unit_cost"]) == (110, D("90.0000"))

    # ---- DAY2: BBB is held → it gets a sell tranche, and the buy moves to AAA
    world["clock"]["today"] = DAY2
    with transaction(pool) as conn:
        for iid in ids.values():
            market.upsert_candles(
                conn,
                instrument_id=iid,
                source="TEST",
                candles=[
                    CanonicalCandle(
                        trade_date=DAY1,
                        open=D("100"),
                        high=D("100"),
                        low=D("100"),
                        close=D("100"),
                        volume=50_000,
                    )
                ],
            )
    TokenService(engine).exchange(account, "day-two-code", actor="test")
    state.quotes = {ids["AAA"]: D("96"), ids["BBB"]: D("91"), ids["CCC"]: D("104")}
    plan2 = runs.plan(account_id=account, universe_id=universe, actor="test")
    assert (plan2.buys, plan2.sells) == (1, 1)
    orders2 = {
        o["side"]: o
        for o in rows(pool, "SELECT * FROM atom.order_request WHERE run_id = %s", (plan2.run_id,))
    }
    assert orders2["SELL"]["order_kind"] == "GTT"
    assert orders2["SELL"]["trigger_price"] == D("93.1500")  # 90 x 1.035, rounded UP
    assert orders2["BUY"]["instrument_id"] == ids["AAA"]
    cand2 = {
        r["instrument_id"]: r
        for r in rows(pool, "SELECT * FROM atom.run_candidate WHERE run_id = %s", (plan2.run_id,))
    }
    assert cand2[ids["BBB"]]["holdings_status"] == "HELD"

    runs.release(plan2.run_id, actor="test")
    state.candles = {
        ids["BBB"]: [
            CanonicalCandle(
                trade_date=DAY2,
                open=D("92"),
                high=D("94"),
                low=D("91"),
                close=D("93.5"),
                volume=70_000,
            )
        ],
        ids["AAA"]: [
            CanonicalCandle(
                trade_date=DAY2,
                open=D("97"),
                high=D("98"),
                low=D("96.5"),
                close=D("97"),
                volume=70_000,
            )
        ],
    }
    settled2 = runs.settle(plan2.run_id)
    assert settled2["new_fills"] == 1  # the GTT sell hit; the AAA buy's low never reached 96

    closures = rows(pool, "SELECT * FROM atom.lot_closure")
    assert [(c["quantity"], c["unit_proceeds"]) for c in closures] == [(110, D("93.1500"))]
    gain = rows(pool, "SELECT gain_on_actual_cost FROM atom.v_realised_gain")
    assert gain[0]["gain_on_actual_cost"] == D("346.5000")  # 110 x (93.15 - 90)


def test_a_discarded_plan_frees_the_day(world: dict) -> None:
    engine, state, ids = world["engine"], world["state"], world["ids"]
    TokenService(engine).exchange(world["account"], "code", actor="test")
    state.quotes = {ids["AAA"]: D("95")}
    runs = RunService(engine)
    first = runs.plan(account_id=world["account"], universe_id=world["universe"], actor="test")
    runs.discard(first.run_id, actor="test")
    second = runs.plan(account_id=world["account"], universe_id=world["universe"], actor="test")
    assert second.run_id != first.run_id
    [status] = rows(world["pool"], "SELECT status FROM atom.run WHERE run_id = %s", (first.run_id,))
    assert status["status"] == "FAILED"


def test_live_onboarding_excludes_what_was_already_held(world: dict) -> None:
    """D-137: ATOM manages only what ATOM bought."""
    pool, ids = world["pool"], world["ids"]
    with transaction(pool) as conn:
        conn.execute(
            "UPDATE atom.trading_account SET execution_mode = 'LIVE', "
            "egress_ip = '13.127.7.83', proxy_url = 'http://127.0.0.1:3128'"
        )
    world["state"].holdings = {
        ids["CCC"]: CanonicalHolding(
            instrument_id=ids["CCC"], total_quantity=40, average_price=D("80"), free_quantity=40
        )
    }
    result = TokenService(world["engine"]).exchange(world["account"], "code", actor="test")
    assert result["onboarding"]["excluded"] == [{"instrument_id": ids["CCC"], "quantity": 40}]
    [excl] = rows(pool, "SELECT * FROM atom.account_exclusion")
    assert (excl["exclusion_type"], excl["quantity"]) == ("EXCLUSION", 40)
