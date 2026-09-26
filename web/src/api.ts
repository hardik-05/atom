// The only module that talks to the engine. Same origin, cookie session, and a
// custom header on every mutation — which a cross-site page cannot send without
// a CORS preflight the engine never approves.

export class ApiError extends Error {
  status: number;
  gate: string | null;
  kind: string | null;
  constructor(status: number, message: string, gate: string | null, kind: string | null) {
    super(message);
    this.status = status;
    this.gate = gate;
    this.kind = kind;
  }
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

let onUnauthorised: () => void = () => {};
export function setUnauthorisedHandler(fn: () => void) {
  onUnauthorised = fn;
}

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Atom-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/login")) onUnauthorised();
    const message =
      (data && (data.error || (Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join("; ") : data.detail))) ||
      `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, String(message), data?.gate ?? null, data?.type ?? null);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  del: <T>(path: string) => request<T>("DELETE", path),
};

// ------------------------------------------------------------------ types
// Money and prices arrive as STRINGS (the engine never sends a float price).

export type Money = string;

export interface Session {
  trade_date: string;
  status: "PENDING" | "VALID" | "INVALID" | "CLEARED";
  obtained_at: string | null;
  verified_at: string | null;
}

export interface Account {
  trading_account_id: number;
  investor_id: number;
  investor_name: string;
  broker_code: string;
  broker_name: string;
  broker_client_code: string;
  execution_mode: "LIVE" | "DRY";
  egress_ip: string | null;
  proxy_url: string | null;
  status: string;
  onboarded_at: string | null;
  auth_flow: string;
  depository_authorisation: "DDPI" | "POA" | "EDIS" | "UNKNOWN";
  session?: Session | null;
  secrets_present?: Record<string, boolean>;
}

export interface Universe {
  universe_id: number;
  name: string;
  source: string;
  status: string;
  member_count: number;
  categories: string[] | null;
}

export interface Run {
  run_id: number;
  trading_account_id: number;
  universe_id: number;
  universe_name: string;
  investor_name: string;
  broker_code: string;
  run_type: string;
  execution_mode: "LIVE" | "DRY";
  trade_date: string;
  status: "QUEUED" | "EXECUTING" | "COMPLETED" | "FAILED";
  started_at: string;
  finished_at: string | null;
  config_snapshot: Record<string, unknown>;
}

export interface Job {
  job_id: string;
  kind: string;
  status: "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  progress: number;
  total: number;
  message: string;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Overview {
  today: string;
  accounts: Account[];
  universes: Universe[];
  runs: Run[];
  jobs: Job[];
  instrument_counts: { instruments: number; mapped: number; classified: number };
}

export interface Funds {
  available_cash: Money;
  used_margin: Money;
  as_of: string;
  components: Record<string, Money>;
}

export interface HoldingRow {
  source: "HOLDING" | "T1_POSITION";
  instrument_id: number;
  symbol: string | null;
  name: string | null;
  instrument_status: string | null;
  total_quantity: number;
  free_quantity: number | null;
  unsettled_quantity: number;
  average_price: Money;
  last_price: Money | null;
  withheld_quantity: number;
}

export interface Quote {
  symbol: string | null;
  instrument_id?: number;
  last_price?: Money;
  close_price?: Money | null;
  volume?: number | null;
  as_of?: string;
  error?: string;
}

export interface Candle {
  trade_date: string;
  open: Money;
  high: Money;
  low: Money;
  close: Money;
  volume: number | null;
}

export interface InstrumentHit {
  instrument_id: number;
  isin: string;
  symbol: string;
  name: string;
  asset_class: string;
  status: string;
  bucket: string | null;
  tier1_index: string | null;
  broker_token: string | null;
  tradable: boolean | null;
  tick_size: Money | null;
}

export interface Candidate {
  run_candidate_id: number;
  instrument_id: number;
  symbol: string;
  name: string;
  category: string;
  rank: number;
  mean_price: Money;
  median_price: Money | null;
  ltp: Money;
  deviation_pct: Money;
  nav: Money | null;
  nav_premium_pct: Money | null;
  holdings_status: string | null;
  gate_failed: string | null;
  decision: "BOUGHT" | "SOLD" | "SKIPPED" | "NOT_CONSIDERED";
  decision_reason: string;
}

export interface OrderRow {
  order_request_id: number;
  instrument_id: number;
  symbol: string;
  side: "BUY" | "SELL";
  order_kind: "LIMIT" | "GTT";
  quantity: number;
  limit_price: Money;
  trigger_price: Money | null;
  idempotency_key: string;
  broker_order_id: string | null;
  status: string;
  reject_reason: string | null;
  placed_at: string | null;
}

export interface RunLog {
  run_log_id: number;
  level: string;
  stage: string;
  message: string;
  context: Record<string, unknown> | null;
  logged_at: string;
}

export interface RunDetail {
  run: Run;
  candidates: Candidate[];
  orders: OrderRow[];
  logs: RunLog[];
}

export interface CoverageRow {
  instrument_id: number;
  symbol: string;
  category: string | null;
  member_status: string;
  mapped: boolean;
  tradable: boolean | null;
  tick_size: Money | null;
  bars: number;
  last_bar: string | null;
  nav: Money | null;
  nav_date: string | null;
}

export interface ConfigKey {
  config_key_id: number;
  key_name: string;
  scope: "ACCOUNT_CATEGORY" | "ACCOUNT" | "GLOBAL";
  value_type: string;
  is_required: boolean;
  suggested_value: string | null;
  description: string;
}

export interface ConfigView {
  categories: string[];
  keys: ConfigKey[];
  values: { key_name: string; category_code: string | null; value_text: string | null; updated_at: string; updated_by: string }[];
  globals: { key_name: string; value_text: string | null; updated_at: string; updated_by: string }[];
  status: { ok: boolean; error: string | null };
}

export interface PositionRow {
  instrument_id: number;
  symbol: string;
  name: string;
  universe_name: string;
  quantity_open: number;
  lot_count: number;
  actual_unit_cost: Money;
  strategy_unit_cost: Money;
  synthetic_quantity: number | null;
  actual_quantity: number | null;
  first_acquired_on: string;
}

export interface ExclusionRow {
  account_exclusion_id: number;
  instrument_id: number;
  symbol: string;
  name: string;
  exclusion_type: "EXCLUSION" | "FREEZE";
  quantity: number;
  created_by: string;
  created_at: string;
}

export interface AuditRow {
  action_audit_id: number;
  actor: string;
  action: string;
  entity: string;
  entity_id: number | null;
  payload: Record<string, unknown> | null;
  occurred_at: string;
}
