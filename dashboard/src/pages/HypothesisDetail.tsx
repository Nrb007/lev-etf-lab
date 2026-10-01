import { Link, useParams } from "react-router-dom";
import { useDemoDetail, useDetail, type Loaded } from "../data";
import { Load } from "../components/Load";
import { DemoBanner } from "../components/DemoBanner";
import { HoldoutBadge, VerdictBadge } from "../components/Badges";
import { DrawdownChart, EquityChart, RegimeChart } from "../components/Charts";
import { Heatmap } from "../components/Heatmap";
import { Markdown } from "../lib/markdown";
import { TEST_ORDER } from "../lib/tests";
import { num, pct, sci } from "../lib/format";
import type { Detail, Metrics, RegimePartition, TestResult } from "../types";

function Battery({ detail }: { detail: Detail }) {
  const { tests } = detail.verdict;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Test</th>
            <th className="num">Value</th>
            <th>Threshold</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {TEST_ORDER.filter((t) => tests[t.key]).map((t) => {
            const r: TestResult = tests[t.key];
            const insufficient = r.value == null;
            return (
              <tr key={t.key} className={r.pass ? "row-pass" : "row-fail"}>
                <td>
                  <strong>{t.label}</strong>
                  <div className="muted small">{t.short}</div>
                </td>
                <td className="num">{insufficient ? "n/a" : sci(r.value)}</td>
                <td>
                  {t.op} {r.threshold}
                </td>
                <td>
                  <span className={`badge ${r.pass ? "badge-advance" : "badge-reject"}`}>{r.pass ? "pass" : "fail"}</span>
                  {insufficient && <span className="muted small"> {String(r.details["reason"] ?? "undefined")}</span>}
                </td>
              </tr>
            );
          })}
          <tr>
            <td>
              <strong>Hold-out</strong>
              <div className="muted small">Scored once, only for an advanced hypothesis; pass or fail and the date only</div>
            </td>
            <td className="num">n/a</td>
            <td>same sign of excess, excess Sharpe &gt;= 0</td>
            <td><HoldoutBadge holdout={detail.holdout} /></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

const METRIC_ROWS: { key: string; label: string; fmt: (v: number | null) => string }[] = [
  { key: "cagr", label: "CAGR", fmt: pct },
  { key: "ann_vol", label: "Annualised volatility", fmt: pct },
  { key: "sharpe", label: "Sharpe", fmt: (v) => num(v) },
  { key: "sortino", label: "Sortino", fmt: (v) => num(v) },
  { key: "max_drawdown", label: "Max drawdown", fmt: pct },
  { key: "calmar", label: "Calmar", fmt: (v) => num(v) },
  { key: "time_in_market", label: "Time in market", fmt: pct },
  { key: "total_turnover", label: "Total turnover", fmt: (v) => num(v, 1) },
];

function MetricsTable({ metrics }: { metrics: Detail["metrics"] }) {
  const cols: [string, Metrics][] = [
    ["Strategy", metrics.strategy],
    ["Buy and hold", metrics.buy_and_hold],
    ["50% fund / 50% cash", metrics.half_cash],
  ];
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Train split, after costs</th>
            {cols.map(([name]) => (
              <th key={name} className="num">{name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              {cols.map(([name, m]) => (
                <td key={name} className="num">{row.fmt(m[row.key] ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Regimes({ detail }: { detail: Detail }) {
  const regime = detail.verdict.tests["regime"];
  const partitions = (regime?.details["partitions"] ?? {}) as Record<string, RegimePartition>;
  const names: Record<string, string> = { year: "By calendar year", vix_tercile: "By VIX tercile (0 = lowest)" };
  const entries = Object.entries(partitions);
  if (entries.length === 0) return <p className="muted">No regime breakdown.</p>;
  return (
    <div className="regimes">
      {entries.map(([key, p]) => (
        <div key={key}>
          <RegimeChart title={names[key] ?? key} excess={p.excess_by_regime} />
          <p className="muted small">
            {p.fraction_positive == null ? "n/a" : pct(p.fraction_positive, 0)} of regimes positive
            {p.max_share != null && <>; largest single regime carries {pct(p.max_share, 0)} of total excess</>}.
          </p>
        </div>
      ))}
    </div>
  );
}

function Body({ detail }: { detail: Detail }) {
  const v = detail.verdict;
  return (
    <>
      <h1>
        {detail.id}: {detail.title}
      </h1>
      <p className="badges">
        <VerdictBadge verdict={v.train_verdict} /> <HoldoutBadge holdout={detail.holdout} />
        {detail.reviews.pre && <span className="badge badge-none">skeptic pre-run: {detail.reviews.pre}</span>}
        {detail.reviews.post && <span className="badge badge-none">skeptic post-run: {detail.reviews.post}</span>}
      </p>
      <p className="muted small">
        {detail.universe.fund}
        {detail.universe.underlying ? ` on ${detail.universe.underlying}` : ""}, {detail.universe.research_universe}{" "}
        universe, {detail.window[0]} to {detail.window[1]} (train split). Registered {detail.registered_at}. N ={" "}
        {v.n_trials} trials in the ledger, {detail.n_trials_hypothesis} of them this hypothesis's grid. Chosen point:{" "}
        {Object.entries(detail.chosen_params).map(([k, val]) => `${k} = ${val}`).join(", ")}.
      </p>

      <section aria-labelledby="mechanism">
        <h2 id="mechanism">Mechanism</h2>
        <p>{detail.mechanism}</p>
        <p className="muted small">Prior trials: {detail.notes_on_prior_trials}</p>
      </section>

      <section aria-labelledby="equity">
        <h2 id="equity">Equity curve against the benchmarks</h2>
        <EquityChart curves={detail.curves} />
        <MetricsTable metrics={detail.metrics} />
      </section>

      <section aria-labelledby="drawdown">
        <h2 id="drawdown">Drawdown</h2>
        <DrawdownChart curves={detail.curves} />
      </section>

      <section aria-labelledby="battery">
        <h2 id="battery">Test battery</h2>
        <p>
          {v.train_verdict === "advance"
            ? "All seven train-split tests passed."
            : `Rejected: ${v.reasons.length} of 7 tests failed.`}{" "}
          Thresholds come from <code>config/thresholds.yaml</code> (hash <code>{v.thresholds_hash.slice(0, 12)}</code>).
        </p>
        <Battery detail={detail} />
      </section>

      <section aria-labelledby="heatmap">
        <h2 id="heatmap">Parameter sensitivity</h2>
        <Heatmap detail={detail} />
      </section>

      <section aria-labelledby="regimes">
        <h2 id="regimes">Regime breakdown</h2>
        <p className="muted">Excess return over buy and hold within each regime.</p>
        <Regimes detail={detail} />
      </section>

      <section aria-labelledby="report">
        <h2 id="report">Report</h2>
        {detail.report_md ? (
          <Markdown source={detail.report_md} />
        ) : (
          <p className="muted">No report has been written for this hypothesis yet.</p>
        )}
      </section>

      {detail.review_md && (
        <section aria-labelledby="review">
          <h2 id="review">Skeptic review</h2>
          <details>
            <summary>Show the skeptic's reviews</summary>
            <Markdown source={detail.review_md} />
          </details>
        </section>
      )}
    </>
  );
}

function Page({ result, demo }: { result: Loaded<Detail>; demo: boolean }) {
  return (
    <>
      <p><Link to="/hypotheses">&larr; All hypotheses</Link></p>
      {demo && <DemoBanner />}
      <Load result={result}>{(d) => <Body detail={d} />}</Load>
    </>
  );
}

function RealDetail({ id }: { id: string }) {
  return <Page result={useDetail(id)} demo={false} />;
}

function DemoDetail({ id }: { id: string }) {
  return <Page result={useDemoDetail(id)} demo />;
}

export function HypothesisDetail({ demo = false }: { demo?: boolean }) {
  const { id = "" } = useParams();
  return demo ? <DemoDetail id={id} /> : <RealDetail id={id} />;
}
