// Piezas de UI compartidas: tarjetas de métricas, badges y tablas.

import { ReactNode } from "react";
import { pnlColor } from "../api";

export function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: number | null;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${tone !== undefined ? pnlColor(tone) : ""}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

export function SideBadge({ side }: { side: string }) {
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
        side === "long" ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
      }`}
    >
      {side.toUpperCase()}
    </span>
  );
}

const REASON_LABEL: Record<string, [string, string]> = {
  sl: ["SL", "bg-red-500/15 text-red-400"],
  be: ["Breakeven", "bg-slate-500/20 text-slate-300"],
  trail: ["SL trailing", "bg-emerald-500/15 text-emerald-400"],
  tp: ["TP", "bg-emerald-500/15 text-emerald-400"],
  ladder: ["Escalera", "bg-emerald-500/15 text-emerald-400"],
  end: ["Fin de datos", "bg-amber-500/15 text-amber-400"],
  open: ["Apertura", "bg-sky-500/15 text-sky-400"],
  step: ["Escalón", "bg-sky-500/15 text-sky-400"],
};

export function ReasonBadge({ reason }: { reason: string | null }) {
  if (!reason) return <span>–</span>;
  const [label, cls] = REASON_LABEL[reason] ?? [reason, "bg-slate-700 text-slate-300"];
  return <span className={`px-2 py-0.5 rounded-full text-xs ${cls}`}>{label}</span>;
}

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      {(title || right) && (
        <div className="flex items-center justify-between mb-3">
          {title && <h2 className="text-sm font-semibold text-slate-300">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Th({ children }: { children?: ReactNode }) {
  return (
    <th className="text-left text-xs uppercase tracking-wide text-slate-500 font-medium px-3 py-2">
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`px-3 py-2 text-sm ${className}`}>{children}</td>;
}

export function Empty({ text }: { text: string }) {
  return <div className="text-center text-slate-500 py-10 text-sm">{text}</div>;
}
