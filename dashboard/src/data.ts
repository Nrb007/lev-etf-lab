import { useEffect, useState } from "react";
import type { Detail, IndexData, JudgeValidation } from "./types";

// JSON is copied next to the page by `lab dashboard build` (see core/dashboard_build.py).
const BASE = "./data";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}/${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export type Loaded<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

export function useJson<T>(path: string): Loaded<T> {
  const [result, setResult] = useState<Loaded<T>>({ state: "loading" });
  useEffect(() => {
    let cancelled = false;
    setResult({ state: "loading" });
    getJson<T>(path).then(
      (data) => !cancelled && setResult({ state: "ready", data }),
      (err: Error) => !cancelled && setResult({ state: "error", message: err.message }),
    );
    return () => {
      cancelled = true;
    };
  }, [path]);
  return result;
}

export const useIndex = () => useJson<IndexData>("index.json");
export const useJudgeValidation = () => useJson<JudgeValidation>("judge_validation.json");
export const useDetail = (id: string) => useJson<Detail>(`${id}/detail.json`);
export const useDemoIndex = () => useJson<IndexData>("demo/index.json");
export const useDemoDetail = (id: string) => useJson<Detail>(`demo/${id}/detail.json`);
