// Detalle de fills de un trade (compartido por Histórico y Simulación).

import { useQuery } from "@tanstack/react-query";
import { api, fmtDate, fmtPrice, fmtUsd, pnlColor, Trade } from "../api";
import { ReasonBadge, Td, Th } from "./ui";

export default function FillsDetail({ trade }: { trade: Trade }) {
  const { data: fills } = useQuery({
    queryKey: ["fills", trade.id],
    queryFn: () => api.fills(trade.id),
  });
  return (
    <div className="bg-slate-950/60 rounded-lg p-3 my-1">
      <div className="text-xs text-slate-500 mb-2">
        Fills · SL inicial {fmtPrice(trade.initial_sl)} · TP {fmtPrice(trade.tp)} · margen {fmtUsd(trade.margin)} · score {trade.score.toFixed(3)}
      </div>
      <table className="w-full">
        <thead>
          <tr><Th>Hora</Th><Th>Tipo</Th><Th>Precio</Th><Th>Tamaño</Th><Th>PnL</Th><Th>Comisión</Th></tr>
        </thead>
        <tbody>
          {(fills ?? []).map((f) => (
            <tr key={f.id} className="border-t border-slate-800/40">
              <Td className="text-xs text-slate-400">{fmtDate(f.time)}</Td>
              <Td><ReasonBadge reason={f.kind} /></Td>
              <Td className="font-mono">{fmtPrice(f.price)}</Td>
              <Td className="font-mono text-xs">{f.size.toPrecision(4)}</Td>
              <Td className={`font-mono ${pnlColor(f.pnl)}`}>{f.kind === "open" ? "–" : fmtUsd(f.pnl)}</Td>
              <Td className="font-mono text-xs text-slate-400">{fmtUsd(f.fee, 4)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
