"""Tokens, onboarding, market data and reference data.

Each public method is one unit of work: it opens its own transaction, builds
its adapter against that transaction's connection, and closes both. Callers —
the web layer, the CLI, a job — never hold a connection across a broker call
they did not make themselves.
"""

from __future__ import annotations

import contextlib
import csv
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from atom.adapters import amfi
from atom.domain.errors import AuthError, ValidationError
from atom.infra.clock import IST, today_ist
from atom.orchestration import history
from atom.orchestration.engine import Engine, close_adapter
from atom.orchestration.jobs import Job
from atom.persistence.db import transaction
from atom.persistence.repositories import accounts, config, instruments, market, orders, universes
from atom.strategy import shortlist

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REFERENCE_CSV = DATA_DIR / "reference" / "etf-reference-data-2026-09-20.csv"
BUCKETS_CSV = DATA_DIR / "buckets" / "etf-tradable-buckets-2026-09-17.csv"
ETF_UNIVERSE = "NSE ETFs"
ETF_CATEGORIES = ["EQUITY", "COMMODITY", "GLOBAL"]
T = TypeVar("T")

# How far back the automatic sync after a token refresh reaches.
AUTO_HISTORY_DAYS = 400

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

    def all_universe_ids(self) -> list[int]:
        with transaction(self.engine.pool) as conn:
            return [int(u["universe_id"]) for u in universes.list_universes(conn)]

    def sync_history(
        self,
        job: Job,
        *,
        account_id: int,
        universe_ids: list[int],
        days: int,
        build_shortlist: bool = True,
    ) -> dict[str, Any]:
        """Bring every member's daily bars up to yesterday, fetching only the gaps.

        Ask for ``days`` of history and an instrument that already holds all but
        the last two costs one request for those two. Requests run in parallel
        behind the adapter's rate limiter; the bars land in a few bulk statements.
        Today's bar is not fetched — the run takes its own price when it executes.
        """
        started = time.monotonic()
        today = today_ist()
        end = today - timedelta(days=1)
        wanted_from = today - timedelta(days=days)

        def run(conn: Any, adapter: Any, ref: Any, acct: dict[str, Any]) -> dict[str, Any]:
            source = acct["broker_code"]
            members: dict[int, dict[str, Any]] = {}
            for universe_id in universe_ids:
                for m in universes.current_members(conn, universe_id, broker_id=acct["broker_id"]):
                    members.setdefault(int(m["instrument_id"]), m)
            ids = list(members)
            have = market.coverage(conn, ids)
            state = market.sync_state(conn, ids, source=source)

            tasks: list[history.Task] = []
            unmapped: list[str] = []
            suspended: list[str] = []
            current = 0
            for iid, m in members.items():
                if not m["broker_token"]:
                    unmapped.append(m["symbol"])
                    continue
                if not m["tradable"]:
                    # Cannot be bought, so its volume can never qualify it: not fetched.
                    suspended.append(m["symbol"])
                    continue
                cov, st = have.get(iid) or {}, state.get(iid) or {}
                ranges = history.plan_ranges(
                    wanted_from=wanted_from,
                    end=end,
                    first_bar=cov.get("first_date"),
                    last_bar=cov.get("last_date"),
                    requested_from=st.get("requested_from"),
                    synced_through=st.get("synced_through"),
                )
                if ranges:
                    tasks.append(history.Task(iid, m["symbol"], m["broker_token"], ranges))
                else:
                    current += 1

            job.update(total=len(tasks), progress=0, message=f"fetching {len(tasks)} instruments")
            done = 0

            def progress(outcome: history.Outcome) -> None:
                nonlocal done
                done += 1
                job.update(progress=done, message=f"{outcome.task.symbol} ({done}/{len(tasks)})")

            outcomes = history.fetch_all(
                lambda token, start, stop: adapter.fetch_daily_candles(ref, token, start, stop),
                tasks,
                on_done=progress,
            )

            job.update(message="writing to the database")
            good = [o for o in outcomes if o.error is None and not o.skipped]
            written = market.upsert_candles_bulk(
                conn,
                bars=[(o.task.instrument_id, bar) for o in good for bar in o.bars],
                source=source,
            )
            market.record_sync_state(
                conn, [(o.task.instrument_id, wanted_from, end) for o in good], source=source
            )
            failed = [
                {"symbol": o.task.symbol, "error": o.error} for o in outcomes if o.error is not None
            ]
            shortlists = (
                self._build_shortlists(conn, acct, universe_ids, today) if build_shortlist else []
            )
            return {
                "shortlists": shortlists,
                "window": [wanted_from.isoformat(), end.isoformat()],
                "instruments": len(members),
                "already_current": current,
                "instruments_fetched": len(good),
                "api_calls": history.summary(outcomes)["calls"],
                "bars_written": written,
                "failed": failed,
                "unmapped": unmapped,
                "suspended": suspended,
                "seconds": round(time.monotonic() - started, 1),
            }

        return self._with_adapter(account_id, run)

    @staticmethod
    def _shortlist_settings(
        conn: Any, account_id: int, universe_id: int
    ) -> dict[str, tuple[int, int, Decimal] | None]:
        """``{category: (size, window, threshold)}``; None where a key is not configured."""
        stored = {
            (v["key_name"], v["category_code"]): v["value_text"]
            for v in config.account_values(conn, account_id, universe_id)
            if v["is_configured"] and v["value_text"] is not None
        }
        out: dict[str, tuple[int, int, Decimal] | None] = {}
        for category in universes.categories(conn, universe_id):
            try:
                out[category] = (
                    int(stored[("shortlist_size", category)]),
                    int(stored[("volume_window_days", category)]),
                    Decimal(stored[("volume_threshold_units", category)]),
                )
            except (KeyError, ValueError, ArithmeticError):
                out[category] = None
        return out

    def rebuild_shortlists(self, account_id: int, universe_ids: list[int]) -> list[dict[str, Any]]:
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            return self._build_shortlists(conn, acct, universe_ids, today_ist())

    def history_days(self, account_id: int, universe_id: int) -> int:
        """Calendar days of history the volume windows need: trading days are about 5 in 7,
        less holidays, so 1.6x the longest window plus a margin."""
        with transaction(self.engine.pool) as conn:
            settings = self._shortlist_settings(conn, account_id, universe_id)
        windows = [s[1] for s in settings.values() if s is not None]
        return max(30, int(max(windows, default=0) * 1.6) + 15)

    def sync_all(
        self, job: Job, *, account_id: int, universe_id: int, reference: ReferenceService
    ) -> dict[str, Any]:
        """D-213. One button: instrument master, then history (only the gaps), then NAV, then
        the shortlist from the configuration as it stands now."""
        started = time.monotonic()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
        out: dict[str, Any] = {}
        job.update(message="1/4 instrument master")
        out["master"] = reference.sync_instruments(job, broker_code=acct["broker_code"])
        days = self.history_days(account_id, universe_id)
        job.update(message=f"2/4 history, {days} days", progress=0, total=None)
        out["history"] = self.sync_history(
            job, account_id=account_id, universe_ids=[universe_id], days=days, build_shortlist=False
        )
        job.update(message="3/4 NAV", progress=None, total=None)
        try:
            out["nav"] = self.sync_nav(job)
        except Exception as exc:  # NAV does not decide the shortlist; report and carry on
            out["nav"] = {"error": f"{type(exc).__name__}: {exc}"}
        job.update(message="4/4 shortlist")
        out["shortlists"] = self.rebuild_shortlists(account_id, [universe_id])
        out["seconds"] = round(time.monotonic() - started, 1)
        return out

    def buyable(self, account_id: int, universe_id: int) -> dict[str, Any]:
        """Every member of each category with its average volume, the stored shortlist marked
        IN, and why each other one is out. Read from the database only."""
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            settings = self._shortlist_settings(conn, account_id, universe_id)
            members = universes.current_members(conn, universe_id, broker_id=acct["broker_id"])
            stored = universes.shortlist(conn, account_id=account_id, universe_id=universe_id)
            cats = []
            for category, setting in settings.items():
                rows_in = {int(r["instrument_id"]): r for r in stored.get(category, [])}
                built = [r["built_at"] for r in rows_in.values()]
                cat_members = [m for m in members if m["category"] == category]
                ids = [int(m["instrument_id"]) for m in cat_members]
                volumes: dict[int, tuple[Decimal, int]] = {}
                live: dict[int, int] = {}
                if setting is not None:
                    size, window, threshold = setting
                    volumes = market.average_volumes(conn, ids, window=window, before=today)
                    pool = {
                        int(m["instrument_id"]): str(m["symbol"])
                        for m in cat_members
                        if m["broker_token"] and m["tradable"]
                    }
                    live = {
                        iid: rank
                        for iid, rank, _, _ in shortlist.pick(
                            {i: v for i, v in volumes.items() if i in pool},
                            pool,
                            size=size,
                            window=window,
                            threshold=threshold,
                        )
                    }
                rows = []
                for m in cat_members:
                    iid = int(m["instrument_id"])
                    avg, vdays = volumes.get(iid, (None, 0))
                    if iid in rows_in:
                        avg = rows_in[iid]["avg_volume"] if avg is None else avg
                    reason = None
                    if iid not in rows_in:
                        if not m["broker_token"]:
                            reason = "not mapped at the broker"
                        elif not m["tradable"]:
                            reason = "suspended at the broker"
                        elif setting is None:
                            reason = "shortlist not configured"
                        elif vdays < setting[1]:
                            reason = f"only {vdays} of {setting[1]} days of volume"
                        elif avg is not None and avg < setting[2]:
                            reason = "average volume below the threshold"
                        elif iid in live:
                            reason = "would be in after a rebuild"
                        else:
                            reason = f"outside the top {setting[0]}"
                    rows.append(
                        {
                            "instrument_id": iid,
                            "symbol": m["symbol"],
                            "name": m["name"],
                            "member_status": m["member_status"],
                            "avg_volume": avg,
                            "volume_days": vdays,
                            "rank": rows_in[iid]["rank"] if iid in rows_in else None,
                            "in_shortlist": iid in rows_in,
                            "reason": reason,
                        }
                    )
                rows.sort(
                    key=lambda r: (
                        r["rank"] is None,
                        r["rank"] or 0,
                        -(r["avg_volume"] or 0),
                        str(r["symbol"]),
                    )
                )
                cats.append(
                    {
                        "category": category,
                        "shortlist_size": setting[0] if setting else None,
                        "volume_window_days": setting[1] if setting else None,
                        "volume_threshold_units": setting[2] if setting else None,
                        "built_at": max(built) if built else None,
                        "in_count": len(rows_in),
                        "stale": setting is not None and set(live) != set(rows_in),
                        "rows": rows,
                    }
                )
        out: dict[str, Any] = _jsonable({"as_of": today, "categories": cats})
        return out

    @staticmethod
    def _build_shortlists(
        conn: Any, acct: dict[str, Any], universe_ids: list[int], today: date
    ) -> list[dict[str, Any]]:
        """Rebuild each category's shortlist from the volume now in ``price_daily``."""
        account_id = int(acct["trading_account_id"])
        report: list[dict[str, Any]] = []
        for universe_id in universe_ids:
            settings = DataService._shortlist_settings(conn, account_id, universe_id)
            members = universes.current_members(conn, universe_id, broker_id=acct["broker_id"])
            for category, setting in settings.items():
                if setting is None:
                    report.append(
                        {
                            "universe_id": universe_id,
                            "category": category,
                            "skipped": "shortlist_size, volume_window_days or "
                            "volume_threshold_units is not configured",
                        }
                    )
                    continue
                size, window, threshold = setting
                pool = [
                    m
                    for m in members
                    if m["category"] == category and m["broker_token"] and m["tradable"]
                ]
                symbols = {int(m["instrument_id"]): str(m["symbol"]) for m in pool}
                volumes = market.average_volumes(conn, list(symbols), window=window, before=today)
                chosen = shortlist.pick(
                    volumes, symbols, size=size, window=window, threshold=threshold
                )
                universes.replace_shortlist(
                    conn,
                    account_id=account_id,
                    universe_id=universe_id,
                    category=category,
                    rows=chosen,
                )
                report.append(
                    {
                        "universe_id": universe_id,
                        "category": category,
                        "wanted": size,
                        "chosen": len(chosen),
                        "candidates": len(pool),
                        "short_of_volume_history": sum(
                            1 for iid in symbols if volumes.get(iid, (0, 0))[1] < window
                        ),
                    }
                )
        return report

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


class HoldingService:
    """D-212. Which holdings ATOM may sell: one switch per instrument.

    ON for what ATOM bought, OFF for what it found at onboarding (D-137). Switching a bot
    holding OFF freezes its open lots (D-062); ON releases the freeze. Switching a manual
    holding ON adopts it: the exclusion is released and an EXTERNAL lot is opened at the
    broker's average price, after which it is sold exactly like an ATOM lot.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def controls(self, account_id: int) -> list[dict[str, Any]]:
        with transaction(self.engine.pool) as conn:
            lots = orders.open_lots(conn, account_id=account_id)
            rows = orders.active_exclusions(conn, account_id)
            names = {
                int(r["instrument_id"]): r
                for r in instruments.by_ids(
                    conn, sorted({lot.instrument_id for lot in lots}), broker_id=None
                )
            }
        by: dict[int, dict[str, Any]] = {}

        def row(iid: int) -> dict[str, Any]:
            return by.setdefault(
                iid,
                {
                    "instrument_id": iid,
                    "symbol": None,
                    "name": None,
                    "atom_quantity": 0,
                    "external_quantity": 0,
                    "excluded_quantity": 0,
                    "frozen_quantity": 0,
                    "cost": Decimal(0),
                    "acquired_from": None,
                },
            )

        for lot in lots:
            r = row(lot.instrument_id)
            key = "external_quantity" if lot.provenance.value == "EXTERNAL" else "atom_quantity"
            r[key] += lot.quantity_open
            r["cost"] += lot.unit_cost * lot.quantity_open
            if r["acquired_from"] is None or lot.acquired_on < r["acquired_from"]:
                r["acquired_from"] = lot.acquired_on
            meta = names.get(lot.instrument_id, {})
            r["symbol"], r["name"] = meta.get("symbol"), meta.get("name")
        for e in rows:
            r = row(int(e["instrument_id"]))
            key = "frozen_quantity" if e["exclusion_type"] == "FREEZE" else "excluded_quantity"
            r[key] += int(e["quantity"])
            r["symbol"], r["name"] = e["symbol"], e["name"]
        out = []
        for r in by.values():
            lot_qty = r["atom_quantity"] + r["external_quantity"]
            if r["atom_quantity"] and r["external_quantity"]:
                source = "ATOM_AND_MANUAL"
            elif r["atom_quantity"]:
                source = "ATOM"
            elif r["external_quantity"]:
                source = "MANUAL_ADOPTED"
            else:
                source = "MANUAL"
            cost = r.pop("cost")
            r["average_cost"] = (cost / lot_qty).quantize(Decimal("0.0001")) if lot_qty else None
            r["source"] = source
            r["sell_enabled"] = lot_qty > 0 and r["frozen_quantity"] == 0
            out.append(r)
        out.sort(key=lambda r: str(r["symbol"]))
        return [_jsonable(r) for r in out]

    def set_sell(
        self, account_id: int, instrument_id: int, *, enabled: bool, universe_id: int, actor: str
    ) -> dict[str, Any]:
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            lots = [
                lot
                for lot in orders.open_lots(conn, account_id=account_id)
                if lot.instrument_id == instrument_id
            ]
            rows = [
                e
                for e in orders.active_exclusions(conn, account_id)
                if int(e["instrument_id"]) == instrument_id
            ]
            freezes = [e for e in rows if e["exclusion_type"] == "FREEZE"]
            exclusions = [e for e in rows if e["exclusion_type"] == "EXCLUSION"]
            lot_qty = sum(lot.quantity_open for lot in lots)
            done: dict[str, Any] = {"instrument_id": instrument_id, "enabled": enabled}
            if not enabled:
                if lot_qty == 0:
                    raise ValidationError("nothing of this holding is ATOM's to hold back")
                for e in freezes:
                    orders.release_exclusion(conn, int(e["account_exclusion_id"]))
                orders.add_exclusion(
                    conn,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    exclusion_type="FREEZE",
                    quantity=lot_qty,
                    created_by=f"holding-switch:{actor}",
                )
                done["frozen"] = lot_qty
            else:
                for e in freezes:
                    orders.release_exclusion(conn, int(e["account_exclusion_id"]))
                done["unfrozen"] = sum(int(e["quantity"]) for e in freezes)
                if exclusions:
                    done["adopted"] = self._adopt(
                        conn, acct, instrument_id, universe_id, exclusions, lot_qty
                    )
                elif lot_qty == 0:
                    raise ValidationError("ATOM holds nothing of this instrument")
            accounts.audit(
                conn,
                actor=actor,
                action="holding_sell_enabled" if enabled else "holding_sell_disabled",
                entity="trading_account",
                entity_id=account_id,
                payload=_jsonable(done),
            )
        return done

    def _adopt(
        self,
        conn: Any,
        acct: dict[str, Any],
        instrument_id: int,
        universe_id: int,
        exclusions: list[dict[str, Any]],
        lot_qty: int,
    ) -> dict[str, Any]:
        """Turn a manual holding into an EXTERNAL lot ATOM sells (D-212)."""
        account_id = int(acct["trading_account_id"])
        if acct["execution_mode"] != "LIVE":
            raise ValidationError("only a LIVE account holds real shares to adopt")
        member = next(
            (
                m
                for m in universes.current_members(conn, universe_id, broker_id=acct["broker_id"])
                if int(m["instrument_id"]) == instrument_id
            ),
            None,
        )
        if member is None or member["category"] is None:
            raise ValidationError(
                "this ETF is not in a category of the selected universe, so it has no profit "
                "target to sell at"
            )
        ref = accounts.account_ref(conn, account_id, today_ist())
        adapter = self.engine.adapter(acct["broker_code"], conn)
        try:
            held = adapter.fetch_holdings(ref) + adapter.fetch_positions(ref)
        finally:
            close_adapter(adapter)
        mine = [h for h in held if h.instrument_id == instrument_id]
        broker_total = sum(h.total_quantity for h in mine)
        priced = [h for h in mine if h.average_price and h.average_price > 0 and h.total_quantity]
        if not priced:
            raise ValidationError("the broker reports no average price for this holding")
        avg = (
            sum((Decimal(h.average_price) * h.total_quantity for h in priced), Decimal(0))
            / sum(h.total_quantity for h in priced)
        ).quantize(Decimal("0.0001"))
        excluded = sum(int(e["quantity"]) for e in exclusions)
        quantity = min(excluded, broker_total - lot_qty)
        if quantity <= 0:
            raise ValidationError(
                f"the broker holds {broker_total} and ATOM's lots already account for {lot_qty}"
            )
        for e in exclusions:
            orders.release_exclusion(conn, int(e["account_exclusion_id"]))
        acquired = min(e["created_at"] for e in exclusions).astimezone(IST).date()
        lot_id = orders.insert_lot(
            conn,
            account_id=account_id,
            universe_id=universe_id,
            instrument_id=instrument_id,
            buy_order_id=None,
            fill_id=None,
            quantity=quantity,
            unit_cost=avg,
            acquired_on=acquired,
            provenance="EXTERNAL",
        )
        return {"lot_id": lot_id, "quantity": quantity, "unit_cost": avg, "acquired_on": acquired}


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
                    reference=True,
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
