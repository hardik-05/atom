import { useEffect, useMemo, useState } from "react";
import { api, type CoverageRow, type Job } from "../api";
import { useApp } from "../context";
import { day, price } from "../format";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorNote, Loading, Notice, PageHeader, TableBox, inputCls, statusTone, useAction, useAsync } from "../ui";

function useJob(onDone: () => void) {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!job || job.status === "DONE" || job.status === "FAILED") return;
    const t = setInterval(async () => {
      const next = await api.get<Job>(`/jobs/${job.job_id}`).catch(() => null);
      if (next) {
        setJob(next);
        if (next.status === "DONE" || next.status === "FAILED") onDone();
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, onDone]);
  return [job, setJob] as const;
}

function JobLine({ job }: { job: Job | null }) {
  if (!job) return null;
  const pctDone = job.total ? Math.round((job.progress / job.total) * 100) : null;
  return (
    <div className="mt-2 rounded-md border border-line bg-bg px-3 py-2 text-[12px]">
      <div className="flex items-center justify-between gap-2">
        <span>
          <Badge tone={statusTone(job.status)}>{job.status}</Badge> <span className="ml-1 text-muted">{job.kind}</span>
        </span>
        {pctDone !== null && <span className="num">{job.progress}/{job.total}</span>}
      </div>
      {pctDone !== null && job.status === "RUNNING" && (
        <div className="mt-1.5 h-1 overflow-hidden rounded bg-line">
          <div className="h-full bg-accent transition-all" style={{ width: `${pctDone}%` }} />
        </div>
      )}
      <div className="mt-1 text-muted">{job.error ?? job.message}</div>
      {job.status === "DONE" && Object.keys(job.result).length > 0 && (
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted">{JSON.stringify(job.result, null, 1)}</pre>
      )}
    </div>
  );
}

export function UniversePage() {
  const app = useApp();
  const universeId = app.universeId;
  const coverage = useAsync(
    () => (universeId ? api.get<CoverageRow[]>(`/market/coverage?universe_id=${universeId}`) : Promise.resolve([] as CoverageRow[])),
    [universeId],
  );
  const action = useAction();
  const [days, setDays] = useState(400);
  const [filter, setFilter] = useState("");
  const [confirmFreeze, setConfirmFreeze] = useState<CoverageRow | null>(null);
  const [imported, setImported] = useState<Record<string, unknown> | null>(null);
  const reload = coverage.reload;
  const [syncJob, setSyncJob] = useJob(reload);
  const [historyJob, setHistoryJob] = useJob(reload);
  const [navJob, setNavJob] = useJob(reload);

  const rows = useMemo(
    () => (coverage.data ?? []).filter((r) => !filter || r.symbol.toLowerCase().includes(filter.toLowerCase()) || (r.category ?? "").toLowerCase().includes(filter.toLowerCase())),
    [coverage.data, filter],
  );
  const stats = useMemo(() => {
    const all = coverage.data ?? [];
    return {
      members: all.length,
      mapped: all.filter((r) => r.mapped).length,
      withHistory: all.filter((r) => r.bars >= 20).length,
      withNav: all.filter((r) => r.nav).length,
      frozen: all.filter((r) => r.member_status === "FROZEN").length,
    };
  }, [coverage.data]);

  return (
    <>
      <PageHeader title="Universe & market data" subtitle={app.universe ? `${app.universe.name} — categories ${app.universe.categories?.join(" → ") ?? "—"}` : "No universe yet"} />

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card title="1 · Reference data">
          <p className="mb-3 text-[13px] text-muted">
            The 311 tradable NSE ETFs with ISINs and their classification, and the <b>NSE ETFs</b> universe (EQUITY → COMMODITY → GLOBAL). Safe to re-run.
          </p>
          <Button
            variant="primary"
            busy={action.busy}
            onClick={async () => {
              const r = await action.act(() => api.post<Record<string, unknown>>("/reference/import"));
              if (r) {
                setImported(r);
                await app.refresh();
                await reload();
              }
            }}
          >
            Import reference
          </Button>
          {imported && <pre className="mt-2 font-mono text-[11px] text-muted">{JSON.stringify(imported)}</pre>}
        </Card>
        <Card title="2 · Instrument master">
          <p className="mb-3 text-[13px] text-muted">Maps every ATOM instrument to Upstox's key by ISIN, marks suspended ones, seeds tick sizes. Daily after 06:00.</p>
          <Button onClick={async () => setSyncJob(await api.post<Job>("/instruments/sync", { broker_code: "UPSTOX" }))}>Sync Upstox master</Button>
          <JobLine job={syncJob} />
        </Card>
        <Card title="3 · Price history">
          <p className="mb-3 text-[13px] text-muted">Daily bars for every member up to yesterday — what the mean/median deviation is computed from. Incremental.</p>
          <div className="flex gap-2">
            <select className={inputCls} value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[120, 250, 400, 750].map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
            <Button
              disabled={!app.accountId || !universeId}
              onClick={async () => setHistoryJob(await api.post<Job>("/market/sync-history", { account_id: app.accountId, universe_id: universeId, days }))}
            >
              Sync history
            </Button>
          </div>
          {!app.account?.session || app.account.session.status !== "VALID" ? <p className="mt-2 text-[11px] text-warn">Needs today's Upstox token.</p> : null}
          <JobLine job={historyJob} />
        </Card>
        <Card title="4 · NAV">
          <p className="mb-3 text-[13px] text-muted">AMFI's daily NAV file, for the NAV-premium gate. Public; no token needed.</p>
          <Button onClick={async () => setNavJob(await api.post<Job>("/market/sync-nav"))}>Sync NAV</Button>
          <JobLine job={navJob} />
        </Card>
      </div>
      <div className="mt-3">
        <ErrorNote error={action.error} onDismiss={action.clear} />
      </div>

      <Card
        className="mt-4"
        pad={false}
        title={`Members · ${stats.members} · ${stats.mapped} mapped · ${stats.withHistory} with ≥20 bars · ${stats.withNav} with NAV · ${stats.frozen} frozen`}
        actions={<input className={inputCls} placeholder="filter symbol or category" value={filter} onChange={(e) => setFilter(e.target.value)} />}
      >
        {coverage.loading && !coverage.data && <Loading />}
        <div className="px-4 pt-3">
          <ErrorNote error={coverage.error} />
        </div>
        {coverage.data && coverage.data.length === 0 && (
          <Empty title="This universe has no members yet">Import the reference data to create the NSE ETFs universe with its 311 members.</Empty>
        )}
        {rows.length > 0 && (
          <TableBox exportName="universe-coverage.csv" rows={rows as unknown as Record<string, unknown>[]}>
            <table className="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Category</th>
                  <th>Member</th>
                  <th>Upstox</th>
                  <th className="num">Tick</th>
                  <th className="num">Bars</th>
                  <th>Last bar</th>
                  <th className="num">NAV</th>
                  <th>NAV date</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.instrument_id}>
                    <td className="font-medium">{r.symbol}</td>
                    <td>{r.category ?? <span className="text-warn">none</span>}</td>
                    <td>
                      <Badge tone={statusTone(r.member_status)}>{r.member_status}</Badge>
                    </td>
                    <td>{r.mapped ? r.tradable ? <Badge tone="success">mapped</Badge> : <Badge tone="block">suspended</Badge> : <Badge tone="warn">unmapped</Badge>}</td>
                    <td className="num">{r.tick_size ?? "—"}</td>
                    <td className={`num ${r.bars < 20 ? "text-warn" : ""}`}>{r.bars}</td>
                    <td>{day(r.last_bar)}</td>
                    <td className="num">{price(r.nav)}</td>
                    <td>{day(r.nav_date)}</td>
                    <td>
                      <button className="text-[12px] text-accent hover:underline" onClick={() => setConfirmFreeze(r)}>
                        {r.member_status === "FROZEN" ? "unfreeze" : "freeze"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        )}
      </Card>
      {!app.accountId && <div className="mt-3"><Notice>History sync needs an account with a token; create one first.</Notice></div>}

      <ConfirmDialog
        open={!!confirmFreeze}
        title={confirmFreeze?.member_status === "FROZEN" ? `Unfreeze ${confirmFreeze?.symbol}` : `Freeze ${confirmFreeze?.symbol}`}
        consequence={
          confirmFreeze?.member_status === "FROZEN"
            ? "It becomes eligible for new buys again from the next run. Recorded in the audit log."
            : "It stays a member, keeps its history and any position is still sold at target — but it takes no new buys. Recorded in the audit log."
        }
        confirmLabel={confirmFreeze?.member_status === "FROZEN" ? "Unfreeze" : "Freeze"}
        busy={action.busy}
        onCancel={() => setConfirmFreeze(null)}
        onConfirm={async () => {
          if (!confirmFreeze || !universeId) return;
          await action.act(() =>
            api.put(`/universes/${universeId}/members/${confirmFreeze.instrument_id}`, {
              member_status: confirmFreeze.member_status === "FROZEN" ? "ACTIVE" : "FROZEN",
              reason: "set from the console",
            }),
          );
          setConfirmFreeze(null);
          await reload();
        }}
      />
    </>
  );
}
