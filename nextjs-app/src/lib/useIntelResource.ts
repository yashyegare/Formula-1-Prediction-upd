import { useEffect, useState } from "react";
import type { z } from "zod";
export type IntelResource<T> = {
  status: "idle" | "loading" | "ready" | "empty" | "error";
  data: T | null;
  error: string | null;
};
export function useIntelResource<T>(
  path: string | null,
  schema: z.ZodType<T>,
  attempt = 0
): IntelResource<T> {
  const [state, setState] = useState<IntelResource<T>>({
    status: "idle",
    data: null,
    error: null,
  });
  useEffect(() => {
    const controller = new AbortController();
    let timedOut = false;
    if (!path) {
      setState({ status: "idle", data: null, error: null });
      return () => controller.abort();
    }
    setState({ status: "loading", data: null, error: null });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 20000);
    fetch(path, { signal: controller.signal, credentials: "same-origin" })
      .then(async (response) => {
        if (response.status === 404) {
          if (!controller.signal.aborted)
            setState({ status: "empty", data: null, error: null });
          return;
        }
        if (!response.ok)
          throw new Error(
            "The analysis service could not complete this request."
          );
        const parsed = schema.safeParse(await response.json());
        if (!parsed.success)
          throw new Error("This analysis response could not be verified.");
        if (!controller.signal.aborted)
          setState({ status: "ready", data: parsed.data, error: null });
      })
      .catch(() => {
        if (!controller.signal.aborted || timedOut)
          setState({
            status: "error",
            data: null,
            error: timedOut
              ? "The request took too long. Please try again."
              : "The analysis could not be loaded. Please try again.",
          });
      })
      .finally(() => clearTimeout(timer));
    return () => {
      timedOut = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [path, schema, attempt]);
  return state;
}
