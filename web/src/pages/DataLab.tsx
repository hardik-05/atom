import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Candle, type Funds, type HoldingRow, type InstrumentHit, type Quote } from "../api";
import { useApp } from "../context";
import { inr, pct, price, qty, when } from "../format";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader, StatTile, TableBox, inputCls, statusTone, useAction, useAsync } from "../ui";

export function DataLab() {
  const app = useApp();
  const id = app.accountId;
  if (!id) return <Notice>Select or create an account first.</Notice>;
  return (
    <>
      <PageHeader title="Data lab" subtitle="Live reads from the broker, through this account's egress. Nothing here places an order." />
      <FundsCard accountId={id} />
      <HoldingsCard accountId={id} />
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1.4fr]">
        <QuotesCard accountId={id} />
        <HistoryCard accountId={id} />
      </div>
    </>
  );
}

function FundsCard({ accountId }: { accountId: number }) {
  const funds = useAsync(() => api.get<Funds>(`/accounts/${accountId}/funds`), [accountId]);
  return (
    <div className="mb-4">
      <ErrorNote error={funds.error} />
      {funds.data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Available for delivery" value={inr(funds.data.available_cash)} sub={`as of ${when(funds.data.as_of)} · broker-reported`} />
          <StatTile label="Used margin" value={inr(funds.data.used_margin)} sub="broker-reported" />
          {Object.entries(funds.data.components)
            .filter(([k]) => !["available_margin", "used_margin"].includes(k))
            .slice(0, 2)
            .map(([k, v]) => (
              <StatTile key={k} label={k.replace(/_/g, " ")} value={inr(v)} sub="broker-reported" />
            ))}
        </div>
      )}
      {funds.loading && !funds.data && <Loading />}
    </div>
  );
}

function HoldingsCard({ accountId }: { accountId: number }) {
  const h = useAsync(() => api.get<HoldingRow[]>(`/accounts/${accountId}/holdings`), [accountId]);
  return (
    <Card title="Holdings at the broker" pad={false} actions={<Button onClick={h.reload} busy={h.loading}>Refresh</Button>}>
      <div className="px-4 pt-3">
        <ErrorNote error={h.error} />
      </div>
      {h.data && h.data.length === 0 && <Empty title="No holdings">The broker reports no long-term holdings or open delivery positions.</Empty>}
      {h.data && h.data.length > 0 && (
        <TableBox exportName="holdings.csv" rows={h.data as unknown as Record<string, unknown>[]}>
          <table className="data">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Source</th>
                <th className="num">Total</th>
                <th className="num">Free to sell</th>
                <th className="num">T1</th>
                <th className="num">Excluded</th>
                <th className="num">Avg price</th>
                <th className="num">LTP</th>
                <th className="num">vs avg</th>
                <th>ATOM status</th>
              </tr>
            </thead>
            <tbody>
              {h.data.map((row) => {
                const change = row.last_price && Number(row.average_price) > 0 ? ((Number(row.last_price) - Number(row.average_price)) / Number(row.average_price)) * 100 : null;
                return (
                  <tr key={`${row.source}-${row.instrument_id}`}>
                    <td>
                      <div className="font-medium">{row.symbol ?? row.instrument_id}</div>
                      <div className="max-w-[260px] truncate text-[11px] text-faint">{row.name}</div>
                    </td>
                    <td>{row.source === "HOLDING" ? "holding" : "T1 position"}</td>
                    <td className="num">{qty(row.total_quantity)}</td>
                    <td className="num">{row.free_quantity === null ? <span className="text-warn" title="not published by the broker; the total is used and the fallback is logged">assumed</span> : qty(row.free_quantity)}</td>
                    <td className="num">{qty(row.unsettled_quantity) }</td>
                    <td className="num">{row.withheld_quantity ? qty(row.withheld_quantity) : "—"}</td>
                    <td className="num">{price(row.average_price)}</td>
                    <td className="num">{price(row.last_price)}</td>
                    <td className={`num ${change === null ? "" : change >= 0 ? "text-gain" : "text-loss"}`}>{pct(change)}</td>
                    <td>
                      <Badge tone={statusTone(row.instrument_status)}>{row.instrument_status ?? "—"}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableBox>
      )}
      {h.loading && !h.data && <Loading />}
    </Card>
  );
}

function InstrumentPicker({ onPick, placeholder }: { onPick: (hit: InstrumentHit) => void; placeholder: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);
  const action = useAction();
  async function search(text: string) {
    setQ(text);
    if (text.trim().length < 2) return setHits([]);
    const r = await action.act(() => api.get<InstrumentHit[]>(`/instruments?q=${encodeURIComponent(text.trim())}`));
    if (r) setHits(r.slice(0, 8));
  }
  return (
    <div className="relative">
      <input className={`${inputCls} w-full`} value={q} placeholder={placeholder} onChange={(e) => void search(e.target.value)} />
      {hits.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-md border border-line bg-raised shadow-xl">
          {hits.map((h) => (
            <li key={h.instrument_id}>
              <button
                className="flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-[13px] hover:bg-accent-soft"
                onClick={() => {
                  onPick(h);
                  setHits([]);
                  setQ("");
                }}
              >
                <span>
                  <span className="font-medium">{h.symbol}</span> <span className="text-faint">{h.name}</span>
                </span>
                {!h.broker_token && <Badge tone="warn">unmapped</Badge>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function QuotesCard({ accountId }: { accountId: number }) {
  const [picked, setPicked] = useState<InstrumentHit[]>([]);
  const [quotes, setQuotes] = useState<Quote[] | null>(null);
  const action = useAction();
  async function fetchQuotes() {
    const r = await action.act(() => api.post<Quote[]>(`/accounts/${accountId}/quotes`, { instrument_ids: picked.map((p) => p.instrument_id) }));
    if (r) setQuotes(r);
  }
  return (
    <Card title="Live quotes" actions={<Button variant="primary" onClick={fetchQuotes} busy={action.busy} disabled={!picked.length}>Fetch</Button>}>
      <InstrumentPicker placeholder="Add an ETF — NIFTYBEES, GOLDBEES…" onPick={(h) => setPicked((p) => (p.some((x) => x.instrument_id === h.instrument_id) ? p : [...p, h]))} />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {picked.map((p) => (
          <button key={p.instrument_id} className="rounded border border-line px-2 py-0.5 text-[12px] hover:border-loss" onClick={() => setPicked((x) => x.filter((y) => y.instrument_id !== p.instrument_id))}>
            {p.symbol} ×
          </button>
        ))}
      </div>
      <div className="mt-3">
        <ErrorNote error={action.error} />
      </div>
      {quotes && (
        <table className="data mt-2">
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="num">LTP</th>
              <th className="num">Prev close</th>
              <th className="num">Change</th>
              <th className="num">Volume</th>
              <th>As of</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => {
              const change = q.last_price && q.close_price ? ((Number(q.last_price) - Number(q.close_price)) / Number(q.close_price)) * 100 : null;
              return (
                <tr key={q.symbol ?? q.instrument_id}>
                  <td className="font-medium">{q.symbol}</td>
                  {q.error ? (
                    <td colSpan={5} className="text-warn">
                      {q.error}
                    </td>
                  ) : (
                    <>
                      <td className="num">{price(q.last_price)}</td>
                      <td className="num">{price(q.close_price)}</td>
                      <td className={`num ${change === null ? "" : change >= 0 ? "text-gain" : "text-loss"}`}>{pct(change)}</td>
                      <td className="num">{qty(q.volume)}</td>
                      <td>{when(q.as_of)}</td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function HistoryCard({ accountId }: { accountId: number }) {
  const [inst, setInst] = useState<InstrumentHit | null>(null);
  const [days, setDays] = useState(120);
  const [bars, setBars] = useState<Candle[] | null>(null);
  const action = useAction();
  async function load(store: boolean) {
    if (!inst) return;
    const r = await action.act(() => api.get<Candle[]>(`/accounts/${accountId}/candles?instrument_id=${inst.instrument_id}&days=${days}&store=${store}`));
    if (r) setBars(r);
  }
  const chart = (bars ?? []).map((b) => ({ d: b.trade_date.slice(5), close: Number(b.close) }));
  const closes = chart.map((c) => c.close);
  const mean = closes.length ? closes.reduce((a, b) => a + b, 0) / closes.length : null;
  return (
    <Card
      title="Historical daily bars"
      actions={
        <>
          <select className={inputCls} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[30, 60, 120, 250, 500].map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
          <Button onClick={() => load(false)} busy={action.busy} disabled={!inst}>
            Fetch
          </Button>
          <Button variant="primary" onClick={() => load(true)} busy={action.busy} disabled={!inst} title="Fetch and write into the price history the strategy reads">
            Fetch &amp; store
          </Button>
        </>
      }
    >
      <InstrumentPicker placeholder="Pick one instrument" onPick={setInst} />
      {inst && <div className="mt-2 text-[12px] text-muted">{inst.symbol} · {inst.isin}</div>}
      <div className="mt-3">
        <ErrorNote error={action.error} />
      </div>
      {bars && bars.length === 0 && <Empty title="No bars returned">The broker returned no daily bars for this range.</Empty>}
      {bars && bars.length > 0 && (
        <>
          <div className="mb-2 text-[12px] text-muted">
            {bars.length} bars · mean close {price(mean)} · last {price(bars[bars.length - 1]!.close)}
          </div>
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={chart} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="d" tick={{ fill: "var(--text-muted)", fontSize: 11 }} minTickGap={24} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--text-muted)", fontSize: 11 }} width={56} />
                <Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", fontSize: 12 }} />
                <Line type="monotone" dataKey="close" stroke="var(--accent)" dot={false} strokeWidth={1.8} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Card>
  );
}
