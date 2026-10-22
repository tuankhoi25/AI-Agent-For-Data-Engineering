"use client";

import { useMemo } from "react";
import {
  AssistantRuntimeProvider,
  AuiConfig,
  InMemoryThreadListAdapter,
  Tools,
  useRemoteThreadListRuntime,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { ThreadList, ThreadListNew } from "@/components/assistant-ui/elements/thread-list.aui";
import { visualizationToolkit } from "@/components/visualization-toolkit";
import { threadComponents } from "@/components/assistant-message";

function useBakeryRuntime() {
  const agent = useMemo(() => new HttpAgent({ url: "/api/agent" }), []);
  return useAgUiRuntime({ agent, showThinking: false });
}

export function Assistant() {
  const adapter = useMemo(() => new InMemoryThreadListAdapter(), []);
  const runtime = useRemoteThreadListRuntime({ runtimeHook: useBakeryRuntime, adapter });
  const config = AuiConfig({ tools: Tools({ toolkit: visualizationToolkit }) });

  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[240px_minmax(0,1fr)] md:grid-rows-1">
        <aside className="border-b p-3 md:border-e md:border-b-0">
          <div className="md:hidden"><ThreadListNew /></div>
          <div className="hidden md:block"><ThreadList /></div>
        </aside>
        <main className="min-h-0 min-w-0" data-ui-build="tool-render-fix-20261013" data-perspective-build="single-view-5.5.1"><Thread components={threadComponents} /></main>
      </div>
    </AssistantRuntimeProvider>
  );
}
