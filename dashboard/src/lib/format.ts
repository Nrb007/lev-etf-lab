export function pct(value: number | null | undefined, digits = 1): string {
  return value == null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 2): string {
  return value == null ? "n/a" : value.toFixed(digits);
}

export function sci(value: number | null | undefined): string {
  if (value == null) return "n/a";
  return Math.abs(value) < 0.001 && value !== 0 ? value.toExponential(1) : value.toFixed(3);
}
