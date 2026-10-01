import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDemoIndex, useIndex } from "../data";
import { Load, LoadDemo } from "../components/Load";
import { DemoBadge, DemoBanner } from "../components/DemoBanner";
import { FailingTests, HoldoutBadge, VerdictBadge } from "../components/Badges";
import { num, pct } from "../lib/format";
import { sortRows, type SortKey, type SortState } from "../lib/sort";
import type { IndexRow } from "../types";

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "id", label: "ID" },
  { key: "title", label: "Hypothesis" },
  { key: "train_verdict", label: "Train verdict" },
  { key: "failing", label: "Failing tests" },
  { key: "sharpe", label: "Sharpe", numeric: true },
  { key: "benchmark_sharpe", label: "Buy-and-hold Sharpe", numeric: true },
  { key: "cagr", label: "CAGR", numeric: true },
  { key: "max_drawdown", label: "Max drawdown", numeric: true },
  { key: "trials", label: "Trials", numeric: true },
  { key: "holdout", label: "Hold-out" },
];

export function HypothesesTable({ rows, demo = false }: { rows: IndexRow[]; demo?: boolean }) {
  const [sort, setSort] = useState<SortState>({ key: "id", dir: "asc" });
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);
  const toggle = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                className={c.numeric ? "num" : undefined}
                aria-sort={sort.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
              >
                <button type="button" onClick={() => toggle(c.key)}>
                  {c.label}
                  {sort.key === c.key && <span aria-hidden="true">{sort.dir === "asc" ? " ▲" : " ▼"}</span>}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id} className={`row-${r.train_verdict}`}>
              <td>
                {demo && <DemoBadge />}
                <Link to={`${demo ? "/demo" : "/hypotheses"}/${r.id}`}>{r.id}</Link>
              </td>
              <td>{r.title}</td>
              <td><VerdictBadge verdict={r.train_verdict} /></td>
              <td><FailingTests reasons={r.reasons} /></td>
              <td className="num">{num(r.sharpe)}</td>
              <td className="num">{num(r.benchmark_sharpe)}</td>
              <td className="num">{pct(r.cagr)}</td>
              <td className="num">{pct(r.max_drawdown)}</td>
              <td className="num">{r.trials}</td>
              <td><HoldoutBadge holdout={r.holdout} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Hypotheses() {
  const index = useIndex();
  const demo = useDemoIndex();
  return (
    <>
      <h1>Hypotheses</h1>
      <p className="lede">
        Every hypothesis that was run, advanced or rejected. Rejections are results: they are what the judge is
        for, and they count toward N. Click a column to sort; click an ID for the full test battery.
      </p>
      <Load result={index}>
        {(data) =>
          data.hypotheses.length === 0 ? (
            <p className="callout">No real hypotheses have been run yet.</p>
          ) : (
            <HypothesesTable rows={data.hypotheses} />
          )
        }
      </Load>
      <p className="muted small">
        Sharpe and drawdown columns are the chosen (best in-sample) grid point on the train split, after costs.
        Hold-out results show only pass or fail and the date scored, never metrics.
      </p>
      <LoadDemo result={demo}>
        {(data) => (
          <section aria-labelledby="demo-hypotheses">
            <h2 id="demo-hypotheses">Demo run (simulated data)</h2>
            <DemoBanner />
            <HypothesesTable rows={data.hypotheses} demo />
          </section>
        )}
      </LoadDemo>
    </>
  );
}
