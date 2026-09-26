import { useEffect, useMemo, useState } from "react";
import { api, type ConfigKey, type ConfigView } from "../api";
import { useApp } from "../context";
import { when } from "../format";
import { Badge, Button, Card, ErrorNote, Loading, Notice, PageHeader, inputCls, useAction, useAsync } from "../ui";

// No defaults anywhere (D-037). A suggested value is shown as a placeholder and
// applied only when the operator presses "use suggestion" — never silently.
// Clearing a field and saving stores an explicit NULL, which for a per-category
// key means "do not buy this category" (D-039, D-068).

type Cell = { key: string; category: string | null };
const cellId = (c: Cell) => `${c.key}|${c.category ?? ""}`;

export function ConfigPage() {
  const app = useApp();
  const { accountId, universeId } = app;
  const view = useAsync(
    () => (accountId && universeId ? api.get<ConfigView>(`/config?account_id=${accountId}&universe_id=${universeId}`) : Promise.resolve(null)),
    [accountId, universeId],
  );
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const action = useAction();

  const stored = useMemo(() => {
    const map: Record<string, { value: string | null; at: string; by: string }> = {};
    for (const v of view.data?.values ?? []) map[cellId({ key: v.key_name, category: v.category_code })] = { value: v.value_text, at: v.updated_at, by: v.updated_by };
    for (const g of view.data?.globals ?? []) map[cellId({ key: g.key_name, category: null })] = { value: g.value_text, at: g.updated_at, by: g.updated_by };
    return map;
  }, [view.data]);

  useEffect(() => setDraft({}), [view.data]);

  if (!accountId || !universeId) return <Notice>Select an account and a universe in the header first.</Notice>;
  if (view.loading && !view.data) return <Loading />;
  if (!view.data) return <ErrorNote error={view.error} />;
  const data = view.data;
  const byScope = (scope: ConfigKey["scope"]) => data.keys.filter((k) => k.scope === scope);
  const dirty = Object.keys(draft).length;

  function editor(k: ConfigKey, category: string | null) {
    const id = cellId({ key: k.key_name, category });
    const current = stored[id];
    const has = id in draft;
    const value = has ? draft[id] : current?.value;
    const isBool = k.value_type === "BOOLEAN";
    const unset = current === undefined && !has;
    return (
      <div className="flex min-w-[150px] flex-col gap-1">
        {isBool ? (
          <select
            className={`${inputCls} ${unset && k.is_required ? "border-warn" : ""}`}
            value={value === null ? "__null" : value ?? ""}
            onChange={(e) => setDraft((d) => ({ ...d, [id]: e.target.value === "__null" ? null : e.target.value }))}
          >
            <option value="">{unset ? "— not set —" : ""}</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            className={`${inputCls} ${unset && k.is_required ? "border-warn" : ""} font-mono`}
            value={value ?? ""}
            placeholder={unset ? (k.suggested_value ? `suggested ${k.suggested_value}` : "not set") : value === null ? "NULL (switched off)" : ""}
            onChange={(e) => setDraft((d) => ({ ...d, [id]: e.target.value === "" ? null : e.target.value }))}
          />
        )}
        <div className="flex items-center gap-2 text-[11px]">
          {unset && k.suggested_value && (
            <button className="text-accent hover:underline" onClick={() => setDraft((d) => ({ ...d, [id]: k.suggested_value }))}>
              use suggestion
            </button>
          )}
          {has && <span className="text-warn">unsaved</span>}
          {!has && current && current.value === null && <Badge tone="block">NULL</Badge>}
        </div>
      </div>
    );
  }

  async function save() {
    const changes = Object.entries(draft).map(([id, value]) => {
      const [key, category] = id.split("|");
      return { key_name: key, category_code: category || null, value_text: value };
    });
    const r = await action.act(() => api.put<ConfigView>("/config", { account_id: accountId, universe_id: universeId, changes }));
    if (r) view.setData(r);
  }

  function suggestAll() {
    const next: Record<string, string | null> = { ...draft };
    for (const k of data.keys) {
      const cats = k.scope === "ACCOUNT_CATEGORY" ? data.categories : [null];
      for (const c of cats) {
        const id = cellId({ key: k.key_name, category: c });
        if (stored[id] === undefined && !(id in next) && k.suggested_value !== null && k.is_required) next[id] = k.suggested_value;
      }
    }
    setDraft(next);
  }

  return (
    <>
      <PageHeader
        title="Configuration"
        subtitle={`${app.account?.investor_name ?? ""} · ${app.universe?.name ?? ""} — frozen into each run at its start (D-061)`}
        actions={
          <>
            <Button onClick={suggestAll}>Fill empty with suggestions</Button>
            <Button variant="primary" onClick={save} busy={action.busy} disabled={!dirty}>
              Save {dirty ? `(${dirty})` : ""}
            </Button>
          </>
        }
      />
      <div className="mb-4">
        {data.status.ok ? (
          <Notice tone="success">Complete and valid — a run can resolve this configuration.</Notice>
        ) : (
          <Notice tone="warn">
            <div className="font-medium">A run would be refused at pre-flight:</div>
            <div className="mt-1 whitespace-pre-wrap text-[12px]">{data.status.error}</div>
          </Notice>
        )}
      </div>
      <ErrorNote error={action.error} onDismiss={action.clear} />

      <Card title="Per category" className="mt-4" pad={false}>
        <div className="overflow-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Key</th>
                {data.categories.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {byScope("ACCOUNT_CATEGORY").map((k) => (
                <tr key={k.key_name}>
                  <td className="max-w-[320px]">
                    <div className="font-mono text-[12px] font-medium">{k.key_name}</div>
                    <div className="text-[11px] text-faint">{k.description}</div>
                  </td>
                  {data.categories.map((c) => (
                    <td key={c}>{editor(k, c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {(["ACCOUNT", "GLOBAL"] as const).map((scope) => (
          <Card key={scope} title={scope === "ACCOUNT" ? "Account" : "Global — every account, every universe"} pad={false}>
            <table className="data">
              <tbody>
                {byScope(scope).map((k) => {
                  const cur = stored[cellId({ key: k.key_name, category: null })];
                  return (
                    <tr key={k.key_name}>
                      <td className="max-w-[340px]">
                        <div className="flex items-center gap-2 font-mono text-[12px] font-medium">
                          {k.key_name} {!k.is_required && <Badge>optional</Badge>}
                          {k.key_name === "kill_switch" && <Badge tone="danger">stops all orders</Badge>}
                        </div>
                        <div className="text-[11px] text-faint">{k.description}</div>
                        {cur && <div className="text-[11px] text-faint">set {when(cur.at)} by {cur.by}</div>}
                      </td>
                      <td>{editor(k, null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
    </>
  );
}
