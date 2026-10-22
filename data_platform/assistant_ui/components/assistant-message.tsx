"use client";

import { MessagePrimitive, ThreadPrimitive, groupPartByType, useAuiState } from "@assistant-ui/react";
import { AssistantMessage } from "./assistant-ui/elements/thread.aui";
import { ToolTrace } from "./tool-trace";
import { ToolGroupRoot, ToolGroupTrigger, ToolGroupContent } from "./assistant-ui/elements/tool-group.aui";
import { standaloneToolNames } from "./visualization-toolkit";

const flatParts = groupPartByType({});

function TraceMessage() {
  return (
    <MessagePrimitive.GroupedParts groupBy={flatParts}>
      {({ part }) => part.type === "tool-call" && !standaloneToolNames.has(part.toolName)
        ? part.toolUI ?? <ToolTrace {...part} /> : <></>}
    </MessagePrimitive.GroupedParts>
  );
}
const traceComponents = { Message: TraceMessage };

function AssistantMessageWithTurnTrace() {
  // Keep selectors stable. Derived arrays belong outside useAuiState snapshots.
  const messages = useAuiState(s => s.thread.messages);
  const index = useAuiState(s => s.message.index);
  const content = useAuiState(s => s.message.content);
  const incomplete = useAuiState(s => s.message.status?.type === "incomplete");
  const isRunning = useAuiState(s => s.thread.isRunning);
  let start = index;
  let end = index + 1;
  while (start > 0 && messages[start - 1].role === "assistant") start--;
  while (end < messages.length && messages[end].role === "assistant") end++;
  const response = messages.slice(start, end);
  const calls = response.flatMap(message => message.content.filter(part =>
    part.type === "tool-call" && !standaloneToolNames.has(part.toolName)));
  const visible = incomplete || content.some(part => {
    if (part.type === "reasoning") return false;
    if (part.type === "text") return part.text.trim().length > 0;
    if (part.type === "tool-call") return standaloneToolNames.has(part.toolName);
    return true;
  });

  return (
    <>
      {index === start && calls.length > 0 ? (
        <div className="px-2" data-testid="turn-tool-trace">
          <ToolGroupRoot variant="ghost">
            <ToolGroupTrigger count={calls.length} active={isRunning && end === messages.length} />
            <ToolGroupContent>
              {response.map(message => (
                <ThreadPrimitive.Unstable_MessageById key={message.id} messageId={message.id} components={traceComponents} />
              ))}
            </ToolGroupContent>
          </ToolGroupRoot>
        </div>
      ) : null}
      {visible ? <AssistantMessage /> : null}
    </>
  );
}

// Use the registry body renderer, replacing only its per-message tool grouping.
// Original AG-UI messages, tool IDs, results and checkpoint history are untouched.
export const threadComponents = {
  AssistantMessage: AssistantMessageWithTurnTrace,
  ToolFallback: ToolTrace,
  ToolGroup: () => null,
};
