import type { Detail } from "../types";

export interface HeatCell {
  x: number | string;
  y: number | string;
  sharpe: number | null;
  chosen: boolean;
}

export interface Heat {
  xName: string;
  yName: string;
  xs: (number | string)[];
  ys: (number | string)[];
  cells: HeatCell[];
  /** params beyond the two plotted, held at the chosen point */
  fixed: Record<string, number | string>;
}

/** Sharpe over the first two parameters; further parameters are held at the chosen point. */
export function buildHeat(detail: Detail): Heat | null {
  const [xName, yName] = detail.param_names;
  if (!xName) return null;
  const fixed: Record<string, number | string> = {};
  for (const name of detail.param_names.slice(2)) fixed[name] = detail.chosen_params[name];
  const rows = detail.grid.filter((g) => Object.entries(fixed).every(([k, v]) => g.params[k] === v));
  const xs = detail.param_values[xName];
  const ys = yName ? detail.param_values[yName] : [0];
  const cells: HeatCell[] = [];
  for (const yv of ys) {
    for (const xv of xs) {
      const hit = rows.find((g) => g.params[xName] === xv && (!yName || g.params[yName] === yv));
      cells.push({
        x: xv,
        y: yName ? yv : "",
        sharpe: hit?.sharpe ?? null,
        chosen: detail.chosen_params[xName] === xv && (!yName || detail.chosen_params[yName] === yv),
      });
    }
  }
  return { xName, yName: yName ?? "", xs, ys: yName ? ys : [""], cells, fixed };
}

/** Diverging colour: blue for positive Sharpe, orange for negative, scaled by the largest |value|. */
export function heatColor(value: number | null, maxAbs: number): string {
  if (value == null || maxAbs === 0) return "var(--surface-2)";
  const t = Math.min(1, Math.abs(value) / maxAbs);
  const hue = value >= 0 ? 215 : 28;
  return `hsl(${hue} 65% ${92 - 45 * t}%)`;
}
