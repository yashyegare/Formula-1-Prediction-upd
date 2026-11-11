import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import DriverPortrait from "./DriverPortrait";
import portraits from "../data/driver-portraits.json";
import roster from "../../../flask-app/current_roster.json";

it("ships a local WebP portrait for every driver in the predictor roster", () => {
  for (const name of roster.active_drivers) {
    const key = name
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
    const src = (portraits as Record<string, string>)[key];
    expect(src, name).toMatch(/^\/drivers\/[a-z0-9]+\.webp$/);
    const path = resolve(process.cwd(), "public", src!.slice(1));
    expect(existsSync(path), name).toBe(true);
    expect(readFileSync(path).subarray(8, 12).toString(), name).toBe("WEBP");
  }
});

it("resets the portrait on selection and falls back cleanly when an image fails", () => {
  (
    globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    act(() => root.render(<DriverPortrait name="Max Verstappen" />));
    act(() => host.querySelector("img")!.dispatchEvent(new Event("load")));
    expect(host.querySelector('[data-loaded="true"]')).not.toBeNull();
    act(() => root.render(<DriverPortrait name="Liam Lawson" />));
    expect(host.querySelector("img")?.getAttribute("src")).toBe(
      "/drivers/liamlawson.webp"
    );
    expect(host.querySelector('[data-loaded="false"]')).not.toBeNull();
    act(() => host.querySelector("img")!.dispatchEvent(new Event("error")));
    expect(host.querySelector("img")).toBeNull();
    expect(host.textContent).toBe("LL");
    act(() => root.render(<DriverPortrait name="New Driver" />));
    expect(host.querySelector("img")).toBeNull();
    expect(host.textContent).toBe("ND");
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
