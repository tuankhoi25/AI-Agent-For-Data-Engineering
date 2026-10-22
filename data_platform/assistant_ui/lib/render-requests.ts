import { ToolResponse } from "assistant-stream";
import type { PerspectiveArgs, RenderResult } from "./perspective-parameters";

type Request = { args: PerspectiveArgs; started: () => void; finish: (result: RenderResult) => void; settled: boolean };
const requests = new Map<string, Request>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());

export function subscribeRenderRequests(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export const hasRenderRequest = (id: string) => requests.has(id);
export const getRenderArgs = (id: string) => requests.get(id)?.args;
export const startReportRender = (id: string) => requests.get(id)?.started();

// execute remains the SDK's tool owner. The visible renderer completes it;
// validation or receipt of args alone never returns a successful tool result.
export function requestReportRender(id: string, signal: AbortSignal, args: PerspectiveArgs): Promise<ToolResponse<RenderResult>> {
  return new Promise(resolve => {
    const abort = () => {
      request.finish({ status: "error", error: "Report rendering was cancelled." });
      releaseRenderRequest(id);
    };
    // Once the renderer starts it owns a progress deadline, including history
    // renders. This timer diagnoses a missing renderer instead of racing it.
    const timer = setTimeout(() => request.finish({ status: "error", error: "Report renderer did not start within 30 seconds." }), 30_000);
    const request: Request = {
      args,
      started: () => clearTimeout(timer),
      settled: false,
      finish: outcome => {
        if (request.settled) return;
        request.settled = true;
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        resolve(new ToolResponse({ result: outcome, isError: outcome.status === "error" }));
      },
    };
    requests.set(id, request);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    notify();
  });
}

export function completeReportRender(id: string, outcome: RenderResult) {
  requests.get(id)?.finish(outcome);
}

export function releaseRenderRequest(id: string) {
  if (requests.delete(id)) notify();
}
