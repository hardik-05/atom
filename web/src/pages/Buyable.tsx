import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type BuyableView, type Job } from "../api";
import { useApp } from "../context";
import { qty, when } from "../format";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader, TableBox, inputCls, useAsync } from "../ui";
import { JobLine, useJob } from "./Universe";

// D-213. Which ETFs a run may buy: the stored shortlist, built at Sync from the
// Configuration's viable-universe keys. The Universe & data page is unchanged.
export function BuyablePage() {
  const app = useApp();
  const { accountId, universeId } = app;
  const view = useAsync(
    () => (accountId && universeId ? api.get<BuyableView>(`/universes/${universeId}/buyable?account_id=${accountId}`) : Promise.resolve(null)),
    [accountId, universeId],
  );
  const [job, setJob] = useJob(view.reload);
  const [tab, setTab] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [showOut, setShowOut] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const cats = view.data?.categories ?? [];
  const cat = cats.find((c) => c.category === tab) ?? cats[0];
  const rows = useMemo(
    () =>
      (cat?.rows ?? []).filter(
        (r) =>
          (showOut || r.in_shortlist) &&
          (!filter || r.symbol.toLowerCase().includes(filter.toLowerCase()) || (r.name ?? "").toLowerCase().includes(filter.toLowerCase())),
      ),
    [cat, filter, showOut],
  );
  const running = job?.status === "RUNNING" || job?.status === "QUEUED";
  const tokenOk = app.account?.session?.status === "VALID";

  async function syncAll() {
    setError(null);
    try {
      setJob(await api.post<Job>("/market/sync-all", { account_id: accountId, universe_id: universeId }));
    } catch (e) {
      setError(e as Error);
    }
  }

  if (!accountId || !universeId) return <Notice>Select an account and a universe in the header first.</Notice>;

  return (
    <>
      <PageHeader
        title="Buyable universe"
        subtitle="Per category, the ETFs a run may buy: the top N by average daily volume. Built at Sync, never during a run."
        actions={
          <Button variant="primary" onClick={syncAll} busy={running} disabled={running || !tokenOk}>
            Sync all
          </Button>
        }
      />
      <div className="mb-3 space-y-2">
        {!tokenOk && <Notice tone="warn">Sync all needs today's broker token.</Notice>}
        <Notice>
          <b>Sync all</b> runs, in order: the instrument master, price history (only the missing days — after a config change this costs almost nothing), NAV,
          then rebuilds the shortlist from the configuration below. Prices at Execute are fetched only for the shortlisted ETFs.
        </Notice>
        <ErrorNote error={error ?? view.error} onDismiss={() => setError(null)} />
        <JobLine job={job} />
      </div>

      {view.loading && !view.data && <Loading />}
      {view.data && cats.length === 0 && <Empty title="This universe has no categories">Import the reference data on Universe &amp; data first.</Empty>}

      {cat && (
        <>
          <div className="mb-3 flex flex-wrap gap-2">
            {cats.map((c) => (
              <button
                key={c.category}
                onClick={() => setTab(c.category)}
                className={`rounded-md border px-3 py-1.5 text-[13px] ${c.category === cat.category ? "border-accent bg-accent/10 font-medium text-accent" : "border-line text-muted hover:text-fg"}`}
              >
                {c.category} <span className="ml-1 text-[11px]">{c.in_count}/{c.rows.length}</span>
              </button>
            ))}
          </div>

          <Card
            title={`${cat.category} · ${cat.in_count} buyable of ${cat.rows.length}`}
            pad={false}
            actions={
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1 text-[12px] text-muted">
                  <input type="checkbox" checked={showOut} onChange={(e) => setShowOut(e.target.checked)} /> show excluded
                </label>
                <input className={inputCls} placeholder="filter ticker or name" value={filter} onChange={(e) => setFilter(e.target.value)} />
              </div>
            }
          >
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-line px-4 py-2.5 text-[12px] text-muted">
              <span>
                top <b className="text-fg">{cat.shortlist_size ?? "—"}</b>
              </span>
              <span>
                over <b className="text-fg">{cat.volume_window_days ?? "—"}</b> trading days
              </span>
              <span>
                at least <b className="text-fg">{cat.volume_threshold_units != null ? qty(Number(cat.volume_threshold_units)) : "—"}</b> units a day
              </span>
              <Link className="text-accent hover:underline" to="/config">
                change in Configuration →
              </Link>
              <span className="ml-auto">built {cat.built_at ? when(cat.built_at) : "never"}</span>
            </div>
            {cat.shortlist_size == null && (
              <div className="px-4 pt-3">
                <Notice tone="warn">The viable-universe keys are not set for {cat.category}; nothing in it can be bought.</Notice>
              </div>
            )}
            {cat.stale && (
              <div className="px-4 pt-3">
                <Notice tone="warn">The configuration or the volume data changed since the list was built. Press Sync all to rebuild it.</Notice>
              </div>
            )}
            <TableBox exportName={`buyable-${cat.category.toLowerCase()}.csv`} rows={rows as unknown as Record<string, unknown>[]}>
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">Rank</th>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th className="num">Avg volume</th>
                    <th className="num">Days</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.instrument_id} className={r.in_shortlist ? "" : "opacity-70"}>
                      <td className="num">{r.rank ?? ""}</td>
                      <td className="font-medium">{r.symbol}</td>
                      <td className="max-w-[320px] truncate text-[12px] text-muted">{r.name}</td>
                      <td className="num">{r.avg_volume != null ? qty(Math.round(Number(r.avg_volume))) : "—"}</td>
                      <td className={`num ${cat.volume_window_days && r.volume_days < cat.volume_window_days ? "text-warn" : ""}`}>{r.volume_days}</td>
                      <td>
                        {r.in_shortlist ? <Badge tone="success">IN</Badge> : <Badge>OUT</Badge>}
                        {r.member_status === "FROZEN" && (
                          <span className="ml-1">
                            <Badge tone="block">frozen member</Badge>
                          </span>
                        )}
                        {r.reason && <span className="ml-2 text-[11px] text-faint">{r.reason}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBox>
          </Card>
        </>
      )}
    </>
  );
}
