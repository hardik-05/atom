import { api, type ExclusionRow, type PositionRow } from "../api";
import { useApp } from "../context";
import { day, inr, price, qty, when } from "../format";
import { Badge, Card, Empty, ErrorNote, Loading, Notice, PageHeader, TableBox, useAsync } from "../ui";

export function PositionsPage() {
  const app = useApp();
  const id = app.accountId;
  const positions = useAsync(() => (id ? api.get<PositionRow[]>(`/accounts/${id}/positions`) : Promise.resolve([])), [id]);
  const exclusions = useAsync(() => (id ? api.get<ExclusionRow[]>(`/accounts/${id}/exclusions`) : Promise.resolve([])), [id]);
  if (!id) return <Notice>Select an account first.</Notice>;

  return (
    <>
      <PageHeader title="Positions" subtitle="What ATOM holds from its own lots. Strategy and actual cost are shown side by side and never blended (D-190)." />
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
