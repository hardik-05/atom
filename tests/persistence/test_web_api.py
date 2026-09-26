"""The console API over HTTP, against the real schema and the fake broker."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atom.adapters.fake import FakeAdapter, FakeBrokerState
from atom.domain.models import CanonicalCandle
from atom.infra import secrets as paths
from atom.infra.clock import today_ist
from atom.infra.secrets import MemorySecretStore
from atom.infra.settings import Settings
from atom.orchestration.engine import Engine
from atom.orchestration.jobs import JobRunner
from atom.persistence.db import DbSettings, make_pool, transaction
from atom.persistence.migrate import apply_all
from atom.persistence.repositories import instruments, market, universes
from atom.web import security
from atom.web.app import create_app

D = Decimal
HDR = {"X-Atom-Request": "1"}
TOTP = security.new_totp_secret()


@pytest.fixture
def client(migrated_dsn: str) -> Iterator[tuple[TestClient, FakeBrokerState]]:
    apply_all(migrated_dsn, drop_schema_first=True)
    pool = make_pool(
        DbSettings(
            dsn=migrated_dsn,
            min_size=1,
            max_size=4,
            connect_timeout_sec=10,
            statement_timeout_ms=30_000,
        )
    )
    pool.open()
    secrets = MemorySecretStore(
        {
            paths.CONSOLE_USERNAME: "operator",
            paths.CONSOLE_PASSWORD_HASH: security.hash_password("a long enough password"),
            paths.CONSOLE_TOTP: TOTP,
            paths.CONSOLE_SESSION_KEY: "s" * 48,
        }
    )
    state = FakeBrokerState()
    fake = FakeAdapter(state)
    settings = Settings(
        env="dev",
        region="ap-south-1",
        public_base_url="http://testserver",
        secret_backend="memory",
        static_dir=None,
        activity_marker=None,
        cookie_secure=False,
    )
    engine = Engine(
        pool=pool, secrets=secrets, settings=settings, adapter_factory=lambda code, conn, eng: fake
    )
    jobs = JobRunner()
    with TestClient(create_app(engine, jobs)) as c:
        yield c, state
    jobs.shutdown()
    pool.close()


def login(c: TestClient) -> None:
    code = security.totp_at(TOTP, int(time.time()) // 30)
    r = c.post(
        "/api/auth/login",
        headers=HDR,
        json={"username": "operator", "password": "a long enough password", "totp": code},
    )
    assert r.status_code == 200, r.text


def test_everything_but_health_requires_a_session(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/accounts").status_code == 401


def test_a_mutation_without_the_request_header_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    r = c.post("/api/auth/login", json={"username": "x", "password": "y", "totp": "000000"})
    assert r.status_code == 403


def test_one_message_for_every_login_failure(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    bad_totp = c.post(
        "/api/auth/login",
        headers=HDR,
        json={"username": "operator", "password": "a long enough password", "totp": "000000"},
    )
    bad_user = c.post(
        "/api/auth/login",
        headers=HDR,
        json={"username": "someone", "password": "x", "totp": "000000"},
    )
    assert bad_totp.status_code == bad_user.status_code == 401
    assert bad_totp.json() == bad_user.json()


def test_the_whole_console_flow(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    login(c)
    assert c.get("/api/auth/me").json()["user"] == "operator"

    investor = c.post(
        "/api/investors",
        headers=HDR,
        json={
            "external_key": "INV-NIDHI",
            "display_name": "Nidhi",
            "relationship": "SELF",
            "onboarded_on": today_ist().isoformat(),
        },
    ).json()["investor_id"]
    created = c.post(
        "/api/accounts",
        headers=HDR,
        json={
            "investor_id": investor,
            "broker_code": "UPSTOX",
            "broker_client_code": "nid001",
            "execution_mode": "DRY",
        },
    ).json()
    account = created["trading_account_id"]
    assert "/atom/brokers/upstox/" in created["next_step"]

    # token: authorize URL, then the pasted code
    assert c.post(f"/api/accounts/{account}/token/authorize", headers=HDR).json()["url"]
    exchanged = c.post(
        f"/api/accounts/{account}/token/exchange", headers=HDR, json={"code": "pasted-code"}
    ).json()
    assert exchanged["ok"] and exchanged["onboarding"]["mode"] == "DRY"

    # funds come back with money as a STRING, never a float
    funds = c.get(f"/api/accounts/{account}/funds").json()
    assert funds["available_cash"] == "1000000.0000"


def test_plan_release_settle_over_http(client, migrated_dsn: str) -> None:  # type: ignore[no-untyped-def]
    c, state = client
    login(c)
    investor = c.post(
        "/api/investors",
        headers=HDR,
        json={
            "external_key": "INV-2",
            "display_name": "Nidhi",
            "relationship": "SELF",
            "onboarded_on": today_ist().isoformat(),
        },
    ).json()["investor_id"]
    account = c.post(
        "/api/accounts",
        headers=HDR,
        json={
            "investor_id": investor,
            "broker_code": "UPSTOX",
            "broker_client_code": "NID002",
            "execution_mode": "DRY",
        },
    ).json()["trading_account_id"]

    pool = make_pool(
        DbSettings(
            dsn=migrated_dsn,
            min_size=1,
            max_size=1,
            connect_timeout_sec=10,
            statement_timeout_ms=30_000,
        )
    )
    pool.open()
    today = today_ist()
    with transaction(pool) as conn:
        broker_id = instruments.broker_id_for(conn, "UPSTOX")
        universe = universes.create_universe(
            conn, name="API ETFs", source="MANUAL", created_by="test", categories=["EQUITY"]
        )
        iid = instruments.upsert_instrument(
            conn,
            isin="INF000000ZZ9",
            symbol="ZZZ",
            name="ZZZ",
            instrument_type="ETF",
            asset_class="EQUITY",
            tick_size=D("0.01"),
        )
        instruments.upsert_broker_instrument(
            conn,
            broker_id=broker_id,
            instrument_id=iid,
            broker_token=str(iid),
            broker_symbol="ZZZ",
            tradable=True,
        )
        universes.set_member(
            conn, universe_id=universe, instrument_id=iid, member_status="ACTIVE", changed_by="test"
        )
        market.upsert_candles(
            conn,
            instrument_id=iid,
            source="TEST",
            candles=[
                CanonicalCandle(
                    trade_date=today - timedelta(days=n),
                    open=D("50"),
                    high=D("51"),
                    low=D("49"),
                    close=D("50"),
                    volume=90_000,
                )
                for n in range(1, 6)
            ],
        )
    pool.close()

    changes = [
        {"key_name": k, "value_text": v}
        for k, v in {
            "category_priority": "EQUITY",
            "daily_spend_cap_inr": "20000",
            "max_orders_per_run": "5",
            "dry_run": "true",
            "budget_buffer_pct": "99",
            "buy_limit_premium_pct": "0",
            "kill_switch": "false",
            "market_open_gate_time": "09:30",
        }.items()
    ]
    changes += [
        {"key_name": k, "category_code": "EQUITY", "value_text": v}
        for k, v in {
            "profit_target_pct": "3",
            "depth_levels": "2",
            "trade_amount_inr": "5000",
            "lookback_days": "5",
            "average_method": "MEDIAN",
            "category_enabled": "true",
            "nav_check_enabled": "false",
            "nav_premium_tolerance_pct": "1",
            "volume_threshold_units": "1000",
            "volume_window_days": "5",
        }.items()
    ]
    view = c.put(
        "/api/config",
        headers=HDR,
        json={"account_id": account, "universe_id": universe, "changes": changes},
    ).json()
    assert view["status"]["ok"], view["status"]

    # planning before a token is refused at pre-flight with a named gate
    no_token = c.post(
        "/api/runs/plan", headers=HDR, json={"account_id": account, "universe_id": universe}
    )
    assert no_token.status_code == 409 and no_token.json()["gate"] == "onboarding"

    c.post(f"/api/accounts/{account}/token/exchange", headers=HDR, json={"code": "abc123"})
    state.quotes = {iid: D("45")}
    planned = c.post(
        "/api/runs/plan", headers=HDR, json={"account_id": account, "universe_id": universe}
    )
    assert planned.status_code == 201, planned.text
    run_id = planned.json()["run_id"]

    detail = c.get(f"/api/runs/{run_id}").json()
    [order] = detail["orders"]
    assert (
        order["status"] == "INTENT"
        and order["limit_price"] == "45.0000"
        and order["quantity"] == 110
    )

    assert c.post(f"/api/runs/{run_id}/release", headers=HDR).json()["placed"] == 1
    state.candles = {
        iid: [
            CanonicalCandle(
                trade_date=today, open=D("46"), high=D("46"), low=D("44"), close=D("45"), volume=1
            )
        ]
    }
    settled = c.post(f"/api/runs/{run_id}/settle", headers=HDR).json()
    assert settled["new_fills"] == 1
    positions = c.get(f"/api/accounts/{account}/positions").json()
    assert positions[0]["quantity_open"] == 110


def test_an_unconfigured_console_leaks_nothing_to_anonymous_callers(migrated_dsn: str) -> None:
    """Before console-setup, an anonymous request is a plain 401 — not an error
    naming which SSM parameter is missing — and sign-in says what to run."""
    pool = make_pool(
        DbSettings(
            dsn=migrated_dsn,
            min_size=1,
            max_size=1,
            connect_timeout_sec=10,
            statement_timeout_ms=30_000,
        )
    )
    settings = Settings(
        env="dev",
        region="ap-south-1",
        public_base_url="http://testserver",
        secret_backend="memory",
        static_dir=None,
        activity_marker=None,
        cookie_secure=False,
    )
    engine = Engine(pool=pool, secrets=MemorySecretStore(), settings=settings)
    jobs = JobRunner()
    with TestClient(create_app(engine, jobs)) as c:
        anonymous = c.get("/api/overview")
        assert anonymous.status_code == 401
        assert "/atom/" not in anonymous.text
        forged = c.get("/api/overview", cookies={"atom_session": "a.b"})
        assert forged.status_code == 401
        login = c.post(
            "/api/auth/login",
            headers=HDR,
            json={"username": "x", "password": "y", "totp": "000000"},
        )
        assert login.status_code == 503 and "console-setup" in login.json()["error"]
        assert "/atom/" not in login.text
    jobs.shutdown()
