import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtPct, Run } from "../api";
import { useSource } from "../state";
import { Card, Empty, Td, Th } from "../components/ui";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

const numberField = (v: string) => (v === "" ? undefined : Number(v));

export default function Backtest() {
  const qc = useQueryClient();
  const { setSource } = useSource();

  const [dateFrom, setDateFrom] = useState(isoDaysAgo(90));
  const [dateTo, setDateTo] = useState(isoDaysAgo(1));
  const [form, setForm] = useState({
    trades_per_day: "", leverage: "", risk_reward: "", risk_per_trade_pct: "",
    min_score: "", step_pct: "", partial_close_pct: "", atr_mult: "",
    trail_mode: "", basis: "", entry_mode: "", pullback_pct: "", timeout_hours: "", on_timeout: "",
  });

  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (q) => ((q.state.data ?? []).some((r: Run) => r.status === "running") ? 2000 : 15000),
  });

  const launch = useMutation({
    mutationFn: () => {
      const overrides: Record<string, unknown> = {};
      if (form.trades_per_day) overrides.trades_per_day = numberField(form.trades_per_day);
      if (form.leverage) overrides.leverage = numberField(form.leverage);
      if (form.risk_reward) overrides.risk_reward = numberField(form.risk_reward);
      if (form.risk_per_trade_pct) overrides.risk_per_trade_pct = numberField(form.risk_per_trade_pct);
      if (form.min_score) overrides.min_score = numberField(form.min_score);
      const steps: Record<string, unknown> = {};
      if (form.step_pct) steps.step_pct = numberField(form.step_pct);
      if (form.partial_close_pct) steps.partial_close_pct = numberField(form.partial_close_pct);
      if (form.trail_mode) steps.trail_mode = form.trail_mode;
      if (form.basis) steps.basis = form.basis;
      if (Object.keys(steps).length) overrides.steps = steps;
      if (form.atr_mult) overrides.stop = { atr_mult: numberField(form.atr_mult) };
      const entry: Record<string, unknown> = {};
      if (form.entry_mode) entry.mode = form.entry_mode;
      if (form.pullback_pct) entry.pullback_pct = numberField(form.pullback_pct);
      if (form.timeout_hours) entry.timeout_hours = numberField(form.timeout_hours);
      if (form.on_timeout) entry.on_timeout = form.on_timeout;
      if (Object.keys(entry).length) overrides.entry = entry;
      return api.launchBacktest({ date_from: dateFrom, date_to: dateTo, overrides });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deleteRun(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const field = (label: string, key: keyof typeof form, placeholder: string) => (
    <label className="block">
      <span className="text-xs text-slate-500">{label}</span>
      <input
        className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      />
    </label>
  );

  return (
    <div className="space-y-4">
      <Card title="Nuevo backtest">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <label className="block">
            <span className="text-xs text-slate-500">Desde</span>
            <input type="date" className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                   value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">Hasta</span>
            <input type="date" className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                   value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          {field("Trades/día", "trades_per_day", "3")}
          {field("Apalancamiento", "leverage", "10")}
          {field("Risk:Reward", "risk_reward", "3")}
          {field("Riesgo/trade %", "risk_per_trade_pct", "1.0")}
          {field("Score mínimo", "min_score", "0.3")}
          {field("Escalón %", "step_pct", "1.0")}
          {field("Cierre parcial %", "partial_close_pct", "50")}
          {field("ATR mult (SL)", "atr_mult", "1.5")}
          <label className="block">
            <span className="text-xs text-slate-500">Trailing</span>
            <select className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                    value={form.trail_mode} onChange={(e) => setForm({ ...form, trail_mode: e.target.value })}>
              <option value="">(config)</option>
              <option value="previous_step">Escalón anterior</option>
              <option value="breakeven_only">Solo breakeven</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">Base del escalón</span>
            <select className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                    value={form.basis} onChange={(e) => setForm({ ...form, basis: e.target.value })}>
              <option value="">(config)</option>
              <option value="margin_pnl">% PnL sobre margen</option>
              <option value="price">% precio</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">Entrada</span>
            <select className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                    value={form.entry_mode} onChange={(e) => setForm({ ...form, entry_mode: e.target.value })}>
              <option value="">(config)</option>
              <option value="market">A mercado</option>
              <option value="pullback_limit">Límite en pullback</option>
            </select>
          </label>
          {field("Pullback %", "pullback_pct", "0.5")}
          {field("Validez limitada (h)", "timeout_hours", "6")}
          <label className="block">
            <span className="text-xs text-slate-500">Al expirar</span>
            <select className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                    value={form.on_timeout} onChange={(e) => setForm({ ...form, on_timeout: e.target.value })}>
              <option value="">(config)</option>
              <option value="cancel">Cancelar</option>
              <option value="market">Entrar a mercado</option>
            </select>
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-2 rounded-md text-sm font-medium"
          >
            {launch.isPending ? "Lanzando…" : "Ejecutar backtest"}
          </button>
          <span className="text-xs text-slate-500">
            Los campos vacíos usan el valor de config.yaml. Requiere velas en cache (python -m bot fetch).
          </span>
          {launch.isError && <span className="text-xs text-red-400">{String(launch.error)}</span>}
        </div>
      </Card>

      <Card title="Runs">
        {runs?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800">
                  <Th>#</Th><Th>Rango</Th><Th>Estado</Th><Th>Retorno</Th><Th>Max DD</Th>
                  <Th>Trades</Th><Th>Win rate</Th><Th>PF</Th><Th>Comisiones</Th><Th>Días ≥ +1%</Th><Th></Th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const m = r.metrics;
                  return (
                    <tr key={r.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30">
                      <Td className="font-mono">#{r.id}</Td>
                      <Td className="text-xs">{r.date_from} → {r.date_to}</Td>
                      <Td>
                        {r.status === "running" ? (
                          <div className="w-24 bg-slate-800 rounded-full h-2" title={`${Math.round(r.progress * 100)}%`}>
                            <div className="bg-sky-500 h-2 rounded-full transition-all" style={{ width: `${r.progress * 100}%` }} />
                          </div>
                        ) : r.status === "error" ? (
                          <span className="text-red-400 text-xs" title={r.error ?? ""}>error</span>
                        ) : (
                          <span className="text-emerald-400 text-xs">hecho</span>
                        )}
                      </Td>
                      <Td className={m ? (m.total_return_pct >= 0 ? "text-emerald-400" : "text-red-400") : ""}>
                        {m ? fmtPct(m.total_return_pct) : "–"}
                      </Td>
                      <Td>{m ? `${m.max_drawdown_pct}%` : "–"}</Td>
                      <Td>{m?.num_trades ?? "–"}</Td>
                      <Td>{m ? `${m.win_rate_pct}%` : "–"}</Td>
                      <Td>{m?.profit_factor ?? "–"}</Td>
                      <Td className="text-xs text-slate-400">{m ? `${m.total_fees} $` : "–"}</Td>
                      <Td>{m ? `${m.days_above_1pct_target}/${m.num_days}` : "–"}</Td>
                      <Td>
                        <div className="flex gap-2 justify-end">
                          {r.status === "done" && (
                            <button
                              className="text-xs text-sky-400 hover:underline"
                              onClick={() => setSource({ kind: "backtest", runId: r.id })}
                            >
                              ver en dashboard
                            </button>
                          )}
                          <button className="text-xs text-slate-500 hover:text-red-400" onClick={() => del.mutate(r.id)}>
                            borrar
                          </button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty text="Aún no hay backtests. Configura y lanza el primero arriba." />
        )}
      </Card>
    </div>
  );
}
