import { Link } from "react-router-dom";
import { useDemoIndex, useIndex } from "../data";
import { Load, LoadDemo } from "../components/Load";
import { DemoBanner } from "../components/DemoBanner";
import { num } from "../lib/format";
import type { IndexData } from "../types";

const STAGES: { key: keyof IndexData["funnel"]; label: string; note: string }[] = [
  { key: "proposed", label: "Proposed", note: "Pre-registered hypotheses with at least one recorded trial" },
  { key: "passed_skeptic", label: "Passed skeptic", note: "Pre-run review by the skeptic agent recommended 'clear'" },
  { key: "passed_judge", label: "Passed judge (train)", note: "All seven train-split tests passed: verdict 'advance'" },
  { key: "passed_holdout", label: "Passed hold-out", note: "Scored once on untouched data; pass or fail only" },
];

function Funnel({ data, id, to }: { data: IndexData; id: string; to: string }) {
  const top = Math.max(1, data.funnel.proposed);
  return (
    <>
      <ol className="funnel" aria-labelledby={id}>
        {STAGES.map((s) => (
          <li key={s.key}>
            <div className="funnel-label">
              <strong>{s.label}</strong>
              <span className="muted small">{s.note}</span>
            </div>
            <div className="funnel-bar-wrap">
              <div
                className="funnel-bar"
                style={{ width: `${Math.max(2, (100 * data.funnel[s.key]) / top)}%` }}
                aria-hidden="true"
              />
              <span className="funnel-count">{data.funnel[s.key]}</span>
            </div>
          </li>
        ))}
      </ol>
      <p>
        <Link to={to}>See every hypothesis, including the rejected ones</Link>
      </p>
    </>
  );
}

export function Overview() {
  const index = useIndex();
  const demo = useDemoIndex();
  return (
    <>
      <h1>Overview</h1>
      <p className="lede">
        A research system that proposes, critiques and statistically judges hypotheses about when leveraged
        tech ETFs are cheap or expensive to hold. Agents propose and critique; deterministic code produces
        every number and every verdict. A run that finds nothing is a valid outcome.
      </p>
      <Load result={index}>
        {(data) => (
          <>
            <section aria-labelledby="funnel">
              <h2 id="funnel">Funnel</h2>
              {data.funnel.proposed === 0 && (
                <p className="callout">No real research has been run yet. Zeros here are the true state.</p>
              )}
              <Funnel data={data} id="funnel" to="/hypotheses" />
            </section>

            <section aria-labelledby="trials">
              <h2 id="trials">
                Total trials: <span className="big-number">N = {data.n_trials}</span>
              </h2>
              <p>
                Every backtest counts, including each point of every parameter grid, whether or not anyone
                looked at it. That count matters because of multiple testing: if you try enough variants of an idea
                on the same history, the best one will look good by luck alone, even when every variant is noise.
                The more trials there are, the better the luckiest one looks, so the bar it has to clear rises with
                N. The judge deflates each Sharpe ratio for exactly this.
              </p>
              {data.expected_max_sharpe_annual != null && (
                <p className="callout">
                  With N = {data.n_trials} trials, the judge's deflated-Sharpe test expects the best of them to show an
                  annualised Sharpe ratio of about <strong>{num(data.expected_max_sharpe_annual)}</strong> from luck
                  alone. A result has to beat that, not zero.
                </p>
              )}
              <p className="muted small">
                Judge thresholds are read from <code>config/thresholds.yaml</code>; its hash is stored in every
                verdict{data.thresholds_hash.length === 1 && <> (<code>{data.thresholds_hash[0].slice(0, 12)}</code>)</>}.
                Data last exported {data.generated_at}.
              </p>
            </section>
          </>
        )}
      </Load>

      <LoadDemo result={demo}>
        {(data) => (
          <section aria-labelledby="demo-funnel">
            <h2 id="demo-funnel">Demo run (simulated data)</h2>
            <DemoBanner />
            <Funnel data={data} id="demo-funnel" to="/hypotheses" />
            <p>
              Demo trials: <span className="big-number">N = {data.n_trials}</span>
              {data.expected_max_sharpe_annual != null && (
                <>
                  {" "}
                  (the demo's deflated-Sharpe test expects about {num(data.expected_max_sharpe_annual)} annualised
                  from luck alone)
                </>
              )}
              . These are not counted in the real N above.
            </p>
          </section>
        )}
      </LoadDemo>
    </>
  );
}
