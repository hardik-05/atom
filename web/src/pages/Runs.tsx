import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Candidate, type Run, type RunDetail } from "../api";
import { useApp } from "../context";
import { day, inr, pct, price, qty, when } from "../format";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorNote, Loading, Mono, Notice, PageHeader, TableBox, statusTone, useAction, useAsync } from "../ui";

export function RunsPage() {
  const app = useApp();
  const navigate = useNavigate();
  const list = useAsync(() => api.get<Run[]>("/runs"), []);
  const action = useAction();

  async function plan() {
    const r = await action.act(() =>
      api.post<{ run_id: number }>("/runs/plan", { account_id: app.accountId, universe_id: app.universeId }),
    );
    if (r) navigate(`/runs/${r.run_id}`);
  }

  return (
    <>
      <PageHeader
        title="Execute"
        subtitle="Plan computes every decision and writes each order as an intent. Nothing reaches the broker until you release it."
        actions={
          <Button variant="primary" onClick={plan} busy={action.busy} disabled={!app.accountId || !app.universeId}>
            Plan today's run
          </Button>
        }
      />
      {app.account && (
        <div className="mb-3">
          <Notice tone={app.account.execution_mode === "LIVE" ? "warn" : "info"}>
            {app.account.investor_name} · {app.account.broker_name} is a <b>{app.account.execution_mode}</b> account
            {app.account.execution_mode === "LIVE"
              ? " — a released run places real orders. The dry_run config key forces DRY for this universe without touching the account."
              : " — released orders are simulated against each day's high and low; nothing is sent."}
          </Notice>
        </div>
      )}
      <ErrorNote error={action.error} onDismiss={action.clear} />
      <Card title="Runs" className="mt-4" pad={false}>
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.length === 0 && (
          <Empty title="No runs yet">
            Before the first plan: import reference data, sync the instrument master and price history, complete the configuration, and generate today's token.
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
  const buyValue = useMemo(
    () => (d?.orders ?? []).filter((o) => o.side === "BUY").reduce((s, o) => s + Number(o.limit_price) * o.quantity, 0),
    [d],
  );
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
            {run.status === "EXECUTING" && intents.length > 0 && (
              <>
                <Button variant="ghost" onClick={() => setConfirm("discard")}>
                  Discard plan
                </Button>
                <Button variant={live ? "danger" : "primary"} onClick={() => setConfirm("release")}>
                  Release {intents.length} order{intents.length === 1 ? "" : "s"}
                </Button>
              </>
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

      <Card title={`Execution list · ${d.orders.length} order${d.orders.length === 1 ? "" : "s"} · buys ${inr(buyValue)}`} pad={false}>
        {d.orders.length === 0 ? (
          <Empty title="No orders in this run">Every candidate's reason is in the proposal table below.</Empty>
        ) : (
          <TableBox exportName={`run-${id}-orders.csv`} rows={d.orders as unknown as Record<string, unknown>[]}>
            <table className="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Kind</th>
                  <th className="num">Qty</th>
                  <th className="num">Limit</th>
                  <th className="num">Trigger</th>
                  <th className="num">Value</th>
                  <th>Status</th>
                  <th>Broker id</th>
                  <th>Ref</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {d.orders.map((o) => (
                  <tr key={o.order_request_id}>
                    <td className="font-medium">{o.symbol}</td>
                    <td className={o.side === "BUY" ? "text-gain" : "text-loss"}>{o.side}</td>
                    <td>{o.order_kind}</td>
                    <td className="num">{qty(o.quantity)}</td>
                    <td className="num">{price(o.limit_price)}</td>
                    <td className="num">{price(o.trigger_price)}</td>
                    <td className="num">{inr(Number(o.limit_price) * o.quantity)}</td>
                    <td>
                      <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                    </td>
                    <td>
                      <Mono>{o.broker_order_id ?? "—"}</Mono>
                    </td>
                    <td>
                      <Mono>{o.idempotency_key}</Mono>
                    </td>
                    <td className="max-w-[280px] text-[12px] text-muted">{o.reject_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        )}
      </Card>

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
        title={live ? `Place ${intents.length} REAL orders` : `Release ${intents.length} paper orders`}
        tone={live ? "danger" : "primary"}
        consequence={
          live ? (
            <>
              ATOM first cancels its own resting GTT sells for this universe and verifies they are gone, then places these orders at{" "}
              {run.broker_code} from this account's registered address. Buys total {inr(buyValue)}. Orders are limit orders; a buy the broker
              rejects for funds is recorded and the rest continue.
            </>
          ) : (
            <>Nothing is sent to {run.broker_code}. Orders are recorded as placed and filled on settle only if the day's high/low reached them.</>
          )
        }
        confirmLabel={live ? "Place real orders" : "Release"}
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
        title="Discard this plan"
        consequence="Every intent is cancelled before anything is sent and the run is marked FAILED, which frees today's slot so a fresh plan can be made."
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
