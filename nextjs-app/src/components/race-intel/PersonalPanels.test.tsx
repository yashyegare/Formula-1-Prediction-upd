import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PostmortemPanel from "../PostmortemPanel";
import ReconcilePanel from "../ReconcilePanel";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  vi.unstubAllGlobals();
});
function Panels() {
  return (
    <>
      <PostmortemPanel season={2026} />
      <ReconcilePanel season={2026} />
    </>
  );
}
it("guides anonymous visitors to sign in", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 401 }))
  );
  await act(async () => root.render(<Panels />));
  expect(host.textContent?.match(/Sign in/g)).toHaveLength(2);
  expect(host.querySelectorAll('a[href="/"]')).toHaveLength(2);
});
it("distinguishes no saved prediction from a service failure", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 }))
  );
  await act(async () => root.render(<Panels />));
  expect(host.textContent?.match(/No prediction saved for 2026/g)).toHaveLength(
    2
  );
  expect(host.querySelector("button")).toBeNull();
});
it("offers recovery for a malformed successful response instead of crashing", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response('{"season":2026}'))
  );
  await act(async () => root.render(<Panels />));
  expect(host.textContent).toContain("Postmortem unavailable");
  expect(host.textContent).toContain("Reconciliation unavailable");
  expect(host.querySelectorAll("button")).toHaveLength(2);
});
