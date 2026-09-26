import { useState } from "react";
import { api } from "../api";
import { Button, ErrorNote, Field, inputCls } from "../ui";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { username, password, totp });
      onSignedIn();
    } catch (err) {
      setError(err as Error);
      setTotp("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-navy px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex flex-col items-center gap-2">
          <svg viewBox="0 0 32 32" className="h-12 w-12" aria-hidden>
            <circle cx="16" cy="16" r="4" fill="#06b6d4" />
            <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.4" />
            <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.4" transform="rotate(60 16 16)" />
            <ellipse cx="16" cy="16" rx="12" ry="4.8" fill="none" stroke="#06b6d4" strokeWidth="1.4" transform="rotate(120 16 16)" />
          </svg>
          <div className="text-[22px] font-bold tracking-[0.3em] text-white">ATOM</div>
          <div className="text-[12px] text-slate-400">MetaAlgo Capital · operator console</div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-[10px] border border-white/10 bg-[#111827] p-6 text-[#e8eef7]">
          <Field label="Username">
            <input className={inputCls} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </Field>
          <Field label="Password">
            <input className={inputCls} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Field label="Authenticator code">
            <input
              className={`${inputCls} font-mono tracking-[0.4em]`}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              value={totp}
              onChange={(e) => setTotp(e.target.value.replace(/\D/g, ""))}
              required
            />
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
        </form>
        <p className="mt-4 text-center text-[11px] text-slate-500">Five failed attempts lock this address out for fifteen minutes.</p>
      </div>
    </div>
  );
}
