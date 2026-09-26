"""The run: plan → release → settle.

RUN-LIFECYCLE.md's seven phases, split at the one point where a human decides.

``plan``      phases 0-4 without sending anything. Pre-flight, reference data,
              reconciliation, the sell tranches and the buy decisions are all
              computed, every candidate is recorded, and every order is written
              as an INTENT row with its idempotency key BEFORE anything leaves
              the building (D-094). The operator sees the execution list.
``release``   the sends: cancel ATOM's resting GTTs, verify they are gone,
              place the fresh tranche GTTs, then the buys. Through the
              OrderGateway, the only place DRY and LIVE differ (D-045).
``settle``    phase 6: order states, fills, lots, closures. Idempotent.
``discard``   an unreleased plan the operator does not want. The run is FAILED
              and so does not consume the day's slot (D-057e).

A failure after the run row exists marks the run FAILED with the reason in its
log — so "why did nothing happen today" always has an answer in SQL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from atom.adapters.client_ref import make_client_ref
from atom.domain.enums import GttStatus, Side
from atom.domain.errors import (
    AtomError,
    AuthError,
    BrokerError,
    ConfigError,
    InsufficientFundsError,
    IpBlockedError,
    PreflightError,
    ReconciliationError,
    TransientError,
    ValidationError,
)
from atom.domain.models import GttIntent, OrderIntent
from atom.infra.clock import now_ist, now_utc, today_ist
from atom.infra.egress import EgressCheckError, observed_egress_ip
from atom.orchestration.engine import Engine, close_adapter
from atom.orchestration.gateway import DryGateway, LiveGateway, OrderGateway
from atom.persistence.db import transaction
from atom.persistence.repositories import (
    accounts,
    config,
    instruments,
    market,
    orders,
    runs,
    universes,
)
from atom.strategy.buy import Market, Member, Position, plan_buys
from atom.strategy.config import RunConfig, resolve
from atom.strategy.sell import SellInput, plan_sells

MARKET_CLOSE = (15, 30)


@dataclass(frozen=True, slots=True)
class PlanResult:
    run_id: int
    execution_mode: str
    buys: int
    sells: int
    candidates: int


class RunService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ================================================================== plan
    def plan(self, *, account_id: int, universe_id: int, actor: str) -> PlanResult:
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            acct = accounts.get_account(conn, account_id)
            cfg = self._config(conn, account_id, universe_id)
            mode = "DRY" if acct["execution_mode"] == "DRY" or cfg.dry_run else "LIVE"
            self._preflight_static(conn, acct, cfg, universe_id, today, mode)
            snapshot_id = universes.snapshot(
                conn, universe_id=universe_id, effective_from=today, generated_by=actor
            )
            batch_id = runs.create_batch(conn, triggered_by=actor, trade_date=today)
            run_id = runs.create_run(
                conn,
                batch_id=batch_id,
                account_id=account_id,
                universe_id=universe_id,
                snapshot_id=snapshot_id,
                run_type="EXECUTE",
                execution_mode=mode,
                trade_date=today,
                config_snapshot=cfg.snapshot(),
            )
            runs.log(
                conn,
                run_id,
                level="INFO",
                stage="PREFLIGHT",
                message=f"run created by {actor} in {mode} mode",
                context={"universe_id": universe_id},
            )

        try:
            with transaction(self.engine.pool) as conn:
                result = self._plan_body(conn, run_id, acct, cfg, universe_id, today, mode)
        except Exception as exc:
            self._fail(run_id, "PLAN", exc)
            raise
        return result

    def _config(self, conn: Any, account_id: int, universe_id: int) -> RunConfig:
        cats = universes.categories(conn, universe_id)
        values = config.account_values(conn, account_id, universe_id)
        globals_ = config.global_values(conn)
        try:
            return resolve(
                universe_categories=cats,
                account_values={
                    (v["key_name"], v["category_code"]): (v["is_configured"], v["value_text"])
                    for v in values
                },
                global_values={
                    g["key_name"]: (g["is_configured"], g["value_text"]) for g in globals_
                },
            )
        except ConfigError as exc:
            raise PreflightError(str(exc), gate="config", account_id=account_id) from exc

    def _preflight_static(
        self,
        conn: Any,
        acct: dict[str, Any],
        cfg: RunConfig,
        universe_id: int,
        today: date,
        mode: str,
    ) -> None:
        aid = int(acct["trading_account_id"])
        if cfg.kill_switch:
            raise PreflightError("the global kill switch is ON", gate="kill_switch", account_id=aid)
        if acct["onboarded_at"] is None:
            raise PreflightError(
                "account not onboarded — generate its first token so existing holdings are "
                "excluded (D-137)",
                gate="onboarding",
                account_id=aid,
            )
        existing = runs.live_execute_run(
            conn, account_id=aid, universe_id=universe_id, trade_date=today
        )
        if existing:
            raise PreflightError(
                f"run {existing['run_id']} already exists for today ({existing['status']}); "
                "discard it first if it should be replaced",
                gate="one_run_per_day",
                account_id=aid,
            )
        if mode == "LIVE":
            now = now_ist()
            gate_h, gate_m = (int(p) for p in cfg.market_open_gate_time.split(":"))
            if now.weekday() >= 5:
                raise PreflightError("market closed: weekend", gate="market_clock", account_id=aid)
            if (now.hour, now.minute) < (gate_h, gate_m) or (now.hour, now.minute) >= MARKET_CLOSE:
                raise PreflightError(
                    f"outside the run window {cfg.market_open_gate_time}-15:30 IST "
                    f"(now {now:%H:%M})",
                    gate="market_clock",
                    account_id=aid,
                )

    def _plan_body(
        self,
        conn: Any,
        run_id: int,
        acct: dict[str, Any],
        cfg: RunConfig,
        universe_id: int,
        today: date,
        mode: str,
    ) -> PlanResult:
        aid = int(acct["trading_account_id"])
        broker_id = int(acct["broker_id"])
        ref = accounts.account_ref(conn, aid, today)
        adapter = self.engine.adapter(acct["broker_code"], conn)
        try:
            # ---- phase 0: token (tested, never computed) and egress
            probe = adapter.probe_token(ref)
            if not probe.ok:
                accounts.mark_session(conn, account_id=aid, trade_date=today, status="INVALID")
                raise PreflightError(f"token invalid: {probe.detail}", gate="token", account_id=aid)
            if mode == "LIVE":
                self._check_egress(acct)
            runs.log(
                conn,
                run_id,
                level="INFO",
                stage="PREFLIGHT",
                message="pre-flight passed",
                context={"token": probe.detail, "mode": mode},
            )

            # ---- phase 1: reference
            members = universes.current_members(conn, universe_id, broker_id=broker_id)
            ids = [int(m["instrument_id"]) for m in members]
            lots_all = orders.open_lots(conn, account_id=aid)
            lots_universe = [lot for lot in lots_all if lot.universe_id == universe_id]
            held_ids = {lot.instrument_id for lot in lots_universe}
            info = {
                int(r["instrument_id"]): r
                for r in instruments.by_ids(conn, sorted(set(ids) | held_ids), broker_id=broker_id)
            }
            tokens = [
                str(info[i]["broker_token"])
                for i in sorted(set(ids) | held_ids)
                if info.get(i, {}).get("broker_token")
            ]
            quotes = (
                {q.instrument_id: q for q in adapter.fetch_quotes(ref, tokens)} if tokens else {}
            )
            depth = max(
                (max(c.lookback_days, c.volume_window_days) for c in cfg.categories.values()),
                default=1,
            )
            bars = market.recent_bars(conn, ids, before=today, limit=depth)
            navs = market.latest_navs(conn, ids, on_or_before=today)
            runs.log(
                conn,
                run_id,
                level="INFO",
                stage="REFERENCE",
                message=f"{len(members)} members, {len(quotes)} quotes, "
                f"{sum(1 for b in bars.values() if b)} with history, {len(navs)} with NAV",
            )

            # ---- phase 2: reconcile (LIVE only — a paper book is never read against the broker)
            withheld = orders.withheld_by_instrument(conn, aid)
            free: dict[int, int | None] = {}
            if mode == "LIVE":
                free = self._reconcile(conn, run_id, adapter, ref, lots_all, withheld)

            # ---- phase 3: sell plan
            member_cat = {int(m["instrument_id"]): m["category"] for m in members}
            sell_inputs: dict[int, SellInput] = {}
            universe_qty: dict[int, int] = defaultdict(int)
            for lot in lots_universe:
                universe_qty[lot.instrument_id] += lot.quantity_open
            for iid, qty in universe_qty.items():
                meta = info.get(iid, {})
                cat = member_cat.get(iid) or meta.get("asset_class")
                cat_cfg = cfg.categories.get(cat) if cat else None
                if mode == "LIVE":
                    broker_free = free.get(iid)
                    cap = (
                        None
                        if broker_free is None
                        else min(qty, broker_free - withheld.get(iid, 0))
                    )
                else:
                    cap = qty
                sell_inputs[iid] = SellInput(
                    category=cat,
                    profit_target_pct=cat_cfg.profit_target_pct if cat_cfg else None,
                    tick_size=meta.get("tick_size"),
                    sellable_quantity=cap,
                )
            tranches, skipped = plan_sells(lots_universe, sell_inputs)
            for s in skipped:
                runs.log(
                    conn,
                    run_id,
                    level="WARNING",
                    stage="SELL",
                    message=f"{info.get(s.instrument_id, {}).get('symbol', s.instrument_id)}: "
                    f"{s.reason}",
                )
            sells_blocked = self._sell_authorisation_blocked(adapter, probe.flags, mode)
            if sells_blocked and tranches:
                runs.log(conn, run_id, level="WARNING", stage="SELL", message=sells_blocked)
                tranches = []

            seq = 0
            for tranche in tranches:
                seq += 1
                ltp = (
                    quotes[tranche.instrument_id].last_price
                    if tranche.instrument_id in quotes
                    else None
                )
                # A GTT "ABOVE" trigger cannot be placed at or below the price the
                # market is already at; a plain DAY limit at the target does the
                # same job and fills today.
                use_gtt = adapter.capabilities.supports_gtt and (
                    ltp is None or ltp < tranche.target_price
                )
                orders.insert_intent(
                    conn,
                    run_id=run_id,
                    account_id=aid,
                    universe_id=universe_id,
                    instrument_id=tranche.instrument_id,
                    side="SELL",
                    order_kind="GTT" if use_gtt else "LIMIT",
                    quantity=tranche.quantity,
                    limit_price=tranche.target_price,
                    trigger_price=tranche.target_price if use_gtt else None,
                    idempotency_key=make_client_ref(trade_date=today, run_id=run_id, sequence=seq),
                )
                runs.log(
                    conn,
                    run_id,
                    level="INFO",
                    stage="SELL",
                    message=f"{info[tranche.instrument_id]['symbol']}: {tranche.basis_kind.value} "
                    f"tranche {tranche.quantity} @ {tranche.target_price} "
                    f"(basis {tranche.basis_price})",
                )

            # ---- phase 4: buy plan
            bought_today = orders.bought_today(
                conn, account_id=aid, universe_id=universe_id, trade_date=today
            )
            proxies = {
                lot.instrument_id for lot in lots_universe if lot.synthetic_cost_basis is not None
            }
            plan_members = [
                Member(
                    instrument_id=int(m["instrument_id"]),
                    symbol=str(m["symbol"]),
                    category=m["category"],
                    member_frozen=m["member_status"] == "FROZEN",
                    instrument_status=str(m["instrument_status"]),
                    broker_mapped=m["broker_token"] is not None,
                    broker_tradable=bool(m["tradable"]),
                    tick_size=m["tick_size"],
                )
                for m in members
            ]
            market_view = {
                iid: Market(
                    ltp=quotes[iid].last_price if iid in quotes else None,
                    closes=[b["close_px"] for b in bars.get(iid, [])],
                    volumes=[b["volume"] for b in bars.get(iid, [])],
                    nav=(navs.get(iid) or {}).get("nav"),
                    nav_date=(navs.get(iid) or {}).get("trade_date"),
                )
                for iid in ids
            }
            positions = {
                iid: Position(
                    held_in_universe=iid in held_ids,
                    holds_harvest_proxy=iid in proxies,
                    withheld_quantity=withheld.get(iid, 0),
                    bought_today=iid in bought_today,
                )
                for iid in ids
            }
            buy_plan = plan_buys(
                config=cfg,
                members=plan_members,
                market=market_view,
                positions=positions,
                today=today,
                orders_already_planned=seq,
            )
            for row in buy_plan.candidates:
                runs.add_candidate(conn, run_id, row)
            for buy in buy_plan.orders:
                seq += 1
                orders.insert_intent(
                    conn,
                    run_id=run_id,
                    account_id=aid,
                    universe_id=universe_id,
                    instrument_id=buy.instrument_id,
                    side="BUY",
                    order_kind="LIMIT",
                    quantity=buy.quantity,
                    limit_price=buy.limit_price,
                    trigger_price=None,
                    idempotency_key=make_client_ref(trade_date=today, run_id=run_id, sequence=seq),
                )
            runs.log(
                conn,
                run_id,
                level="INFO",
                stage="BUY",
                message=f"planned {len(buy_plan.orders)} buys worth {buy_plan.spent}; "
                f"{len(tranches)} sell tranches; awaiting release",
                context={"spent": str(buy_plan.spent)},
            )
        finally:
            close_adapter(adapter)
        return PlanResult(
            run_id=run_id,
            execution_mode=mode,
            buys=len(buy_plan.orders),
            sells=len(tranches),
            candidates=len(buy_plan.candidates),
        )

    def _check_egress(self, acct: dict[str, Any]) -> None:
        aid = int(acct["trading_account_id"])
        try:
            actual = observed_egress_ip(acct["proxy_url"])
        except EgressCheckError as exc:
            raise PreflightError(
                f"egress unverifiable: {exc}", gate="egress_ip", account_id=aid
            ) from exc
        if actual != acct["egress_ip"]:
            # An infrastructure fault, never retried: on Dhan a changed IP cannot be
            # re-registered for seven days (D-173).
            raise PreflightError(
                f"traffic leaves from {actual}, but this account is registered for "
                f"{acct['egress_ip']}",
                gate="egress_ip",
                account_id=aid,
            )

    def _reconcile(
        self,
        conn: Any,
        run_id: int,
        adapter: Any,
        ref: Any,
        lots_all: list[Any],
        withheld: dict[int, int],
    ) -> dict[int, int | None]:
        """D-182. Ownership: broker total = ATOM lots + withheld + unattributed.
        A NEGATIVE residual — ATOM believes it holds what it does not — aborts,
        because the sells it would place would be rejected or, worse, sell stock
        that belongs to someone's manual position."""
        held = adapter.fetch_holdings(ref) + adapter.fetch_positions(ref)
        broker_total: dict[int, int] = defaultdict(int)
        free: dict[int, int | None] = {}
        for h in held:
            broker_total[h.instrument_id] += h.total_quantity
            if h.free_quantity is not None:
                free[h.instrument_id] = (free.get(h.instrument_id) or 0) + h.free_quantity
            elif h.instrument_id not in free:
                free[h.instrument_id] = None
        atom_total: dict[int, int] = defaultdict(int)
        for lot in lots_all:
            atom_total[lot.instrument_id] += lot.quantity_open
        problems = []
        for iid in set(broker_total) | set(atom_total) | set(withheld):
            residual = broker_total.get(iid, 0) - atom_total.get(iid, 0) - withheld.get(iid, 0)
            if residual < 0:
                problems.append(
                    f"instrument {iid}: broker {broker_total.get(iid, 0)}, ATOM lots "
                    f"{atom_total.get(iid, 0)}, withheld {withheld.get(iid, 0)}"
                )
            elif residual > 0:
                runs.log(
                    conn,
                    run_id,
                    level="WARNING",
                    stage="RECONCILE",
                    message=f"instrument {iid}: {residual} units held that ATOM did not buy and "
                    "are not excluded — left alone, never auto-attributed (D-086)",
                )
        if problems:
            raise ReconciliationError("negative attribution residual: " + "; ".join(problems))
        runs.log(
            conn, run_id, level="INFO", stage="RECONCILE", message="books agree with the broker"
        )
        return free

    @staticmethod
    def _sell_authorisation_blocked(adapter: Any, flags: dict[str, Any], mode: str) -> str | None:
        caps = adapter.capabilities
        if mode != "LIVE" or not caps.requires_sell_authorisation:
            return None
        if flags.get("poa") or flags.get("ddpi"):
            return None
        return (
            f"sell pass skipped: {caps.broker_code} needs depository authorisation "
            f"({caps.sell_authorisation_scope.value}) and the account shows neither POA nor DDPI"
        )

    # =============================================================== release
    def release(self, run_id: int, *, actor: str) -> dict[str, Any]:
        today = today_ist()
        with transaction(self.engine.pool) as conn:
            run = runs.get_run(conn, run_id)
            if run["status"] != "EXECUTING":
                raise ValidationError(f"run {run_id} is {run['status']}, not awaiting release")
            if run["trade_date"] != today:
                raise ValidationError(
                    f"run {run_id} was planned for {run['trade_date']}; plan a fresh one"
                )
            intents = [o for o in orders.orders_for_run(conn, run_id) if o["status"] == "INTENT"]
            if not intents:
                raise ValidationError(f"run {run_id} has nothing left to release")
            is_set, kill = config.global_value(conn, "kill_switch")
            if not is_set or (kill or "").lower() != "false":
                raise PreflightError(
                    "kill switch is ON (or unset); nothing sent", gate="kill_switch"
                )
            acct = accounts.get_account(conn, int(run["trading_account_id"]))
            ref = accounts.account_ref(conn, int(acct["trading_account_id"]), today)
            runs.log(conn, run_id, level="INFO", stage="SELL", message=f"released by {actor}")

        placed, rejected, halted = 0, 0, None
        # The adapter's instrument resolver reads through this connection for the
        # whole release; order-state writes go through their own short
        # transactions, so each send is recorded the moment it returns.
        with self.engine.pool.connection() as adapter_conn:
            adapter = self.engine.adapter(acct["broker_code"], adapter_conn)
            try:
                gateway: OrderGateway
                if run["execution_mode"] == "DRY":
                    gateway = DryGateway()
                else:
                    gateway = LiveGateway(adapter, ref)
                    probe = adapter.probe_token(ref)
                    if not probe.ok:
                        raise PreflightError(f"token no longer valid: {probe.detail}", gate="token")
                    self._check_egress(acct)

                # Sell pass first: cancel ATOM's resting GTTs, VERIFY, then place
                # (D-063). Always, even with no new tranches — a stale GTT from an
                # earlier run is exactly what the cancel exists to clear.
                self._cancel_and_verify(run, gateway)
                ordered = [o for o in intents if o["side"] == "SELL"] + [
                    o for o in intents if o["side"] == "BUY"
                ]
                for order in ordered:
                    outcome = self._send(run, order, gateway)
                    if outcome == "placed":
                        placed += 1
                    elif outcome == "rejected":
                        rejected += 1
                    else:
                        halted = outcome
                        break
            except AtomError as exc:
                self._fail(run_id, "SELL", exc)
                raise
            finally:
                close_adapter(adapter)

        with transaction(self.engine.pool) as conn:
            runs.log(
                conn,
                run_id,
                level="WARNING" if halted else "INFO",
                stage="BUY",
                message=f"release finished: {placed} placed, {rejected} rejected"
                + (f"; HALTED — {halted}" if halted else ""),
            )
            if halted:
                runs.set_status(conn, run_id, "FAILED")
        return {"placed": placed, "rejected": rejected, "halted": halted}

    def _cancel_and_verify(self, run: dict[str, Any], gateway: OrderGateway) -> None:
        run_id = int(run["run_id"])
        with transaction(self.engine.pool) as conn:
            resting = [
                g
                for g in orders.live_gtts(
                    conn,
                    account_id=int(run["trading_account_id"]),
                    universe_id=int(run["universe_id"]),
                )
                if g["run_id"] != run_id
            ]
        cancelled: list[str] = []
        for gtt in resting:
            gateway.cancel_gtt(str(gtt["broker_order_id"]))
            cancelled.append(str(gtt["broker_order_id"]))
        survivors: set[str] = set()
        remaining = gateway.resting_gtt_ids()
        if remaining is not None:
            survivors = remaining & set(cancelled)
        with transaction(self.engine.pool) as conn:
            for gtt in resting:
                if str(gtt["broker_order_id"]) not in survivors:
                    orders.mark_status(
                        conn,
                        int(gtt["order_request_id"]),
                        status="CANCELLED",
                        reject_reason=f"replaced by run {run_id}",
                    )
            runs.log(
                conn,
                run_id,
                level="INFO",
                stage="SELL",
                message=f"cancelled {len(cancelled) - len(survivors)} of ATOM's resting GTTs",
            )
        if survivors:
            # Two live sells for one holding is the failure D-055 forbids.
            raise ReconciliationError(
                f"GTTs still resting after cancel: {sorted(survivors)} — run halted"
            )

    def _send(self, run: dict[str, Any], order: dict[str, Any], gateway: OrderGateway) -> str:
        """One order. Returns ``placed`` / ``rejected``, or a halt reason."""
        order_id = int(order["order_request_id"])
        side = Side(order["side"])
        try:
            if order["order_kind"] == "GTT":
                state = gateway.place_gtt(
                    GttIntent(
                        instrument_id=int(order["instrument_id"]),
                        quantity=int(order["quantity"]),
                        trigger_price=Decimal(order["trigger_price"]),
                        limit_price=Decimal(order["limit_price"]),
                        client_ref=str(order["idempotency_key"]),
                        side=side,
                    ),
                    order_request_id=order_id,
                )
                broker_id, status = state.broker_gtt_id, "PLACED"
            else:
                ostate = gateway.place_order(
                    OrderIntent(
                        trading_account_id=int(run["trading_account_id"]),
                        universe_id=int(run["universe_id"]),
                        instrument_id=int(order["instrument_id"]),
                        side=side,
                        quantity=int(order["quantity"]),
                        limit_price=Decimal(order["limit_price"]),
                        client_ref=str(order["idempotency_key"]),
                    ),
                    order_request_id=order_id,
                )
                broker_id, status = ostate.broker_order_id, ostate.status.value
        except InsufficientFundsError as exc:
            # Funds cannot be known ahead of the exchange: record verbatim, carry on (D-052).
            with transaction(self.engine.pool) as conn:
                orders.mark_status(conn, order_id, status="REJECTED", reject_reason=str(exc))
            return "rejected"
        except TransientError as exc:
            # The request may or may not have reached the broker. IN_FLIGHT, never
            # terminal (D-180) — settlement finds out which — and stop sending.
            with transaction(self.engine.pool) as conn:
                orders.mark_status(conn, order_id, status="IN_FLIGHT", reject_reason=str(exc))
            return f"transport failure on order {order_id}: {exc}"
        except (AuthError, IpBlockedError) as exc:
            with transaction(self.engine.pool) as conn:
                orders.mark_status(conn, order_id, status="REJECTED", reject_reason=str(exc))
            return f"{type(exc).__name__}: {exc}"
        except BrokerError as exc:
            with transaction(self.engine.pool) as conn:
                orders.mark_status(conn, order_id, status="REJECTED", reject_reason=str(exc))
            if isinstance(exc, ValidationError):
                return "rejected"
            return f"unmapped broker error on order {order_id}: {exc}"
        with transaction(self.engine.pool) as conn:
            orders.mark_sent(
                conn, order_id, broker_order_id=broker_id, status=status, placed_at=now_utc()
            )
        return "placed"

    # ================================================================ settle
    def settle(self, run_id: int) -> dict[str, Any]:
        with transaction(self.engine.pool) as conn:
            run = runs.get_run(conn, run_id)
            acct = accounts.get_account(conn, int(run["trading_account_id"]))
            run_orders = [o for o in orders.orders_for_run(conn, run_id) if o["broker_order_id"]]
            ref = accounts.account_ref(conn, int(acct["trading_account_id"]), today_ist())
            adapter = self.engine.adapter(acct["broker_code"], conn)
            try:
                if run["execution_mode"] == "DRY":
                    summary = self._settle_dry(
                        conn, run, run_orders, adapter, ref, int(acct["broker_id"])
                    )
                else:
                    summary = self._settle_live(conn, run, run_orders, adapter, ref)
            finally:
                close_adapter(adapter)
            open_limits = [
                o
                for o in orders.orders_for_run(conn, run_id)
                if o["order_kind"] == "LIMIT" and o["status"] in orders.UNSETTLED
            ]
            if (
                run["status"] == "EXECUTING"
                and not open_limits
                and not any(o["status"] == "INTENT" for o in orders.orders_for_run(conn, run_id))
            ):
                runs.set_status(conn, run_id, "COMPLETED")
                summary["run_completed"] = True
            runs.log(
                conn, run_id, level="INFO", stage="SETTLE", message="settle pass", context=summary
            )
        return summary

    def _apply_fill(
        self,
        conn: Any,
        run: dict[str, Any],
        order: dict[str, Any],
        quantity: int,
        price: Decimal,
        filled_at: datetime,
        trade_id: str | None,
    ) -> bool:
        fill_id = orders.insert_fill(
            conn,
            order_id=int(order["order_request_id"]),
            quantity=quantity,
            fill_price=price,
            filled_at=filled_at,
            broker_trade_id=trade_id,
        )
        if fill_id is None:
            return False  # already recorded — settlement is idempotent
        if order["side"] == "BUY":
            # unit_cost is the fill price until the charges model lands (Q-313 blocks
            # the STT rate). Recorded in the run log so the gap is visible, not silent.
            orders.insert_lot(
                conn,
                account_id=int(run["trading_account_id"]),
                universe_id=int(run["universe_id"]),
                instrument_id=int(order["instrument_id"]),
                buy_order_id=int(order["order_request_id"]),
                fill_id=fill_id,
                quantity=quantity,
                unit_cost=price,
                acquired_on=filled_at.date(),
            )
        else:
            closed = orders.close_lots_fifo(
                conn,
                account_id=int(run["trading_account_id"]),
                universe_id=int(run["universe_id"]),
                instrument_id=int(order["instrument_id"]),
                sell_order_id=int(order["order_request_id"]),
                quantity=quantity,
                unit_proceeds=price,
                closed_on=filled_at.date(),
            )
            if closed != quantity:
                raise ReconciliationError(
                    f"sold {quantity} of instrument {order['instrument_id']} but ATOM's lots held "
                    f"only {closed}"
                )
        return True

    def _settle_live(
        self,
        conn: Any,
        run: dict[str, Any],
        run_orders: list[dict[str, Any]],
        adapter: Any,
        ref: Any,
    ) -> dict[str, Any]:
        book = {o.broker_order_id: o for o in adapter.fetch_orders(ref)}
        fills = adapter.fetch_fills(ref, run["trade_date"])
        gtts = (
            {g.broker_gtt_id: g for g in adapter.fetch_gtts(ref)}
            if any(o["order_kind"] == "GTT" for o in run_orders)
            else {}
        )
        new_fills, updated = 0, 0
        for order in run_orders:
            broker_order_id = str(order["broker_order_id"])
            if order["order_kind"] == "GTT":
                gtt = gtts.get(broker_order_id)
                if gtt is None or gtt.status is not GttStatus.TRIGGERED:
                    continue
                broker_order_id = str(gtt.broker_flags.get("triggered_order_id") or "")
                if not broker_order_id:
                    continue
            for f in fills:
                if f.broker_order_id == broker_order_id and self._apply_fill(
                    conn, run, order, f.quantity, f.fill_price, f.filled_at, f.broker_trade_id
                ):
                    new_fills += 1
            state = book.get(broker_order_id)
            if state is not None and order["order_kind"] == "LIMIT":
                status = state.status.value
                if status != order["status"]:
                    orders.mark_status(
                        conn,
                        int(order["order_request_id"]),
                        status=status,
                        reject_reason=state.reject_reason,
                    )
                    updated += 1
            elif order["order_kind"] == "GTT" and orders.filled_quantity(
                conn, int(order["order_request_id"])
            ) >= int(order["quantity"]):
                orders.mark_status(conn, int(order["order_request_id"]), status="FILLED")
                updated += 1
        return {"mode": "LIVE", "new_fills": new_fills, "status_updates": updated}

    def _settle_dry(
        self,
        conn: Any,
        run: dict[str, Any],
        run_orders: list[dict[str, Any]],
        adapter: Any,
        ref: Any,
        broker_id: int,
    ) -> dict[str, Any]:
        """The paper fill engine (EXECUTION-MODES-AND-DRY-RUN.md 4). Conservative on
        purpose: a buy fills at its limit only if the day's LOW reached it, a sell only
        if the HIGH did; never better than the limit, never partial; an unfilled DAY
        buy expires with the day."""
        trade_date: date = run["trade_date"]
        day_over = today_ist() > trade_date
        new_fills, pending, expired = 0, 0, 0
        live = [o for o in run_orders if o["status"] in ("PLACED", "PARTIAL")]
        tokens = {
            int(r["instrument_id"]): r["broker_token"]
            for r in instruments.by_ids(
                conn, [int(o["instrument_id"]) for o in live], broker_id=broker_id
            )
        }
        for order in live:
            order_id = int(order["order_request_id"])
            token = tokens.get(int(order["instrument_id"]))
            bars = adapter.fetch_daily_candles(ref, token, trade_date, trade_date) if token else []
            limit = Decimal(order["limit_price"])
            bar = bars[-1] if bars else None
            hit = bar is not None and (
                bar.low <= limit if order["side"] == "BUY" else bar.high >= limit
            )
            if not hit:
                if order["order_kind"] == "LIMIT" and day_over:
                    reason = (
                        "paper DAY order expired: no bar for the day"
                        if bar is None
                        else f"paper DAY order expired: the day never reached {limit}"
                    )
                    orders.mark_status(conn, order_id, status="CANCELLED", reject_reason=reason)
                    expired += 1
                else:
                    pending += 1
                continue
            filled_at = datetime.combine(trade_date, datetime.min.time(), tzinfo=now_ist().tzinfo)
            if self._apply_fill(
                conn, run, order, int(order["quantity"]), limit, filled_at, f"DRY-{order_id}"
            ):
                new_fills += 1
            orders.mark_status(conn, order_id, status="FILLED")
        return {"mode": "DRY", "new_fills": new_fills, "pending": pending, "expired": expired}

    # ================================================================ discard
    def discard(self, run_id: int, *, actor: str) -> None:
        with transaction(self.engine.pool) as conn:
            run = runs.get_run(conn, run_id)
            run_orders = orders.orders_for_run(conn, run_id)
            if any(o["status"] != "INTENT" for o in run_orders):
                raise ValidationError(
                    "orders from this run have already been sent; settle it instead"
                )
            if run["status"] != "EXECUTING":
                raise ValidationError(f"run {run_id} is {run['status']}")
            for o in run_orders:
                orders.mark_status(
                    conn,
                    int(o["order_request_id"]),
                    status="CANCELLED",
                    reject_reason=f"plan discarded by {actor} before release",
                )
            runs.log(conn, run_id, level="INFO", stage="PLAN", message=f"discarded by {actor}")
            runs.set_status(conn, run_id, "FAILED")
            accounts.audit(
                conn, actor=actor, action="run_discarded", entity="run", entity_id=run_id
            )

    # ================================================================ helpers
    def _fail(self, run_id: int, stage: str, exc: Exception) -> None:
        with transaction(self.engine.pool) as conn:
            runs.log(
                conn,
                run_id,
                level="ERROR",
                stage=stage
                if stage
                in {"PREFLIGHT", "REFERENCE", "RECONCILE", "SELL", "BUY", "HARVEST", "SETTLE"}
                else "PREFLIGHT",
                message=f"{type(exc).__name__}: {exc}",
                context={"gate": getattr(exc, "gate", None)},
            )
            current = runs.get_run(conn, run_id)
            if current["status"] == "EXECUTING":
                runs.set_status(conn, run_id, "FAILED")
