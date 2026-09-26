import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api, setUnauthorisedHandler } from "./api";
import { AppProvider } from "./context";
import { Layout } from "./Layout";
import { Loading } from "./ui";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Tokens, UpstoxCallback } from "./pages/Tokens";
import { DataLab } from "./pages/DataLab";
import { UniversePage } from "./pages/Universe";
import { ConfigPage } from "./pages/Config";
import { RunsPage, RunDetailPage } from "./pages/Runs";
import { PositionsPage } from "./pages/Positions";
import { SetupPage } from "./pages/Setup";
import { AuditPage } from "./pages/Audit";

interface Me {
  user: string;
  env: string;
  upstox_redirect_uri: string;
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
    setUnauthorisedHandler(() => setMe(null));
    void load();
  }, [load]);

  if (!checked) return <Loading />;

  return (
    <BrowserRouter>
      {me === null ? (
        <Routes>
          <Route path="*" element={<Login onSignedIn={load} />} />
        </Routes>
      ) : (
        <AppProvider user={me.user} env={me.env} redirectUri={me.upstox_redirect_uri}>
          <Routes>
            <Route element={<Layout onSignOut={() => setMe(null)} />}>
              <Route index element={<Overview />} />
              <Route path="tokens" element={<Tokens />} />
              <Route path="brokers/upstox/callback" element={<UpstoxCallback />} />
              <Route path="data" element={<DataLab />} />
              <Route path="universe" element={<UniversePage />} />
              <Route path="config" element={<ConfigPage />} />
              <Route path="runs" element={<RunsPage />} />
              <Route path="runs/:runId" element={<RunDetailPage />} />
              <Route path="positions" element={<PositionsPage />} />
              <Route path="setup" element={<SetupPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </AppProvider>
      )}
    </BrowserRouter>
  );
}
