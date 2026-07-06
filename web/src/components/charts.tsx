// Gráficas basadas en recharts: curva de equity y barras de PnL/retorno.

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EquityPoint } from "../api";

const axis = { stroke: "#475569", fontSize: 11 } as const;
const tooltipStyle = {
  backgroundColor: "#0f172a",
  border: "1px solid #334155",
  borderRadius: 8,
  fontSize: 12,
};

export function EquityChart({ points }: { points: EquityPoint[] }) {
  const data = points.map((p) => ({
    ...p,
    label: new Date(p.time).toLocaleDateString("es-ES", { day: "2-digit", month: "short" }),
  }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="label" {...axis} tickLine={false} minTickGap={40} />
        <YAxis {...axis} tickLine={false} domain={["auto", "auto"]} width={70}
               tickFormatter={(v: number) => v.toLocaleString("es-ES")} />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v: number) => [`${v.toFixed(2)} $`, "Equity"]}
          labelFormatter={(_, p) => (p?.[0] ? new Date((p[0].payload as EquityPoint).time).toLocaleString("es-ES") : "")}
        />
        <Area type="monotone" dataKey="equity" stroke="#34d399" strokeWidth={2} fill="url(#eq)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export interface BarPoint {
  label: string;
  value: number;
}

export function PnlBars({
  data,
  unit = "$",
  target,
  height = 240,
}: {
  data: BarPoint[];
  unit?: string;
  target?: number;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="label" {...axis} tickLine={false} minTickGap={30} />
        <YAxis {...axis} tickLine={false} width={60} />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v: number) => [`${v.toFixed(2)} ${unit}`, unit === "%" ? "Retorno" : "PnL"]}
          cursor={{ fill: "#33415522" }}
        />
        <ReferenceLine y={0} stroke="#475569" />
        {target !== undefined && (
          <ReferenceLine y={target} stroke="#eab308" strokeDasharray="4 4"
                         label={{ value: `objetivo ${target}%`, fill: "#eab308", fontSize: 10, position: "insideTopRight" }} />
        )}
        <Bar dataKey="value" radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.value >= 0 ? "#34d399" : "#f87171"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
