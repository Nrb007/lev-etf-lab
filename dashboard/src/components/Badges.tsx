import type { HoldoutStatus, TrainVerdict } from "../types";
import { testLabel } from "../lib/tests";

export function VerdictBadge({ verdict }: { verdict: TrainVerdict }) {
  return <span className={`badge badge-${verdict}`}>{verdict}</span>;
}

export function HoldoutBadge({ holdout }: { holdout: HoldoutStatus | null }) {
  if (!holdout) return <span className="badge badge-none">not scored</span>;
  if (holdout.verdict === "error") return <span className="badge badge-fail">hold-out error ({holdout.scored_on})</span>;
  return (
    <span className={`badge badge-${holdout.verdict === "pass" ? "holdout-pass" : "holdout-fail"}`}>
      hold-out {holdout.verdict} ({holdout.scored_on})
    </span>
  );
}

export function FailingTests({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return <span className="muted">none</span>;
  return (
    <span className="chips">
      {reasons.map((r) => (
        <span className="chip" key={r} title={testLabel(r)}>
          {r}
        </span>
      ))}
    </span>
  );
}
