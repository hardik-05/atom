import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Candidate, type OrderRow, type Run, type RunDetail } from "../api";
import { useApp } from "../context";
import { day, inr, pct, price, qty, when } from "../format";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorNote, Loading, Mono, Notice, PageHeader, Spinner, TableBox, statusTone, useAction, useAsync } from "../ui";

export function RunsPage() {
  const app = useApp();
  const navigate = useNavigate();
  const list = useAsync(() => api.get<Run[]>("/runs"), []);
  const action = useAction();

  async function execute() {
    const r = await action.act(() =>
      api.post<{ run_id: number }>("/runs/plan", { account_id: app.accountId, universe_id: app.universeId }),
    );
    if (r) navigate(`/runs/${r.run_id}`);
  }

  return (
    <>
      <PageHeader
        title="Execute"
        subtitle="Execute sends today's sells to the broker straight away and, at the same time, works out today's buys from the shortlist. The buys go out only when you approve them, once a day."
        actions={
          <Button variant="primary" onClick={execute} busy={action.busy} disabled={!app.accountId || !app.universeId}>
            Execute
          </Button>
        }
      />
      {app.account && (
        <div className="mb-3">
          <Notice tone={app.account.execution_mode === "LIVE" ? "warn" : "info"}>
            {app.account.investor_name} · {app.account.broker_name} is a <b>{app.account.execution_mode}</b> account
            {app.account.execution_mode === "LIVE"
              ? " — Execute places real sell orders at once, and approved buys are real orders. The dry_run config key forces DRY for this universe without touching the account."
              : " — orders are simulated against each day's high and low; nothing is sent."}
          </Notice>
        </div>
      )}
      <ErrorNote error={action.error} onDismiss={action.clear} />
      <Card title="Runs" className="mt-4" pad={false}>
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.length === 0 && (
          <Empty title="No runs yet">
            Before the first Execute: import reference data, sync the instrument master and price history, complete the configuration, and generate today's token.
          </Empty>
        )}
        {list.data && list.data.length > 0 && (
          <TableBox>
            <table className="data">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Trade date</th>
                  <th>Account</th>
                  <th>Universe</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      <Link className="text-accent hover:underline" to={`/runs/${r.run_id}`}>
                        {r.run_id}
                      </Link>
                    </td>
                    <td>{day(r.trade_date)}</td>
                    <td>
                      {r.investor_name} · {r.broker_code}
                    </td>
                    <td>{r.universe_name}</td>
                    <td>
                      <Badge tone={r.execution_mode === "LIVE" ? "danger" : "info"}>{r.execution_mode}</Badge>
                    </td>
                    <td>
                      <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                    </td>
                    <td>{when(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        )}
      </Card>
    </>
  );
}

function decisionTone(c: Candidate) {
  if (c.decision === "BOUGHT" || c.decision === "SOLD") return "success" as const;
  if (c.gate_failed === "proxy_block" || c.gate_failed === "freeze") return "block" as const;
  if (c.decision === "SKIPPED") return "warn" as const;
  return "neutral" as const;
}

export function RunDetailPage() {
  const { runId } = useParams();
  const id = Number(runId);
  const detail = useAsync(() => api.get<RunDetail>(`/runs/${id}`), [id]);
  const action = useAction();
  const [confirm, setConfirm] = useState<"release" | "discard" | null>(null);
  const [category, setCategory] = useState<string>("ALL");
  const [outcome, setOutcome] = useState<Record<string, unknown> | null>(null);

  const d = detail.data;
  const intents = d?.orders.filter((o) => o.status === "INTENT") ?? [];
  const sellOrders = d?.orders.filter((o) => o.side === "SELL") ?? [];
  const buyOrders = d?.orders.filter((o) => o.side === "BUY") ?? [];
  const buyIntents = buyOrders.filter((o) => o.status === "INTENT");
  const buyValue = useMemo(
    () => buyIntents.reduce((s, o) => s + Number(o.limit_price) * o.quantity, 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d],
  );
  const p = d?.progress ?? null;
  const working = !!p && (["PLANNING", "SENDING"].includes(p.sells) || ["WAITING", "CALCULATING"].includes(p.buys));
  const reload = detail.reload;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void reload(), 2000);
    return () => clearInterval(t);
  }, [working, reload]);
  const categories = useMemo(() => ["ALL", ...Array.from(new Set((d?.candidates ?? []).map((c) => c.category)))], [d]);

  if (detail.loading && !d) return <Loading />;
  if (!d) return <ErrorNote error={detail.error} />;
  const run = d.run;
  const live = run.execution_mode === "LIVE";
  const shown = d.candidates.filter((c) => category === "ALL" || c.category === category);

  return (
    <>
      <PageHeader
        title={`Run #${run.run_id}`}
        subtitle={`${run.investor_name} · ${run.broker_code} · ${run.universe_name} · trade date ${day(run.trade_date)}`}
        actions={
          <>
            <Badge tone={live ? "danger" : "info"}>{run.execution_mode}</Badge>
            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
            {run.status === "EXECUTING" && intents.length > 0 && !working && (
              <Button variant="ghost" onClick={() => setConfirm("discard")}>
                Discard
              </Button>
            )}
            {run.status !== "FAILED" && intents.length === 0 && d.orders.length > 0 && (
              <Button
                onClick={async () => {
                  const r = await action.act(() => api.post<Record<string, unknown>>(`/runs/${id}/settle`));
                  if (r) {
                    setOutcome(r);
                    await detail.reload();
                  }
                }}
                busy={action.busy}
              >
                Settle
              </Button>
            )}
          </>
        }
      />
      <ErrorNote error={action.error} onDismiss={action.clear} />
      {outcome && (
        <div className="mb-3">
          <Notice tone="success">
            <Mono>{JSON.stringify(outcome)}</Mono>
          </Notice>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title={
            <span className="flex items-center gap-2">
              1 · Sells <SellState run={d} />
            </span>
          }
          pad={false}
        >
          {sellOrders.length === 0 ? (
            <div className="p-4 text-[13px] text-muted">
              {p && ["PLANNING"].includes(p.sells) ? (
                <span className="flex items-center gap-2">
                  <Spinner small /> Working out today's sells…
                </span>
              ) : p?.sells === "ALREADY_SENT" ? (
                "Today's sells were already sent by an earlier Execute."
              ) : p?.sells === "FAILED" ? (
                <span className="text-loss">{p.sells_error}</span>
              ) : (
                "Nothing to sell today."
              )}
            </div>
          ) : (
            <OrdersTable orders={sellOrders} exportName={`run-${id}-sells.csv`} />
          )}
          {p?.sells_error && sellOrders.length > 0 && <div className="border-t border-line p-3 text-[12px] text-loss">{p.sells_error}</div>}
        </Card>

        <Card
          title={
            <span className="flex items-center gap-2">
              2 · Buys <BuyState run={d} />
            </span>
          }
          actions={
            run.status === "EXECUTING" &&
            buyIntents.length > 0 &&
            !working && (
              <Button variant={live ? "danger" : "primary"} onClick={() => setConfirm("release")}>
                Approve {buyIntents.length} buy{buyIntents.length === 1 ? "" : "s"} · {inr(buyValue)}
              </Button>
            )
          }
          pad={false}
        >
          {buyOrders.length === 0 ? (
            <div className="p-4 text-[13px] text-muted">
              {p && ["WAITING", "CALCULATING"].includes(p.buys) ? (
                <span className="flex items-center gap-2">
                  <Spinner small /> Fetching prices for the shortlist and ranking the candidates…
                </span>
              ) : p?.buy_error ? (
                <span className="text-loss">{p.buy_error}</span>
              ) : (
                "No buys today. Every candidate's reason is in the proposal table below."
              )}
            </div>
          ) : (
            <OrdersTable orders={buyOrders} exportName={`run-${id}-buys.csv`} />
          )}
        </Card>
      </div>

      <Card
        title={`Proposal table · ${d.candidates.length} candidates`}
        className="mt-4"
        pad={false}
        actions={
          <div className="flex gap-1">
            {categories.map((c) => (
              <button key={c} onClick={() => setCategory(c)} className={`rounded px-2 py-0.5 text-[12px] ${category === c ? "bg-accent-soft text-accent" : "text-muted hover:text-ink"}`}>
                {c}
              </button>
            ))}
          </div>
        }
      >
        <TableBox exportName={`run-${id}-candidates.csv`} rows={shown as unknown as Record<string, unknown>[]} maxHeight="60vh">
          <table className="data">
            <thead>
              <tr>
                <th>Cat</th>
                <th className="num">Rank</th>
                <th>Symbol</th>
                <th className="num">LTP</th>
                <th className="num">Reference</th>
                <th className="num">Median</th>
                <th className="num">Deviation</th>
                <th className="num">NAV prem.</th>
                <th>Held</th>
                <th>Decision</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.run_candidate_id}>
                  <td className="text-[12px] text-muted">{c.category}</td>
                  <td className="num">{c.rank || "—"}</td>
                  <td className="font-medium">{c.symbol}</td>
                  <td className="num">{price(c.ltp)}</td>
                  <td className="num">{price(c.mean_price)}</td>
                  <td className="num">{price(c.median_price)}</td>
                  <td className={`num ${Number(c.deviation_pct) < 0 ? "text-loss" : Number(c.deviation_pct) > 0 ? "text-gain" : ""}`}>{c.rank ? pct(c.deviation_pct) : "—"}</td>
                  <td className="num">{pct(c.nav_premium_pct)}</td>
                  <td>{c.holdings_status === "HELD" ? <Badge tone="info">held</Badge> : ""}</td>
                  <td>
                    <Badge tone={decisionTone(c)}>{c.decision.replace("_", " ")}</Badge>
                    {c.gate_failed && <div className="mt-0.5 font-mono text-[10px] text-faint">{c.gate_failed}</div>}
                  </td>
                  <td className="max-w-[420px] text-[12px] text-muted">{c.decision_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableBox>
      </Card>

      <Card title="Run log" className="mt-4" pad={false}>
        <TableBox maxHeight="40vh">
          <table className="data">
            <tbody>
              {d.logs.map((l) => (
                <tr key={l.run_log_id}>
                  <td className="w-[110px] text-[12px] text-faint">{when(l.logged_at)}</td>
                  <td className="w-[90px]">
                    <Badge tone={l.level === "ERROR" ? "danger" : l.level === "WARNING" ? "warn" : "neutral"}>{l.stage}</Badge>
                  </td>
                  <td className="text-[12px]">{l.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableBox>
      </Card>

      <ConfirmDialog
        open={confirm === "release"}
        title={live ? `Approve ${buyIntents.length} REAL buys` : `Approve ${buyIntents.length} paper buys`}
        tone={live ? "danger" : "primary"}
        consequence={
          live ? (
            <>
              The buys are placed at {run.broker_code} from this account's registered address. This is the day's one approval. Buys
              total {inr(buyValue)}. Orders are limit orders; a buy the broker
              rejects for funds is recorded and the rest continue.
            </>
          ) : (
            <>Nothing is sent to {run.broker_code}. Orders are recorded as placed and filled on settle only if the day's high/low reached them.</>
          )
        }
        confirmLabel={live ? "Place real buys" : "Approve"}
        busy={action.busy}
        onCancel={() => setConfirm(null)}
        onConfirm={async () => {
          const r = await action.act(() => api.post<Record<string, unknown>>(`/runs/${id}/release`));
          setConfirm(null);
          if (r) setOutcome(r);
          await detail.reload();
        }}
      />
      <ConfirmDialog
        open={confirm === "discard"}
        title="Discard these buys"
        consequence="The unapproved buys are cancelled, so a fresh Execute can be run today. Sells already sent are not recalled."
        confirmLabel="Discard"
        tone="danger"
        busy={action.busy}
        onCancel={() => setConfirm(null)}
        onConfirm={async () => {
          await action.act(() => api.post(`/runs/${id}/discard`));
          setConfirm(null);
          await detail.reload();
        }}
      />
    </>
  );
}

function SellState({ run }: { run: RunDetail }) {
  const p = run.progress;
  const sells = run.orders.filter((o) => o.side === "SELL");
  if (p?.sells === "PLANNING" || p?.sells === "SENDING")
    return (
      <Badge tone="info">
        <Spinner small /> {p.sells === "PLANNING" ? "planning" : "sending"}
      </Badge>
    );
  if (p?.sells === "FAILED") return <Badge tone="danger">not sent</Badge>;
  if (p?.sells === "ALREADY_SENT") return <Badge tone="neutral">sent earlier</Badge>;
  const sent = sells.filter((o) => o.status !== "INTENT" && o.status !== "CANCELLED").length;
  if (sells.length === 0) return <Badge tone="neutral">none</Badge>;
  return <Badge tone={sent === sells.length ? "success" : "warn"}>{sent} of {sells.length} sent</Badge>;
}

function BuyState({ run }: { run: RunDetail }) {
  const p = run.progress;
  const buys = run.orders.filter((o) => o.side === "BUY");
  if (p?.buys === "WAITING" || p?.buys === "CALCULATING")
    return (
      <Badge tone="info">
        <Spinner small /> calculating
      </Badge>
    );
  if (p?.buys === "FAILED") return <Badge tone="danger">not planned</Badge>;
  if (buys.length === 0) return <Badge tone="neutral">none</Badge>;
  if (buys.some((o) => o.status === "INTENT")) return <Badge tone="warn">awaiting approval</Badge>;
  if (buys.every((o) => o.status === "CANCELLED")) return <Badge tone="neutral">discarded</Badge>;
  return <Badge tone="success">approved</Badge>;
}

function OrdersTable({ orders, exportName }: { orders: OrderRow[]; exportName: string }) {
  return (
    <TableBox exportName={exportName} rows={orders as unknown as Record<string, unknown>[]}>
      <table className="data">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Kind</th>
            <th className="num">Qty</th>
            <th className="num">Limit</th>
            <th className="num">Value</th>
            <th>Status</th>
            <th>Broker id</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.order_request_id}>
              <td className="font-medium">{o.symbol}</td>
              <td>{o.order_kind}</td>
              <td className="num">{qty(o.quantity)}</td>
              <td className="num">{price(o.limit_price)}</td>
              <td className="num">{inr(Number(o.limit_price) * o.quantity)}</td>
              <td>
                <Badge tone={statusTone(o.status)}>{o.status}</Badge>
              </td>
              <td>
                <Mono>{o.broker_order_id ?? "—"}</Mono>
              </td>
              <td className="max-w-[240px] text-[12px] text-muted">{o.reject_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableBox>
  );
}
