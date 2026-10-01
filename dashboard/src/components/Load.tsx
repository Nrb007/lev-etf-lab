import type { ReactNode } from "react";
import type { Loaded } from "../data";

export function Load<T>({ result, children }: { result: Loaded<T>; children: (data: T) => ReactNode }) {
  if (result.state === "loading") return <p className="muted">Loading...</p>;
  if (result.state === "error") return <p className="error" role="alert">Could not load data: {result.message}</p>;
  return <>{children(result.data)}</>;
}
