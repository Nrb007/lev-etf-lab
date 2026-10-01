import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it } from "vitest";
import { Shell } from "../src/App";
import { detailAdvance, detailReject, index, mockFetch, validation } from "./fixtures";

beforeAll(() => {
  // Recharts measures its container; jsdom has no layout, so give it a size.
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  mockFetch({
    "index.json": index,
    "judge_validation.json": validation,
    "H-0001/detail.json": detailAdvance,
    "H-0002/detail.json": detailReject,
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
  it("Overview: funnel, N and why N matters", async () => {
    renderAt("/");
    expect((await screen.findAllByText(/N = 224/)).length).toBeGreaterThan(0);
    for (const label of ["Proposed", "Passed skeptic", "Passed judge (train)", "Passed hold-out"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/multiple testing/i)).toBeInTheDocument();
    expect(screen.getByText(/3\.21/)).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
  });

  it("Hypotheses: rejected rows are shown by default, with failing tests and badges", async () => {
    renderAt("/hypotheses");
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // header + both hypotheses
    const rejected = screen.getByRole("row", { name: /H-0002/ });
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
    renderAt("/hypotheses/H-0001");
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
  });

  it("Hypothesis detail: a rejected hypothesis shows failing tests against thresholds and hold-out pass/fail only", async () => {
    renderAt("/hypotheses/H-0002");
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
});
