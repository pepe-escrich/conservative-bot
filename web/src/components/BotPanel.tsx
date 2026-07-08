// Panel de cuenta y control del bot: saldo demo OKX, iniciar/parar, reset de KPIs.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtUsd, pnlColor } from "../api";
import { Card } from "./ui";

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold mb-4">{title}</h3>
        {children}
      </div>
    </div>
  );
}

const btn = "px-3 py-1.5 rounded-md text-sm font-medium disabled:opacity-50";

export default function BotPanel() {
  const qc = useQueryClient();
  const { data: acc } = useQuery({ queryKey: ["account"], queryFn: api.account, refetchInterval: 10000 });
  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10000 });

  const [modal, setModal] = useState<"start" | "stop" | "reset" | null>(null);
  const [fraction, setFraction] = useState("10");
  const [closeOnStop, setCloseOnStop] = useState(false);
  const [resetAmount, setResetAmount] = useState("");
  const [closeOnReset, setCloseOnReset] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["account"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
    qc.invalidateQueries({ queryKey: ["equity"] });
  };
  const onOk = () => { setModal(null); setError(""); refresh(); };
  const onErr = (e: unknown) => setError(String(e));

  const start = useMutation({ mutationFn: () => api.startBot(Number(fraction) || null), onSuccess: onOk, onError: onErr });
  const stop = useMutation({ mutationFn: () => api.stopBot(closeOnStop), onSuccess: onOk, onError: onErr });
  const reset = useMutation({
    mutationFn: () => api.resetAccount(resetAmount === "" ? null : Number(resetAmount), closeOnReset),
    onSuccess: onOk,
    onError: onErr,
  });
  const runNow = useMutation({
    mutationFn: api.runNow,
    onSuccess: () => setTimeout(refresh, 3000),  // dar tiempo a que abra los trades
    onError: onErr,
  });

  if (!acc) return null;
  const running = acc.running;
  const openTrades = status?.open_trades ?? 0;

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">
            Capital del bot {acc.execution_mode === "okx" ? (acc.demo ? "· OKX demo" : "· OKX REAL") : "· paper"}
          </div>
          <div className="text-2xl font-semibold mt-0.5">{fmtUsd(acc.bot_equity)}</div>
          <div className="text-xs text-slate-500 mt-0.5">
            {acc.execution_mode === "okx"
              ? acc.balance != null
                ? `saldo demo total ${fmtUsd(acc.balance)} — el bot solo opera con su capital`
                : "sin conexión con OKX"
              : "modo simulado interno"}
          </div>
          {acc.balance_error && <div className="text-xs text-red-400 mt-0.5" title={acc.balance_error}>error leyendo saldo (¿keys en .env?)</div>}
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">PnL bot desde reset</div>
          <div className={`text-xl font-semibold mt-0.5 ${pnlColor(acc.bot_pnl_since_reset)}`}>{fmtUsd(acc.bot_pnl_since_reset)}</div>
          <div className="text-xs text-slate-500 mt-0.5">referencia {fmtUsd(acc.reference_capital)}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Bot</div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`w-2.5 h-2.5 rounded-full ${running ? "bg-emerald-400" : "bg-slate-600"}`} />
            <span className="text-sm">{running ? `operando · ${acc.capital_fraction_pct}% por trade` : "parado"}</span>
          </div>
          {running && (
            <div className="text-xs text-slate-500 mt-0.5">
              {openTrades} posiciones · {status?.pending_orders ?? 0} limitadas pendientes
            </div>
          )}
        </div>
        <div className="ml-auto flex gap-2">
          {running ? (
            <>
              <button
                className={`${btn} bg-sky-700 hover:bg-sky-600 text-white`}
                title="Ejecuta ya el ciclo diario (scoring + apertura de trades)"
                onClick={() => runNow.mutate()}
                disabled={runNow.isPending}
              >
                {runNow.isPending ? "Ejecutando…" : "Ciclo ahora"}
              </button>
              <button className={`${btn} bg-red-600/80 hover:bg-red-500 text-white`} onClick={() => setModal("stop")}>
                Parar bot
              </button>
            </>
          ) : (
            <button className={`${btn} bg-emerald-600 hover:bg-emerald-500 text-white`} onClick={() => setModal("start")}>
              Iniciar bot
            </button>
          )}
          <button className={`${btn} bg-slate-700 hover:bg-slate-600 text-white`} onClick={() => setModal("reset")}>
            Reset
          </button>
        </div>
      </div>

      {modal === "start" && (
        <Modal title="Iniciar bot" onClose={() => setModal(null)}>
          <label className="block mb-4">
            <span className="text-xs text-slate-500">% del capital remanente por trade (margen)</span>
            <input className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                   value={fraction} onChange={(e) => setFraction(e.target.value)} />
          </label>
          <p className="text-xs text-slate-500 mb-4">
            Abrirá {status?.trades_per_day ?? "?"} trades/día a las {status?.schedule ?? "07:00"} con apalancamiento {status?.leverage ?? "?"}x
            {acc.execution_mode === "okx" ? ` en tu cuenta ${acc.demo ? "demo" : "REAL"} de OKX.` : " en modo simulado."}
          </p>
          {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
          <div className="flex justify-end gap-2">
            <button className={`${btn} text-slate-400`} onClick={() => setModal(null)}>Cancelar</button>
            <button className={`${btn} bg-emerald-600 hover:bg-emerald-500 text-white`} disabled={start.isPending}
                    onClick={() => start.mutate()}>
              {start.isPending ? "Arrancando…" : "Iniciar"}
            </button>
          </div>
        </Modal>
      )}

      {modal === "stop" && (
        <Modal title="Parar bot" onClose={() => setModal(null)}>
          {openTrades > 0 ? (
            <label className="flex items-start gap-2 mb-4 text-sm">
              <input type="checkbox" className="mt-0.5" checked={closeOnStop} onChange={(e) => setCloseOnStop(e.target.checked)} />
              <span>
                Cerrar ahora los <b>{openTrades} trades activos</b> a mercado.
                <span className="block text-xs text-slate-500 mt-1">
                  Si no los cierras, las posiciones quedan abiertas SIN gestión (ni escalones ni stop del bot) hasta que lo reinicies.
                </span>
              </span>
            </label>
          ) : (
            <p className="text-sm text-slate-400 mb-4">No hay trades activos.</p>
          )}
          {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
          <div className="flex justify-end gap-2">
            <button className={`${btn} text-slate-400`} onClick={() => setModal(null)}>Cancelar</button>
            <button className={`${btn} bg-red-600/80 hover:bg-red-500 text-white`} disabled={stop.isPending}
                    onClick={() => stop.mutate()}>
              {stop.isPending ? "Parando…" : "Parar"}
            </button>
          </div>
        </Modal>
      )}

      {modal === "reset" && (
        <Modal title="Reset de cuenta y KPIs" onClose={() => setModal(null)}>
          <label className="block mb-3">
            <span className="text-xs text-slate-500">Nuevo capital de referencia ($)</span>
            <input className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
                   placeholder={acc.execution_mode === "okx" ? "vacío = saldo real de la cuenta" : String(acc.reference_capital)}
                   value={resetAmount} onChange={(e) => setResetAmount(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 mb-3 text-sm">
            <input type="checkbox" checked={closeOnReset} onChange={(e) => setCloseOnReset(e.target.checked)} />
            Cerrar antes las posiciones abiertas
          </label>
          <p className="text-xs text-slate-500 mb-4">
            Borra del dashboard el PnL, win rate e histórico actuales (quedan archivados en la base de datos)
            y empieza a contar desde el nuevo capital de referencia. El saldo real de la demo de OKX no cambia:
            eso se recarga desde la web de OKX.
          </p>
          {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
          <div className="flex justify-end gap-2">
            <button className={`${btn} text-slate-400`} onClick={() => setModal(null)}>Cancelar</button>
            <button className={`${btn} bg-amber-600 hover:bg-amber-500 text-white`} disabled={reset.isPending}
                    onClick={() => reset.mutate()}>
              {reset.isPending ? "Reseteando…" : "Resetear"}
            </button>
          </div>
        </Modal>
      )}
    </Card>
  );
}
