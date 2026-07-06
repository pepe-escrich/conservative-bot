import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useSource } from "./state";
import Dashboard from "./pages/Dashboard";
import ActiveTrades from "./pages/ActiveTrades";
import History from "./pages/History";
import Pnl from "./pages/Pnl";
import Backtest from "./pages/Backtest";

const tabs = [
  { to: "/", label: "Dashboard" },
  { to: "/trades", label: "Trades activos" },
  { to: "/historico", label: "Histórico" },
  { to: "/pnl", label: "PnL" },
  { to: "/backtest", label: "Backtest" },
];

export default function App() {
  const { source, setSource } = useSource();
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 10000 });
  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status });

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-6 flex-wrap">
          <h1 className="text-lg font-bold tracking-tight">
            <span className="text-emerald-400">conservative</span>-bot
          </h1>
          <nav className="flex gap-1">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.to === "/"}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-md text-sm ${
                    isActive ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {status && (
              <span
                className={`px-2 py-0.5 rounded-full text-xs ${
                  status.paper_running
                    ? "bg-emerald-500/15 text-emerald-400"
                    : "bg-slate-700/50 text-slate-400"
                }`}
                title={`Exchange: ${status.exchange} · ${status.schedule}`}
              >
                paper {status.paper_running ? "activo" : "parado"}
              </span>
            )}
            <label className="text-slate-400">Fuente</label>
            <select
              className="bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm"
              value={source.kind === "paper" ? "paper" : String(source.runId)}
              onChange={(e) => {
                const v = e.target.value;
                setSource(v === "paper" ? { kind: "paper" } : { kind: "backtest", runId: Number(v) });
              }}
            >
              <option value="paper">Paper trading</option>
              {(runs ?? [])
                .filter((r) => r.status === "done")
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    Backtest #{r.id} ({r.date_from} → {r.date_to})
                  </option>
                ))}
            </select>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trades" element={<ActiveTrades />} />
          <Route path="/historico" element={<History />} />
          <Route path="/pnl" element={<Pnl />} />
          <Route path="/backtest" element={<Backtest />} />
        </Routes>
      </main>
    </div>
  );
}
