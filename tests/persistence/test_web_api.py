"""The console API over HTTP, against the real schema and the fake broker."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

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
    yield from _serve(migrated_dsn, static_dir=None)


@pytest.fixture
def site(migrated_dsn: str, tmp_path: Path) -> Iterator[TestClient]:
    """The app serving a stand-in web/dist: the console shell and bundle, and the
    public placeholder pages under site/."""
    (tmp_path / "index.html").write_text("CONSOLE SHELL")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("CONSOLE BUNDLE")
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "home.html").write_text("PLACEHOLDER HOME")
    (tmp_path / "site" / "login.html").write_text("SIGN IN")
    (tmp_path / "site" / "site.css").write_text("body{}")
    for c, _ in _serve(migrated_dsn, static_dir=tmp_path):
        yield c


def _serve(
    migrated_dsn: str, *, static_dir: Path | None
) -> Iterator[tuple[TestClient, FakeBrokerState]]:
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
        static_dir=static_dir,
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


def password_step(c: TestClient) -> None:
    r = c.post(
        "/api/auth/password",
        headers=HDR,
        json={"username": "operator", "password": "a long enough password"},
    )
    assert r.status_code == 200 and r.json() == {"next": "totp"}, r.text


def login(c: TestClient) -> None:
    password_step(c)
    code = security.totp_at(TOTP, int(time.time()) // 30)
    r = c.post("/api/auth/totp", headers=HDR, json={"totp": code})
    assert r.status_code == 200, r.text


def test_everything_but_health_requires_a_session(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/accounts").status_code == 401


def test_a_mutation_without_the_request_header_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    r = c.post("/api/auth/password", json={"username": "x", "password": "y"})
    assert r.status_code == 403


def test_one_message_for_every_login_failure(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    bad_user = c.post(
        "/api/auth/password", headers=HDR, json={"username": "someone", "password": "x"}
    )
    bad_password = c.post(
        "/api/auth/password", headers=HDR, json={"username": "operator", "password": "x"}
    )
    password_step(c)
    bad_totp = c.post("/api/auth/totp", headers=HDR, json={"totp": "000000"})
    assert bad_user.status_code == bad_password.status_code == bad_totp.status_code == 401
    assert bad_user.json() == bad_password.json() == bad_totp.json()


def test_the_password_alone_is_not_a_session(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    password_step(c)
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/auth/me").status_code == 401


def test_the_code_step_needs_the_password_step_first(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    code = security.totp_at(TOTP, int(time.time()) // 30)
    r = c.post("/api/auth/totp", headers=HDR, json={"totp": code})
    assert r.status_code == 401 and r.json()["restart"] is True
    assert c.get("/api/overview").status_code == 401


def test_both_steps_share_one_lockout(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    password_step(c)
    for _ in range(security.MAX_FAILURES):
        c.post("/api/auth/totp", headers=HDR, json={"totp": "000000"})
    r = c.post(
        "/api/auth/password",
        headers=HDR,
        json={"username": "operator", "password": "a long enough password"},
    )
    assert r.status_code == 429


def test_signing_in_clears_the_pending_cookie(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    login(c)
    assert security.PENDING_COOKIE not in c.cookies
    assert c.get("/api/auth/me").json()["user"] == "operator"


def test_an_anonymous_visitor_sees_only_the_placeholder(site: TestClient) -> None:
    assert site.get("/").text == "PLACEHOLDER HOME"
    assert site.get("/overview").text == "PLACEHOLDER HOME"
    assert site.get("/login").text == "SIGN IN"
    assert site.get("/site/site.css").status_code == 200
    assert site.get("/assets/app.js").status_code == 404
    assert site.get("/index.html").status_code == 404
    assert site.get("/api/nothing").status_code == 404


def test_the_password_alone_does_not_open_the_console(site: TestClient) -> None:
    password_step(site)
    assert site.get("/").text == "PLACEHOLDER HOME"
    assert site.get("/assets/app.js").status_code == 404


def test_a_signed_in_operator_lands_on_the_console(site: TestClient) -> None:
    login(site)
    assert site.get("/").text == "CONSOLE SHELL"
    assert site.get("/overview").text == "CONSOLE SHELL"
    assert site.get("/assets/app.js").text == "CONSOLE BUNDLE"
    r = site.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_the_broker_callback_gets_the_shell_without_a_cookie(site: TestClient) -> None:
    """The broker's redirect is cross-site, so a SameSite=Strict cookie is absent."""
    assert site.get("/brokers/upstox/callback?code=x").text == "CONSOLE SHELL"
    assert site.get("/assets/app.js").status_code == 404


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
            "depository_authorisation": "DDPI",
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
            "depository_authorisation": "DDPI",
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
        universes.replace_shortlist(
            conn,
            account_id=account,
            universe_id=universe,
            category="EQUITY",
            rows=[(iid, 1, D("90000"), 5)],
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
            "shortlist_size": "10",
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
        login = c.post("/api/auth/password", headers=HDR, json={"username": "x", "password": "y"})
        assert login.status_code == 503 and "console-setup" in login.json()["error"]
        assert "/atom/" not in login.text
    jobs.shutdown()


def _code() -> str:
    return security.totp_at(TOTP, int(time.time()) // 30)


NEW_PASSWORD = "a brand new password"


def reset_verify(c: TestClient, *, username: str = "operator", totp: str | None = None):  # type: ignore[no-untyped-def]
    return c.post(
        "/api/auth/reset/verify",
        headers=HDR,
        json={"username": username, "totp": totp or _code()},
    )


def reset_password(c: TestClient, new_password: str = NEW_PASSWORD):  # type: ignore[no-untyped-def]
    return c.post("/api/auth/reset/password", headers=HDR, json={"new_password": new_password})


def test_forgot_password_is_two_screens(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert reset_verify(c).json() == {"next": "password"}
    assert reset_password(c).status_code == 200
    old = c.post(
        "/api/auth/password",
        headers=HDR,
        json={"username": "operator", "password": "a long enough password"},
    )
    new = c.post(
        "/api/auth/password",
        headers=HDR,
        json={"username": "operator", "password": NEW_PASSWORD},
    )
    assert old.status_code == 401 and new.status_code == 200


def test_a_wrong_code_or_user_is_refused_at_the_first_screen(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert reset_verify(c, totp="000000").status_code == 401
    assert reset_verify(c, username="someone").status_code == 401
    # nothing was verified, so the second screen has no standing
    r = reset_password(c)
    assert r.status_code == 401 and r.json()["restart"] is True
    password_step(c)  # the old password still works


def test_the_second_screen_refuses_a_short_password_and_keeps_the_proof(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    reset_verify(c)
    assert reset_password(c, "short").status_code == 422
    assert reset_password(c).status_code == 200


def test_a_reset_proof_is_not_a_session(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    reset_verify(c)
    assert c.get("/api/overview").status_code == 401


def test_a_reset_proof_works_once(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    reset_verify(c)
    stale = dict(c.cookies)
    assert reset_password(c).status_code == 200
    c.cookies.clear()
    for name, value in stale.items():
        c.cookies.set(name, value)
    assert reset_password(c, "yet another password").status_code == 401


def test_a_reset_signs_out_a_signed_in_browser(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    login(c)
    stale = dict(c.cookies)
    reset_verify(c)
    reset_password(c)
    c.cookies.clear()
    for name, value in stale.items():
        c.cookies.set(name, value)
    assert c.get("/api/overview").status_code == 401


def test_change_password_needs_the_current_one_and_keeps_this_browser_in(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    login(c)
    wrong = c.post(
        "/api/auth/change-password",
        headers=HDR,
        json={"current_password": "not it at all!!", "new_password": "a brand new password"},
    )
    assert wrong.status_code == 403
    ok = c.post(
        "/api/auth/change-password",
        headers=HDR,
        json={
            "current_password": "a long enough password",
            "new_password": "a brand new password",
        },
    )
    assert ok.status_code == 200
    assert c.get("/api/overview").status_code == 200
    c.cookies.clear()
    r = c.post(
        "/api/auth/password",
        headers=HDR,
        json={"username": "operator", "password": "a brand new password"},
    )
    assert r.status_code == 200


def test_change_password_requires_a_session(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    r = c.post(
        "/api/auth/change-password",
        headers=HDR,
        json={"current_password": "x", "new_password": "a brand new password"},
    )
    assert r.status_code == 401
