"use client";

import { defineToolkit, type ToolCallMessagePartProps } from "@assistant-ui/react";
import { ToolResponse } from "assistant-stream";
import { z } from "zod";
import { ToolTrace } from "./tool-trace";
import { PerspectiveCard } from "./perspective-card";
import { perspectiveParameters, type PerspectiveArgs, type RenderResult } from "@/lib/perspective-parameters";
import { loadPerspective, PERSPECTIVE_VERSION } from "@/lib/perspective-runtime";
import { useRenderTool } from "@/lib/use-render-tool";
import { requestReportRender, startReportRender } from "@/lib/render-requests";

function ReportToolUI(props: ToolCallMessagePartProps<PerspectiveArgs, RenderResult>) {
  const { parsed, pending, error, report } = useRenderTool(props, perspectiveParameters);
  if (parsed?.success && (pending || props.result !== undefined)) return <PerspectiveCard {...parsed.data} externalError={error} onRenderResult={report} onRenderStart={() => startReportRender(props.toolCallId)} />;
  if (error) return <p role="alert">Không thể hiển thị Perspective: {error}</p>;
  return <p role="status">Preparing visualization…</p>;
}

export const visualizationToolkit = defineToolkit({
  inspect_perspective: {
    type: "frontend",
    description: "Inspect the browser's installed Perspective visual plugins and column roles before configuring a chart or grid. This is visualization capability metadata, not business metadata or Cube model metadata. No database query.",
    parameters: z.object({}),
    render: ToolTrace,
    execute: async () => {
      try {
        const { plugins } = await loadPerspective();
        return {
          version: PERSPECTIVE_VERSION, plugins,
          presentation: "One chart, grid or Number Card per render_perspective call; no dashboard layout.",
          number_card: { plugin: "Number Card", columns: ["one numeric field"],
            group_by: "Omit for one summary row; for multiple rows use a grouping field and an explicit aggregate",
            split_by: [], plugin_config: { unit: "verified unit label", locale: "vi-VN", decimals: 2 } },
          filter_scope: "supplied_table",
          note: "Native filters and pivots operate on supplied rows. Query Cube/DBHub first with the needed grain and filter fields.",
        };
      } catch (cause) {
        return new ToolResponse({ result: { error: cause instanceof Error ? cause.message : String(cause) }, isError: true });
      }
    },
  },
  render_perspective: {
    type: "frontend",
    display: "standalone",
    description: "Display verified query rows as one interactive Perspective chart, data grid/pivot or Number Card in chat. Supply one typed table and one native view config; inspect plugins and column roles with inspect_perspective. Native filters act on supplied rows, not a new database query. No dashboard, layout, tabs, SQL, HTML or executable JavaScript.",
    parameters: perspectiveParameters,
    execute: async (args: PerspectiveArgs, { toolCallId, abortSignal }) => requestReportRender(toolCallId, abortSignal, args),
    experimental_onSchemaValidationError: async args => {
      const parsed = perspectiveParameters.safeParse(args);
      const error = parsed.success ? "Invalid visualization arguments." : parsed.error.issues
        .map(issue => `${issue.path.join(".") || "report"}: ${issue.message}`).join("; ");
      return new ToolResponse({ result: { status: "error", error } as RenderResult, isError: true });
    },
    render: ReportToolUI,
  },
});
export const standaloneToolNames = new Set(["render_perspective"]);
