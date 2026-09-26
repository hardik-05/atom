// Number rendering, per docs/06-web/DESIGN-SYSTEM.md section 2.
//   - Indian digit grouping (₹12,34,567.89)
//   - 2 decimals displayed; the engine stores 4
//   - Unicode minus (U+2212), which aligns with digits at tabular width
//   - explicit sign on deltas
//   - "—" where there is no value: ₹0.00 and "no data" are different facts

const MINUS = "−";
const DASH = "—";

const grouped = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function parse(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function signed(text: string, n: number, withPlus: boolean): string {
  if (n < 0) return MINUS + text.replace("-", "");
  return withPlus && n > 0 ? `+${text}` : text;
}

export function inr(value: string | number | null | undefined, opts: { sign?: boolean } = {}): string {
  const n = parse(value);
  if (n === null) return DASH;
  return signed(`₹${grouped.format(Math.abs(n))}`, n, !!opts.sign);
}

export function price(value: string | number | null | undefined): string {
  const n = parse(value);
  if (n === null) return DASH;
  return signed(grouped.format(Math.abs(n)), n, false);
}

export function pct(value: string | number | null | undefined, opts: { sign?: boolean } = { sign: true }): string {
  const n = parse(value);
  if (n === null) return DASH;
  return signed(`${Math.abs(n).toFixed(2)}%`, n, opts.sign !== false);
}

export function qty(value: number | string | null | undefined): string {
  const n = parse(value);
  if (n === null) return DASH;
  return signed(whole.format(Math.abs(n)), n, false);
}

export function tone(value: string | number | null | undefined): "gain" | "loss" | "neutral" {
  const n = parse(value);
  if (n === null || n === 0) return "neutral";
  return n > 0 ? "gain" : "loss";
}

export function when(value: string | null | undefined): string {
  if (!value) return DASH;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function day(value: string | null | undefined): string {
  if (!value) return DASH;
  const d = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export { DASH };

export function toCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  if (!rows.length) return "";
  const cols = columns ?? Object.keys(rows[0]!);
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function downloadCsv(name: string, rows: Record<string, unknown>[], columns?: string[]) {
  const blob = new Blob([toCsv(rows, columns)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
