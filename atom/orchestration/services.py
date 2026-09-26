"""Tokens, onboarding, market data and reference data.

Each public method is one unit of work: it opens its own transaction, builds
its adapter against that transaction's connection, and closes both. Callers —
the web layer, the CLI, a job — never hold a connection across a broker call
they did not make themselves.
"""

from __future__ import annotations

import contextlib
import csv
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from atom.adapters import amfi
from atom.domain.errors import AuthError, ValidationError
from atom.infra.clock import today_ist
from atom.orchestration.engine import Engine, close_adapter
from atom.orchestration.jobs import Job
from atom.persistence.db import transaction
from atom.persistence.repositories import accounts, config, instruments, market, orders, universes

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REFERENCE_CSV = DATA_DIR / "reference" / "etf-reference-data-2026-09-20.csv"
BUCKETS_CSV = DATA_DIR / "buckets" / "etf-tradable-buckets-2026-09-17.csv"
ETF_UNIVERSE = "NSE ETFs"
ETF_CATEGORIES = ["EQUITY", "COMMODITY", "GLOBAL"]
T = TypeVar("T")

ASSET_CLASS = {"EQUITY": "EQUITY", "COMMODITY": "COMMODITY", "GLOBAL INDICES": "GLOBAL"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class TokenService:
    """The daily broker session: authorize, exchange, probe, clear."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def auth_url(self, account_id: int) -> str:
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            ref = accounts.account_ref(conn, account_id, today_ist())
            adapter = self.engine.adapter(acct["broker_code"], conn)
            try:
                url = adapter.build_auth_url(ref)
            finally:
                close_adapter(adapter)
        if url is None:
            raise ValidationError(
                f"{acct['broker_code']} has no browser login; paste a token instead"
            )
        return url

    def exchange(self, account_id: int, code: str, *, actor: str) -> dict[str, Any]:
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            ref = accounts.account_ref(conn, account_id, today)
            adapter = self.engine.adapter(acct["broker_code"], conn)
            try:
                token = adapter.exchange_code(ref, code)
                # Whose token is this? A code pasted into the wrong account's
                # screen would otherwise bind one investor's broker session to
                # another investor's ledger. Checked BEFORE the session is kept.
                expected = str(acct["broker_client_code"])
                if token.broker_client_id and token.broker_client_id.upper() != expected.upper():
                    self.engine.secrets.delete(token.secret_ref)
                    live_ref = ref.__class__(**{**asdict(ref), "secret_ref": token.secret_ref})
                    # Best effort: the secret is already gone either way.
                    with contextlib.suppress(Exception):
                        adapter.revoke_token(live_ref)
                    raise AuthError(
                        f"this code belongs to broker client {token.broker_client_id}, "
                        f"but the account is {expected}. The token was discarded.",
                        broker=acct["broker_code"],
                    )
                accounts.record_session(
                    conn,
                    account_id=account_id,
                    trade_date=today,
                    status="PENDING",
                    secret_ref=token.secret_ref,
                    obtained_at=token.obtained_at,
                )
                live = accounts.account_ref(conn, account_id, today)
                probe = adapter.probe_token(live)
                accounts.mark_session(
                    conn,
                    account_id=account_id,
                    trade_date=today,
                    status="VALID" if probe.ok else "INVALID",
                )
                onboarding = None
                if probe.ok and acct["onboarded_at"] is None:
                    onboarding = self._onboard(conn, adapter, live, acct, actor)
                accounts.audit(
                    conn,
                    actor=actor,
                    action="broker_token_generated",
                    entity="trading_account",
                    entity_id=account_id,
                    payload={"probe_ok": probe.ok, "onboarded": onboarding is not None},
                )
            finally:
                close_adapter(adapter)
        return {
            "ok": probe.ok,
            "detail": probe.detail,
            "flags": _jsonable(probe.flags),
            "onboarding": onboarding,
        }

    def _onboard(
        self, conn: Any, adapter: Any, ref: Any, acct: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        """D-137: everything already held when an account is connected is excluded,
        in one pass, so the first run can never sell what the operator never handed
        over. A paper account's book starts empty and reads nothing from the broker."""
        excluded: list[dict[str, Any]] = []
        if acct["execution_mode"] == "LIVE":
            held = adapter.fetch_holdings(ref) + adapter.fetch_positions(ref)
            totals: dict[int, int] = {}
            for h in held:
                totals[h.instrument_id] = totals.get(h.instrument_id, 0) + h.total_quantity
            for instrument_id, quantity in sorted(totals.items()):
                if quantity > 0:
                    orders.add_exclusion(
                        conn,
                        account_id=acct["trading_account_id"],
                        instrument_id=instrument_id,
                        exclusion_type="EXCLUSION",
                        quantity=quantity,
                        created_by=f"onboarding:{actor}",
                    )
                    excluded.append({"instrument_id": instrument_id, "quantity": quantity})
        accounts.mark_onboarded(conn, acct["trading_account_id"])
        return {"mode": acct["execution_mode"], "excluded": excluded}

    def status(self, account_id: int) -> dict[str, Any]:
        with transaction(self.engine.pool) as conn:
            session = accounts.get_session(conn, account_id, today_ist())
        return {"trade_date": today_ist().isoformat(), "session": _jsonable(session)}

    def probe(self, account_id: int) -> dict[str, Any]:
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            ref = accounts.account_ref(conn, account_id, today)
            if ref.secret_ref is None:
                return {"ok": False, "detail": "no token for today"}
            adapter = self.engine.adapter(acct["broker_code"], conn)
            try:
                probe = adapter.probe_token(ref)
            finally:
                close_adapter(adapter)
            accounts.mark_session(
                conn,
                account_id=account_id,
                trade_date=today,
                status="VALID" if probe.ok else "INVALID",
            )
        return {"ok": probe.ok, "detail": probe.detail, "flags": _jsonable(probe.flags)}

    def clear(self, account_id: int, *, actor: str) -> None:
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            ref = accounts.account_ref(conn, account_id, today)
            if ref.secret_ref:
                adapter = self.engine.adapter(acct["broker_code"], conn)
                try:
                    adapter.revoke_token(ref)
                except Exception:
                    pass
                finally:
                    close_adapter(adapter)
                self.engine.secrets.delete(ref.secret_ref)
            accounts.clear_session(conn, account_id=account_id, trade_date=today)
            accounts.audit(
                conn,
                actor=actor,
                action="broker_token_cleared",
                entity="trading_account",
                entity_id=account_id,
            )


class DataService:
    """Reads from the broker for the console, and the data pool the strategy uses."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _with_adapter(self, account_id: int, fn: Callable[..., T]) -> T:
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            ref = accounts.account_ref(conn, account_id, today_ist())
            adapter = self.engine.adapter(acct["broker_code"], conn)
            try:
                return fn(conn, adapter, ref, acct)
            finally:
                close_adapter(adapter)

    def funds(self, account_id: int) -> dict[str, Any]:
        def run(conn: Any, adapter: Any, ref: Any, acct: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = _jsonable(asdict(adapter.fetch_funds(ref)))
            return out

        return self._with_adapter(account_id, run)

    def holdings(self, account_id: int) -> list[dict[str, Any]]:
        def run(conn: Any, adapter: Any, ref: Any, acct: dict[str, Any]) -> list[dict[str, Any]]:
            rows = [("HOLDING", h) for h in adapter.fetch_holdings(ref)]
            rows += [("T1_POSITION", h) for h in adapter.fetch_positions(ref)]
            info = {
                int(r["instrument_id"]): r
                for r in instruments.by_ids(
                    conn, [h.instrument_id for _, h in rows], broker_id=acct["broker_id"]
                )
            }
            withheld = orders.withheld_by_instrument(conn, account_id)
            out = []
            for source, h in rows:
                meta = info.get(h.instrument_id, {})
                out.append(
                    {
                        "source": source,
                        "instrument_id": h.instrument_id,
                        "symbol": meta.get("symbol"),
                        "name": meta.get("name"),
                        "instrument_status": meta.get("status"),
                        "total_quantity": h.total_quantity,
                        "free_quantity": h.free_quantity,
                        "unsettled_quantity": h.unsettled_quantity,
                        "average_price": str(h.average_price),
                        "last_price": None if h.last_price is None else str(h.last_price),
                        "withheld_quantity": withheld.get(h.instrument_id, 0),
                    }
                )
            return out

        return self._with_adapter(account_id, run)

    def quotes(self, account_id: int, instrument_ids: list[int]) -> list[dict[str, Any]]:
        def run(conn: Any, adapter: Any, ref: Any, acct: dict[str, Any]) -> list[dict[str, Any]]:
            rows = instruments.by_ids(conn, instrument_ids, broker_id=acct["broker_id"])
            tokens = [r["broker_token"] for r in rows if r["broker_token"]]
            symbol = {int(r["instrument_id"]): r["symbol"] for r in rows}
            unmapped = [r["symbol"] for r in rows if not r["broker_token"]]
            quotes = adapter.fetch_quotes(ref, tokens)
            out = [{"symbol": symbol.get(q.instrument_id), **_jsonable(asdict(q))} for q in quotes]
            out += [
                {"symbol": s, "error": "no broker mapping — run the instrument sync"}
                for s in unmapped
            ]
            return out

        return self._with_adapter(account_id, run)

    def candles(
        self, account_id: int, instrument_id: int, from_date: date, to_date: date, *, store: bool
    ) -> list[dict[str, Any]]:
        def run(conn: Any, adapter: Any, ref: Any, acct: dict[str, Any]) -> list[dict[str, Any]]:
            [row] = instruments.by_ids(conn, [instrument_id], broker_id=acct["broker_id"])
            if not row["broker_token"]:
                raise ValidationError(f"{row['symbol']} has no {acct['broker_code']} mapping")
            bars = adapter.fetch_daily_candles(ref, row["broker_token"], from_date, to_date)
            if store:
                market.upsert_candles(
                    conn, instrument_id=instrument_id, candles=bars, source=acct["broker_code"]
                )
            return [_jsonable(asdict(b)) for b in bars]

        return self._with_adapter(account_id, run)

    def sync_history(
        self, job: Job, *, account_id: int, universe_id: int, days: int
    ) -> dict[str, Any]:
        """Bring every member's daily bars up to yesterday. Incremental: an
        instrument already covered is fetched only from its last bar onward."""
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            members = universes.current_members(conn, universe_id, broker_id=acct["broker_id"])
            have = market.coverage(conn, [int(m["instrument_id"]) for m in members])
        job.update(total=len(members), message="fetching daily bars")
        stored, failed, skipped = 0, [], []
        for index, m in enumerate(members, start=1):
            job.update(progress=index, message=f"{m['symbol']} ({index}/{len(members)})")
            if not m["broker_token"]:
                skipped.append(m["symbol"])
                continue
            covered = have.get(int(m["instrument_id"]))
            start = today - timedelta(days=days)
            if covered and covered["last_date"] and covered["first_date"] <= start:
                start = covered["last_date"] + timedelta(days=1)
            end = today - timedelta(days=1)
            if start > end:
                continue
            try:
                self.candles(account_id, int(m["instrument_id"]), start, end, store=True)
                stored += 1
            except Exception as exc:
                failed.append({"symbol": m["symbol"], "error": str(exc)[:200]})
                if isinstance(exc, AuthError):
                    break  # every later call would fail the same way
        return {"instruments_updated": stored, "failed": failed, "unmapped": skipped}

    def sync_nav(self, job: Job) -> dict[str, Any]:
        job.update(message="downloading AMFI NAV file")
        records = amfi.fetch(proxy_url=self.engine.settings.data_proxy_url)
        with transaction(self.engine.pool) as conn:
            index = instruments.isin_index(conn)
            written = 0
            for isin, rec in records.items():
                iid = index.get(isin)
                if iid is not None:
                    market.upsert_nav(conn, instrument_id=iid, trade_date=rec.nav_date, nav=rec.nav)
                    written += 1
        return {"navs_in_file": len(records), "matched_instruments": written}

    def coverage(self, universe_id: int, broker_code: str) -> list[dict[str, Any]]:
        with transaction(self.engine.pool) as conn:
            broker_id = instruments.broker_id_for(conn, broker_code)
            members = universes.current_members(conn, universe_id, broker_id=broker_id)
            ids = [int(m["instrument_id"]) for m in members]
            cov = market.coverage(conn, ids)
            navs = market.latest_navs(conn, ids, on_or_before=today_ist())
        return [
            _jsonable(
                {
                    "instrument_id": m["instrument_id"],
                    "symbol": m["symbol"],
                    "category": m["category"],
                    "member_status": m["member_status"],
                    "mapped": m["broker_token"] is not None,
                    "tradable": m["tradable"],
                    "tick_size": m["tick_size"],
                    "bars": (cov.get(int(m["instrument_id"])) or {}).get("bars", 0),
                    "last_bar": (cov.get(int(m["instrument_id"])) or {}).get("last_date"),
                    "nav": (navs.get(int(m["instrument_id"])) or {}).get("nav"),
                    "nav_date": (navs.get(int(m["instrument_id"])) or {}).get("trade_date"),
                }
            )
            for m in members
        ]


class ReferenceService:
    """The ETF reference data and each broker's instrument master."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def import_reference(self, *, actor: str) -> dict[str, Any]:
        """Load the 311 tradable NSE ETFs, their classification, and the ETF
        universe with its three categories. Safe to re-run: instruments upsert on
        ISIN and universe membership only changes when it actually differs."""
        buckets = {r["SYMBOL"]: r for r in csv.DictReader(BUCKETS_CSV.open(encoding="utf-8-sig"))}
        refs = list(csv.DictReader(REFERENCE_CSV.open(encoding="utf-8-sig")))
        added = 0
        with transaction(self.engine.pool) as conn:
            existing = universes.find_universe(conn, ETF_UNIVERSE)
            universe_id = (
                int(existing["universe_id"])
                if existing
                else universes.create_universe(
                    conn,
                    name=ETF_UNIVERSE,
                    source="IMPORTED",
                    created_by=actor,
                    categories=ETF_CATEGORIES,
                    description="Tradable NSE ETFs from the 2026-09-17 bucket classification",
                )
            )
            for ref in refs:
                b = buckets.get(ref["SYMBOL"])
                if b is None:
                    continue
                iid = instruments.upsert_instrument(
                    conn,
                    isin=ref["ISIN"],
                    symbol=ref["SYMBOL"],
                    name=ref["SCHEME_NAME"] or ref["SYMBOL"],
                    instrument_type="ETF",
                    asset_class=ASSET_CLASS[b["NSE_CATEGORY"]],
                )
                instruments.upsert_classification(
                    conn,
                    instrument_id=iid,
                    bucket=b["ATOM_BUCKET"],
                    tier2_group=b["TIER2_GROUP"] or b["ATOM_BUCKET"],
                    tier1_index=b["TIER1_INDEX"] or b["TIER2_GROUP"] or b["ATOM_BUCKET"],
                    assignment_status=b["ASSIGNMENT_STATUS"] or "UNASSIGNED",
                    assigned_by=b["ASSIGNED_BY"] or actor,
                )
                if universes.set_member(
                    conn,
                    universe_id=universe_id,
                    instrument_id=iid,
                    member_status="ACTIVE",
                    changed_by=actor,
                    reason="reference import",
                ):
                    added += 1
            accounts.audit(
                conn,
                actor=actor,
                action="reference_import",
                entity="universe",
                entity_id=universe_id,
                payload={"members_changed": added},
            )
        return {"universe_id": universe_id, "instruments": len(refs), "members_changed": added}

    def sync_instruments(self, job: Job, *, broker_code: str) -> dict[str, Any]:
        """Map every ATOM instrument to the broker's key, by ISIN only.

        Tick size: ATOM prices against its own reference value (D-209). Where it
        has none yet, the broker's — converted and verified — seeds it; where
        the two disagree, ATOM's is kept and the disagreement reported.
        """
        job.update(message=f"downloading {broker_code} instrument master")
        with transaction(self.engine.pool) as conn:
            adapter = self.engine.adapter(broker_code, conn)
            try:
                master = list(adapter.fetch_instruments())
            finally:
                close_adapter(adapter)
        job.update(message=f"mapping {len(master)} broker instruments", total=len(master))
        mapped, changed, tick_conflicts = 0, [], []
        with transaction(self.engine.pool) as conn:
            broker_id = instruments.broker_id_for(conn, broker_code)
            index = instruments.isin_index(conn)
            ticks = {
                int(r["instrument_id"]): r["tick_size"]
                for r in instruments.by_ids(conn, list(index.values()), broker_id=broker_id)
            }
            for row in master:
                if not row.isin or row.isin not in index:
                    continue
                iid = index[row.isin]
                previous = instruments.upsert_broker_instrument(
                    conn,
                    broker_id=broker_id,
                    instrument_id=iid,
                    broker_token=row.broker_token,
                    broker_symbol=row.broker_symbol,
                    tradable=row.tradable,
                )
                if previous:
                    changed.append({"isin": row.isin, "from": previous, "to": row.broker_token})
                ours = ticks.get(iid)
                if ours is None and row.tick_size is not None:
                    from atom.persistence.db import execute

                    execute(
                        conn,
                        "UPDATE atom.instrument SET tick_size = %s WHERE instrument_id = %s",
                        (row.tick_size, iid),
                    )
                elif ours is not None and row.tick_size is not None and ours != row.tick_size:
                    tick_conflicts.append(
                        {"isin": row.isin, "atom": str(ours), "broker": str(row.tick_size)}
                    )
                mapped += 1
        return {
            "master_rows": len(master),
            "mapped": mapped,
            "token_changes": changed,
            "tick_conflicts": tick_conflicts,
        }


class ConfigService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def view(self, account_id: int, universe_id: int) -> dict[str, Any]:
        from atom.strategy.config import resolve

        with transaction(self.engine.pool) as conn:
            cats = universes.categories(conn, universe_id)
            key_rows = config.keys(conn)
            values = config.account_values(conn, account_id, universe_id)
            globals_ = config.global_values(conn)
            status: dict[str, Any] = {"ok": True, "error": None}
            try:
                resolve(
                    universe_categories=cats,
                    account_values={
                        (v["key_name"], v["category_code"]): (True, v["value_text"]) for v in values
                    },
                    global_values={g["key_name"]: (True, g["value_text"]) for g in globals_},
                )
            except Exception as exc:
                status = {"ok": False, "error": str(exc)}
        view: dict[str, Any] = _jsonable(
            {
                "categories": cats,
                "keys": key_rows,
                "values": values,
                "globals": globals_,
                "status": status,
            }
        )
        return view

    def set_values(
        self, account_id: int, universe_id: int, changes: list[dict[str, Any]], *, actor: str
    ) -> None:
        with transaction(self.engine.pool) as conn:
            scopes = {k["key_name"]: k["scope"] for k in config.keys(conn)}
            for change in changes:
                key = change["key_name"]
                if key not in scopes:
                    raise ValidationError(f"unknown config key {key!r}")
                value = change.get("value_text")
                if scopes[key] == "GLOBAL":
                    config.set_global_value(conn, key_name=key, value_text=value, updated_by=actor)
                else:
                    config.set_account_value(
                        conn,
                        account_id=account_id,
                        universe_id=universe_id,
                        key_name=key,
                        category_code=change.get("category_code")
                        if scopes[key] == "ACCOUNT_CATEGORY"
                        else None,
                        value_text=value,
                        updated_by=actor,
                    )
            accounts.audit(
                conn,
                actor=actor,
                action="config_change",
                entity="trading_account",
                entity_id=account_id,
                payload={"universe_id": universe_id, "changes": changes},
            )
