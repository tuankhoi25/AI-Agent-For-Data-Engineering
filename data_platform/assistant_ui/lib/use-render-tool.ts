"use client";

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import type { ToolCallMessagePartProps } from "@assistant-ui/react";
import type { z } from "zod";
import type { RenderResult } from "./perspective-parameters";
import { completeReportRender, getRenderArgs, hasRenderRequest, releaseRenderRequest, subscribeRenderRequests } from "./render-requests";

export function useRenderTool<TArgs extends Record<string, unknown>>(
  { toolCallId, args, argsText, result, isError }: ToolCallMessagePartProps<TArgs, RenderResult>,
  schema: z.ZodType<TArgs>,
) {
  const pending = useSyncExternalStore(subscribeRenderRequests, () => hasRenderRequest(toolCallId), () => false);
  const executedArgs = useSyncExternalStore(subscribeRenderRequests, () => getRenderArgs(toolCallId), () => undefined);
  const parsed = useMemo(() => {
    // The executor has already validated this payload. Snapshot messages can
    // carry parsed args without streamed argsText; they are valid history too.
    try { return schema.safeParse(executedArgs ?? (argsText.trim() ? JSON.parse(argsText) : args)); } catch { return null; }
  }, [schema, executedArgs, argsText, args]);
  const report = useCallback((outcome: RenderResult) => completeReportRender(toolCallId, outcome), [toolCallId]);
  useEffect(() => {
    if (result !== undefined) releaseRenderRequest(toolCallId);
  }, [toolCallId, result]);
  useEffect(() => {
    if (pending && parsed && !parsed.success) report({ status: "error", error: parsed.error.message });
  }, [pending, parsed, report]);
  const error = result?.status === "error" ? result.error : isError ? String(result) : undefined;
  return { parsed, pending, error, report };
}
