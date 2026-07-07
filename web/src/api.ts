// Cliente de la API + tipos compartidos por las vistas.

export type Source = { kind: "paper" } | { kind: "backtest"; runId: number };

export function sourceParams(src: Source): string {
  return src.kind === "paper" ? "mode=paper" : `run_id=${src.runId}`;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

async function send<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export interface Summary {
  source: string;
  equity: number;
  unrealized_pnl?: number;
  capital_inicial: number;
  total_return_pct: number;
  today_pnl: number | null;
  today_pnl_pct: number | null;
  daily_target_pct?: number;
  open_trades: number;
  closed_trades: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  total_fees: number;
  metrics?: Record<string, unknown>;
}

export interface Trade {
  id: number;
  run_id: number | null;
  mode: string;
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  entry_time: number;
  size: number;
  initial_sl: number;
  tp: number;
  leverage: number;
  margin: number;
  score: number;
  current_sl: number;
  steps_hit: number;
  remaining_size: number;
  realized_pnl: number;
  fees_paid: number;
  status: "open" | "closed";
  close_time: number | null;
  close_reason: string | null;
  last_price?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct_margin?: number;
  next_step_price?: number;
}

export interface Fill {
  id: number;
  time: number;
  price: number;
  size: number;
  kind: string;
  pnl: number;
  fee: number;
}

export interface EquityPoint {
  time: number;
  equity: number;
}

export interface PnlBucket {
  bucket: string;
  pnl: number;
  fees: number;
  trades: number;
  wins: number;
  win_rate_pct: number | null;
}

export interface Run {
  id: number;
  created_at: string;
  date_from: string;
  date_to: string;
  status: "running" | "done" | "error";
  progress: number;
  error: string | null;
  metrics: Record<string, any> | null;
}

export interface Score {
  symbol: string;
  date: string;
  score: number;
  side: string;
  selected: number;
  breakdown: Record<string, number>;
}

export interface Status {
  exchange: string;
  universe: string[];
  schedule: string;
  trades_per_day: number;
  leverage: number;
  paper_enabled: boolean;
  paper_running: boolean;
}

export const api = {
  summary: (src: Source) => get<Summary>(`/api/summary?${sourceParams(src)}`),
  equity: (src: Source) => get<EquityPoint[]>(`/api/equity?${sourceParams(src)}`),
  trades: (params: string) => get<Trade[]>(`/api/trades?${params}`),
  fills: (tradeId: number) => get<Fill[]>(`/api/trades/${tradeId}/fills`),
  pnl: (src: Source, interval: string) =>
    get<PnlBucket[]>(`/api/pnl?${sourceParams(src)}&interval=${interval}`),
  scores: (src: Source) => get<Score[]>(`/api/scores?${sourceParams(src)}`),
  status: () => get<Status>("/api/status"),
  profiles: () => get<Record<string, Record<string, unknown>>>("/api/profiles"),
  runs: () => get<Run[]>("/api/backtests"),
  launchBacktest: (body: { date_from: string; date_to: string; overrides: Record<string, unknown> }) =>
    send<{ run_id: number }>("POST", "/api/backtests", body),
  deleteRun: (id: number) => send<{ deleted: number }>("DELETE", `/api/backtests/${id}`),
};

// ---- formato ----
export const fmtUsd = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : v.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + " $";

export const fmtPct = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const fmtPrice = (v: number | null | undefined) =>
  v == null ? "–" : v.toLocaleString("es-ES", { maximumSignificantDigits: 6 });

export const fmtDate = (ms: number | null | undefined) =>
  ms == null ? "–" : new Date(ms).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });

export const pnlColor = (v: number | null | undefined) =>
  v == null ? "text-slate-400" : v >= 0 ? "text-emerald-400" : "text-red-400";
