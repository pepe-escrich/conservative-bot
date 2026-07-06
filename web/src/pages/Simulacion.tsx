import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtPct, fmtUsd, pnlColor, Run } from "../api";
import { Card, Empty, StatCard, Td, Th } from "../components/ui";
import { EquityChart } from "../components/charts";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

async function getRun(id: number): Promise<Run> {
  const r = await fetch(`/api/backtests/${id}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export default function Simulacion() {
  const [capital, setCapital] = useState("100");
  const [fraction, setFraction] = useState("10");
  const [period, setPeriod] = useState(30);
  const [runId, setRunId] = useState<number | null>(null);

  const launch = useMutation({
    mutationFn: () =>
      api.launchBacktest({
        date_from: isoDaysAgo(period),
        date_to: isoDaysAgo(1),
        overrides: {
          capital_inicial: Number(capital) || 100,
          sizing: { mode: "capital_fraction", capital_fraction_pct: Number(fraction) || 10 },
        },
      }),
    onSuccess: (d) => setRunId(d.run_id),
  });

  const { data: run } = useQuery({
    queryKey: ["sim-run", runId],
    queryFn: () => getRun(runId!),
    enabled: runId != null,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });

  const done = run?.status === "done";
  const { data: equity } = useQuery({
    queryKey: ["sim-equity", runId],
    queryFn: () => api.equity({ kind: "backtest", runId: runId! }),
    enabled: done,
  });

  const start = Number(capital) || 100;
  const final = equity?.length ? equity[equity.length - 1].equity : null;
  const week = equity && equity.length >= 7 ? equity[6].equity : null;
  const daily = (equity ?? []).map((p, i) => ({
    date: new Date(p.time).toLocaleDateString("es-ES", { day: "2-digit", month: "short" }),
    equity: p.equity,
    ret: i === 0 ? (p.equity / start - 1) * 100 : (p.equity / equity![i - 1].equity - 1) * 100,
  }));

  return (
    <div className="space-y-4">
      <Card title="Simulación de capital">
        <p className="text-sm text-slate-400 mb-4">
          ¿Cuánto quedaría empezando con un capital dado, usando en cada trade un % fijo del capital
          al inicio del día como margen? Usa la estrategia y configuración actuales (config.yaml)
          sobre datos reales del periodo.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-xs text-slate-500">Capital inicial ($)</span>
            <input
              className="mt-1 w-32 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">% capital por trade</span>
            <input
              className="mt-1 w-32 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
              value={fraction}
              onChange={(e) => setFraction(e.target.value)}
            />
          </label>
          <div className="flex gap-1">
            {[
              { d: 7, label: "1 semana" },
              { d: 30, label: "1 mes" },
              { d: 90, label: "3 meses" },
            ].map((p) => (
              <button
                key={p.d}
                onClick={() => setPeriod(p.d)}
                className={`px-3 py-1.5 rounded-md text-sm ${
                  period === p.d ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending || run?.status === "running"}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-2 rounded-md text-sm font-medium"
          >
            {run?.status === "running" ? `Simulando… ${Math.round((run.progress ?? 0) * 100)}%` : "Simular"}
          </button>
          {launch.isError && <span className="text-xs text-red-400">{String(launch.error)}</span>}
          {run?.status === "error" && <span className="text-xs text-red-400">{run.error}</span>}
        </div>
      </Card>

      {done && final != null && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Capital inicial" value={fmtUsd(start)} />
            <StatCard
              label="Tras 1 semana"
              value={week != null ? fmtUsd(week) : "–"}
              sub={week != null ? fmtPct((week / start - 1) * 100) : undefined}
              tone={week != null ? week - start : undefined}
            />
            <StatCard
              label={`Tras ${period} días`}
              value={fmtUsd(final)}
              sub={fmtPct((final / start - 1) * 100)}
              tone={final - start}
            />
            <StatCard
              label="Trades / win rate"
              value={`${run?.metrics?.num_trades ?? "–"} · ${run?.metrics?.win_rate_pct ?? "–"}%`}
              sub={`comisiones ${run?.metrics?.total_fees ?? "–"} $ · DD ${run?.metrics?.max_drawdown_pct ?? "–"}%`}
            />
          </div>

          <Card title="Evolución del capital">
            {equity && equity.length > 1 ? <EquityChart points={equity} /> : <Empty text="Curva no disponible." />}
          </Card>

          <Card title="Día a día">
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-800">
                    <Th>Día</Th><Th>Capital</Th><Th>Retorno diario</Th>
                  </tr>
                </thead>
                <tbody>
                  {daily.map((d, i) => (
                    <tr key={i} className="border-b border-slate-800/60 last:border-0">
                      <Td className="text-xs text-slate-400">{d.date}</Td>
                      <Td className="font-mono">{fmtUsd(d.equity)}</Td>
                      <Td className={`font-mono ${pnlColor(d.ret)}`}>{fmtPct(d.ret)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
