import { api, type AuditRow } from "../api";
import { when } from "../format";
import { Card, Empty, ErrorNote, Loading, PageHeader, TableBox, useAsync } from "../ui";

export function AuditPage() {
  const rows = useAsync(() => api.get<AuditRow[]>("/audit"), []);
  return (
    <>
      <PageHeader title="Audit log" subtitle="Every operator action. Append-only: the engine's database role cannot amend or delete these rows." />
      <Card pad={false}>
        {rows.loading && !rows.data && <Loading />}
        <ErrorNote error={rows.error} />
        {rows.data && rows.data.length === 0 && <Empty title="Nothing recorded yet" />}
        {rows.data && rows.data.length > 0 && (
          <TableBox exportName="audit.csv" rows={rows.data as unknown as Record<string, unknown>[]}>
            <table className="data">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.map((r) => (
                  <tr key={r.action_audit_id}>
                    <td className="whitespace-nowrap">{when(r.occurred_at)}</td>
                    <td>{r.actor}</td>
                    <td className="font-mono text-[12px]">{r.action}</td>
                    <td>
                      {r.entity}
                      {r.entity_id !== null ? ` #${r.entity_id}` : ""}
                    </td>
                    <td className="max-w-[520px] truncate font-mono text-[11px] text-muted">{r.payload ? JSON.stringify(r.payload) : ""}</td>
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
