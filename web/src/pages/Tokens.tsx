import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Account, type Candle, type Funds, type HoldingRow, type InstrumentHit, type Quote } from "../api";
import { useApp } from "../context";
import { inr, price, qty, when } from "../format";
import { Badge, Button, Card, ErrorNote, Field, Loading, Mono, Notice, PageHeader, inputCls, statusTone, useAction, useAsync } from "../ui";

interface ExchangeResult {
  ok: boolean;
  detail: string;
  flags: Record<string, unknown>;
  onboarding: { mode: string; excluded: { instrument_id: number; quantity: number }[] } | null;
}

const TEST_SYMBOLS = ["NIFTYBEES", "GOLDBEES", "BANKBEES"];

export function Tokens() {
  const app = useApp();
  const [params] = useSearchParams();
  const accountId = app.accountId;
  const acct = useAsync(() => (accountId ? api.get<Account>(`/accounts/${accountId}`) : Promise.resolve(null)), [accountId]);
  const [code, setCode] = useState(params.get("code") ?? "");
  const [result, setResult] = useState<ExchangeResult | null>(null);
  const [probe, setProbe] = useState<{ ok: boolean; detail: string } | null>(null);
  const [runTests, setRunTests] = useState(0);
  const action = useAction();

  if (!accountId) {
    return (
      <>
        <PageHeader title="Broker tokens" />
        <Notice>
          No trading account yet. Create one under <Link className="text-accent underline" to="/setup">Investors &amp; accounts</Link>.
        </Notice>
      </>
    );
  }
  if (acct.loading && !acct.data) return <Loading />;
  const account = acct.data;
  if (!account) return <ErrorNote error={acct.error} />;
  const secretsMissing = Object.entries(account.secrets_present ?? {}).filter(([, v]) => !v).map(([k]) => k);
  const session = account.session;

  async function authorize() {
    const r = await action.act(() => api.post<{ url: string }>(`/accounts/${accountId}/token/authorize`));
    if (r) window.open(r.url, "_blank", "noopener,noreferrer");
  }

  async function exchange() {
    const r = await action.act(() => api.post<ExchangeResult>(`/accounts/${accountId}/token/exchange`, { code: code.trim() }));
    if (r) {
      setResult(r);
      setCode("");
      await Promise.all([acct.reload(), app.refresh()]);
      if (r.ok) setRunTests((n) => n + 1);
    }
  }

  return (
    <>
      <PageHeader
        title="Broker tokens"
        subtitle={`${account.investor_name} · ${account.broker_name} · ${account.broker_client_code} — a fresh token each trading day; validity is tested, never assumed (D-170).`}
      />

      {secretsMissing.length > 0 && (
        <div className="mb-4">
          <Notice tone="warn">
            <div className="font-medium">This account's {account.broker_name} app credentials are not stored yet ({secretsMissing.join(", ")}).</div>
            <div className="mt-1">From your own machine, run:</div>
            <pre className="mt-1 overflow-x-auto rounded bg-bg p-2 font-mono text-[12px]">
              python -m atom.cli broker-secret --account-id {account.trading_account_id} --broker {account.broker_code}
            </pre>
            <div className="mt-1 text-muted">The key and secret go straight to SSM at a hidden prompt — never into this page or a chat.</div>
          </Notice>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <Card title="Generate today's token">
          <ol className="space-y-5">
            <li>
              <div className="mb-1 text-[13px] font-semibold">1 · Sign in at {account.broker_name}</div>
              <p className="mb-2 text-[13px] text-muted">
                Opens {account.broker_name}'s login in a new tab. Enter Nidhi's credentials and 2FA there — ATOM never sees them.
              </p>
              <Button variant="primary" onClick={authorize} busy={action.busy} disabled={secretsMissing.length > 0}>
                Generate token ↗
              </Button>
            </li>
            <li>
              <div className="mb-1 text-[13px] font-semibold">2 · Paste the code back</div>
              <p className="mb-2 text-[13px] text-muted">
                After sign-in {account.broker_name} redirects to ATOM with <Mono>?code=…</Mono> in the address bar. If that page opens
                here, the code is filled in automatically; otherwise copy it from the address bar.
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  className={`${inputCls} min-w-[260px] flex-1 font-mono`}
                  placeholder="authorisation code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  spellCheck={false}
                />
                <Button variant="primary" onClick={exchange} busy={action.busy} disabled={code.trim().length < 4}>
                  Exchange for token
                </Button>
              </div>
            </li>
          </ol>
          <div className="mt-4">
            <ErrorNote error={action.error} onDismiss={action.clear} />
          </div>
          {result && (
            <div className="mt-4">
              <Notice tone={result.ok ? "success" : "warn"}>
                <div className="font-medium">{result.ok ? "Token stored and verified." : "Token stored but the probe failed."}</div>
                <div className="mt-0.5 text-muted">{result.detail}</div>
                {result.onboarding && (
                  <div className="mt-1">
                    First connection — onboarding done ({result.onboarding.mode}).{" "}
                    {result.onboarding.mode === "LIVE"
                      ? `${result.onboarding.excluded.length} pre-existing holding(s) excluded, so ATOM never sells what it did not buy (D-137).`
                      : "Paper account: the book starts empty and the broker's real holdings are never read into it."}
                  </div>
                )}
              </Notice>
            </div>
          )}
        </Card>

        <Card
          title="Today's session"
          actions={
            <>
              <Button
                onClick={async () => {
                  const r = await action.act(() => api.post<{ ok: boolean; detail: string }>(`/accounts/${accountId}/token/probe`));
                  if (r) {
                    setProbe(r);
                    await acct.reload();
                  }
                }}
                disabled={!session || session.status === "CLEARED"}
              >
                Test token
              </Button>
              <Button
                variant="ghost"
                onClick={async () => {
                  if (await action.act(() => api.del(`/accounts/${accountId}/token`))) {
                    setProbe(null);
                    setResult(null);
                    await Promise.all([acct.reload(), app.refresh()]);
                  }
                }}
                disabled={!session || session.status === "CLEARED"}
              >
                Revoke &amp; clear
              </Button>
            </>
          }
        >
          {session ? (
            <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-[13px]">
              <dt className="text-muted">Status</dt>
              <dd>
                <Badge tone={statusTone(session.status)}>{session.status}</Badge>
              </dd>
              <dt className="text-muted">Trade date</dt>
              <dd>{session.trade_date}</dd>
              <dt className="text-muted">Obtained</dt>
              <dd>{when(session.obtained_at)}</dd>
              <dt className="text-muted">Last verified</dt>
              <dd>{when(session.verified_at)}</dd>
            </dl>
          ) : (
            <p className="text-[13px] text-muted">No token for today yet. Tokens are per trading day; yesterday's is never reused.</p>
          )}
          {probe && (
            <div className="mt-3">
              <Notice tone={probe.ok ? "success" : "warn"}>{probe.detail}</Notice>
            </div>
          )}
          <div className="mt-4 border-t border-line pt-3 text-[12px] text-muted">
            <div className="font-medium text-ink">Redirect URI to register in the {account.broker_name} developer app</div>
            <div className="mt-1 flex items-center gap-2">
              <Mono>{app.redirectUri}</Mono>
              <button className="text-accent hover:underline" onClick={() => navigator.clipboard?.writeText(app.redirectUri)}>
                copy
              </button>
            </div>
            <div className="mt-1">It must match character for character, or {account.broker_name} refuses the sign-in.</div>
          </div>
        </Card>
      </div>

      <div className="mt-4">
        <ConnectionTest accountId={accountId} trigger={runTests} enabled={session?.status === "VALID"} />
      </div>
    </>
  );
}

// ----------------------------------------------------------------------------
// The acceptance test from the brief: once the bearer token lands, prove the
// account and the data pool are both reachable — funds, holdings, live quotes
// for a few ETFs, and the daily history the deviation metric is computed from.

type Step<T> = { state: "idle" | "running" | "ok" | "error"; data?: T; error?: string; ms?: number };

function useStep<T>() {
  return useState<Step<T>>({ state: "idle" });
}

function ConnectionTest({ accountId, trigger, enabled }: { accountId: number; trigger: number; enabled: boolean }) {
  const [funds, setFunds] = useStep<Funds>();
  const [holdings, setHoldings] = useStep<HoldingRow[]>();
  const [quotes, setQuotes] = useStep<Quote[]>();
  const [candles, setCandles] = useStep<{ symbol: string; bars: Candle[] }>();
  const [running, setRunning] = useState(false);

  async function timed<T>(set: (s: Step<T>) => void, fn: () => Promise<T>) {
    set({ state: "running" });
    const t0 = performance.now();
    try {
      const data = await fn();
      set({ state: "ok", data, ms: Math.round(performance.now() - t0) });
    } catch (e) {
      set({ state: "error", error: (e as Error).message, ms: Math.round(performance.now() - t0) });
    }
  }

  async function run() {
    setRunning(true);
    await timed(setFunds, () => api.get<Funds>(`/accounts/${accountId}/funds`));
    await timed(setHoldings, () => api.get<HoldingRow[]>(`/accounts/${accountId}/holdings`));
    const hits = (
      await Promise.all(TEST_SYMBOLS.map((s) => api.get<InstrumentHit[]>(`/instruments?q=${s}`).catch(() => [] as InstrumentHit[])))
    )
      .map((list, i) => list.find((h) => h.symbol === TEST_SYMBOLS[i]))
      .filter((h): h is InstrumentHit => !!h);
    await timed(setQuotes, async () => {
      if (!hits.length) throw new Error("test ETFs not in the instrument table — import reference data on Universe & data first");
      return api.post<Quote[]>(`/accounts/${accountId}/quotes`, { instrument_ids: hits.map((h) => h.instrument_id) });
    });
    await timed(setCandles, async () => {
      const first = hits.find((h) => h.broker_token);
      if (!first) throw new Error("no mapped instrument — run the instrument sync on Universe & data first");
      const bars = await api.get<Candle[]>(`/accounts/${accountId}/candles?instrument_id=${first.instrument_id}&days=45`);
      return { symbol: first.symbol, bars };
    });
    setRunning(false);
  }

  useEffect(() => {
    if (trigger > 0) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  const badge = (s: Step<unknown>) =>
    s.state === "idle" ? (
      <Badge>not run</Badge>
    ) : s.state === "running" ? (
      <Badge tone="info">running</Badge>
    ) : s.state === "ok" ? (
      <Badge tone="success">ok · {s.ms} ms</Badge>
    ) : (
      <Badge tone="danger">failed · {s.ms} ms</Badge>
    );

  return (
    <Card
      title="Connection test"
      actions={
        <Button variant="primary" onClick={run} busy={running} disabled={!enabled}>
          Run test calls
        </Button>
      }
    >
      {!enabled && <p className="mb-3 text-[13px] text-muted">Needs a valid token for today.</p>}
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold">Funds</span>
            {badge(funds)}
          </div>
          {funds.state === "ok" && funds.data && (
            <div className="grid grid-cols-2 gap-2 text-[13px]">
              <div className="text-muted">Available</div>
              <div className="num">{inr(funds.data.available_cash)}</div>
              <div className="text-muted">Used margin</div>
              <div className="num">{inr(funds.data.used_margin)}</div>
            </div>
          )}
          {funds.error && <p className="text-[12px] text-loss">{funds.error}</p>}
        </div>

        <div className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold">Holdings</span>
            {badge(holdings)}
          </div>
          {holdings.state === "ok" && holdings.data && (
            <p className="text-[13px]">
              {holdings.data.length} position{holdings.data.length === 1 ? "" : "s"} ·{" "}
              {holdings.data.slice(0, 4).map((h) => h.symbol ?? h.instrument_id).join(", ")}
              {holdings.data.length > 4 ? "…" : ""}{" "}
              <Link to="/data" className="text-accent hover:underline">
                see all
              </Link>
            </p>
          )}
          {holdings.error && <p className="text-[12px] text-loss">{holdings.error}</p>}
        </div>

        <div className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold">Live quotes</span>
            {badge(quotes)}
          </div>
          {quotes.state === "ok" && quotes.data && (
            <table className="data">
              <tbody>
                {quotes.data.map((q) => (
                  <tr key={q.symbol ?? q.instrument_id}>
                    <td>{q.symbol}</td>
                    <td className="num">{q.error ? <span className="text-warn">{q.error}</span> : price(q.last_price)}</td>
                    <td className="num text-muted">{q.volume != null ? `vol ${qty(q.volume)}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {quotes.error && <p className="text-[12px] text-loss">{quotes.error}</p>}
        </div>

        <div className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold">Historical (daily)</span>
            {badge(candles)}
          </div>
          {candles.state === "ok" && candles.data && (
            <p className="text-[13px]">
              {candles.data.symbol}: {candles.data.bars.length} bars
              {candles.data.bars.length > 0 &&
                `, ${candles.data.bars[0]!.trade_date} → ${candles.data.bars[candles.data.bars.length - 1]!.trade_date}, last close ${price(
                  candles.data.bars[candles.data.bars.length - 1]!.close,
                )}`}
            </p>
          )}
          {candles.error && <p className="text-[12px] text-loss">{candles.error}</p>}
        </div>
      </div>
    </Card>
  );
}

// ----------------------------------------------------------------------------
// Where the broker sends the operator back. Upstox appends ?code=…&state=<account>.

export function UpstoxCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const app = useApp();
  const code = params.get("code") ?? "";
  const state = Number(params.get("state"));
  const target = app.accounts.find((a) => a.trading_account_id === state);

  useEffect(() => {
    if (target) app.setAccountId(target.trading_account_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target?.trading_account_id]);

  return (
    <>
      <PageHeader title="Upstox sign-in complete" subtitle="The authorisation code is single-use and expires within minutes." />
      <Card>
        {code ? (
          <div className="space-y-4">
            <Field label="Authorisation code">
              <div className="flex items-center gap-2">
                <code className="rounded bg-bg px-2 py-1 font-mono text-[13px]">{code}</code>
                <button className="text-[12px] text-accent hover:underline" onClick={() => navigator.clipboard?.writeText(code)}>
                  copy
                </button>
              </div>
            </Field>
            {target ? (
              <Button variant="primary" onClick={() => navigate(`/tokens?code=${encodeURIComponent(code)}`)}>
                Use it for {target.investor_name} · {target.broker_client_code}
              </Button>
            ) : (
              <Notice tone="warn">The returning state does not match an account here; paste the code on the Tokens screen for the right account.</Notice>
            )}
          </div>
        ) : (
          <Notice tone="warn">No code in the address — {params.get("error_description") ?? params.get("error") ?? "the sign-in did not complete"}.</Notice>
        )}
      </Card>
    </>
  );
}
