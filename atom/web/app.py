"""The console API, and the SPA it serves.

One process, one origin: the browser loads the React app and calls ``/api`` on
the same host, so there is no CORS to configure and no API reachable from a
page ATOM did not serve. The browser holds no database or broker credential;
every request goes through here (AUTH-AND-ACCESS.md).

Money leaves as STRINGS. FastAPI's default encoder turns ``Decimal`` into
``float``, which would round a price in binary on its way to the screen; every
response here is built by ``_json`` instead.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from atom.domain.errors import (
    AtomError,
    AuthError,
    BrokerError,
    ConfigError,
    IpBlockedError,
    PreflightError,
    ReconciliationError,
    ValidationError,
)
from atom.infra import secrets as paths
from atom.infra.clock import today_ist
from atom.infra.secrets import SecretNotFoundError
from atom.orchestration.engine import Engine
from atom.orchestration.jobs import Job, JobRunner
from atom.orchestration.runner import RunService
from atom.orchestration.services import (
    ConfigService,
    DataService,
    ReferenceService,
    TokenService,
)
from atom.persistence.db import QueryShapeError, transaction
from atom.persistence.repositories import accounts, instruments, orders, runs, universes
from atom.web import security

CSRF_HEADER = "x-atom-request"


# ---------------------------------------------------------------- encoding


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return str(value)


class AtomJSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=_default, separators=(",", ":")).encode()


def _json(content: Any, status: int = 200) -> AtomJSON:
    return AtomJSON(content=content, status_code=status)


def _job(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


# ------------------------------------------------------------------ bodies


class LoginBody(BaseModel):
    username: str
    password: str
    totp: str


class InvestorBody(BaseModel):
    external_key: str = Field(min_length=3, max_length=40)
    display_name: str = Field(min_length=1, max_length=80)
    relationship: str
    onboarded_on: date


class AccountBody(BaseModel):
    investor_id: int
    broker_code: str
    broker_client_code: str = Field(min_length=2, max_length=40)
    execution_mode: str
    egress_ip: str | None = None
    proxy_url: str | None = None


class CodeBody(BaseModel):
    code: str = Field(min_length=4, max_length=512)


class QuotesBody(BaseModel):
    instrument_ids: list[int] = Field(min_length=1, max_length=500)


class SyncHistoryBody(BaseModel):
    account_id: int
    universe_id: int
    days: int = Field(ge=5, le=1500)


class SyncInstrumentsBody(BaseModel):
    broker_code: str


class ConfigChange(BaseModel):
    key_name: str
    category_code: str | None = None
    value_text: str | None = None


class ConfigBody(BaseModel):
    account_id: int
    universe_id: int
    changes: list[ConfigChange]


class PlanBody(BaseModel):
    account_id: int
    universe_id: int


class MemberBody(BaseModel):
    member_status: str
    reason: str | None = None


# --------------------------------------------------------------------- app


def create_app(engine: Engine, jobs: JobRunner) -> FastAPI:
    app = FastAPI(title="ATOM", docs_url=None, redoc_url=None, openapi_url=None)
    throttle = security.LoginThrottle()
    key_cache: dict[str, tuple[float, str]] = {}

    tokens = TokenService(engine)
    data = DataService(engine)
    reference = ReferenceService(engine)
    config_service = ConfigService(engine)
    run_service = RunService(engine)

    def secret(path: str) -> str:
        """Console secrets, cached for five minutes: an SSM round trip per request
        would add latency to every click, and rotation still lands promptly."""
        hit = key_cache.get(path)
        if hit and time.monotonic() - hit[0] < 300:
            return hit[1]
        value = engine.secrets.get(path)
        key_cache[path] = (time.monotonic(), value)
        return value

    # ---------------------------------------------------------- middleware
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        # A custom header cannot be sent cross-origin without a CORS preflight this
        # server never approves — so its presence on a mutation proves same-origin.
        mutating = request.method not in ("GET", "HEAD", "OPTIONS")
        if path.startswith("/api/") and mutating and request.headers.get(CSRF_HEADER) != "1":
            return _json({"error": "missing request header", "type": "Forbidden"}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AtomError)
    async def atom_error(request: Request, exc: AtomError) -> Response:
        status = 400
        if isinstance(exc, PreflightError):
            status = 409
        elif isinstance(exc, ConfigError):
            status = 422
        elif isinstance(exc, (ReconciliationError, AuthError, IpBlockedError)):
            status = 409
        elif isinstance(exc, ValidationError):
            status = 400
        elif isinstance(exc, BrokerError):
            status = 502
        elif isinstance(exc, QueryShapeError):
            status = 404
        body = {"error": str(exc), "type": type(exc).__name__, "gate": getattr(exc, "gate", None)}
        return _json(body, status)

    @app.exception_handler(LookupError)
    async def lookup_error(request: Request, exc: LookupError) -> Response:
        return _json({"error": str(exc), "type": "LookupError"}, 409)

    # ---------------------------------------------------------------- auth
    def current_user(request: Request) -> str:
        cookie = request.cookies.get(security.SESSION_COOKIE)
        if not cookie:
            # Decided before any secret is read: an anonymous request must get a
            # plain 401, never an error that reveals how the console is set up.
            raise _UnauthorisedError()
        try:
            key = secret(paths.CONSOLE_SESSION_KEY)
        except SecretNotFoundError:
            raise _UnauthorisedError() from None
        user = security.read_session(cookie, key)
        if user is None:
            raise _UnauthorisedError()
        marker = engine.settings.activity_marker
        if marker is not None:
            # The idle-shutdown timer stops the instance after an hour without
            # this file being touched. Only authenticated use counts.
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(str(int(time.time())))
            except OSError:
                pass
        return user

    @app.exception_handler(_UnauthorisedError)
    async def unauthorised(request: Request, exc: _UnauthorisedError) -> Response:
        return _json({"error": "not signed in", "type": "Unauthorised"}, 401)

    public = APIRouter(prefix="/api")
    api = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

    @public.get("/health")
    def health() -> Response:
        return _json({"ok": True, "env": engine.settings.env, "today": today_ist()})

    @public.post("/auth/login")
    def login(body: LoginBody, request: Request) -> Response:
        client = request.client.host if request.client else "unknown"
        wait = throttle.locked_for(client)
        if wait:
            return _json({"error": f"too many attempts; try again in {wait // 60 + 1} min"}, 429)
        try:
            ok = (
                body.username == secret(paths.CONSOLE_USERNAME)
                and security.verify_password(body.password, secret(paths.CONSOLE_PASSWORD_HASH))
                and security.verify_totp(secret(paths.CONSOLE_TOTP), body.totp)
            )
        except SecretNotFoundError:
            # The operator needs to know the console is not set up; the SSM path
            # and which part is missing stay in the engine's own log.
            message = (
                "console sign-in is not configured yet — run: python -m atom.cli console-setup"
            )
            return _json({"error": message}, 503)
        if not ok:
            throttle.fail(client)
            # One message for every failure: which factor was wrong is information
            # an attacker would like to have and the operator does not need.
            return _json({"error": "sign-in failed"}, 401)
        throttle.succeed(client)
        response = _json({"user": body.username})
        response.set_cookie(
            security.SESSION_COOKIE,
            security.sign_session(body.username, secret(paths.CONSOLE_SESSION_KEY)),
            max_age=security.SESSION_SECONDS,
            httponly=True,
            secure=engine.settings.cookie_secure,
            samesite="strict",
            path="/",
        )
        with transaction(engine.pool) as conn:
            accounts.audit(conn, actor=body.username, action="console_login", entity="console")
        return response

    @public.post("/auth/logout")
    def logout() -> Response:
        response = _json({"ok": True})
        response.delete_cookie(security.SESSION_COOKIE, path="/")
        return response

    @api.get("/auth/me")
    def me(user: str = Depends(current_user)) -> Response:
        return _json(
            {
                "user": user,
                "env": engine.settings.env,
                "upstox_redirect_uri": engine.settings.upstox_redirect_uri,
            }
        )

    # ------------------------------------------------------------ overview
    @api.get("/overview")
    def overview() -> Response:
        today = today_ist()
        with transaction(engine.pool) as conn:
            accts = accounts.list_accounts(conn)
            for a in accts:
                a["session"] = accounts.get_session(conn, int(a["trading_account_id"]), today)
            body = {
                "today": today,
                "accounts": accts,
                "universes": universes.list_universes(conn),
                "runs": runs.list_runs(conn, limit=10),
                "instrument_counts": instruments.counts(
                    conn, broker_id=instruments.broker_id_for(conn, "UPSTOX")
                ),
            }
        body["jobs"] = [_job(j) for j in jobs.recent()[:10]]
        return _json(body)

    # -------------------------------------------------- investors, accounts
    @api.get("/brokers")
    def brokers() -> Response:
        with transaction(engine.pool) as conn:
            return _json(accounts.list_brokers(conn))

    @api.get("/investors")
    def investors() -> Response:
        with transaction(engine.pool) as conn:
            return _json(accounts.list_investors(conn))

    @api.post("/investors")
    def create_investor(body: InvestorBody, user: str = Depends(current_user)) -> Response:
        with transaction(engine.pool) as conn:
            iid = accounts.create_investor(
                conn,
                external_key=body.external_key,
                display_name=body.display_name,
                relationship=body.relationship,
                onboarded_on=body.onboarded_on,
            )
            accounts.audit(
                conn, actor=user, action="investor_created", entity="investor", entity_id=iid
            )
        return _json({"investor_id": iid}, 201)

    @api.get("/accounts")
    def list_accounts() -> Response:
        with transaction(engine.pool) as conn:
            return _json(accounts.list_accounts(conn))

    @api.post("/accounts")
    def create_account(body: AccountBody, user: str = Depends(current_user)) -> Response:
        if body.execution_mode not in ("LIVE", "DRY"):
            raise ValidationError("execution_mode must be LIVE or DRY")
        with transaction(engine.pool) as conn:
            aid = accounts.create_account(
                conn,
                investor_id=body.investor_id,
                broker_code=body.broker_code,
                broker_client_code=body.broker_client_code.strip().upper(),
                execution_mode=body.execution_mode,
                egress_ip=body.egress_ip,
                proxy_url=body.proxy_url,
            )
            accounts.audit(
                conn,
                actor=user,
                action="account_created",
                entity="trading_account",
                entity_id=aid,
                payload={"mode": body.execution_mode},
            )
        return _json(
            {
                "trading_account_id": aid,
                "next_step": (
                    "store the broker app's credentials in SSM: "
                    f"{paths.broker_secret_path(body.broker_code, aid, 'api_key')} and "
                    f"{paths.broker_secret_path(body.broker_code, aid, 'api_secret')}"
                ),
            },
            201,
        )

    @api.get("/accounts/{account_id}")
    def get_account(account_id: int) -> Response:
        with transaction(engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            acct["session"] = accounts.get_session(conn, account_id, today_ist())
            acct["secrets_present"] = {
                name: engine.secrets.exists(
                    paths.broker_secret_path(acct["broker_code"], account_id, name)
                )
                for name in ("api_key", "api_secret")
            }
        return _json(acct)

    # --------------------------------------------------------------- tokens
    @api.post("/accounts/{account_id}/token/authorize")
    def authorize(account_id: int) -> Response:
        return _json({"url": tokens.auth_url(account_id)})

    @api.post("/accounts/{account_id}/token/exchange")
    def exchange(account_id: int, body: CodeBody, user: str = Depends(current_user)) -> Response:
        return _json(tokens.exchange(account_id, body.code, actor=user))

    @api.post("/accounts/{account_id}/token/probe")
    def probe(account_id: int) -> Response:
        return _json(tokens.probe(account_id))

    @api.delete("/accounts/{account_id}/token")
    def clear(account_id: int, user: str = Depends(current_user)) -> Response:
        tokens.clear(account_id, actor=user)
        return _json({"ok": True})

    # ----------------------------------------------------------------- data
    @api.get("/accounts/{account_id}/funds")
    def funds(account_id: int) -> Response:
        return _json(data.funds(account_id))

    @api.get("/accounts/{account_id}/holdings")
    def holdings(account_id: int) -> Response:
        return _json(data.holdings(account_id))

    @api.post("/accounts/{account_id}/quotes")
    def quotes(account_id: int, body: QuotesBody) -> Response:
        return _json(data.quotes(account_id, body.instrument_ids))

    @api.get("/accounts/{account_id}/candles")
    def candles(
        account_id: int, instrument_id: int, days: int = 90, store: bool = False
    ) -> Response:
        to_date = today_ist() - timedelta(days=1)
        from_date = to_date - timedelta(days=max(5, min(days, 1500)))
        return _json(data.candles(account_id, instrument_id, from_date, to_date, store=store))

    @api.get("/accounts/{account_id}/positions")
    def positions(account_id: int) -> Response:
        with transaction(engine.pool) as conn:
            return _json(orders.positions(conn, account_id))

    @api.get("/accounts/{account_id}/exclusions")
    def exclusions(account_id: int) -> Response:
        with transaction(engine.pool) as conn:
            return _json(orders.active_exclusions(conn, account_id))

    # ---------------------------------------------------- reference, market
    @api.get("/instruments")
    def search_instruments(q: str = "", broker_code: str = "UPSTOX") -> Response:
        with transaction(engine.pool) as conn:
            broker_id = instruments.broker_id_for(conn, broker_code)
            return _json(instruments.search(conn, q, broker_id=broker_id, limit=50) if q else [])

    @api.post("/reference/import")
    def import_reference(user: str = Depends(current_user)) -> Response:
        return _json(reference.import_reference(actor=user))

    @api.post("/instruments/sync")
    def sync_instruments(body: SyncInstrumentsBody) -> Response:
        job = jobs.submit(
            "instrument_sync", lambda j: reference.sync_instruments(j, broker_code=body.broker_code)
        )
        return _json(_job(job), 202)

    @api.post("/market/sync-history")
    def sync_history(body: SyncHistoryBody) -> Response:
        job = jobs.submit(
            "history_sync",
            lambda j: data.sync_history(
                j, account_id=body.account_id, universe_id=body.universe_id, days=body.days
            ),
        )
        return _json(_job(job), 202)

    @api.post("/market/sync-nav")
    def sync_nav() -> Response:
        return _json(_job(jobs.submit("nav_sync", data.sync_nav)), 202)

    @api.get("/market/coverage")
    def coverage(universe_id: int, broker_code: str = "UPSTOX") -> Response:
        return _json(data.coverage(universe_id, broker_code))

    @api.get("/jobs")
    def list_jobs() -> Response:
        return _json([_job(j) for j in jobs.recent()])

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str) -> Response:
        job = jobs.get(job_id)
        return _json(_job(job)) if job else _json({"error": "no such job"}, 404)

    # ------------------------------------------------------------ universes
    @api.get("/universes")
    def list_universes() -> Response:
        with transaction(engine.pool) as conn:
            return _json(universes.list_universes(conn))

    @api.get("/universes/{universe_id}/members")
    def members(universe_id: int, broker_code: str = "UPSTOX") -> Response:
        with transaction(engine.pool) as conn:
            broker_id = instruments.broker_id_for(conn, broker_code)
            return _json(universes.current_members(conn, universe_id, broker_id=broker_id))

    @api.put("/universes/{universe_id}/members/{instrument_id}")
    def set_member(
        universe_id: int, instrument_id: int, body: MemberBody, user: str = Depends(current_user)
    ) -> Response:
        if body.member_status not in ("ACTIVE", "FROZEN"):
            raise ValidationError("member_status must be ACTIVE or FROZEN")
        with transaction(engine.pool) as conn:
            changed = universes.set_member(
                conn,
                universe_id=universe_id,
                instrument_id=instrument_id,
                member_status=body.member_status,
                changed_by=user,
                reason=body.reason,
            )
            accounts.audit(
                conn,
                actor=user,
                action="universe_member_status",
                entity="universe",
                entity_id=universe_id,
                payload={"instrument_id": instrument_id, "status": body.member_status},
            )
        return _json({"changed": changed})

    # --------------------------------------------------------------- config
    @api.get("/config")
    def get_config(account_id: int, universe_id: int) -> Response:
        return _json(config_service.view(account_id, universe_id))

    @api.put("/config")
    def put_config(body: ConfigBody, user: str = Depends(current_user)) -> Response:
        config_service.set_values(
            body.account_id, body.universe_id, [c.model_dump() for c in body.changes], actor=user
        )
        return _json(config_service.view(body.account_id, body.universe_id))

    # ----------------------------------------------------------------- runs
    @api.get("/runs")
    def list_runs() -> Response:
        with transaction(engine.pool) as conn:
            return _json(runs.list_runs(conn, limit=100))

    @api.post("/runs/plan")
    def plan(body: PlanBody, user: str = Depends(current_user)) -> Response:
        result = run_service.plan(
            account_id=body.account_id, universe_id=body.universe_id, actor=user
        )
        return _json(result, 201)

    @api.get("/runs/{run_id}")
    def get_run(run_id: int) -> Response:
        with transaction(engine.pool) as conn:
            return _json(
                {
                    "run": runs.get_run(conn, run_id),
                    "candidates": runs.candidates(conn, run_id),
                    "orders": orders.orders_for_run(conn, run_id),
                    "logs": runs.logs(conn, run_id),
                }
            )

    @api.post("/runs/{run_id}/release")
    def release(run_id: int, user: str = Depends(current_user)) -> Response:
        return _json(run_service.release(run_id, actor=user))

    @api.post("/runs/{run_id}/settle")
    def settle(run_id: int) -> Response:
        return _json(run_service.settle(run_id))

    @api.post("/runs/{run_id}/discard")
    def discard(run_id: int, user: str = Depends(current_user)) -> Response:
        run_service.discard(run_id, actor=user)
        return _json({"ok": True})

    @api.get("/audit")
    def audit() -> Response:
        with transaction(engine.pool) as conn:
            return _json(accounts.recent_audit(conn, limit=200))

    app.include_router(public)
    app.include_router(api)

    # ------------------------------------------------------------------ SPA
    static = engine.settings.static_dir
    if static is not None and (static / "index.html").exists():
        _mount_spa(app, static)
    return app


class _UnauthorisedError(Exception):
    pass


def _mount_spa(app: FastAPI, static: Path) -> None:
    assets = static / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = static / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            return _json({"error": "not found"}, 404)
        candidate = (static / path).resolve()
        if path and candidate.is_file() and static.resolve() in candidate.parents:
            return FileResponse(candidate)
        # Every client-side route — including /brokers/upstox/callback, where the
        # broker sends the operator back with a code — is served the app shell.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
