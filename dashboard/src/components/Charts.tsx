import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CurveRow } from "../types";
import { pct } from "../lib/format";

const COLORS = { strategy: "var(--accent)", buy_and_hold: "var(--muted-line)", half_cash: "var(--warn)" };
const NAMES: Record<string, string> = { strategy: "Strategy", buy_and_hold: "Buy and hold", half_cash: "50% fund / 50% cash" };
function multiple(v: number): string {
  return `${new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)}x`;
}

const SERIES = ["strategy", "buy_and_hold", "half_cash"] as const;

export function EquityChart({ curves }: { curves: CurveRow[] }) {
  return (
    <div className="chart" role="img" aria-label="Equity curve of the strategy against the benchmarks (log scale)">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={curves} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(0, 4)} minTickGap={40} stroke="var(--muted)" />
          <YAxis scale="log" domain={["auto", "auto"]} stroke="var(--muted)" tickFormatter={multiple} width={64} />
          <Tooltip formatter={(v) => multiple(Number(v))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
          <Legend />
          {SERIES.map((s) => (
            <Line key={s} type="monotone" dataKey={`equity_${s}`} name={NAMES[s]} stroke={COLORS[s]} dot={false} strokeWidth={s === "strategy" ? 2.2 : 1.4} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DrawdownChart({ curves }: { curves: CurveRow[] }) {
  return (
    <div className="chart" role="img" aria-label="Drawdown of the strategy against buy and hold">
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={curves} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(0, 4)} minTickGap={40} stroke="var(--muted)" />
          <YAxis tickFormatter={(v: number) => pct(v, 0)} stroke="var(--muted)" width={56} />
          <Tooltip formatter={(v) => pct(Number(v))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
          <Legend />
          <Area type="monotone" dataKey="drawdown_buy_and_hold" name="Buy and hold" stroke={COLORS.buy_and_hold} fill={COLORS.buy_and_hold} fillOpacity={0.15} isAnimationActive={false} />
          <Area type="monotone" dataKey="drawdown_strategy" name="Strategy" stroke={COLORS.strategy} fill={COLORS.strategy} fillOpacity={0.3} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RegimeChart({ title, excess }: { title: string; excess: Record<string, number> }) {
  const rows = Object.entries(excess).map(([regime, value]) => ({ regime, value }));
  return (
    <figure className="chart-block">
      <figcaption>{title}</figcaption>
      <div role="img" aria-label={`${title}: excess return per regime`}>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="regime" stroke="var(--muted)" interval={0} tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={(v: number) => pct(v, 0)} stroke="var(--muted)" width={56} />
            <ReferenceLine y={0} stroke="var(--muted)" />
            <Tooltip formatter={(v) => pct(Number(v))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
            <Bar dataKey="value" name="Excess return vs buy and hold" fill="var(--accent)" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export interface PowerPoint {
  t: number;
  [edge: string]: number;
}

export function PowerChart({ points, edges }: { points: PowerPoint[]; edges: string[] }) {
  const palette = ["var(--muted-line)", "var(--accent)", "var(--warn)", "var(--ok)"];
  return (
    <div className="chart" role="img" aria-label="Judge power: share of planted edges advanced, by sample length and edge size">
      <ResponsiveContainer width="100%" height={310}>
        <LineChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 20 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} ticks={points.map((p) => p.t)} stroke="var(--muted)" label={{ value: "T (trading days)", position: "insideBottom", offset: -2, fill: "var(--muted)" }} height={44} />
          <YAxis domain={[0, 1]} tickFormatter={(v: number) => pct(v, 0)} stroke="var(--muted)" width={48} />
          <Tooltip formatter={(v) => pct(Number(v), 0)} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
          <Legend verticalAlign="top" />
          {edges.map((edge, i) => (
            <Line key={edge} type="monotone" dataKey={edge} name={`edge Sharpe ${edge}`} stroke={palette[i % palette.length]} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
