import type { IndexRow } from "../types";

export type SortKey =
  | "id"
  | "title"
  | "train_verdict"
  | "failing"
  | "sharpe"
  | "benchmark_sharpe"
  | "cagr"
  | "max_drawdown"
  | "trials"
  | "holdout";

export interface SortState {
  key: SortKey;
  dir: "asc" | "desc";
}

function holdoutRank(row: IndexRow): number {
  if (!row.holdout) return 0;
  return row.holdout.verdict === "pass" ? 2 : 1;
}

function value(row: IndexRow, key: SortKey): string | number {
  switch (key) {
    case "failing":
      return row.reasons.length;
    case "holdout":
      return holdoutRank(row);
    case "train_verdict":
      return row.train_verdict === "advance" ? 1 : 0;
    default: {
      const v = row[key];
      return v == null ? Number.NEGATIVE_INFINITY : v;
    }
  }
}

/** Stable sort; every row is kept (rejected hypotheses are results, SPEC Section 1.5). */
export function sortRows(rows: IndexRow[], { key, dir }: SortState): IndexRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return rows
    .map((row, i) => ({ row, i }))
    .sort((a, b) => {
      const x = value(a.row, key);
      const y = value(b.row, key);
      const cmp = typeof x === "string" && typeof y === "string" ? x.localeCompare(y) : Number(x) - Number(y);
      return cmp !== 0 ? sign * cmp : a.i - b.i;
    })
    .map(({ row }) => row);
}
