import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api, setUnauthorisedHandler } from "./api";
import { AppProvider } from "./context";
import { Layout } from "./Layout";
import { Loading } from "./ui";
import { Overview } from "./pages/Overview";
import { Tokens, UpstoxCallback } from "./pages/Tokens";
import { DataLab } from "./pages/DataLab";
import { UniversePage } from "./pages/Universe";
import { ConfigPage } from "./pages/Config";
import { RunsPage, RunDetailPage } from "./pages/Runs";
import { PositionsPage } from "./pages/Positions";
import { AccountsPage } from "./pages/Accounts";
import { AuditPage } from "./pages/Audit";

interface Me {
  user: string;
  env: string;
  upstox_redirect_uri: string;
}

// Signing in happens on the public site (web/public/site), not in this app: the
// server serves this bundle only to a signed-in browser, so a missing or expired
// session leaves for "/", which then serves the placeholder home page. Vite has no
// such server, so in development the sign-in page is reached directly.
function leave() {
  window.location.replace(import.meta.env.DEV ? "/site/login.html" : "/");
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  const load = useCallback(async () => {
    try {
      setMe(await api.get<Me>("/auth/me"));
    } catch {
      setMe(null);
    } finally {
      setChecked(true);
    }
  }, []);

  useEffect(() => {
    setUnauthorisedHandler(leave);
    void load();
  }, [load]);

  useEffect(() => {
    if (checked && me === null) leave();
  }, [checked, me]);

  if (!checked || me === null) return <Loading />;

  return (
    <BrowserRouter>
      <AppProvider user={me.user} env={me.env} redirectUri={me.upstox_redirect_uri}>
        <Routes>
          <Route element={<Layout onSignOut={leave} />}>
            <Route index element={<Overview />} />
            <Route path="tokens" element={<Tokens />} />
            <Route path="brokers/upstox/callback" element={<UpstoxCallback />} />
            <Route path="data" element={<DataLab />} />
            <Route path="universe" element={<UniversePage />} />
            <Route path="config" element={<ConfigPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="positions" element={<PositionsPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="setup" element={<Navigate to="/accounts" replace />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
