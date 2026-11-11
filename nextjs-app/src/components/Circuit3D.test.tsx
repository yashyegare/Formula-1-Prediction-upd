import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Circuit3D from "./Circuit3D";

const mocks = vi.hoisted(() => ({
  rotate: vi.fn(),
  reset: vi.fn(),
  setPaused: vi.fn(),
  dispose: vi.fn(),
  create: vi.fn(),
}));
vi.mock("../lib/circuitScene", () => ({ createCircuitScene: mocks.create }));
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.create.mockReturnValue(mocks);
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  (
    globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("interactive circuit lifecycle", () => {
  const points = "10,10 100,10 100,100 10,10";
  it("keeps one GPU scene when motion is paused and connects accessible controls", async () => {
    const onError = vi.fn();
    await act(async () => {
      root.render(
        <Circuit3D
          points={points}
          name="Test circuit"
          paused={false}
          onError={onError}
        />
      );
    });
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    act(() =>
      (
        host.querySelector(
          '[aria-label="Rotate circuit left"]'
        ) as HTMLButtonElement
      ).click()
    );
    expect(mocks.rotate).toHaveBeenCalledWith(-1);
    act(() =>
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent === "Reset view")!
        .click()
    );
    expect(mocks.reset).toHaveBeenCalledOnce();
    await act(async () => {
      root.render(
        <Circuit3D
          points={points}
          name="Test circuit"
          paused={true}
          onError={onError}
        />
      );
    });
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.setPaused).toHaveBeenLastCalledWith(true);
    expect(onError).not.toHaveBeenCalled();
  });
  it("disposes GPU resources when leaving the 3D view", async () => {
    await act(async () => {
      root.render(
        <Circuit3D
          points={points}
          name="Test circuit"
          paused={false}
          onError={vi.fn()}
        />
      );
    });
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledOnce());
    act(() => root.render(<p>Static outline</p>));
    expect(mocks.dispose).toHaveBeenCalledOnce();
  });
  it("requests a fallback when WebGL initialization fails", async () => {
    mocks.create.mockImplementationOnce(() => {
      throw new Error("WebGL unavailable");
    });
    const onError = vi.fn();
    await act(async () => {
      root.render(
        <Circuit3D
          points={points}
          name="Test circuit"
          paused={false}
          onError={onError}
        />
      );
    });
    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
  });
});
