// Compatibility probe for the unchanged community plugin, outside the production bundle.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const packageDir = process.env.SUMMARY_PACKAGE_DIR ?? '/tmp/bakery-perspective-summary-trial/node_modules/perspective-summary';
const packageInfo = JSON.parse(await fs.readFile(path.join(packageDir, 'package.json'), 'utf8'));
const plugin = await fs.readFile(path.join(packageDir, 'dist/cdn/perspective-viewer-summary.js'), 'utf8');
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/summary-trial.js', route => route.fulfill({ contentType: 'text/javascript', body: plugin }));
  await page.goto(process.env.ASSISTANT_UI_URL ?? 'http://localhost:3000', { waitUntil: 'networkidle' });
  const outcome = await page.evaluate(async () => {
    const base = '/perspective/5.5.1';
    await import(`${base}/viewer/dist/cdn/perspective-viewer.js`);
    await import(`${base}/perspective-viewer-datagrid.js`);
    await customElements.whenDefined('perspective-viewer');
    await import('/summary-trial.js');
    await new Promise(resolve => setTimeout(resolve, 100));
    const Summary = customElements.get('perspective-viewer-summary');
    const element = document.createElement('perspective-viewer-summary');
    const diagnostics = {
      customElementDefined: !!Summary,
      hasStaticConfig: typeof element.get_static_config === 'function',
      legacyName: element.name,
    };
    const viewer = document.createElement('perspective-viewer');
    viewer.style.cssText = 'display:block;width:800px;height:300px';
    document.body.append(viewer);
    let table, client;
    try {
      const engine = await import(`${base}/perspective.js`);
      engine.init_client(fetch(`${base}/client.wasm`));
      engine.init_server(() => fetch(`${base}/server.wasm`));
      client = await engine.worker();
      table = await client.table([{ Revenue: 100, Receipts: 2, Average: 50 }], { name: 'summary-trial' });
      await viewer.load(client);
      await viewer.restore({ table: 'summary-trial', plugin: 'Summary', columns: ['Revenue', 'Receipts', 'Average'], group_by: [] });
      await viewer.flush();
      const config = await viewer.save();
      return { ...diagnostics, rendered: config.plugin === 'Summary', config };
    } catch (error) {
      return { ...diagnostics, rendered: false, error: String(error) };
    } finally {
      await viewer.delete().catch(() => {});
      await table?.delete().catch(() => {});
      viewer.remove();
    }
  });
  assert.equal(outcome.customElementDefined, true, 'Plugin bundle did not load');
  const report = { plugin: `${packageInfo.name}@${packageInfo.version}`, host: 'Perspective 5.5.1', peerDependencies: packageInfo.peerDependencies, ...outcome, pageErrors };
  await fs.writeFile('/tmp/bakery-perspective-summary-compatibility.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
