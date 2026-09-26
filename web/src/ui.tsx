import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "./api";
import { downloadCsv } from "./format";

// ------------------------------------------------------------------ hooks

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fn());
      setLoadedAt(new Date());
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void run();
  }, [run]);
  return { data, error, loading, reload: run, loadedAt, setData };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const act = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e as Error);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, act, clear: () => setError(null) };
}

// ------------------------------------------------------------- primitives

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  children,
  variant = "secondary",
  busy,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-contrast hover:opacity-90 border-transparent",
    secondary: "bg-surface text-ink border-line hover:bg-accent-soft",
    ghost: "bg-transparent text-muted border-transparent hover:text-ink hover:bg-accent-soft",
    danger: "bg-loss text-white border-transparent hover:opacity-90",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  const size = small ? "h-3.5 w-3.5" : "h-5 w-5";
  return (
    <span
      role="status"
      aria-label="loading"
      className={`${size} inline-block animate-spin rounded-full border-2 border-current border-t-transparent opacity-70`}
    />
  );
}

export function Card({ title, actions, children, className = "", pad = true }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <section className={`rounded-[10px] border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 className="text-[14px] font-semibold">{title}</h2>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={pad ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function StatTile({ label, value, sub, tone }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "gain" | "loss" | "neutral" | "warn";
}) {
  const color = tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="rounded-[10px] border border-line bg-surface px-4 py-3">
      <div className="text-[12px] font-medium text-muted">{label}</div>
      <div className={`num mt-1 text-left text-[20px] font-semibold ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-faint">{sub}</div>}
    </div>
  );
}

export type BadgeTone = "success" | "warn" | "block" | "neutral" | "info" | "danger";

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  const map: Record<BadgeTone, string> = {
    success: "text-gain border-gain/40 bg-gain/10",
    warn: "text-warn border-warn/40 bg-warn/10",
    block: "text-block border-block/40 bg-block/10",
    neutral: "text-neutral border-line bg-transparent",
    info: "text-accent border-accent/40 bg-accent-soft",
    danger: "text-loss border-loss/40 bg-loss/10",
  };
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${map[tone]}`}>
      {children}
    </span>
  );
}

export function statusTone(status: string | null | undefined): BadgeTone {
  switch (status) {
    case "VALID":
    case "FILLED":
    case "COMPLETED":
    case "BOUGHT":
    case "SOLD":
    case "DONE":
    case "ACTIVE":
      return "success";
    case "PLACED":
    case "PARTIAL":
    case "EXECUTING":
    case "RUNNING":
    case "INTENT":
    case "PENDING":
      return "info";
    case "IN_FLIGHT":
    case "SKIPPED":
    case "REVIEW":
      return "warn";
    case "FROZEN":
    case "BLOCKED":
      return "block";
    case "REJECTED":
    case "FAILED":
    case "INVALID":
      return "danger";
    default:
      return "neutral";
  }
}

export function ErrorNote({ error, onDismiss }: { error: Error | null; onDismiss?: () => void }) {
  if (!error) return null;
  const gate = error instanceof ApiError && error.gate ? error.gate : null;
  return (
    <div role="alert" className="flex items-start justify-between gap-3 rounded-md border border-loss/40 bg-loss/10 px-3 py-2 text-[13px] text-loss">
      <div>
        {gate && <span className="mr-2 font-mono text-[11px] uppercase">[{gate}]</span>}
        {error.message}
      </div>
      {onDismiss && (
        <button onClick={onDismiss} className="text-loss/70 hover:text-loss" aria-label="dismiss">
          ×
        </button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "success"; children: ReactNode }) {
  const map = {
    info: "border-accent/40 bg-accent-soft text-ink",
    warn: "border-warn/40 bg-warn/10 text-ink",
    success: "border-gain/40 bg-gain/10 text-ink",
  };
  return <div className={`rounded-md border px-3 py-2 text-[13px] ${map[tone]}`}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 px-6 py-10 text-center">
      <div className="text-[14px] font-medium">{title}</div>
      {children && <div className="max-w-md text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function Loading() {
  return (
    <div className="flex items-center gap-2 px-4 py-8 text-muted">
      <Spinner /> Loading…
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-ink placeholder:text-faint focus:border-accent focus:outline-none";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[20px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function TableBox({ children, exportName, rows, maxHeight = "70vh" }: {
  children: ReactNode;
  exportName?: string;
  rows?: Record<string, unknown>[];
  maxHeight?: string;
}) {
  return (
    <div>
      {exportName && rows && rows.length > 0 && (
        <div className="flex justify-end px-3 pt-2">
          <button onClick={() => downloadCsv(exportName, rows)} className="text-[12px] text-accent hover:underline">
            Export CSV
          </button>
        </div>
      )}
      <div className="overflow-auto" style={{ maxHeight }}>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, consequence, confirmLabel, tone = "primary", busy, onConfirm, onCancel }: {
  open: boolean;
  title: string;
  consequence: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      className="m-auto w-[min(520px,92vw)] rounded-[10px] border border-line bg-raised p-0 text-ink shadow-2xl backdrop:bg-black/50"
    >
      <div className="p-5">
        <h3 className="text-[16px] font-semibold">{title}</h3>
        <div className="mt-2 text-[13px] text-muted">{consequence}</div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={tone} onClick={onConfirm} busy={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}

export function Drawer({ open, title, onClose, children, width = "min(980px, 96vw)" }: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        className="flex h-full flex-col border-l border-line bg-bg shadow-2xl"
        style={{ width }}
        aria-modal
        role="dialog"
      >
        <header className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
          <div className="text-[15px] font-semibold">{title}</div>
          <Button variant="ghost" onClick={onClose} aria-label="close">
            ✕
          </Button>
        </header>
        <div className="flex-1 overflow-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px]">{children}</span>;
}
