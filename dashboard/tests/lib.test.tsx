import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildHeat, heatColor } from "../src/lib/heatmap";
import { Markdown } from "../src/lib/markdown";
import { sortRows } from "../src/lib/sort";
import { powerSeries } from "../src/pages/JudgeValidation";
import { detailAdvance, index, validation } from "./fixtures";

describe("sortRows", () => {
  it("keeps every row, rejected ones included", () => {
    const out = sortRows(index.hypotheses, { key: "sharpe", dir: "asc" });
    expect(out.map((r) => r.id)).toEqual(["H-0002", "H-0001"]);
    expect(sortRows(index.hypotheses, { key: "sharpe", dir: "desc" }).map((r) => r.id)).toEqual(["H-0001", "H-0002"]);
  });
  it("sorts by failing-test count and hold-out status", () => {
    expect(sortRows(index.hypotheses, { key: "failing", dir: "desc" })[0].id).toBe("H-0002");
    expect(sortRows(index.hypotheses, { key: "holdout", dir: "desc" })[0].id).toBe("H-0002");
  });
  it("is stable and does not mutate its input", () => {
    const copy = [...index.hypotheses];
    sortRows(index.hypotheses, { key: "trials", dir: "asc" });
    expect(index.hypotheses).toEqual(copy);
    expect(sortRows(index.hypotheses, { key: "trials", dir: "asc" }).map((r) => r.id)).toEqual(["H-0001", "H-0002"]);
  });
});

describe("buildHeat", () => {
  it("lays out the grid and marks the chosen point", () => {
    const heat = buildHeat(detailAdvance)!;
    expect(heat.xs).toEqual([5, 10]);
    expect(heat.ys).toEqual([0, 0.01]);
    expect(heat.cells).toHaveLength(4);
    expect(heat.cells.filter((c) => c.chosen)).toHaveLength(1);
    expect(heat.cells.find((c) => c.chosen)).toMatchObject({ x: 10, y: 0, sharpe: 2 });
    expect(heat.cells.find((c) => c.x === 10 && c.y === 0.01)!.sharpe).toBeNull();
  });
  it("holds extra parameters at the chosen point", () => {
    const d = {
      ...detailAdvance,
      param_names: ["a", "b", "c"],
      param_values: { a: [1, 2], b: [1], c: [7, 8] },
      chosen_params: { a: 1, b: 1, c: 8 },
      grid: [
        { params: { a: 1, b: 1, c: 7 }, sharpe: 9, trial: "x" },
        { params: { a: 1, b: 1, c: 8 }, sharpe: 1, trial: "y" },
        { params: { a: 2, b: 1, c: 8 }, sharpe: 2, trial: "z" },
      ],
    };
    const heat = buildHeat(d)!;
    expect(heat.fixed).toEqual({ c: 8 });
    expect(heat.cells.map((c) => c.sharpe)).toEqual([1, 2]);
  });
  it("colours by sign and scales by magnitude", () => {
    expect(heatColor(null, 2)).toContain("surface");
    expect(heatColor(2, 2)).toContain("215");
    expect(heatColor(-2, 2)).toContain("28");
    expect(heatColor(2, 2)).not.toEqual(heatColor(0.2, 2));
  });
});

describe("Markdown", () => {
  it("renders headings, lists, emphasis and code", () => {
    render(<Markdown source={"# Title\n\nSome **bold** and `code`.\n\n- a\n- b\n\n1. x"} />);
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
  it("never turns report text into markup", () => {
    const { container } = render(<Markdown source={'<img src=x onerror="alert(1)"> <script>alert(1)</script>'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
  });
});

describe("powerSeries", () => {
  it("groups planted-edge power by sample length, one series per edge size", () => {
    const { points, edges } = powerSeries(validation.planted_edge);
    expect(edges).toEqual(["1.82", "2.65"]);
    expect(points).toEqual([
      { t: 1500, "1.82": 0.27, "2.65": 0.4 },
      { t: 3000, "1.82": 0.5, "2.65": 0.87 },
    ]);
  });
});
