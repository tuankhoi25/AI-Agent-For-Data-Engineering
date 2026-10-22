import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { fixture, toolEvents, textEvents, reply } from './perspective-fixture.mjs';
const spec = { ...fixture, title: 'Total amount', view: { plugin: 'Number Card', columns: ['Revenue'], group_by: ['Category'], aggregates: { Revenue: 'sum' }, plugin_config: { unit: 'test units', locale: 'en-US', decimals: 2 } } };
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let calls = 0;
  await page.route('**/api/agent', async route => {
    const input = route.request().postDataJSON();
    if (!calls++) await reply(route, input, toolEvents('card', 'render_perspective', spec));
    else {
      const result = JSON.parse(input.messages.find(message => message.role === 'tool' && message.toolCallId === 'card').content);
      assert.equal(result.status, 'ready', JSON.stringify(result));
      await reply(route, input, textEvents('done', 'Card ready.'));
    }
  });
  await page.goto(process.env.ASSISTANT_UI_URL ?? 'http://localhost:3001', { waitUntil: 'networkidle' });
  const input = page.getByRole('textbox', { name: 'Message input', exact: true });
  await input.fill('Show a numeric KPI.'); await input.press('Enter');
  await page.getByText('Card ready.', { exact: true }).waitFor({ timeout: 65000 });
  const viewer = page.locator('perspective-viewer'), card = page.locator('perspective-number-card');
  assert.equal(await card.count(), 1);
  const value = () => card.evaluate(node => node.shadowRoot.querySelector('.value').textContent);
  assert.equal(await value(), '400');
  await viewer.evaluate(async node => { await node.restore({ filter: [['Category', '==', 'Bakery']] }); await node.flush(); });
  assert.equal(await value(), '300');
  await viewer.evaluate(async node => { await node.restore({ filter: [['Category', '==', 'missing']] }); await node.flush(); });
  assert.equal(await value(), '—');
  await page.getByRole('button', { name: 'Reset view', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('perspective-number-card')?.shadowRoot.querySelector('.value').textContent === '400');
  assert.equal((await viewer.evaluate(node => node.save())).plugin_config.unit, 'test units');
  await viewer.evaluate(async node => { const table = await node.getTable(); await table.replace([{ Day: '2026-09-01', Category: 'Bakery', Revenue: 0, Units: 0 }]); await node.flush(); });
  await page.waitForFunction(() => document.querySelector('perspective-number-card')?.shadowRoot.querySelector('.value').textContent === '0');
  await viewer.evaluate(async node => { const table = await node.getTable(); await table.replace([{ Day: '2026-09-01', Category: 'Bakery', Revenue: null, Units: null }]); await node.restore({ group_by: [], aggregates: {} }); await node.flush(); });
  await page.waitForFunction(() => document.querySelector('perspective-number-card')?.shadowRoot.querySelector('.value').textContent === '—');
  assert.equal(calls, 2, 'Local filters/updates must not query the agent');
  await page.getByRole('button', { name: 'New Thread', exact: true }).click();
  assert.equal(await viewer.count(), 0); assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', singleCard: true, engineAggregation: true, filters: true, reset: true, null: true, zero: true, cleanup: true }));
} finally { await browser.close(); }
