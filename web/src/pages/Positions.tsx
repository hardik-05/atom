import { useState } from "react";
import { api, type ExclusionRow, type HoldingControl, type PositionRow } from "../api";
import { useApp } from "../context";
import { day, inr, price, qty, when } from "../format";
import { Badge, Card, ConfirmDialog, Empty, ErrorNote, Loading, Notice, PageHeader, TableBox, useAction, useAsync } from "../ui";

const SOURCE: Record<HoldingControl["source"], { label: string; tone: "info" | "neutral" | "warn" }> = {
  ATOM: { label: "bought by ATOM", tone: "info" },
  ATOM_AND_MANUAL: { label: "ATOM + manual", tone: "info" },
  MANUAL_ADOPTED: { label: "manual · handed to ATOM", tone: "warn" },
  MANUAL: { label: "bought manually", tone: "neutral" },
};

function Switch({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${on ? "bg-accent" : "bg-line"}`}
    >
      <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </button>
  );
}

function HoldingsCard({ accountId, universeId, onChange }: { accountId: number; universeId: number | null; onChange: () => void }) {
  const controls = useAsync(() => api.get<HoldingControl[]>(`/accounts/${accountId}/holding-controls`), [accountId]);
  const action = useAction();
  const [pending, setPending] = useState<{ row: HoldingControl; enable: boolean } | null>(null);

  async function apply() {
    if (!pending || !universeId) return;
    const r = await action.act(() =>
      api.put(`/accounts/${accountId}/holdings/${pending.row.instrument_id}/sell`, { enabled: pending.enable, universe_id: universeId }),
    );
    setPending(null);
    if (r) {
      await controls.reload();
      onChange();
    }
  }

  const p = pending?.row;
  const adopting = !!p && pending!.enable && p.excluded_quantity > 0;
  return (
    <Card title="Holdings — what ATOM may sell" className="mb-4" pad={false}>
      <div className="px-4 pt-3 text-[12px] text-muted">
        One switch per holding. What ATOM bought is <b>on</b>; what was already in the account when it was connected is <b>off</b> and never touched. Switch a
        manual holding on and ATOM sells it like its own — at the category's profit target, from the broker's average price, at the next LIVE Execute.
      </div>
      <div className="px-4 pt-2">
        <ErrorNote error={controls.error ?? action.error} onDismiss={action.clear} />
      </div>
      {controls.loading && !controls.data && <Loading />}
      {controls.data && controls.data.length === 0 && <Empty title="No holdings recorded">Nothing bought by ATOM and nothing excluded at onboarding.</Empty>}
      {controls.data && controls.data.length > 0 && (
        <TableBox exportName="holdings.csv" rows={controls.data as unknown as Record<string, unknown>[]}>
          <table className="data">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Bought</th>
                <th className="num">ATOM qty</th>
                <th className="num">Manual qty</th>
                <th className="num">Cost</th>
                <th>Since</th>
                <th>Sell</th>
              </tr>
            </thead>
            <tbody>
              {controls.data.map((h) => {
                const lotQty = h.atom_quantity + h.external_quantity;
                return (
                  <tr key={h.instrument_id}>
                    <td>
                      <div className="font-medium">{h.symbol}</div>
                      <div className="max-w-[240px] truncate text-[11px] text-faint">{h.name}</div>
                    </td>
                    <td>
                      <Badge tone={SOURCE[h.source].tone}>{SOURCE[h.source].label}</Badge>
                    </td>
                    <td className="num">{qty(h.atom_quantity)}</td>
                    <td className="num">
                      {h.external_quantity > 0 && <div>{qty(h.external_quantity)} <span className="text-[11px] text-faint">handed over</span></div>}
                      {h.excluded_quantity > 0 && <div>{qty(h.excluded_quantity)} <span className="text-[11px] text-faint">kept out</span></div>}
                      {h.external_quantity === 0 && h.excluded_quantity === 0 && "—"}
                    </td>
                    <td className="num">{price(h.average_cost)}</td>
                    <td>{day(h.acquired_from)}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <Switch on={h.sell_enabled} disabled={!universeId} onClick={() => setPending({ row: h, enable: !h.sell_enabled })} />
                        <span className="text-[11px] text-faint">{h.sell_enabled ? (h.frozen_quantity ? "partly held" : "on") : lotQty ? "held" : "off"}</span>
                        {h.sell_enabled && h.excluded_quantity > 0 && (
                          <button className="text-[11px] text-accent hover:underline" onClick={() => setPending({ row: h, enable: true })}>
                            also sell the {qty(h.excluded_quantity)} manual
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableBox>
      )}
      <ConfirmDialog
        open={!!pending}
        title={pending?.enable ? `Let ATOM sell ${p?.symbol}` : `Stop ATOM selling ${p?.symbol}`}
        consequence={
          !pending ? null : pending.enable ? (
            adopting ? (
              <>
                The {qty(p!.excluded_quantity)} units bought manually are handed to ATOM at the broker's average price (read now from the broker). From the next{" "}
                <b>LIVE</b> Execute they are sold like ATOM's own, at this category's profit target. DRY runs never sell them. The account's tax view will count
                these units as ATOM's from today. Recorded in the audit log.
              </>
            ) : (
              <>ATOM sells it again from the next Execute, and may buy more of it. Recorded in the audit log.</>
            )
          ) : (
            <>
              ATOM holds every unit of it and places no sell from the next Execute. It also buys no more of it while switched off. A sell already resting at the
              broker from today stays until the next Execute replaces it. Recorded in the audit log.
            </>
          )
        }
        confirmLabel={pending?.enable ? (adopting ? "Hand to ATOM" : "Switch on") : "Switch off"}
        tone={adopting ? "danger" : "primary"}
        busy={action.busy}
        onCancel={() => setPending(null)}
        onConfirm={apply}
      />
    </Card>
  );
}

export function PositionsPage() {
  const app = useApp();
  const id = app.accountId;
  const positions = useAsync(() => (id ? api.get<PositionRow[]>(`/accounts/${id}/positions`) : Promise.resolve([])), [id]);
  const exclusions = useAsync(() => (id ? api.get<ExclusionRow[]>(`/accounts/${id}/exclusions`) : Promise.resolve([])), [id]);
  if (!id) return <Notice>Select an account first.</Notice>;

  return (
    <>
      <PageHeader title="Positions" subtitle="What ATOM holds from its own lots. Strategy and actual cost are shown side by side and never blended (D-190)." />
      <HoldingsCard
        accountId={id}
        universeId={app.universeId}
        onChange={() => {
          void positions.reload();
          void exclusions.reload();
        }}
      />
      <Card title="ATOM positions" pad={false}>
        {positions.loading && !positions.data && <Loading />}
        <div className="px-4 pt-3">
          <ErrorNote error={positions.error} />
        </div>
        {positions.data && positions.data.length === 0 && (
          <Empty title="ATOM holds nothing yet on this account">
            Positions appear here from settled fills — one lot per fill. Holdings that pre-date onboarding are excluded and listed below.
          </Empty>
        )}
        {positions.data && positions.data.length > 0 && (
          <TableBox exportName="positions.csv" rows={positions.data as unknown as Record<string, unknown>[]}>
            <table className="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Universe</th>
                  <th className="num">Qty</th>
                  <th className="num">Lots</th>
                  <th className="num">Actual cost</th>
                  <th className="num">Strategy cost</th>
                  <th className="num">Invested</th>
                  <th>Since</th>
                  <th>Basis</th>
                </tr>
              </thead>
              <tbody>
                {positions.data.map((p) => (
                  <tr key={`${p.universe_name}-${p.instrument_id}`}>
                    <td>
                      <div className="font-medium">{p.symbol}</div>
                      <div className="max-w-[240px] truncate text-[11px] text-faint">{p.name}</div>
                    </td>
                    <td>{p.universe_name}</td>
                    <td className="num">{qty(p.quantity_open)}</td>
                    <td className="num">{p.lot_count}</td>
                    <td className="num">
                      {price(p.actual_unit_cost)} <span className="text-[11px] text-faint">actual</span>
                    </td>
                    <td className="num">
                      {price(p.strategy_unit_cost)} <span className="text-[11px] text-faint">{p.synthetic_quantity ? "synthetic" : "actual"}</span>
                    </td>
                    <td className="num">{inr(Number(p.actual_unit_cost) * p.quantity_open)}</td>
                    <td>{day(p.first_acquired_on)}</td>
                    <td>{p.synthetic_quantity ? <Badge tone="block">harvest proxy</Badge> : <Badge>actual</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        )}
      </Card>

      <Card title="Excluded & frozen" className="mt-4" pad={false}>
        {exclusions.data && exclusions.data.length === 0 && (
          <Empty title="Nothing excluded">Every held unit not in this list, and not ATOM's, is reported by reconciliation and never sold.</Empty>
        )}
        {exclusions.data && exclusions.data.length > 0 && (
          <TableBox exportName="exclusions.csv" rows={exclusions.data as unknown as Record<string, unknown>[]}>
            <table className="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th className="num">Qty</th>
                  <th>By</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {exclusions.data.map((e) => (
                  <tr key={e.account_exclusion_id}>
                    <td className="font-medium">{e.symbol}</td>
                    <td>
                      <Badge tone={e.exclusion_type === "FREEZE" ? "block" : "neutral"}>{e.exclusion_type}</Badge>
                    </td>
                    <td className="num">{qty(e.quantity)}</td>
                    <td className="text-[12px] text-muted">{e.created_by}</td>
                    <td>{when(e.created_at)}</td>
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
