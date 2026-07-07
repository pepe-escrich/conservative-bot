import { useQuery } from "@tanstack/react-query";
import { api, fmtPct, fmtUsd, pnlColor } from "../api";
import { useSource } from "../state";
import { Card, Empty, SideBadge, StatCard } from "../components/ui";
import { EquityChart, PnlBars } from "../components/charts";
import BotPanel from "../components/BotPanel";

export default function Dashboard() {
  const { source } = useSource();
  const key = source.kind === "paper" ? "paper" : `run-${source.runId}`;

  const { data: summary } = useQuery({
    queryKey: ["summary", key],
    queryFn: () => api.summary(source),
    refetchInterval: 10000,
  });
  const { data: equity } = useQuery({
    queryKey: ["equity", key],
    queryFn: () => api.equity(source),
    refetchInterval: 30000,
  });
  const { data: scores } = useQuery({
    queryKey: ["scores", key],
    queryFn: () => api.scores(source),
    refetchInterval: 60000,
  });

  const dailyReturns = (equity ?? []).slice(1).map((p, i) => {
    const prev = equity![i].equity;
    return {
      label: new Date(p.time).toLocaleDateString("es-ES", { day: "2-digit", month: "short" }),
      value: prev > 0 ? (p.equity / prev - 1) * 100 : 0,
    };
  });

  const lastDate = scores?.[0]?.date;
  const lastScores = (scores ?? []).filter((s) => s.date === lastDate).slice(0, 10);

  return (
    <div className="space-y-4">
      {source.kind === "paper" && <BotPanel />}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Equity" value={fmtUsd(summary?.equity)} sub={`inicial ${fmtUsd(summary?.capital_inicial)}`} />
        <StatCard
          label="PnL hoy"
          value={summary?.today_pnl != null ? fmtUsd(summary.today_pnl) : "–"}
          sub={summary?.today_pnl_pct != null ? `${fmtPct(summary.today_pnl_pct)} · objetivo +1%` : "solo paper"}
          tone={summary?.today_pnl}
        />
        <StatCard label="Retorno total" value={fmtPct(summary?.total_return_pct)} tone={summary?.total_return_pct} />
        <StatCard label="Win rate" value={summary?.win_rate_pct != null ? `${summary.win_rate_pct}%` : "–"}
                  sub={`${summary?.closed_trades ?? 0} trades cerrados`} />
        <StatCard label="Profit factor" value={summary?.profit_factor ?? "–"} />
        <StatCard label="Abiertos" value={summary?.open_trades ?? 0}
                  sub={summary?.unrealized_pnl != null ? `no realizado ${fmtUsd(summary.unrealized_pnl)}` : undefined} />
      </div>

      <Card title="Curva de equity">
        {equity && equity.length > 1 ? <EquityChart points={equity} /> : <Empty text="Sin datos de equity todavía. Lanza un backtest o activa el paper trading." />}
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Retorno diario (%)">
          {dailyReturns.length ? <PnlBars data={dailyReturns} unit="%" target={1} /> : <Empty text="Sin días suficientes." />}
        </Card>
        <Card title={`Último scoring${lastDate ? ` (${lastDate})` : ""}`}>
          {lastScores.length ? (
            <table className="w-full">
              <tbody>
                {lastScores.map((s) => (
                  <tr key={s.symbol} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-1.5 text-sm">{s.symbol.replace(":USDT", "")}</td>
                    <td><SideBadge side={s.side} /></td>
                    <td className={`text-sm text-right font-mono ${pnlColor(s.score)}`}>{s.score.toFixed(3)}</td>
                    <td className="text-right text-xs text-slate-500 pl-3">
                      {s.selected ? "✓ seleccionado" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty text="Aún no hay scores guardados." />
          )}
        </Card>
      </div>
    </div>
  );
}
