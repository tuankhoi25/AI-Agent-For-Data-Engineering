import type { HTMLPerspectiveViewerElement, PluginStaticConfig } from "@perspective-dev/viewer";
import type { Client } from "@perspective-dev/client/inline";
import { registerNumberCard } from "./perspective-number-card";

export const PERSPECTIVE_VERSION = "5.5.1";
let runtime: Promise<{ client: Client; plugins: PluginStaticConfig[] }> | undefined;

// A browser-local engine. Its tables are owned and deleted by each report.
export function loadPerspective() {
  runtime ??= (async () => {
    // Official browser distributions preserve blob-worker imports. Serving them
    // locally avoids bundler rewriting of WASM bootstrap and vendor source paths.
    const base = `/perspective/${PERSPECTIVE_VERSION}`;
    const engine = await import(/* webpackIgnore: true */ `${base}/perspective.js`) as typeof import("@perspective-dev/client/inline");
    await import(/* webpackIgnore: true */ `${base}/viewer/dist/cdn/perspective-viewer.js`) as typeof import("@perspective-dev/viewer");
    engine.init_client(fetch(`${base}/client.wasm`));
    engine.init_server(() => fetch(`${base}/server.wasm`));
    // The official viewer browser entry initializes its colocated WASM.
    await Promise.all([
      import(/* webpackIgnore: true */ `${base}/perspective-viewer-datagrid.js`),
      import(/* webpackIgnore: true */ `${base}/perspective-viewer-charts.js`),
    ]);
    await customElements.whenDefined("perspective-viewer");
    registerNumberCard();
    const client = await engine.worker();
    const probe = document.createElement("perspective-viewer") as HTMLPerspectiveViewerElement;
    const table = await client.table({ value: "float" }, { name: `capabilities:${crypto.randomUUID()}` });
    probe.style.cssText = "position:fixed;left:-10000px;width:100px;height:100px";
    document.body.append(probe);
    try {
      // v5 enumerates plugins through an active panel, not an empty viewer.
      await probe.load(client);
      await probe.restore({ table: await table.get_name(), plugin: "Datagrid", columns: ["value"] });
      await probe.flush();
      const plugins = probe.getAllPlugins().map(plugin => plugin.get_static_config() as PluginStaticConfig);
      return { client, plugins };
    } finally {
      await probe.delete();
      await table.delete();
      probe.remove();
    }
  })().catch(error => { runtime = undefined; throw error; });
  return runtime;
}
