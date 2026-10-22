import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { chromium } from 'playwright';
import { fixture, toolEvents, textEvents, reply } from './perspective-fixture.mjs';

const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  let calls = 0;
  await page.route('**/api/agent', async route => {
    const input = route.request().postDataJSON(); requests.push(input);
    const resultOf = id => JSON.parse(input.messages.find(message => message.role === 'tool' && message.toolCallId === id).content);
    let events;
    switch (calls++) {
      case 0: {
        const params = input.tools.find(tool => tool.name === 'render_perspective').parameters;
        assert(params.properties.table && params.properties.view);
        assert(!params.properties.tables && !params.properties.panels && !params.properties.layout);
        assert(!input.tools.some(tool => /echarts|render_dashboard/.test(tool.name)));
        events = toolEvents('inspect', 'inspect_perspective', {}); break;
      }
      case 1: {
        const info = resultOf('inspect');
        assert(!info.error, info.error);
        assert(info.plugins.some(plugin => plugin.name === 'Y Line'));
        assert.equal(info.layout, undefined);
        assert.equal(info.filter_scope, 'supplied_table');
        events = [...toolEvents('catalog', 'discover_data', {}), { type: 'TOOL_CALL_RESULT', toolCallId: 'catalog', messageId: 'catalog-result', role: 'tool', content: '{}' }, ...toolEvents('view', 'render_perspective', fixture)]; break;
      }
      case 2:
        assert.equal(resultOf('view').status, 'ready', JSON.stringify(resultOf('view')));
        assert.equal(resultOf('view').plugin, 'Y Line');
        events = textEvents('final', 'View ready.'); break;
      default: events = textEvents('followup', 'Follow-up ready.');
    }
    await reply(route, input, events);
  });
  await page.goto(process.env.ASSISTANT_UI_URL ?? 'http://localhost:3001', { waitUntil: 'networkidle' });
  const input = page.getByRole('textbox', { name: 'Message input', exact: true });
  await input.fill('Render a native chart.'); await input.press('Enter');
  await page.getByText('View ready.', { exact: true }).waitFor({ timeout: 65000 });
  assert.equal(calls, 3);
  assert.equal(await page.getByTestId('turn-tool-trace').count(), 1);
  const viewer = page.locator('perspective-viewer');
  assert.equal(await viewer.count(), 1);
  assert.equal((await viewer.evaluate(node => node.save())).plugin, 'Y Line');
  assert.equal(await page.locator('[data-testid="perspective-viewport"]').count(), 0);
  await viewer.evaluate(async node => {
    await node.restore({ plugin: 'Datagrid', columns: ['Day', 'Category', 'Revenue', 'Units'], group_by: [], filter: [['Category', '==', 'Bakery']] });
    await node.flush();
  });
  const rows = await viewer.evaluate(async node => {
    const view = await node.getView({ mode: 'clone' });
    try { return await view.to_json(); } finally { await view.delete(); }
  });
  assert.equal(rows.length, 2); assert(rows.every(row => row.Category === 'Bakery'));
  const downloads = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download view JSON', exact: true }).click();
  const exported = JSON.parse(await fs.readFile(await (await downloads).path(), 'utf8'));
  assert.equal(exported.table.rows.length, 4, 'Export contains supplied data, not only filtered rows');
  assert.deepEqual(exported.view.filter, [['Category', '==', 'Bakery']]);
  assert.equal(exported.view.table, 'observations');
  assert.equal(exported.workspace, undefined);
  await page.getByRole('button', { name: 'Expand view', exact: true }).click();
  await page.waitForFunction(() => !!document.fullscreenElement);
  assert.equal(await viewer.count(), 1);
  assert.deepEqual((await viewer.evaluate(node => node.save())).filter, [['Category', '==', 'Bakery']]);
  await page.getByRole('button', { name: 'Collapse view', exact: true }).click();
  await page.waitForFunction(() => !document.fullscreenElement);
  await page.getByRole('button', { name: 'Reset view', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="perspective-card"] button')?.disabled);
  const reset = await viewer.evaluate(node => node.save());
  assert.equal(reset.plugin, 'Y Line'); assert.equal(reset.filter.length, 0);
  assert.equal(requests.length, 3, 'Interaction must not call the agent');
  await page.setViewportSize({ width: 390, height: 844 });
  assert((await page.getByTestId('perspective-surface').boundingBox()).width <= 390);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  await page.screenshot({ path: '/tmp/bakery-perspective-single-view.png' });
  await page.getByRole('button', { name: 'New Thread', exact: true }).click();
  assert.equal(await viewer.count(), 0);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', singleView: true, noCustomScroll: true, filters: true, export: true, fullscreen: true, reset: true, mobile: true, cleanup: true }));
} finally { await browser.close(); }
