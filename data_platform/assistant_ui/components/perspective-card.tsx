"use client";

import { useEffect, useRef, useState } from "react";
import type { HTMLPerspectiveViewerElement, ViewerConfigUpdate } from "@perspective-dev/viewer";
import type { Table } from "@perspective-dev/client/inline";
import { loadPerspective } from "@/lib/perspective-runtime";
import { normalizeRows, validateVisualization, type PerspectiveArgs, type RenderResult } from "@/lib/perspective-parameters";
import { Button } from "./ui/button";
import { readNumberCard } from "@/lib/perspective-number-card";

type Props = PerspectiveArgs & { onRenderResult?: (result: RenderResult) => void; onRenderStart?: () => void; externalError?: string };

export function PerspectiveCard({ onRenderResult, onRenderStart, externalError, ...args }: Props) {
  const spec = JSON.stringify(args);
  const root = useRef<HTMLElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLPerspectiveViewerElement | null>(null);
  const resetRef = useRef<ViewerConfigUpdate | null>(null);
  const callback = useRef(onRenderResult);
  callback.current = onRenderResult;
  const started = useRef(onRenderStart);
  started.current = onRenderStart;
  const committed = useRef<(() => void) | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const change = () => setExpanded(document.fullscreenElement === root.current);
    document.addEventListener("fullscreenchange", change);
    return () => document.removeEventListener("fullscreenchange", change);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let completed = false;
    let phase = "starting the view";
    let deadline: ReturnType<typeof setTimeout>;
    let viewer: HTMLPerspectiveViewerElement | undefined;
    const tables: Table[] = [];
    setReady(false);
    setError(null);
    started.current?.();
    async function clean() {
      // Error handling and React unmount can both request cleanup. Claim the
      // resources synchronously so each native WASM handle is deleted once.
      const ownedViewer = viewer;
      viewer = undefined;
      const ownedTables = tables.splice(0);
      if (viewerRef.current === ownedViewer) viewerRef.current = null;
      try { await ownedViewer?.delete(); } catch { /* Keep the original failure. */ }
      for (const table of ownedTables) { try { await table.delete(); } catch { /* May be partially initialized. */ } }
      ownedViewer?.remove();
    }
    function fail(cause: unknown) {
      if (cancelled || completed) return;
      completed = true;
      clearTimeout(deadline);
      const message = cause instanceof Error ? cause.message : String(cause);
      setReady(false);
      setError(message);
      callback.current?.({ status: "error", error: message });
      void clean();
    }
    function progress(next: string) {
      if (cancelled || completed) return;
      phase = next;
      clearTimeout(deadline);
      deadline = setTimeout(() => fail(new Error(`View made no progress for 30 seconds while ${phase}.`)), 30_000);
    }
    async function mount() {
      try {
        const report = JSON.parse(spec) as PerspectiveArgs;
        progress("loading Perspective");
        const { client, plugins } = await loadPerspective();
        if (cancelled || completed) return;
        validateVisualization(report, plugins.map(plugin => plugin.name));
        progress(`loading table ${report.table.name}`);
        const table = await client.table(report.table.schema, { name: crypto.randomUUID() });
        tables.push(table);
        await table.update(normalizeRows(report.table));
        if (cancelled || completed) { await clean(); return; }
        // Validate native query configuration before mounting the plugin.
        const { group_by, split_by, aggregates, sort, filter, columns } = report.view;
        const view = await table.view({ group_by, split_by, aggregates, sort, filter,
          columns: columns.filter((name): name is string => name !== null),
          ...(report.view.plugin === "Number Card" ? { group_rollup_mode: "rollup" as const } : {}),
        });
        try { if (report.view.plugin === "Number Card") await readNumberCard(view); }
        finally { await view.delete(); }
        if (cancelled || completed) { await clean(); return; }
        viewer = document.createElement("perspective-viewer") as HTMLPerspectiveViewerElement;
        viewer.setAttribute("theme", "Pro Light");
        viewer.style.cssText = "display:block;width:100%;height:100%;min-width:0";
        host.current!.append(viewer);
        viewerRef.current = viewer;
        progress("binding the view data");
        await viewer.load(client);
        const config = {
          ...report.view, table: await table.get_name(), title: report.title, theme: "Pro Light",
          group_by: report.view.group_by ?? [], split_by: report.view.split_by ?? [],
          aggregates: report.view.aggregates ?? {}, sort: report.view.sort ?? [], filter: report.view.filter ?? [],
        } as ViewerConfigUpdate;
        progress("configuring the view");
        await viewer.restore(config);
        progress("rendering the view");
        await viewer.flush();
        resetRef.current = await viewer.save() as ViewerConfigUpdate;
        if (cancelled || completed) { await clean(); return; }
        progress("committing the view UI");
        committed.current = () => {
          if (cancelled || completed) return;
          completed = true;
          clearTimeout(deadline);
          callback.current?.({ status: "ready", plugin: report.view.plugin, filter_scope: "supplied_table" });
        };
        setReady(true);
      } catch (cause) { fail(cause); await clean(); }
    }
    void mount();
    return () => {
      cancelled = true;
      clearTimeout(deadline);
      committed.current = null;
      viewerRef.current = null;
      void clean();
    };
  }, [spec]);

  // React has committed the ready controls. requestAnimationFrame can stop in
  // a background tab, so it cannot be the completion handshake for a tool.
  useEffect(() => {
    if (!ready) return;
    committed.current?.();
    committed.current = null;
  }, [ready]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }
  const displayError = externalError ?? error;
  return (
    <section ref={root} className="my-4 flex min-w-0 w-full flex-col overflow-hidden rounded-xl border bg-background p-4 text-foreground fullscreen:my-0 fullscreen:h-screen fullscreen:rounded-none" data-testid="perspective-card" aria-label={args.title}>
      <header className="shrink-0">
        <h3 className="font-medium wrap-break-word">{args.title}</h3>
        <p className="mt-1 text-sm text-muted-foreground wrap-break-word">{args.description}</p>
        <div className="my-3 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={!ready || busy} onClick={() => void act(async () => {
            await viewerRef.current!.restore(resetRef.current!);
            await viewerRef.current!.flush();
          })}>Reset view</Button>
          <Button size="sm" variant="outline" disabled={!ready || busy} onClick={() => void act(async () => {
            const view = await viewerRef.current!.save();
            view.table = args.table.name;
            const blob = new Blob([JSON.stringify({ table: args.table, view }, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url; link.download = "perspective-view.json"; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          })}>Download view JSON</Button>
          <Button size="sm" variant="outline" disabled={!ready || busy} onClick={() => void act(async () => {
            if (document.fullscreenElement === root.current) await document.exitFullscreen();
            else await root.current!.requestFullscreen();
            await viewerRef.current!.resize();
          })}>{expanded ? "Collapse view" : "Expand view"}</Button>
        </div>
      </header>
      {displayError ? <p role="alert" className="text-sm text-destructive">Không thể hiển thị Perspective: {displayError}</p> : null}
      {!ready && !displayError ? <p role="status">Loading Perspective…</p> : null}
      <div ref={host} data-testid="perspective-surface" className={`min-w-0 ${expanded ? "min-h-0 flex-1" : "shrink-0"}`} style={displayError ? { height: 0, flex: "none" } : expanded ? undefined : { height: args.height ?? 480 }} />
    </section>
  );
}
