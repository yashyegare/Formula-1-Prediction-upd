import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RaceIntelPage from "../../pages/race-intel";
import axe from "axe-core";

const navigation = vi.hoisted(() => ({
  pathname: "/race-intel",
  query: {} as Record<string, string>,
  replace: vi.fn(),
}));
vi.mock("next/router", () => ({ useRouter: () => navigation }));
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/head", () => ({ default: () => null }));
vi.mock("../PostmortemPanel", () => ({
  default: () => <p>Personal prediction review</p>,
}));
vi.mock("../ReconcilePanel", () => ({
  default: () => <p>Personal point reconciliation</p>,
}));
const driver = {
  driverId: "russell",
  driverCode: "RUS",
  surname: "Russell",
  constructorId: "mercedes",
  grid: 1,
  p_podium: 0.6,
  p_points: 0.25,
  p_out: 0.15,
  expected_position: 4,
  sim_dnf_rate: 0.1,
  actual_position: 1,
  observed_swing: 0,
  sim_swing_mean: 3,
};
const season = {
  season: 2026,
  n_sims: 2000,
  next_round: 2,
  mechanism: { swing_mean: 1, swing_sd: 3, dnf_rate: 0.1 },
  races: [
    {
      year: 2026,
      round: 1,
      name: "Australian Grand Prix",
      date: "2026-03-08",
      status: "raced",
      n_drivers: 1,
      drivers: [driver],
    },
    {
      year: 2026,
      round: 2,
      name: "Chinese Grand Prix",
      date: "2026-03-15",
      status: "scheduled",
      n_drivers: 1,
      drivers: [driver],
    },
  ],
  season_attribution: {
    accuracy: 0.7,
    n_misses: 3,
    cause_share: { other: 1 },
    evidence: { scored: 10 },
  },
};
let host: HTMLDivElement, root: Root;
async function waitForText(text: string) {
  for (let i = 0; i < 40; i++) {
    if (host.textContent?.includes(text)) return;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
  }
  throw new Error(`Missing text: ${text}`);
}
beforeEach(() => {
  (
    globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  navigation.query = {};
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const data = input.includes("next-round")
        ? { season: 2026, results_through_round: 10 }
        : input.includes("/season/")
        ? season
        : null;
      return new Response(JSON.stringify(data), {
        status: data ? 200 : 404,
        headers: { "Content-Type": "application/json" },
      });
    })
  );
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
describe("Race Intel end-to-end presentation", () => {
  it("passes automated WCAG structure, names and form checks", async () => {
    await act(async () => root.render(<RaceIntelPage />));
    await waitForText("Driver outcomes");
    const result = await axe.run(host, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      // jsdom has no layout engine; contrast needs a rendered-browser audit.
      rules: { "color-contrast": { enabled: false } },
    });
    expect(
      result.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => n.target),
      }))
    ).toEqual([]);
  });
  it("opens completed analysis when the official calendar is ahead and shows inclusive probabilities", async () => {
    await act(async () => root.render(<RaceIntelPage />));
    await waitForText("Driver outcomes");
    expect(host.querySelector("#weekend-heading")?.textContent).toBe(
      "Australian Grand Prix"
    );
    expect(host.textContent).toContain("awaiting refresh");
    const row = host.querySelector(".ri-outcomes-table tbody tr")!;
    expect(row.textContent).toContain("85.0%");
    expect(row.textContent).toContain("10.0%");
    expect(row.textContent).toContain("model -3");
  });
  it("offers search recovery and a real button for driver details", async () => {
    await act(async () => root.render(<RaceIntelPage />));
    await waitForText("Driver outcomes");
    const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value"
      )!.set!.call(input, "no driver");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(host.textContent).toContain("No matching drivers");
    const reset = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Try again"
    )!;
    await act(async () => reset.click());
    expect(host.querySelector(".ri-outcomes-table")).not.toBeNull();
    const details = host.querySelector<HTMLButtonElement>(".ri-driver-button")!;
    await act(async () => details.click());
    await waitForText("No season traces available");
    expect(host.textContent).not.toContain("Loading season traces");
    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    await act(async () =>
      dialog.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
      )
    );
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(details);
  });
  it("renders unavailable data with retry instead of an infinite loading state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 503 }))
    );
    await act(async () => root.render(<RaceIntelPage />));
    await waitForText("The analysis desk is unavailable");
    expect(
      [...host.querySelectorAll("button")].some(
        (button) => button.textContent === "Try again"
      )
    ).toBe(true);
  });
});
