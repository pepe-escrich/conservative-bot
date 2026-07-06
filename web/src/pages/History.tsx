import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDate, fmtPrice, fmtUsd, pnlColor, sourceParams, Trade } from "../api";
import { useSource } from "../state";
import { Card, Empty, ReasonBadge, SideBadge, Td, Th } from "../components/ui";

function FillsDetail({ trade }: { trade: Trade }) {
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

export default function History() {
  const { source } = useSource();
  const [symbol, setSymbol] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const params = `${sourceParams(source)}${source.kind === "paper" ? "&mode=paper" : ""}&status=closed${
    symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""
  }&limit=500`;

  const { data: trades } = useQuery({
    queryKey: ["history", params],
    queryFn: () => api.trades(params),
    refetchInterval: 15000,
  });

  const symbols = Array.from(new Set((trades ?? []).map((t) => t.symbol))).sort();

  return (
    <Card
      title="Trades cerrados"
      right={
        <select
          className="bg-slate-800 border border-slate-700 rounded-md px-2 py-1 text-sm"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
        >
          <option value="">Todos los símbolos</option>
          {symbols.map((s) => (
            <option key={s} value={s}>{s.replace(":USDT", "")}</option>
          ))}
        </select>
      }
    >
      {trades?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-800">
                <Th>Cierre</Th><Th>Símbolo</Th><Th>Lado</Th><Th>Entrada</Th><Th>Escalones</Th>
                <Th>Salida</Th><Th>PnL neto</Th><Th>Comisiones</Th><Th>Duración</Th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const hours = t.close_time ? (t.close_time - t.entry_time) / 3_600_000 : null;
                return (
                  <>
                    <tr
                      key={t.id}
                      className="border-b border-slate-800/60 hover:bg-slate-800/30 cursor-pointer"
                      onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                    >
                      <Td className="text-xs text-slate-400">{fmtDate(t.close_time)}</Td>
                      <Td className="font-medium">{t.symbol.replace(":USDT", "")}</Td>
                      <Td><SideBadge side={t.side} /></Td>
                      <Td className="font-mono">{fmtPrice(t.entry_price)}</Td>
                      <Td><span className="px-2 py-0.5 rounded bg-slate-800 text-xs font-mono">{t.steps_hit}</span></Td>
                      <Td><ReasonBadge reason={t.close_reason} /></Td>
                      <Td className={`font-mono ${pnlColor(t.realized_pnl)}`}>{fmtUsd(t.realized_pnl)}</Td>
                      <Td className="font-mono text-xs text-slate-400">{fmtUsd(t.fees_paid)}</Td>
                      <Td className="text-xs text-slate-400">
                        {hours == null ? "–" : hours < 48 ? `${hours.toFixed(1)} h` : `${(hours / 24).toFixed(1)} d`}
                      </Td>
                    </tr>
                    {expanded === t.id && (
                      <tr key={`${t.id}-detail`}>
                        <td colSpan={9}><FillsDetail trade={t} /></td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="Sin trades cerrados para esta fuente." />
      )}
    </Card>
  );
}
