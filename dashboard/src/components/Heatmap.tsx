import type { Detail } from "../types";
import { buildHeat, heatColor } from "../lib/heatmap";
import { num } from "../lib/format";

export function Heatmap({ detail }: { detail: Detail }) {
  const heat = buildHeat(detail);
  if (!heat) return <p className="muted">No parameter grid.</p>;
  const maxAbs = Math.max(0, ...heat.cells.map((c) => Math.abs(c.sharpe ?? 0)));
  const fixed = Object.entries(heat.fixed);
  return (
    <div>
      <div
        className="heatmap"
        style={{ gridTemplateColumns: `auto repeat(${heat.xs.length}, minmax(0, 1fr))` }}
        role="table"
        aria-label={`Sharpe ratio over ${heat.xName}${heat.yName ? ` and ${heat.yName}` : ""}`}
      >
        <div className="heat-corner">{heat.yName ? `${heat.yName} \\ ${heat.xName}` : heat.xName}</div>
        {heat.xs.map((x) => (
          <div key={`h-${x}`} className="heat-head">{String(x)}</div>
        ))}
        {heat.ys.map((y) => (
          <RowCells key={`r-${y}`} y={y} heat={heat} maxAbs={maxAbs} />
        ))}
      </div>
      <p className="muted small">
        Annualised Sharpe of every grid point recorded in the ledger (after costs). Outlined cell: the chosen
        point. A robust edge is a plateau, not a single hot cell.
        {fixed.length > 0 && ` Held at the chosen point: ${fixed.map(([k, v]) => `${k} = ${v}`).join(", ")}.`}
      </p>
    </div>
  );
}

function RowCells({ y, heat, maxAbs }: { y: number | string; heat: NonNullable<ReturnType<typeof buildHeat>>; maxAbs: number }) {
  return (
    <>
      <div className="heat-head">{String(y)}</div>
      {heat.cells
        .filter((c) => c.y === y)
        .map((c) => (
          <div
            key={`${c.x}-${c.y}`}
            className={`heat-cell${c.chosen ? " chosen" : ""}`}
            style={{ background: heatColor(c.sharpe, maxAbs) }}
            title={`${heat.xName} = ${c.x}${heat.yName ? `, ${heat.yName} = ${c.y}` : ""}: Sharpe ${num(c.sharpe)}`}
          >
            {num(c.sharpe, 1)}
          </div>
        ))}
    </>
  );
}
