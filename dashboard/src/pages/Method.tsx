import { TEST_ORDER } from "../lib/tests";

export function Method() {
  return (
    <>
      <h1>Method</h1>
      <p className="callout">
        <strong>Not investment advice.</strong> This project does not replicate any specific fund's method. It is a
        hypothesis-driven research system built on public, free data. It is not investment advice and is not
        connected to any brokerage.
      </p>

      <section aria-labelledby="how">
        <h2 id="how">How the system works</h2>
        <ol>
          <li>
            <strong>Propose.</strong> A <code>hypothesis</code> agent writes a spec (a stated economic or structural
            mechanism, a small parameter grid) and a signal module. "The backtest looked good" is not a mechanism.
          </li>
          <li>
            <strong>Critique.</strong> A <code>skeptic</code> agent reviews the spec and code for lookahead, too
            many parameters, a missing mechanism and unrealistic costs. A <code>block</code> stops the run.
          </li>
          <li>
            <strong>Pre-register.</strong> The spec and signal are committed to git before anything runs. The judge
            reads its thresholds from a global config file that agents cannot edit.
          </li>
          <li>
            <strong>Run.</strong> <code>lab run</code> backtests every grid point on the train split. The engine
            applies each day's signal to the next day's return; signal authors cannot control that lag. Every grid
            point is written to an append-only ledger and raises the trial count N.
          </li>
          <li>
            <strong>Judge.</strong> <code>lab judge</code> runs seven tests on the best in-sample point, using all N
            trials. Advance requires all seven; any failure is a reject.
          </li>
          <li>
            <strong>Hold-out.</strong> Only an advanced hypothesis, only once, only with a human's approval, is
            scored on data the research never saw. The result is pass or fail and a date; no metrics are shown.
          </li>
          <li>
            <strong>Report.</strong> A <code>report</code> agent writes plain-language prose about what the judge
            returned. It cannot change a verdict. Every number on this site comes from deterministic code.
          </li>
        </ol>
      </section>

      <section aria-labelledby="tests">
        <h2 id="tests">The test battery</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Test</th><th>What it asks</th></tr>
            </thead>
            <tbody>
              {TEST_ORDER.map((t, i) => (
                <tr key={t.key}>
                  <td>{i + 1}</td>
                  <td>{t.label}</td>
                  <td>{t.short}</td>
                </tr>
              ))}
              <tr>
                <td>8</td>
                <td>Hold-out</td>
                <td>Same sign of excess return as train, and excess Sharpe at least zero, on untouched data</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Thresholds are shown next to each result on the hypothesis pages; they come from{" "}
          <code>config/thresholds.yaml</code>. The math and the reasoning behind each threshold are in{" "}
          <code>docs/methodology.md</code> in the repository.
        </p>
      </section>

      <section aria-labelledby="data">
        <h2 id="data">Data limitations</h2>
        <ul>
          <li>
            <strong>One long bull market.</strong> The leveraged funds launched in 2010, so the real-fund sample is
            essentially one extended technology bull market with a handful of sharp drawdowns. Conclusions about
            what works in other regimes cannot be drawn from it. The optional <code>synthetic_long</code> universe
            reaches back further (QQQ to 1999) but is a model of the fund, not the fund.
          </li>
          <li>
            <strong>Small effective sample.</strong> Daily returns are highly autocorrelated in volatility and
            trend; a few thousand days contain far fewer independent observations, and regimes (years, volatility
            terciles) number in the tens. That is why the judge is conservative: rejection does not mean "no
            edge", it means the edge was not demonstrated to these standards (see the power curves on the Judge
            validation page).
          </li>
          <li>
            <strong>Synthetic funds are an approximation.</strong> A synthetic 3x QQQ tracks TQQQ with a daily
            correlation slightly below the 0.999 target, mostly from transient close-timing noise. Financing and
            expense assumptions are judgment calls, stressed by the judge's financing test.
          </li>
          <li>
            <strong>Free data.</strong> Adjusted closes from Yahoo Finance and rates from FRED's public CSV; no
            intraday, options or fund NAV data.
          </li>
        </ul>
      </section>

      <section aria-labelledby="holdout">
        <h2 id="holdout">The hold-out, and its known limitation</h2>
        <p>
          The last stretch of history is held out, behind a 21-session embargo, encrypted on disk, and readable only
          by the hold-out scorer. Each hypothesis gets one attempt, recorded in the ledger before the signal sees the
          data. The scorer returns only pass or fail and a timestamp; the dashboard shows exactly that.
        </p>
        <p className="callout">
          <strong>Known limitation.</strong> Permission rules reduce leakage but are not a hard guarantee. Hold-out
          period prices are publicly downloadable, and an agent with shell access could refetch them. Mitigations:
          the data loader truncates at fetch time; the skeptic audits each run for use of post-hold-out data; the
          ledger is reviewed by a human before any hold-out scoring; and the README states the limitation openly.
          Per-agent write scoping is enforced by tool lists and hooks, which are checks on tool calls, not a sandbox.
        </p>
      </section>

      <section aria-labelledby="site">
        <h2 id="site">About this site</h2>
        <p>
          This is a static site generated from the repository's <code>results/</code> folder. It is unlisted and asks
          search engines not to index it, which reduces discoverability but is not access control: anyone with the
          address can read it.
        </p>
      </section>
    </>
  );
}
