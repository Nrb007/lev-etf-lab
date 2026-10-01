import type { IndexData } from "../types";

export function DemoBanner({ index }: { index: IndexData }) {
  if (!index.data_source?.simulated) return null;
  return (
    <div className="banner" role="note">
      <strong>Demo data.</strong> Every result on this site comes from a simulated universe with a planted
      structure, run through the real pipeline to exercise the dashboard. None of it is a research finding about
      any fund.
    </div>
  );
}
