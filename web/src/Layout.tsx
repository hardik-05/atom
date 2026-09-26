import { NavLink, Outlet } from "react-router-dom";
import { api } from "./api";
import { useApp, useTheme, type Theme } from "./context";
import { Badge, statusTone } from "./ui";

const NAV: { to: string; label: string; icon: string }[] = [
  { to: "/", label: "Overview", icon: "◎" },
  { to: "/tokens", label: "Broker tokens", icon: "⚿" },
  { to: "/data", label: "Data lab", icon: "◫" },
  { to: "/universe", label: "Universe & data", icon: "▦" },
  { to: "/config", label: "Configuration", icon: "⚙" },
  { to: "/runs", label: "Execute", icon: "▶" },
  { to: "/positions", label: "Positions", icon: "▤" },
  { to: "/setup", label: "Investors & accounts", icon: "＋" },
  { to: "/audit", label: "Audit log", icon: "☰" },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-4 py-4">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <circle cx="16" cy="16" r="4" fill="#06b6d4" />
        <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.6" />
        <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.6" transform="rotate(60 16 16)" />
        <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.6" transform="rotate(120 16 16)" />
      </svg>
      <div>
        <div className="text-[15px] font-bold tracking-[0.18em] text-white">ATOM</div>
        <div className="text-[10px] uppercase tracking-wider text-slate-400">MetaAlgo Capital</div>
      </div>
    </div>
  );
}

export function Layout({ onSignOut }: { onSignOut: () => void }) {
  const app = useApp();
  const [theme, setTheme] = useTheme();
  const session = app.account?.session;

  return (
    <div className="flex h-full">
      <nav className="hidden w-[228px] shrink-0 flex-col bg-navy md:flex" aria-label="primary">
        <Logo />
        <ul className="flex-1 space-y-0.5 px-2">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition ${
                    isActive ? "bg-[#0e3a47] text-cyan-300" : "text-slate-300 hover:bg-white/5 hover:text-white"
                  }`
                }
              >
                <span className="w-4 text-center opacity-80" aria-hidden>
                  {item.icon}
                </span>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="border-t border-white/10 px-4 py-3 text-[11px] text-slate-400">
          {app.env === "prod" ? "Production" : "Development"} · signed in as <span className="text-slate-200">{app.user}</span>
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
          <label className="flex items-center gap-2 text-[12px] text-muted">
            Account
            <select
              className="rounded-md border border-line bg-bg px-2 py-1 text-[13px] text-ink"
              value={app.accountId ?? ""}
              onChange={(e) => app.setAccountId(e.target.value ? Number(e.target.value) : null)}
            >
              {app.accounts.length === 0 && <option value="">— none yet —</option>}
              {app.accounts.map((a) => (
                <option key={a.trading_account_id} value={a.trading_account_id}>
                  {a.investor_name} · {a.broker_name} · {a.broker_client_code}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-[12px] text-muted">
            Universe
            <select
              className="rounded-md border border-line bg-bg px-2 py-1 text-[13px] text-ink"
              value={app.universeId ?? ""}
              onChange={(e) => app.setUniverseId(e.target.value ? Number(e.target.value) : null)}
            >
              {app.universes.length === 0 && <option value="">— none yet —</option>}
              {app.universes.map((u) => (
                <option key={u.universe_id} value={u.universe_id}>
                  {u.name} ({u.member_count})
                </option>
              ))}
            </select>
          </label>
          {app.account && (
            <div className="flex items-center gap-2">
              <Badge tone={app.account.execution_mode === "LIVE" ? "danger" : "info"}>{app.account.execution_mode}</Badge>
              <Badge tone={statusTone(session?.status)}>token {session?.status?.toLowerCase() ?? "none today"}</Badge>
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <select
              aria-label="theme"
              className="rounded-md border border-line bg-bg px-2 py-1 text-[12px] text-ink"
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
            >
              <option value="system">System theme</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
            <button
              className="rounded-md px-2 py-1 text-[12px] text-muted hover:bg-accent-soft hover:text-ink"
              onClick={async () => {
                await api.post("/auth/logout").catch(() => undefined);
                onSignOut();
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        {app.account?.execution_mode === "DRY" && (
          <div className="border-b border-accent/40 bg-accent-soft px-4 py-1.5 text-[12px] font-medium text-ink" role="note">
            DRY RUN — this account is paper-trading. Orders are computed, recorded and simulated; nothing is sent to{" "}
            {app.account.broker_name}.
          </div>
        )}
        <nav className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-2 py-1 md:hidden" aria-label="primary mobile">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `whitespace-nowrap rounded px-2.5 py-1 text-[12px] ${isActive ? "bg-accent-soft text-accent" : "text-muted"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="flex-1 overflow-auto px-4 py-5 md:px-7">
          <div className="mx-auto max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
