import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Predictor from "./predictor";

vi.mock("../lib/trackExplorer", () => ({
  loadCircuitRegistry: () => Promise.resolve([]),
  explorerTrackUrl: () => null,
}));
let root: Root;
let host: HTMLDivElement;
const roster = {
  season: 2026,
  drivers: ["Max Verstappen"],
  grandsPrix: ["Monaco Grand Prix", "Las Vegas Grand Prix"],
  driverTeam: { "Max Verstappen": "Red Bull" },
};
beforeEach(() => {
  (
    globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  sessionStorage.clear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

it("preserves the chosen race, submits the restored scenario, and carries it into the simulator", async () => {
  sessionStorage.setItem(
    "f1-prediction-scenario-v1",
    JSON.stringify({
      season: 2026,
      round: "Monaco Grand Prix",
      driver: "Max Verstappen",
      quali: 7,
    })
  );
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => roster })
    .mockResolvedValueOnce({ ok: true, json: async () => [2] });
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => {
    root.render(<Predictor defaultRace="Las Vegas Grand Prix" />);
  });
  expect(
    (host.querySelector("#prediction-race") as HTMLSelectElement).value
  ).toBe("Monaco Grand Prix");
  expect(
    (host.querySelector("#prediction-quali") as HTMLInputElement).value
  ).toBe("7");
  await act(async () => {
    (host.querySelector('button[type="submit"]') as HTMLButtonElement).click();
  });
  expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toEqual({
    name: "Max Verstappen",
    round: "Monaco Grand Prix",
    qualifying_pos: "7",
  });
  expect(host.querySelector(".lab-outcome")?.textContent).toContain(
    "Points finish"
  );
  const handoff = host.querySelector(
    ".lab-outcome-actions a"
  ) as HTMLAnchorElement;
  expect(new URL(handoff.href).searchParams.get("race")).toBe(
    "Monaco Grand Prix"
  );
  act(() =>
    (
      host.querySelector(
        '[aria-label="Improve qualifying position"]'
      ) as HTMLButtonElement
    ).click()
  );
  expect(host.querySelector(".lab-outcome")).toBeNull();
  expect(
    JSON.parse(sessionStorage.getItem("f1-prediction-scenario-v1")!).quali
  ).toBe(6);
});

it("recovers from a failed roster load without requiring a page reload", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => roster })
  );
  await act(async () => {
    root.render(<Predictor defaultRace="Las Vegas Grand Prix" />);
  });
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await act(async () => {
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Retry loading")!
      .click();
  });
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(
    (host.querySelector("#prediction-race") as HTMLSelectElement).value
  ).toBe("Las Vegas Grand Prix");
});
