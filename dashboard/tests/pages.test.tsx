import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Shell } from "../src/App";
import { detailAdvance, detailReject, emptyIndex, index, mockFetch, realIndex, validation } from "./fixtures";

beforeAll(() => {
  // Recharts measures its container; jsdom has no layout, so give it a size.
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

beforeEach(() => {
  mockFetch({
    "index.json": emptyIndex,
    "demo/index.json": index,
    "judge_validation.json": validation,
    "demo/H-0001/detail.json": detailAdvance,
    "demo/H-0002/detail.json": detailReject,
  });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Shell />
    </MemoryRouter>,
  );
}

describe("five pages render from the results JSON", () => {
  it("Overview: the real funnel is zero and says so; the demo funnel and N are separate", async () => {
    renderAt("/");
    expect(await screen.findByText(/No real research has been run yet/)).toBeInTheDocument();
    expect(screen.getByText("N = 0")).toBeInTheDocument();
    const demo = await screen.findByRole("region", { name: /Demo run \(simulated data\)/ });
    expect(within(demo).getByText(/N = 224/)).toBeInTheDocument();
    expect(within(demo).getByText(/not counted in the real N/)).toBeInTheDocument();
    expect(within(demo).getByText(/Demo run \(simulated data\)\./)).toBeInTheDocument();
    for (const label of ["Proposed", "Passed skeptic", "Passed judge (train)", "Passed hold-out"]) {
      expect(screen.getAllByText(label)).toHaveLength(2);
    }
    expect(screen.getByText(/multiple testing/i)).toBeInTheDocument();
    expect(screen.getByText(/3\.21/)).toBeInTheDocument();
    const real = screen.getByRole("region", { name: /Total trials/ });
    expect(within(real).getByText("N = 0")).toBeInTheDocument(); // demo N never leaks into it
  });

  it("Overview: real numbers are shown without a demo section when there is no demo index", async () => {
    mockFetch({ "index.json": realIndex });
    renderAt("/");
    expect(await screen.findByText("N = 7")).toBeInTheDocument();
    expect(screen.queryByText(/No real research has been run yet/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo run/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Hypotheses: real rows and demo rows are separate; demo rows carry a DEMO badge and /demo links", async () => {
    mockFetch({ "index.json": realIndex, "demo/index.json": index });
    renderAt("/hypotheses");
    const demo = await screen.findByRole("region", { name: /Demo run \(simulated data\)/ });
    const real = screen.getAllByRole("table")[0];
    expect(within(real).getByText("Real idea")).toBeInTheDocument();
    expect(within(real).queryByText("DEMO")).not.toBeInTheDocument();
    expect(within(real).getByRole("link", { name: "H-0001" })).toHaveAttribute("href", "/hypotheses/H-0001");
    expect(within(demo).getAllByText("DEMO")).toHaveLength(2);
    expect(within(demo).getByRole("link", { name: "H-0002" })).toHaveAttribute("href", "/demo/H-0002");
    expect(within(demo).queryByText("Real idea")).not.toBeInTheDocument();
  });

  it("Hypotheses: with no real research the real table says so, and demo rejected rows are shown", async () => {
    renderAt("/hypotheses");
    expect(await screen.findByText(/No real hypotheses have been run yet/)).toBeInTheDocument();
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // demo header + both demo hypotheses
    const rejected = screen.getByRole("row", { name: /H-0002/ });
    expect(within(rejected).getByText("DEMO")).toBeInTheDocument();
    expect(within(rejected).getByText("reject")).toBeInTheDocument();
    expect(within(rejected).getByText("dsr")).toBeInTheDocument();
    expect(within(rejected).getByText("regime")).toBeInTheDocument();
    expect(within(rejected).getByText(/hold-out fail \(2026-10-05\)/)).toBeInTheDocument();
    const advanced = screen.getByRole("row", { name: /H-0001/ });
    expect(within(advanced).getByText("advance")).toBeInTheDocument();
    expect(within(advanced).getByText("not scored")).toBeInTheDocument();
  });

  it("Hypotheses: columns sort", async () => {
    renderAt("/hypotheses");
    await screen.findAllByRole("row");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Sharpe/ }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("H-0002"); // ascending: 0.3 first
    await user.click(screen.getByRole("button", { name: /^Sharpe/ }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("H-0001");
  });

  it("Hypothesis detail: every section of Section 11", async () => {
    renderAt("/demo/H-0001");
    expect(await screen.findByText(/Trend persistence\./)).toBeInTheDocument();
    for (const name of [
      "Mechanism",
      "Equity curve against the benchmarks",
      "Drawdown",
      "Test battery",
      "Parameter sensitivity",
      "Regime breakdown",
      "Report",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("img", { name: /Equity curve/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Drawdown/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Sharpe ratio over window and hurdle/ })).toBeInTheDocument();
    expect(screen.getByText("held up").tagName).toBe("STRONG"); // the report agent's write-up
    expect(screen.getAllByText("pass").length).toBeGreaterThanOrEqual(7);
    expect(screen.getByText("Deflated Sharpe ratio")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/Demo run \(simulated data\)/);
  });

  it("Hypothesis detail: a rejected hypothesis shows failing tests against thresholds and hold-out pass/fail only", async () => {
    renderAt("/demo/H-0002");
    expect(await screen.findByText(/Rejected: 2 of 7 tests failed/)).toBeInTheDocument();
    expect(screen.getAllByText("fail").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/>= 0.95/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/hold-out fail \(2026-10-05\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/insufficient trials/)).toBeInTheDocument();
    expect(screen.getByText(/No report has been written/)).toBeInTheDocument();
  });

  it("Judge validation: false-positive rate and power", async () => {
    renderAt("/judge-validation");
    expect(await screen.findByText(/pure Gaussian noise/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Judge power/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Snooping" })).toBeInTheDocument();
    expect(screen.getAllByText("87%").length).toBeGreaterThan(0);
  });

  it("Method: limitations and the not-investment-advice statement", async () => {
    renderAt("/method");
    expect(await screen.findByText(/Not investment advice\./)).toBeInTheDocument();
    expect(screen.getByText(/One long bull market\./)).toBeInTheDocument();
    expect(screen.getByText(/Small effective sample\./)).toBeInTheDocument();
    expect(screen.getByText(/Known limitation\./)).toBeInTheDocument();
    expect(screen.getByText(/hold-out period prices are publicly downloadable/i)).toBeInTheDocument();
  });

  it("shows an error, not a blank page, when the data is missing", async () => {
    renderAt("/hypotheses/H-9999");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("HTTP 404"));
  });

  it("a real detail page never shows the demo banner and does not read demo data", async () => {
    mockFetch({ "index.json": realIndex, "H-0001/detail.json": detailAdvance });
    renderAt("/hypotheses/H-0001");
    expect(await screen.findByText(/Trend persistence\./)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
