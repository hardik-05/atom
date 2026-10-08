import { useState } from "react";
import { api } from "./api";
import { ConfirmDialog, ErrorNote, Field, Notice, inputCls, useAction } from "./ui";

// Changing the password signs every other browser out (the server rotates the
// session key); this one is re-issued a session and stays signed in.
export function ChangePassword({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const { busy, error, act, clear } = useAction();

  function close() {
    setCurrent("");
    setNext("");
    setAgain("");
    setProblem(null);
    setDone(false);
    clear();
    onClose();
  }

  async function submit() {
    if (done) return close();
    if (next.length < 12) return setProblem("The new password must be at least 12 characters.");
    if (next !== again) return setProblem("The two new passwords do not match.");
    setProblem(null);
    const ok = await act(async () => {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      return true;
    });
    if (ok) setDone(true);
  }

  return (
    <ConfirmDialog
      open={open}
      title="Change password"
      confirmLabel={done ? "Close" : "Change password"}
      busy={busy}
      onConfirm={() => void submit()}
      onCancel={close}
      consequence={
        done ? (
          <Notice tone="success">Password changed. Other signed-in browsers have been signed out.</Notice>
        ) : (
          <div className="flex flex-col gap-3">
            <Field label="Current password">
              <input className={inputCls} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
            </Field>
            <Field label="New password" hint="At least 12 characters.">
              <input className={inputCls} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            </Field>
            <Field label="New password again">
              <input className={inputCls} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
            </Field>
            {problem && <Notice tone="warn">{problem}</Notice>}
            <ErrorNote error={error} />
          </div>
        )
      }
    />
  );
}
