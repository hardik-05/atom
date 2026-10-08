import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Account } from "../api";
import { useApp } from "../context";
import { Badge, Button, Drawer, Empty, ErrorNote, Field, Notice, PageHeader, inputCls, statusTone, useAction, useAsync } from "../ui";

interface Investor {
  investor_id: number;
  display_name: string;
  external_key: string;
  relationship: string;
}

interface Broker {
  broker_code: string;
  display_name: string;
}

const today = () => new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);

const blankInvestor = () => ({ external_key: "", display_name: "", relationship: "SELF", onboarded_on: today() });

export function AccountsPage() {
  const app = useApp();
  const navigate = useNavigate();
  const investors = useAsync(() => api.get<Investor[]>("/investors"), []);
  const brokers = useAsync(() => api.get<Broker[]>("/brokers"), []);
  const action = useAction();
  const [panel, setPanel] = useState<"investor" | "account" | null>(null);
  const [inv, setInv] = useState(blankInvestor());
  const [acc, setAcc] = useState({
    investor_id: 0,
    broker_code: "UPSTOX",
    broker_client_code: "",
    execution_mode: "DRY",
    egress_ip: "13.127.7.83",
    proxy_url: "http://127.0.0.1:3128",
    depository_authorisation: "DDPI",
  });
  const [next, setNext] = useState<string | null>(null);

  const investorId = acc.investor_id || investors.data?.[0]?.investor_id || 0;

  // Entering an account makes it the working account for every screen, then lands
  // on its overview. The drop-down in the header is the other way in.
  function enter(a: Account) {
    app.setAccountId(a.trading_account_id);
    navigate("/");
  }

  function open(which: "investor" | "account") {
    action.clear();
    setNext(null);
    setPanel(which);
  }

  return (
    <>
      <PageHeader
        title="Accounts"
        subtitle="Open an account to work inside it. An investor is a tax identity (one PAN, never stored); a trading account is one broker login for them."
        actions={
          <div className="flex gap-2">
            <Button onClick={() => open("investor")}>Add investor</Button>
            <Button variant="primary" onClick={() => open("account")}>
              Add account
            </Button>
          </div>
        }
      />

      {app.accounts.length === 0 ? (
        <Empty title="No accounts yet">Add an investor, then add a trading account for them.</Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {app.accounts.map((a) => {
            const selected = a.trading_account_id === app.accountId;
            const live = a.execution_mode === "LIVE";
            return (
              <button
                key={a.trading_account_id}
                onClick={() => enter(a)}
                className={`rounded-[10px] border bg-surface p-4 text-left transition hover:border-accent ${
                  selected ? "border-accent ring-1 ring-accent" : "border-line"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[16px] font-semibold">{a.investor_name}</div>
                  <Badge tone={live ? "danger" : "info"}>{live ? "LIVE" : "PAPER"}</Badge>
                </div>
                <div className="mt-1 text-[13px] text-muted">{a.broker_name}</div>
                <div className="mt-3 font-mono text-[12px]">{a.broker_client_code}</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone={statusTone(a.session?.status)}>token {a.session?.status?.toLowerCase() ?? "none today"}</Badge>
                  {selected && <Badge tone="success">current</Badge>}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <Drawer open={panel === "investor"} title="Add investor" onClose={() => setPanel(null)} width="min(520px, 96vw)">
        <ErrorNote error={action.error} onDismiss={action.clear} />
        <form
          className="mt-2 grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await action.act(() => api.post("/investors", inv))) {
              await investors.reload();
              setInv(blankInvestor());
              setPanel(null);
            }
          }}
        >
          <Field label="Display name">
            <input className={inputCls} value={inv.display_name} onChange={(e) => setInv({ ...inv, display_name: e.target.value })} required />
          </Field>
          <Field label="Internal key" hint="A surrogate for the PAN — never the PAN itself (D-128).">
            <input className={`${inputCls} font-mono`} placeholder="INV-NAME" value={inv.external_key} onChange={(e) => setInv({ ...inv, external_key: e.target.value.toUpperCase() })} required />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Relationship" hint="Within SEBI's family definition (D-092).">
              <select className={inputCls} value={inv.relationship} onChange={(e) => setInv({ ...inv, relationship: e.target.value })}>
                {["SELF", "SPOUSE", "DEPENDENT_CHILD", "DEPENDENT_PARENT"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Field>
            <Field label="Onboarded on" hint="Cost of capital accrues from here (D-138).">
              <input type="date" className={inputCls} value={inv.onboarded_on} onChange={(e) => setInv({ ...inv, onboarded_on: e.target.value })} />
            </Field>
          </div>
          <Button type="submit" variant="primary" busy={action.busy}>
            Create investor
          </Button>
        </form>
      </Drawer>

      <Drawer open={panel === "account"} title="Add account" onClose={() => setPanel(null)} width="min(560px, 96vw)">
        <ErrorNote error={action.error} onDismiss={action.clear} />
        {(investors.data?.length ?? 0) === 0 && <Notice tone="warn">Add an investor first; an account belongs to one.</Notice>}
        <form
          className="mt-2 grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            const body = {
              ...acc,
              investor_id: investorId,
              egress_ip: acc.execution_mode === "LIVE" ? acc.egress_ip : acc.egress_ip || null,
              proxy_url: acc.proxy_url || null,
            };
            const r = await action.act(() => api.post<{ trading_account_id: number; next_step: string }>("/accounts", body));
            if (r) {
              setNext(`python -m atom.cli broker-secret --account-id ${r.trading_account_id} --broker ${acc.broker_code}`);
              await app.refresh();
            }
          }}
        >
          <Field label="Investor">
            <select className={inputCls} value={investorId} onChange={(e) => setAcc({ ...acc, investor_id: Number(e.target.value) })}>
              {(investors.data ?? []).map((i) => (
                <option key={i.investor_id} value={i.investor_id}>
                  {i.display_name}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Broker">
              <select className={inputCls} value={acc.broker_code} onChange={(e) => setAcc({ ...acc, broker_code: e.target.value })}>
                {(brokers.data ?? []).map((b) => (
                  <option key={b.broker_code} value={b.broker_code}>
                    {b.display_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Broker client id" hint="Checked against every token: a code for another client is discarded.">
              <input className={`${inputCls} font-mono`} value={acc.broker_client_code} onChange={(e) => setAcc({ ...acc, broker_client_code: e.target.value.toUpperCase() })} required />
            </Field>
          </div>
          <Field label="Mode" hint="DRY (paper) computes and simulates; LIVE sends. Switching never migrates the book.">
            <select className={inputCls} value={acc.execution_mode} onChange={(e) => setAcc({ ...acc, execution_mode: e.target.value })}>
              <option value="DRY">DRY — paper</option>
              <option value="LIVE">LIVE — real orders</option>
            </select>
          </Field>
          <Field label="Depository authorisation" hint="How the demat account authorises sells. DDPI or POA: sells need no per-order step.">
            <select className={inputCls} value={acc.depository_authorisation} onChange={(e) => setAcc({ ...acc, depository_authorisation: e.target.value })}>
              <option value="DDPI">DDPI</option>
              <option value="POA">POA</option>
              <option value="EDIS">EDIS — authorise each sell</option>
              <option value="UNKNOWN">Unknown — use the broker's flags</option>
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Egress IP" hint="The Elastic IP registered with the broker.">
              <input className={`${inputCls} font-mono`} value={acc.egress_ip} onChange={(e) => setAcc({ ...acc, egress_ip: e.target.value })} />
            </Field>
            <Field label="Proxy URL" hint="Squid port bound to that IP.">
              <input className={`${inputCls} font-mono`} value={acc.proxy_url} onChange={(e) => setAcc({ ...acc, proxy_url: e.target.value })} />
            </Field>
          </div>
          <Button type="submit" variant="primary" busy={action.busy} disabled={!investorId}>
            Create account
          </Button>
        </form>
        {next && (
          <div className="mt-4">
            <Notice tone="warn">
              <div className="font-medium">Created. Next: store this account's broker app credentials, from your own machine:</div>
              <pre className="mt-1 overflow-x-auto rounded bg-bg p-2 font-mono text-[12px]">{next}</pre>
            </Notice>
          </div>
        )}
      </Drawer>
    </>
  );
}
