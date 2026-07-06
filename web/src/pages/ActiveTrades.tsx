import { useQuery } from "@tanstack/react-query";
import { api, fmtPct, fmtPrice, fmtUsd, fmtDate, pnlColor, sourceParams } from "../api";
import { useSource } from "../state";
import { Card, Empty, SideBadge, Td, Th } from "../components/ui";

export default function ActiveTrades() {
  const { source } = useSource();
  const params = `${sourceParams(source)}&status=open${source.kind === "paper" ? "&mode=paper" : ""}`;

  const { data: trades } = useQuery({
    queryKey: ["open-trades", params],
    queryFn: () => api.trades(params),
    refetchInterval: 5000,
  });

  if (source.kind === "backtest")
    return <Empty text="Un backtest terminado no tiene trades abiertos. Cambia la fuente a Paper trading." />;

  return (
    <Card title="Posiciones abiertas" right={<span className="text-xs text-slate-500">actualiza cada 5s</span>}>
      {trades?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-800">
                <Th>Símbolo</Th><Th>Lado</Th><Th>Entrada</Th><Th>Último</Th><Th>PnL no realizado</Th>
                <Th>Escalones</Th><Th>SL actual</Th><Th>Sig. escalón</Th><Th>TP</Th><Th>Restante</Th>
                <Th>PnL realizado</Th><Th>Abierto</Th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30">
                  <Td className="font-medium">{t.symbol.replace(":USDT", "")}</Td>
                  <Td><SideBadge side={t.side} /></Td>
                  <Td className="font-mono">{fmtPrice(t.entry_price)}</Td>
                  <Td className="font-mono">{fmtPrice(t.last_price)}</Td>
                  <Td className={`font-mono ${pnlColor(t.unrealized_pnl)}`}>
                    {fmtUsd(t.unrealized_pnl)}{" "}
                    <span className="text-xs">({fmtPct(t.unrealized_pnl_pct_margin)} margen)</span>
                  </Td>
                  <Td>
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-xs font-mono">{t.steps_hit}</span>
                  </Td>
                  <Td className="font-mono">{fmtPrice(t.current_sl)}</Td>
                  <Td className="font-mono text-sky-400">{fmtPrice(t.next_step_price)}</Td>
                  <Td className="font-mono">{fmtPrice(t.tp)}</Td>
                  <Td className="font-mono text-xs">
                    {((t.remaining_size / t.size) * 100).toFixed(0)}%
                  </Td>
                  <Td className={`font-mono ${pnlColor(t.realized_pnl)}`}>{fmtUsd(t.realized_pnl)}</Td>
                  <Td className="text-xs text-slate-400">{fmtDate(t.entry_time)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No hay posiciones abiertas. El bot abrirá los trades del día a la hora programada (07:00)." />
      )}
    </Card>
  );
}
