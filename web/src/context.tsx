import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Account, type Universe } from "./api";

// Account and universe are HEADER context (SCREEN-SPECS.md 14): chosen once and
// shared by every screen, never a per-screen selector that can quietly disagree
// with the one next to it.

interface AppState {
  user: string;
  redirectUri: string;
  env: string;
  accounts: Account[];
  universes: Universe[];
  accountId: number | null;
  universeId: number | null;
  account: Account | null;
  universe: Universe | null;
  setAccountId: (id: number | null) => void;
  setUniverseId: (id: number | null) => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

function stored(key: string): number | null {
  try {
    const v = localStorage.getItem(key);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

function store(key: string, value: number | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch {
    /* private mode: the selection simply is not remembered */
  }
}

export function AppProvider({ user, redirectUri, env, children }: {
  user: string;
  redirectUri: string;
  env: string;
  children: ReactNode;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [universes, setUniverses] = useState<Universe[]>([]);
  const [accountId, setAccountIdState] = useState<number | null>(stored("atom.account"));
  const [universeId, setUniverseIdState] = useState<number | null>(stored("atom.universe"));

  const refresh = useCallback(async () => {
    const [a, u] = await Promise.all([api.get<Account[]>("/accounts"), api.get<Universe[]>("/universes")]);
    setAccounts(a);
    setUniverses(u);
    setAccountIdState((cur) => (cur && a.some((x) => x.trading_account_id === cur) ? cur : a[0]?.trading_account_id ?? null));
    setUniverseIdState((cur) => (cur && u.some((x) => x.universe_id === cur) ? cur : u[0]?.universe_id ?? null));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => store("atom.account", accountId), [accountId]);
  useEffect(() => store("atom.universe", universeId), [universeId]);

  const value = useMemo<AppState>(
    () => ({
      user,
      redirectUri,
      env,
      accounts,
      universes,
      accountId,
      universeId,
      account: accounts.find((a) => a.trading_account_id === accountId) ?? null,
      universe: universes.find((u) => u.universe_id === universeId) ?? null,
      setAccountId: setAccountIdState,
      setUniverseId: setUniverseIdState,
      refresh,
    }),
    [user, redirectUri, env, accounts, universes, accountId, universeId, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

// ------------------------------------------------------------------ theme

export type Theme = "system" | "light" | "dark";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("atom.theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === "system") localStorage.removeItem("atom.theme");
      else localStorage.setItem("atom.theme", theme);
    } catch {
      /* not remembered */
    }
  }, [theme]);
  return [theme, setTheme];
}
