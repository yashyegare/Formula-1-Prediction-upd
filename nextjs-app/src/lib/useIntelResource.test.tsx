import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { z } from "zod";
import { useIntelResource, type IntelResource } from "./useIntelResource";

const schema = z.object({ value: z.number() });
let host: HTMLDivElement;
let root: Root;
let current: IntelResource<{ value: number }>;
function Probe({ path }: { path: string }) {
  current = useIntelResource(path, schema);
  return null;
}
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("ignores a late response from the previous race", async () => {
  let finishOld!: (response: Response) => void;
  let oldSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, options: RequestInit) => {
      if (path === "/old") {
        oldSignal = options.signal as AbortSignal;
        return new Promise<Response>((resolve) => {
          finishOld = resolve;
        });
      }
      return Promise.resolve(new Response(JSON.stringify({ value: 2 })));
    })
  );
  await act(async () => root.render(<Probe path="/old" />));
  await act(async () => root.render(<Probe path="/new" />));
  expect(oldSignal?.aborted).toBe(true);
  expect(current.data?.value).toBe(2);
  await act(async () => finishOld(new Response(JSON.stringify({ value: 1 }))));
  expect(current.data?.value).toBe(2);
});
it("rejects malformed successful responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response('{"value":"invalid"}'))
  );
  await act(async () => root.render(<Probe path="/invalid" />));
  expect(current.status).toBe("error");
  expect(current.data).toBeNull();
});
it("ends loading and exposes retry guidance after a timeout", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_path: string, options: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          options.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError"))
          );
        })
    )
  );
  await act(async () => root.render(<Probe path="/slow" />));
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(current.status).toBe("error");
  expect(current.error).toContain("took too long");
});
