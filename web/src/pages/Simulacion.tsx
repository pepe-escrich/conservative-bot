import { Fragment, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtDate, fmtPct, fmtPrice, fmtUsd, pnlColor, Run } from "../api";
import { Card, Empty, ReasonBadge, SideBadge, StatCard, Td, Th } from "../components/ui";
import { EquityChart } from "../components/charts";
import FillsDetail from "../components/FillsDetail";

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
  const [period, setPeriod] = useState<number | "custom">(30);
  const [dateFrom, setDateFrom] = useState(isoDaysAgo(30));
  const [dateTo, setDateTo] = useState(isoDaysAgo(1));
  const [runId, setRunId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const range =
    period === "custom"
      ? { date_from: dateFrom, date_to: dateTo }
      : { date_from: isoDaysAgo(period), date_to: isoDaysAgo(1) };

  const launch = useMutation({
    mutationFn: () =>
      api.launchBacktest({
        ...range,
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
  const { data: trades } = useQuery({
    queryKey: ["sim-trades", runId],
    queryFn: () => api.trades(`run_id=${runId}&limit=1000`),
    enabled: done,
  });

  const start = Number(capital) || 100;
  const final = equity?.length ? equity[equity.length - 1].equity : null;
  const week = equity && equity.length >= 7 ? equity[6].equity : null;
  const nDays = equity?.length ?? 0;
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
            {(
              [
                { d: 7, label: "1 semana" },
                { d: 30, label: "1 mes" },
                { d: 90, label: "3 meses" },
                { d: "custom", label: "Personalizado" },
              ] as const
            ).map((p) => (
              <button
                key={String(p.d)}
                onClick={() => setPeriod(p.d)}
                className={`px-3 py-1.5 rounded-md text-sm ${
                  period === p.d ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {period === "custom" && (
            <>
              <label className="block">
                <span className="text-xs text-slate-500">Desde</span>
                <input type="date" className="mt-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                       value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs text-slate-500">Hasta</span>
                <input type="date" className="mt-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                       value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
              </label>
            </>
          )}
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
              label={`Tras ${nDays} días`}
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

          <Card title={`Trades de la simulación (${trades?.length ?? 0})`}>
            {trades?.length ? (
              <div className="overflow-x-auto max-h-[32rem] overflow-y-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      <Th>Apertura</Th><Th>Símbolo</Th><Th>Lado</Th><Th>Entrada</Th>
                      <Th>Margen</Th><Th>Escalones</Th><Th>Salida</Th><Th>PnL neto</Th><Th>Comisiones</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <Fragment key={t.id}>
                        <tr
                          className="border-b border-slate-800/60 hover:bg-slate-800/30 cursor-pointer"
                          onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                        >
                          <Td className="text-xs text-slate-400">{fmtDate(t.entry_time)}</Td>
                          <Td className="font-medium">{t.symbol.replace(":USDT", "")}</Td>
                          <Td><SideBadge side={t.side} /></Td>
                          <Td className="font-mono">{fmtPrice(t.entry_price)}</Td>
                          <Td className="font-mono text-xs">{fmtUsd(t.margin)}</Td>
                          <Td><span className="px-2 py-0.5 rounded bg-slate-800 text-xs font-mono">{t.steps_hit}</span></Td>
                          <Td><ReasonBadge reason={t.close_reason} /></Td>
                          <Td className={`font-mono ${pnlColor(t.realized_pnl)}`}>{fmtUsd(t.realized_pnl)}</Td>
                          <Td className="font-mono text-xs text-slate-400">{fmtUsd(t.fees_paid)}</Td>
                        </tr>
                        {expanded === t.id && (
                          <tr>
                            <td colSpan={9}><FillsDetail trade={t} /></td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty text="Sin trades en el periodo." />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
