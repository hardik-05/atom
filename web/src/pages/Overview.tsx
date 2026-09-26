import { Link } from "react-router-dom";
import { api, type Overview as OverviewData } from "../api";
import { day, when } from "../format";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, StatTile, TableBox, statusTone, useAsync } from "../ui";

export function Overview() {
  const { data, error, loading } = useAsync(() => api.get<OverviewData>("/overview"), []);
  if (loading && !data) return <Loading />;
  if (!data) return <ErrorNote error={error} />;
  const valid = data.accounts.filter((a) => a.session?.status === "VALID").length;
  const setupSteps = [
    { done: data.accounts.length > 0, label: "Create the investor and trading account", to: "/setup" },
    { done: data.instrument_counts.instruments > 0, label: "Import the ETF reference data", to: "/universe" },
    { done: data.instrument_counts.mapped > 0, label: "Sync the Upstox instrument master", to: "/universe" },
    { done: valid > 0, label: "Generate today's broker token", to: "/tokens" },
  ];
  const pending = setupSteps.filter((s) => !s.done);

  return (
    <>
      <PageHeader title="Overview" subtitle={`Trading day ${day(data.today)} (IST)`} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Accounts" value={data.accounts.length} sub={`${valid} with a valid token today`} />
        <StatTile label="Universes" value={data.universes.length} sub={data.universes.map((u) => u.name).join(", ") || "none yet"} />
        <StatTile
          label="Instruments"
          value={data.instrument_counts.instruments}
          sub={`${data.instrument_counts.mapped} mapped to Upstox · ${data.instrument_counts.classified} classified`}
        />
        <StatTile label="Runs (recent)" value={data.runs.length} sub={data.runs[0] ? `latest #${data.runs[0].run_id} ${data.runs[0].status.toLowerCase()}` : "none yet"} />
      </div>

      {pending.length > 0 && (
        <Card title="Getting started" className="mt-4">
          <ol className="space-y-2 text-[13px]">
            {setupSteps.map((s, i) => (
              <li key={s.label} className="flex items-center gap-3">
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${s.done ? "bg-gain text-white" : "border border-line text-muted"}`}>
                  {s.done ? "✓" : i + 1}
                </span>
                {s.done ? (
                  <span className="text-muted line-through">{s.label}</span>
                ) : (
                  <Link to={s.to} className="text-accent hover:underline">
                    {s.label}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Accounts" pad={false}>
          {data.accounts.length === 0 ? (
            <Empty title="No accounts yet">Create Nidhi's investor record and her Upstox account under Investors &amp; accounts.</Empty>
          ) : (
            <TableBox>
              <table className="data">
                <thead>
                  <tr>
                    <th>Investor</th>
                    <th>Broker</th>
                    <th>Client</th>
                    <th>Mode</th>
                    <th>Token today</th>
                  </tr>
                </thead>
                <tbody>
                  {data.accounts.map((a) => (
                    <tr key={a.trading_account_id}>
                      <td>{a.investor_name}</td>
                      <td>{a.broker_name}</td>
                      <td className="font-mono text-[12px]">{a.broker_client_code}</td>
                      <td>
                        <Badge tone={a.execution_mode === "LIVE" ? "danger" : "info"}>{a.execution_mode}</Badge>
                      </td>
                      <td>
                        <Badge tone={statusTone(a.session?.status)}>{a.session?.status ?? "none"}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBox>
          )}
        </Card>

        <Card title="Recent runs" pad={false} actions={<Link to="/runs" className="text-[12px] text-accent hover:underline">All runs</Link>}>
          {data.runs.length === 0 ? (
            <Empty title="No runs yet">A run plans against today's quotes and the stored history; nothing is sent until you release it.</Empty>
          ) : (
            <TableBox>
              <table className="data">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Date</th>
                    <th>Universe</th>
                    <th>Mode</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.runs.map((r) => (
                    <tr key={r.run_id}>
                      <td>
                        <Link to={`/runs/${r.run_id}`} className="text-accent hover:underline">
                          {r.run_id}
                        </Link>
                      </td>
                      <td>{day(r.trade_date)}</td>
                      <td>{r.universe_name}</td>
                      <td>{r.execution_mode}</td>
                      <td>
                        <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBox>
          )}
        </Card>
      </div>

      {data.jobs.length > 0 && (
        <Card title="Background jobs" className="mt-4" pad={false}>
          <TableBox>
            <table className="data">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Message</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td>{j.kind}</td>
                    <td>
                      <Badge tone={statusTone(j.status)}>{j.status}</Badge>
                    </td>
                    <td className="num">{j.total ? `${j.progress}/${j.total}` : "—"}</td>
                    <td className="text-muted">{j.error ?? j.message}</td>
                    <td>{when(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        </Card>
      )}
    </>
  );
}
