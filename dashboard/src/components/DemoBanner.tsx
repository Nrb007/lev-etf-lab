export function DemoBanner() {
  return (
    <div className="banner" role="note">
      <strong>Demo run (simulated data).</strong> Everything marked demo comes from a simulated universe with a
      planted structure, run through the real pipeline to exercise the dashboard. None of it is a research
      finding about any fund, and none of it is counted in the real numbers.
    </div>
  );
}

export function DemoBadge() {
  return <span className="badge badge-demo">DEMO</span>;
}
