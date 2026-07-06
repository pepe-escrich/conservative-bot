import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtUsd, pnlColor } from "../api";
import { useSource } from "../state";
import { Card, Empty, Td, Th } from "../components/ui";
import { PnlBars } from "../components/charts";

const intervals = [
  { id: "day", label: "Día" },
  { id: "week", label: "Semana" },
  { id: "month", label: "Mes" },
];

export default function Pnl() {
  const { source } = useSource();
  const [interval, setInterval] = useState("day");
  const key = source.kind === "paper" ? "paper" : `run-${source.runId}`;

  const { data: buckets } = useQuery({
    queryKey: ["pnl", key, interval],
    queryFn: () => api.pnl(source, interval),
    refetchInterval: 30000,
  });

  const bars = (buckets ?? []).map((b) => ({ label: b.bucket, value: b.pnl }));
  const total = (buckets ?? []).reduce((acc, b) => acc + b.pnl, 0);
  const totalFees = (buckets ?? []).reduce((acc, b) => acc + b.fees, 0);

  return (
    <div className="space-y-4">
      <Card
        title="PnL realizado por intervalo"
        right={
          <div className="flex gap-1">
            {intervals.map((i) => (
              <button
                key={i.id}
                onClick={() => setInterval(i.id)}
                className={`px-3 py-1 rounded-md text-sm ${
                  interval === i.id ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                }`}
              >
                {i.label}
              </button>
            ))}
          </div>
        }
      >
        {bars.length ? <PnlBars data={bars} height={300} /> : <Empty text="Sin trades cerrados todavía." />}
      </Card>

      {buckets && buckets.length > 0 && (
        <Card title={`Detalle (total: ${total.toFixed(2)} $ · comisiones: ${totalFees.toFixed(2)} $)`}>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800">
                  <Th>Intervalo</Th><Th>PnL neto</Th><Th>Trades</Th><Th>Ganadores</Th><Th>Win rate</Th><Th>Comisiones</Th>
                </tr>
              </thead>
              <tbody>
                {[...buckets].reverse().map((b) => (
                  <tr key={b.bucket} className="border-b border-slate-800/60 last:border-0">
                    <Td className="font-mono text-xs">{b.bucket}</Td>
                    <Td className={`font-mono ${pnlColor(b.pnl)}`}>{fmtUsd(b.pnl)}</Td>
                    <Td>{b.trades}</Td>
                    <Td>{b.wins}</Td>
                    <Td>{b.win_rate_pct != null ? `${b.win_rate_pct}%` : "–"}</Td>
                    <Td className="font-mono text-xs text-slate-400">{fmtUsd(b.fees)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
