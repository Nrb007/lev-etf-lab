import { useJudgeValidation } from "../data";
import { Load } from "../components/Load";
import { PowerChart, type PowerPoint } from "../components/Charts";
import { testLabel } from "../lib/tests";
import { num, pct } from "../lib/format";
import type { JudgeValidation as JV } from "../types";

export function powerSeries(planted: JV["planted_edge"]): { points: PowerPoint[]; edges: string[] } {
  const edges = [...new Set(planted.map((p) => p.edge_sharpe))].sort((a, b) => a - b).map((e) => e.toFixed(2));
  const ts = [...new Set(planted.map((p) => p.t))].sort((a, b) => a - b);
  const points = ts.map((t) => {
    const row: PowerPoint = { t };
    for (const p of planted.filter((q) => q.t === t)) row[p.edge_sharpe.toFixed(2)] = p.power;
    return row;
  });
  return { points, edges };
}

export function JudgeValidation() {
  const jv = useJudgeValidation();
  return (
    <Load result={jv}>
      {(d) => {
        const { points, edges } = powerSeries(d.planted_edge);
        const limit = d.noise.nominal + d.noise.tolerance;
        const rejections = Object.entries(d.noise.rejections_by_test).sort((a, b) => b[1] - a[1]);
        return (
          <>
            <h1>Judge validation</h1>
            <p className="lede">
              Before trusting the judge with real hypotheses it is tested on simulated worlds where the truth is
              known. These run in CI (<code>tests/judge/</code>) and use the same seven-test battery as{" "}
              <code>lab judge</code>.
            </p>

            <section aria-labelledby="noise">
              <h2 id="noise">Noise: false-positive rate</h2>
              <p>
                {d.noise.n} strategy families on pure Gaussian noise ({d.noise.t} days each): the judge advanced{" "}
                <strong>{pct(d.noise.advance_rate)}</strong> of them. The pass mark is the nominal rate of{" "}
                {pct(d.noise.nominal, 0)} plus three binomial standard errors, {pct(limit)}.
              </p>
              <div className="meter" role="img" aria-label={`Advance rate ${pct(d.noise.advance_rate)} against a limit of ${pct(limit)}`}>
                <div className="meter-fill" style={{ width: `${Math.max(0.5, (100 * d.noise.advance_rate) / limit)}%` }} />
                <div className="meter-limit" />
              </div>
              <p className="muted small">Bar: advance rate as a share of the limit.</p>
              <h3>Why noise is rejected: tests that failed, out of {d.noise.n} noise strategies</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Test</th><th className="num">Rejections</th><th className="num">Share</th></tr>
                  </thead>
                  <tbody>
                    {rejections.map(([key, n]) => (
                      <tr key={key}>
                        <td>{testLabel(key)}</td>
                        <td className="num">{n}</td>
                        <td className="num">{pct(n / d.noise.n, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                A strategy has to pass all seven, so the combined false-positive rate is far below what any single
                test allows.
              </p>
            </section>

            <section aria-labelledby="power">
              <h2 id="power">Planted edge: power</h2>
              <p>
                A predictable component of known size is injected, and the judge has to find it. Power is the share
                of {d.planted_edge[0]?.runs} simulated worlds in which the edge was advanced, by the edge's true Sharpe
                ratio and the sample length T.
              </p>
              <PowerChart points={points} edges={edges} />
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th className="num">Edge Sharpe</th><th className="num">T (days)</th><th className="num">Power</th><th>Most common failing tests</th></tr>
                  </thead>
                  <tbody>
                    {d.planted_edge.map((p) => (
                      <tr key={`${p.beta}-${p.t}`}>
                        <td className="num">{num(p.edge_sharpe)}</td>
                        <td className="num">{p.t}</td>
                        <td className="num">{pct(p.power, 0)}</td>
                        <td>
                          {Object.entries(p.rejections_by_test)
                            .sort((a, b) => b[1] - a[1])
                            .map(([k, n]) => `${k} (${n})`)
                            .join(", ") || "none"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="callout">
                The judge is conservative on short samples: weak edges over a few years almost never advance. A
                rejection does not show there is no edge; it shows the evidence is not strong enough given how many
                things were tried.
              </p>
            </section>

            <section aria-labelledby="snooping">
              <h2 id="snooping">Snooping</h2>
              <p>
                {d.snooping.variants} random-parameter variants of a null signal, in {d.snooping.worlds} simulated
                worlds: the best in-sample variant had a median Sharpe of{" "}
                <strong>{num(d.snooping.median_best_in_sample_sharpe)}</strong> (impressive, and pure luck), and the
                judge advanced <strong>{pct(d.snooping.advance_rate, 0)}</strong> of them.
              </p>
            </section>
          </>
        );
      }}
    </Load>
  );
}
