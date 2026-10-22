"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { ToolFallback } from "./assistant-ui/elements/tool-fallback.aui";

// These calls execute on the backend or through toolkit.execute in the browser.
// A missing result is not an approval request. Never insert a placeholder
// result into the agent transcript from a trace renderer.
export const ToolTrace: ToolCallMessagePartComponent = ({ toolName, argsText, result, status }) => {
  const displayStatus = status?.type === "requires-action" && status.reason === "tool-calls"
    ? { type: "running" as const } : status;
  return (
    <ToolFallback.Root>
      <ToolFallback.Trigger toolName={toolName} status={displayStatus} />
      <ToolFallback.Content>
        <ToolFallback.Error status={status} />
        <ToolFallback.Args argsText={argsText} />
        <ToolFallback.Result result={result} />
      </ToolFallback.Content>
    </ToolFallback.Root>
  );
};
